"""F-b の独立対象一覧 draft 6 (紙 v0.23 / u・v の一次入力表を追補)。実装の適合試験ではない。

FBT-01/02 は紙と許された公開宣言だけから先に固定した。
FBT-03 はその固定後に場面・誤実装の *記述* と照合した別データ。
模型・本体・既存試験を import しない。紙も import 時/pytest 時に読まない。
行の「整理済み」は期待の対応を記述した意味で、実装済み/確認済みではない。
新しい契約をここで定義しない。未決/未対応/未採用は成功の分母から除かない。
表の ID、Python のキー、型の索引名はこの成果物内だけの整理用の名前。
"""

from collections import Counter

FB = "specs/関所F_Fb_今の約束.md"
FA = "specs/関所F_今の約束.md"
NA = "適用外: この行の対象ではない"


def source(path, first, last=None):
    return {"path": path, "first": first, "last": last or first,
            "read_scope": "該当部分"}


def _target(id, kind, subject, *, sources, rules, entries, use, evidence,
            negative, legal, body=NA, contract=NA, branch=NA, field=NA,
            role=NA, domain=NA, run=NA, owner=NA, presence="必須",
            edges=NA, consumer=NA, status="整理済み", issues=(),
            not_applicable_reason="適用外ではない"):
    return dict(id=id, kind=kind, subject=subject, body=body, contract=contract,
                branch=branch, field=field, role=role, domain=domain, run=run,
                owner=owner, presence=presence, edges=edges, use=use,
                evidence=evidence, consumer=consumer, rules=tuple(rules),
                entries=tuple(entries), negative=negative, nearest_legal=legal,
                not_applicable_reason=not_applicable_reason, sources=tuple(sources),
                status=status, issues=tuple(issues), execution="not_run")


_rows = []


def _schema(key, name, fields, *, at, contract=NA, body=NA, role=NA,
            entries=("I-3",), rules=("INV-4", "INV-5", "背骨⑤"),
            use="原記録から対象・版・全欄を照合して使用する", owner="窓口/台帳",
            edges="E: 保存内容。意味を使う段の U/UE は関係の行で区別",
            branches=(), status="整理済み", issues=(), overrides=None,
            kind=None, extra_sources=()):
    """展開する欄は手で列挙した紙の欄だけ。自由JSONを再帰探索しない。"""
    src = (source(FB, at[0], at[-1]),) if isinstance(at, tuple) else (source(FB, at),)
    src += tuple(extra_sources)
    if contract != NA and status == "未決":
        if body == NA:
            body = "未決: この契約のBody宣言"
        if role == NA:
            role = "未決: この契約のRole/Category宣言"
    base = dict(sources=src, rules=rules, entries=entries, use=use,
                evidence="同じ対象の原本・固定宣言・保存済み本文/header/CID。" + use,
                negative="同じ合法な前段で対象/版/内容の一つだけを変更し、当該使用を許さない",
                legal="対象/版/内容を保った再配送・再照合。新しい受信と論理の同一性を分ける",
                body=body, contract=contract, role=role, owner=owner, edges=edges,
                consumer=" / ".join(entries), status=status, issues=issues)
    header_kind = kind or ("contract" if contract != NA else "relation")
    _rows.append(_target("T." + key, header_kind, name, **base))
    for field in fields.split():
        # '?' means nullable, '[]' means the declared collection, never a wildcard walk.
        nullable = field.endswith("?")
        field = field.rstrip("?")
        opts = dict(base)
        opts.update(field=field, presence="必須キー・null可" if nullable else "必須・省略不可")
        if status in ("未決", "未対応"):
            opts["presence"] = "未決: 論理上の欄を列挙。wireの必須性/nullableは全宣言待ち"
        elif "." in field:
            opts["presence"] = "該当する親/枝が存在するときに適用。親がnull/別枝なら適用外" + ("。この欄はnull可" if nullable else "")
        opts.update(negative=f"{name}.{field} のキーを落とす/外側の型を変える。原報告保存と意味の使用の判定を分ける",
                    legal=f"{name}.{field} を宣言された型で保持" + ("。明示nullを省略と区別する" if nullable else "。値だけを理由に原報告を落とさない"))
        if overrides and field in overrides:
            opts.update(overrides[field])
        _rows.append(_target("T." + key + "." + field, "field", name, **opts))
    for branch in branches:
        opts = dict(base)
        opts.update(branch=branch, presence="この枝を選ぶ時に必須",
                    negative=f"{name} の {branch} を別枝/成功へ読み替える",
                    legal=f"{name} の {branch} を保ち、枝固有の必要条件だけを適用する")
        _rows.append(_target("T." + key + ".branch." + branch, "branch", name, **opts))


# ---- FBT-01: Body と共通の公開宣言。wall_ns は不一致報告に隔離。 ----
for _key, _name, _fields, _line in (
    ("observed", "Observed", "route content contract caused_by? source_id? source_time_ns? received_ns?", 110),
    ("decided", "Decided", "inputs[] content contract", 133),
    ("job", "JobOpened", "decision step content contract", 147),
    ("attempt", "AttemptStarted", "job content contract", 160),
    ("prediction", "Prediction", "target about[] basis[] content contract", 171),
    ("interpretation", "Interpretation", "about[] basis[] content contract", 186),
    ("preference", "Preference", "basis[] content contract", 199),
    ("intention", "Intention", "target operation status decided_in supersedes? via? content contract", 210),
):
    _schema("body." + _key, _name, _fields, at=(51, 54), body=_name, kind="body",
            entries=("I-1", "I-2", "I-3", "I-4", "I-5", "I-6", "I-7", "I-8"),
            branches=("confirmed", "withdrawn", "executed") if _key == "intention" else (),
            extra_sources=(source("src/sui/records.py", _line), source(FA, 38, 49)),
            use="Body全枝の外側を保持。新契約のBody/Role/Categoryは別宣言が必要 (F-b:486)",
            overrides={"received_ns": dict(role="r", domain="M", run="ホストの同じrun", presence="一般型null可。F-b受付はr必須", negative="rを保存時刻sに取り替える", legal="保存を遅らせても原本rを保つ"),
                       "source_time_ns": dict(role="u", domain="U", run="送り手の主張。同じrunのMへ昇格不可")})

_schema("record", "Record schema 3", "id at writer producer body schema", at=486,
        extra_sources=(source(FA, 28, 38), source("src/sui/records.py", 309, 315)))
_schema("instant", "Instant (wall_nsは不一致 D-01 に隔離)", "run run_index seq mono_ns", at=(51, 54),
        extra_sources=(source("src/sui/clock.py", 13, 18), source(FA, 28, 30)),
        overrides={"mono_ns": dict(role="s", domain="M", run="Record.at.run", negative="同runで親より逆行", legal="同じmono_nsでもseqは親より大きい"),
                   "run_index": dict(role="順序・時刻ではない"), "seq": dict(role="順序・時刻ではない")})
_schema("producer", "Producer", "component code_version state?", at=486,
        extra_sources=(source("src/sui/records.py", 76, 89), source(FA, 28)))
_schema("state_ref", "StateRef", "lineage revision", at=486,
        extra_sources=(source("src/sui/records.py", 76, 78), source(FA, 28)))
_schema("payload", "Payload", "media_type data", at=(463, 464),
        extra_sources=(source("src/sui/records.py", 15, 17), source(FA, 28)),
        use="未知bytesも保存。自由JSONの中身を勝手にPointや和型と解釈しない")
_schema("contract_ref", "ContractRef", "name version", at=(235, 235),
        extra_sources=(source("src/sui/contracts.py", 10, 12), source(FA, 28)))
_schema("contract_declaration", "Contract", "ref meaning unit state_owner persistence failure cancel redelivery", at=486,
        extra_sources=(source("src/sui/contracts.py", 22, 30), source(FA, 53)))
_schema("ref", "Ref", "kind value", at=51,
        branches=("individual", "run", "decision", "job", "attempt", "observation", "prediction", "interpretation", "preference", "intention"),
        extra_sources=(source("src/sui/ids.py", 28, 44), source(FA, 28)))
_schema("role", "Role", "", at=486, branches=("membrane", "model", "interpreter"),
        extra_sources=(source("src/sui/records.py", 50, 53), source(FA, 38)))
_schema("category", "Category", "", at=486, branches=("fact", "prediction", "interpretation", "preference", "intention"),
        extra_sources=(source("src/sui/records.py", 56, 61), source(FA, 38)))

# ---- 公開の入口の一次入力。内部の論理対応 link.* は別の関係行。 ----
_schema("envelope", "Envelope", "number event received_ns", at=(461, 467),
        entries=("post", "accept"), rules=("INV-1", "INV-11", "I-1"), owner="H→P.receipts",
        extra_sources=(source("src/sui/runtime.py", 104, 107),),
        overrides={"number": dict(use="同番号の再受付は全内容とrを照合", negative="同番号で別内容を渡して前の成功を返す", legal="同番号・全内容・rが一致する再受付"),
                   "received_ns": dict(role="r", domain="M", run="ホストのrun", negative="r>sを入力shapeの拒否にする/成功させる", legal="r=s。後の保存でrは変えない")})
_schema("boot_event", "Boot", "declaration", at=469, entries=("I-6",), rules=("INV-1.c", "INV-13", "I-6"),
        use="1封筒からbootと宣言の2slot。時計の宣言は別封筒")
_schema("boot_decl", "BootDeclaration", "capacity scope routes initial? environment", at=469,
        contract="sui.fb.boot_declaration/1", body="Observed", role="membrane / fact", entries=("I-6",),
        rules=("INV-13", "INV-10", "I-6"), branches=("initialあり", "initial=None"),
        status="未決", issues=("G-02",),
        use="範囲は1つ。initial=Noneは計算を出さず測定・受信を続ける。内部型の全欄は未決")
_schema("boot_fact", "起動事実", "", at=469, contract="sui.s4.boot/1", body="Observed", role="membrane / fact",
        entries=("I-6",), rules=("INV-1.c", "I-6"), extra_sources=(source(FA, 77),), use="content={}。宣言のslotと別々に保存を確かめる")
_schema("initial", "InitialProcess", "", at=(326, 326), entries=("I-6",), rules=("INV-13", "INV-2.g"),
        status="未決", issues=("G-02",), use="生成器・方法・最初の割当・読み手・モデルの意味は紙にある。正確な全欄とnullableは未決")
_schema("resource_scope", "ResourceScope", "", at=469, entries=("I-6",), rules=("INV-10", "背骨③"),
        status="未決", issues=("G-02",), use="縦の1本は資源範囲1つ。公開型の全欄・識別は未決")
_schema("clock_declared", "ClockDeclared", "declaration", at=(1923, 1927), entries=("I-7",), rules=("INV-1", "INV-4", "I-7"))
_schema("clock_source", "ClockSource", "run provider implementation python_version resolution_s monotonic adjustable measurement?",
        at=1925, contract="sui.clock.source/1", body="Observed", role="membrane / fact", entries=("I-7",),
        rules=("INV-1", "INV-5", "I-7"), extra_sources=(source("src/sui/clock_contracts.py", 20, 28), source(FA, 78)),
        use="時計の出どころの宣言d。実測精度の証明にせず、宣言r/sを過去の読みの下限にしない",
        overrides={"resolution_s": dict(role="d", domain="D", presence="正の有理数", negative="非正の解像度を合法な宣言とする", legal="正の有理数を宣言しても精度の認証とはしない")})
_schema("received", "Received", "route_epoch media_type data claims", at=(172, 172),
        contract="sui.fb.received/1", body="Observed", role="membrane / fact", entries=("I-1",),
        rules=("I-1", "INV-1", "背骨②"), extra_sources=(source(FB, 471),),
        use="送り手のID・契約・時刻もclaimsの主張。未知bytesを残し勝手に観測を作らない",
        overrides={"claims": dict(role="uを含む主張", domain="U (時刻を主張した場合)", presence="必須。内側の構造は未決", status="未決", issues=("G-02",))})
_schema("segment_report", "SegmentReport", "segment item_slot item", at=(321, 344),
        contract="sui.fb.segment_report/1", body="Observed", role="membrane / fact", entries=("I-2",),
        rules=("I-2", "INV-6.b", "INV-6.c", "INV-12"), extra_sources=(source(FB, 472),),
        branches=("Started", "Frame", "Gap", "Unavailable", "Claim", "Unproved", "RouteApplied", "Ended"),
        use="原報告の保存では未知のsegment名指しも残す。結びつきで対応と全比較欄を照合")
_schema("work_finished", "WorkFinished", "work started finished outcome", at=473,
        contract="sui.fb.work_report/1", body="Observed", role="membrane / fact", entries=("I-3",),
        rules=("I-3", "INV-15", "INV-2.c"), branches=("WorkOutputs", "WorkFailure", "WorkUnknown"),
        use="Computeの全用途。Dを名乗る報告は保存してもDのEndKnownにしない",
        overrides={"started": dict(role="e開始", domain="M/宣言されたUnavailable", run="生成元run", status="未決", issues=("G-02",)),
                   "finished": dict(role="g", domain="M/宣言されたUnavailable", run="生成元run", status="未決", issues=("G-02",))})
_schema("draw_returned", "DrawReturned", "work outcome", at=(1966, 1970),
        contract="sui.fb.draw_report/1", body="Observed", role="membrane / fact", entries=("I-8",),
        rules=("I-8", "INV-14", "INV-15"), branches=("DrawValue", "DrawFailure", "DrawUnknown"),
        use="Dの終わりはこの外形だけ。Failure/RejectedはTのみ、Unknownは条件付きDU、値は条件付きDF")
for _name in ("WorkOutputs", "WorkFailure", "WorkUnknown", "DrawValue", "DrawFailure", "DrawUnknown"):
    _schema("payload." + _name, _name, "", at=(473, 474),
            entries=("I-8",) if _name.startswith("Draw") else ("I-3",), rules=("INV-15",),
            status="未決", issues=("G-02",), use="枝の意味は決まるが枝内の公開全欄・型・nullableは未決。DTOを発明しない")

# ---- F-a の測定・時計の全欄と和型。根拠は紙、f.pyのクラス本体は読まない。 ----
_schema("reading", "ClockReading", "run time_ns", at=(51, 68), extra_sources=(source(FA, 31),),
        entries=("I-2", "I-3", "I-7"), rules=("INV-5", "INV-12"),
        overrides={"time_ns": dict(role="使用別e/g/a/i/o/j/p。単一available_timeにしない", domain="M", run="reading.run", presence="符号付き整数")})
_schema("clock_reading", "時計の読みの記録", "source reading", at=1883,
        contract="sui.f.clock_reading/1", body="Observed", role="membrane / fact", entries=("I-2", "I-3", "I-7"),
        extra_sources=(source(FA, 66),), use="sourceの宣言とreading.runを結び、通知rと読みtime_nsを分ける")
_schema("unavailable", "Unavailable", "reason basis[]", at=(736, 743), extra_sources=(source(FA, 31),),
        entries=("I-2", "I-3"), rules=("INV-12", "INV-5"), use="不明の根拠E。欠落/null/測定値0/実測時刻へ変換しない")
_schema("measurement_id", "MeasurementId", "origin route_epoch sample_seq component", at=(329, 329),
        extra_sources=(source(FA, 31),), entries=("I-2",), rules=("INV-6", "INV-7", "INV-12"))
_schema("interval", "MeasurementInterval", "clock start_ns end_ns closure", at=(730, 743),
        extra_sources=(source(FA, 31),), entries=("I-2",), rules=("INV-12.a",),
        branches=("両閉", "左閉", "右閉", "両開"),
        use="端点セルと開区間を分ける。同route/run/k/kindで比較。長さの和で代用しない",
        overrides={"start_ns": dict(role="i", domain="M", run="interval.clock"),
                   "end_ns": dict(role="i", domain="M", run="interval.clock", negative="Frame/Claim等の完了窓でend=r+1", legal="完了窓でend=r。Unprovedは未来端も合法")})
_schema("contract_value", "ContractValue", "contract value", at=344, extra_sources=(source(FA, 31),), entries=("I-2",))
_schema("dependency_ref", "DependencyRef", "key basis[]", at=486, extra_sources=(source(FA, 31),))
_schema("frame", "MeasurementFrame", "route_epoch sample_seq measurement_id measurement_interval actual_time value quality gap? source_cursor",
        at=736, contract="sui.f.measurement/1", body="Observed", role="membrane / fact", entries=("I-2",),
        rules=("INV-12.a", "INV-6.b", "INV-7.a"), extra_sources=(source(FA, 93, 95),),
        branches=("actual_time.clock", "actual_time.unavailable", "value.value", "value.unavailable", "gap.null", "gap.Gap"),
        use="完了窓end≤rはactual_time不明でも必要。Frameのみで連続被覆を増やさない")
for _key, _name, _fields, _ln, _fa in (
    ("claim", "CoverageClaim", "route_epoch interval kind contract evidence[]", 742, 96),
    ("gap", "Gap", "route_epoch sequence_range interval reason evidence[]", 740, 97),
    ("measurement_unavailable", "MeasurementUnavailable", "route_epoch requested_interval reason evidence[]", 741, 98),
    ("unproved", "CoverageUnproved", "route_epoch interval missing_contracts evidence[]", 743, 99),
):
    _schema(_key, _name, _fields, at=_ln, contract="sui.f.coverage/1", body="Observed", role="membrane / fact",
            entries=("I-2",), rules=("INV-12.a", "INV-12.b", "INV-6.c"), extra_sources=(source(FA, _fa),),
            use={"claim":"被覆はX内の独立した証拠と契約別Support。kind/contractが未宣言なら意味の境界で不足",
                 "gap":"first≤seq<stop。欠けの報告であり値0/無到着/被覆ではない",
                 "measurement_unavailable":"測れなかった部分を保持。他部分とEnded未確認のrunは残る",
                 "unproved":"未来の未証明区間も可。end≤rを一律に課さない。被覆へ昇格しない"}[_key])
_schema("coverage", "coverageタグ付き和型", "", at=(65, 65), contract="sui.f.coverage/1",
        body="Observed", entries=("I-2",), rules=("INV-12",),
        branches=("claim", "gap", "measurement_unavailable", "coverage_unproved"), extra_sources=(source(FA, 29),))
_schema("route_config", "RouteConfig", "route_epoch origin version sampling_contract clock_contract loss_contract args decision? execution?",
        at=(62, 62), entries=("I-6", "I-2"), rules=("INV-12", "I-6"), branches=("bootstrap", "selected"),
        extra_sources=(source(FA, 76),), use="bootstrapはdecision/execution=null。selectedの変更運用はR4未採用")
_schema("route_applied", "RouteApplied", "config effective_from execution? evidence[]", at=(739, 739),
        contract="sui.f.route_config/1", body="Observed", role="membrane / fact", entries=("I-6", "I-2"),
        rules=("INV-12", "I-6"), branches=("effective_from.clock", "effective_from.unavailable"), extra_sources=(source(FA, 76),))
for _name, _ln in (("Started", 737), ("Ended", 738)):
    _schema("segment." + _name, _name, "", at=(_ln, _ln), entries=("I-2",), rules=("INV-12", "C-O04.run[MeasureSegment]"),
            status="未決", issues=("G-02",), use="segment/work/reading/evidenceの意味は1057。全欄と型の宣言は未決。Endedだけがrun終端候補")
_schema("plan", "ObservationPlan", "model_ref route_epoch measurement_contract kernel cells[] cells[].id cells[].observation.kind cells[].observation.value cells[].outcomes[] time_projection generation_contract",
        at=482, contract="sui.f.observation_plan/1", body="Prediction", role="model / prediction",
        entries=("I-2", "I-3"), extra_sources=(source(FA, 107, 109),))
_schema("old_binding", "ObservationBinding (/1の互換対象)", "plan records[] opportunity step cell slots[] slots[].slot slots[].measurement generated_by[] derived_from[]",
        at=482, contract="sui.f.observation_binding/1", body="Observed", entries=("I-2", "I-3"),
        extra_sources=(source(FA, 110, 111),), use="旧/1のAttempt条件を緩めない。bootstrapのsegment_bindingへ流用しない")
_schema("segment_binding", "segment_binding", "segment report route reading_contract evidence[] generation clock", at=(1054, 1055),
        contract="sui.fb.segment_binding/1", entries=("I-2", "I-3"), rules=("INV-5", "INV-7.b", "INV-12.a"),
        status="未決", issues=("G-01", "G-02"), use="論理欄は紙1054。Body/Role/Category・wire全欄・/2数値射影/閉包は未決")

# ---- 更新・評価の一次入力、名前と版を省略しない。 ----
for _key, _name, _fields, _contract, _body, _role, _fa_line, _fb_line in (
    ("model", "model_source", "document", "sui.f.model_source/1", "Prediction", "model / prediction", 57, 482),
    ("origin", "knowledge_origin", "model", "sui.f.knowledge_origin/1", "Observed", "membrane / fact", 59, 1027),
    ("acquired", "content_acquired", "origin contents[] clock", "sui.f.content_acquired/1", "Observed", "membrane / fact", 60, 1039),
    ("request", "computation_requested", "origin purpose method args inputs[] algorithm_draws[] output_contract", "sui.f.computation_requested/1", "Decided", "model / fact", 61, 1028),
    ("result", "computation_result", "request output.contract output.value", "sui.f.computation_result/1", "Prediction", "model / prediction", 62, 1033),
    ("proof", "computation_proof", "request result role statement.contract statement.value checker", "sui.f.computation_proof/1", "Prediction", "model / prediction", 63, 1035),
    ("completed", "computation_completed", "request result proofs[] started_clock finished_clock", "sui.f.computation_completed/1", "Observed", "membrane / fact", 64, 1037),
    ("adopted", "knowledge_adopted", "origin previous? completion", "sui.f.knowledge_adopted/1", "Decided", "model / fact", 65, 1043),
    ("context", "context_observed", "knowledge_origin observation_reading judgment_reading check_events[] check_events[].kind check_events[].record", "sui.f.context_observed/1", "Observed", "membrane / fact", 67, 1032),
    ("draw_fact", "draw_fact", "generator stream_id request.purpose request.context_key request.ordinal request.law request.args value", "sui.f.draw_fact/1", "Observed", "membrane / fact", 68, 1047),
    ("candidate", "FCandidateDeclaration", "model input_order[] measure? generation.generator generation.args generation.basis[] generation.draws[] continuation.after[] continuation.after[].candidate continuation.after[].policy?", "sui.f.candidate_declaration/1", "Prediction", "model / prediction", 58, 1934),
):
    _schema(_key, _name, _fields, at=_fb_line, contract=_contract, body=_body, role=_role,
            extra_sources=(source(FA, _fa_line),), entries=("I-8", "I-3") if _key == "draw_fact" else ("I-3",),
            branches={"request": ("belief", "query", "certificate"), "proof": ("normalization", "query"),
                      "context": ("check_events.fact", "check_events.clock"),
                      "draw_fact": ("candidate_generation", "selection", "reservation", "algorithm"),
                      "adopted": ("previous=null", "previous=Point")}.get(_key, ()),
            use="事実の入口で再構成。取得・認証・採用を別に照合。/2の追加規則を/1へ移さない")

_schema("finite_update1", "finite_update/1", "model previous_result? observations[]", at=(1086, 1090),
        contract="sui.f.finite_update/1", extra_sources=(source(FA, 267),),
        use="算法draws=[]。Cを方法/origin/argsから求めC⊆I、Iの順と観測の適用順を分ける")
_schema("finite_result", "FiniteUpdateResult", "joint[] evidence_mass", at=373,
        contract="sui.f.finite_update_result/1", extra_sources=(source(FA, 267),), use="普通のDTO。発行ハンドルを要求しないが使う時に実値を再計算")
_schema("finite_statement", "FiniteUpdateStatement", "model request result", at=(363, 374),
        contract="sui.f.finite_update_statement/1", extra_sources=(source(FA, 267),))
_schema("finite_replay", "finite_update_replay", "args", at=1085,
        contract="sui.f.finite_update_replay/1", extra_sources=(source(FA, 267),),
        overrides={"args": dict(presence="必須・厳密に{}", negative="argsにPointらしい文字列を足す", legal="args={}。checkerの存在だけで証明成功とはしない")})
_schema("finite_update2", "finite_update/2", "", at=(479, 486), contract="sui.f.finite_update/2",
        status="未決", issues=("G-01",), use="別registry。args/output/statement/checker/観測射影/数値入力閉包を/1から推定しない")
_schema("target_certificate", "対象指定認証物と発行入口", "target.Q target.R target.proofs[] target.Cq origin view registry result_digest", at=(374, 379),
        rules=("INV-9.a", "INV-7.b", "背骨⑤"), status="未決", issues=("G-01", "G-02"),
        use="必要な結合の意味だけ列挙。正式な型名・署名・契約版・全wire欄は未決。一般履歴読取りの正常復帰で代用しない")
_schema("qgen", "Qgen", "process trigger reader purpose stage_slot method output_contract args input_points[] input_order[] numerical_view allocation permissions",
        at=(1931, 1933), contract="sui.fb.candidate_request/1 (仮称)", rules=("INV-2.g", "INV-16.c", "INV-8"),
        status="未決", issues=("G-02",), use="生成前に固定する論理欄。Body/Role/Categoryと具体wireは未決")
_schema("candidate_generation", "Wgの出力", "", at=1963, contract="sui.fb.candidate_generation/1 (仮称)",
        rules=("INV-2.g", "INV-16.c"), branches=("非空の候補", "NoCandidates", "Failure", "Unknown"),
        status="未決", issues=("G-02",), use="NoCandidatesは確定返答。空のCG/NoDecisionを作らず元目的pGを保全")
_schema("eq", "評価要求EQ", "input numerical_view process trigger method operation environment allocation permissions", at=(1032, 1032),
        contract="未決: F-bの別契約(評価要求)", rules=("INV-16.b", "INV-8", "INV-2.g"),
        status="未決", issues=("G-02",), use="CG保存後、使える文脈o/j等で固定。Qgenの像と同一視しない")
_schema("prepared", "評価の準備の終わりPR", "evaluation_request artifact numerical_view operation", at=1045,
        contract="未決: F-bの別契約(評価の準備の終わり)", rules=("INV-16.b", "INV-15"),
        branches=("FProblem", "NoDecision"), status="未決", issues=("G-02",), use="FProblemのみDを約束。NoDecisionを捏造しない")
_schema("evaluated", "評価の終わりEV", "evaluation_request prepared draw artifact operation numerical_view", at=1049,
        contract="未決: F-bの別契約(評価の終わり)", rules=("INV-16.a", "INV-16.b"),
        branches=("Selected", "NoDecision"), status="未決", issues=("G-02",), use="同じEQ/PR/DF/根/発行artifactの全対応。信念のcompletedではない")
_schema("selection", "選択S", "evaluated artifact root draw", at=1050,
        contract="sui.fb.selection/1", body="Decided", rules=("INV-16.a", "INV-16.b"),
        status="未決", issues=("G-02",), use="認証Selectedだけ。作用の許可にはならない。外側inputs/Role等の宣言は未決")
_schema("terminal", "終わりの記録T", "work request stage first_receipt terminal_kind returned basis view", at=(776, 793),
        contract="sui.fb.work_terminal/1", rules=("INV-15", "INV-2.c"), extra_sources=(source(FB, 1882), source(FB, 1972)),
        status="未決", issues=("G-02",), use="8欄。生成の時計はbasis、generationを第9欄にしない。親は要求と最初の受信。Body等は未決")
for _key, _name, _fields, _line, _contract in (
    ("verification", "V", "target view response issued_certificate link.work link.report", 1041, "未決: 認証返答記録"),
    ("stale", "ST", "intent target_completion planned_previous actual_previous reason view", 1044, "未決: Stale記録"),
    ("draw_unknown", "DU", "draw_request first_receipt unknown_basis view", 1048, "sui.fb.draw_unknown/1"),
    ("conflict", "Xc", "reports[] rule affected view", 1052, "sui.fb.conflict/1"),
    ("waiting", "W", "obligation purpose target missing witness view owner", 1053, "未決: 不足の保持/記録"),
):
    _schema(_key, _name, _fields, at=_line, contract=_contract, rules=("INV-2.c", "INV-5", "INV-7", "INV-15"),
            status="未決", issues=("G-02",), use="紙の論理欄の対応。診断のEvidenceRefsを成功のUseDepsへ読み替えない。Body等は未決")
_schema("descriptor", "Desc(w)", "work_id process trigger purpose stage_slot reader method output_contract args input_points[] numerical_view allocation permissions", at=1007,
        rules=("INV-3.b", "INV-5.b", "INV-8"), owner="P.work", use="全欄を仕事の寿命中固定。PlanRefの解決表は別に保持")
_schema("generation", "Gen(w)", "work_id request stage started finished outcome_kind outcome_content provenance", at=1008,
        rules=("INV-15", "INV-8", "INV-9"), use="実際の返答と原報告を独立照合。配送rを生成の読みの代用にしない")
_schema("fwork", "FWork", "", at=462, entries=("drain",), rules=("INV-2", "INV-3", "INV-10"),
        branches=("MeasureSegment", "Compute", "Draw"), use="列挙は取り除かない。ComputeはWg/Wr/Wp/Wv/Ep/Ee、Drawは縦ではD")
_schema("work_phase", "仕事の実行段と結果知識", "", at=290, entries=("drain", "status"), rules=("INV-3", "INV-10", "INV-15"),
        branches=("Pending", "Starting", "Running", "Stopped", "確かな開始前停止", "knowledge.None", "knowledge.Success", "knowledge.Failure", "knowledge.Unknown"),
        use="実行段と結果知識は独立の軸。Unknown/T保存と停止/解放を混ぜない")
_schema("prepared_entry", "PreparedEntry", "record parents salt header cid", at=468, entries=("Ledger.prepare", "Ledger.write"),
        rules=("INV-4", "INV-5"), use="prepareは書かない。write前と既存点でseal/encode_header/hashを全部照合")
_schema("ledger_entry", "Entry", "cid header id body_type at writer parents seal", at=468,
        entries=("Ledger.write",), rules=("INV-4", "INV-5"), extra_sources=(source("src/sui/ledger.py", 127, 135),))
_schema("purpose_part", "PurposePart", "c0 purpose_role target_part", at=(1320, 1347), rules=("INV-2.a", "INV-2.c", "INV-2.g"),
        owner="元条件と対象を保持する実担当", use="論理上のc0/π/a。新wire保存を要求しない。D3でDirect(p)=偽、引継ぎ後も未達を保持",
        branches=("達成済み", "引継ぎ済み", "未達のまま保全", "削除・消去の違反", "未接続"))
_schema("status", "FStatus (意味の公開契約)", "対象の完全識別 判定像 保存済みPointまたは未保存の識別 根拠", at=(1907, 1921),
        entries=("status",), rules=("背骨②", "背骨⑤", "INV-2.c", "INV-4", "INV-10"),
        branches=("受信・受付・保存", "仕事・開始・占有", "読み・反映・選択", "未判定・不足・食い違い", "測定の区間・部分", "未完の目的と引継ぎ"),
        use="欄名は意味の索引で新クラス/JSONキーを指定しない。整合した局所像、読取専用、未確認≠不存在、照会は状態を進めない")

# F-a 側の公開一次入力の残り。外付け用途を縦の成功に数えない。
_schema("facts_request", "FFactsRequest/prepare_f_from_factsの一次入力", "fixed_parents[] model candidates preferences[] scope context method", at=1032,
        entries=("prepare_f_from_facts",), rules=("INV-8", "INV-16.b", "背骨⑤"), extra_sources=(source(FA, 376, 378), source("src/sui/f_facts.py", 38, 61)))
_schema("scope", "EvaluationScope", "name version H_ns? source?", at=106, extra_sources=(source(FA, 293),),
        branches=("unbounded_total", "one_step", "finite_horizon"), use="有限Hは非負でsource必須。他はH=null。予算を好みにしない")
_schema("artifact", "数学artifact", "contract compiler input.kind input.value environment.reader_view_key environment.registry_key calls[] calls[].op calls[].args output claim.type claim.value",
        at=(1060, 1098), contract="sui.f.math_artifact/2", entries=("I-3", "verify_f_math_result"),
        rules=("INV-16.b", "INV-8", "背骨⑤"), extra_sources=(source(FA, 391),),
        branches=("input.facts", "input.preflight", "input.limit", "input.legacy_bridge"),
        status="未対応", issues=("G-01",), use="全bytesの再認証。直接辺の列挙と全閉包の認証は別。後3枝は縦の利用例で未接続")
_schema("artifact1", "旧数学artifact", "", at=(479, 484), contract="sui.f.math_artifact/1",
        entries=("verify_f_math_result",), rules=("背骨⑤", "INV-8"), extra_sources=(source(FA, 391),),
        use="旧bytes/旧compiler/旧registryを保持。旧bundleへ戻して再認証。当時の不足を新能力で埋めない")
_schema("at", "At", "run time_ns source", at=2021, extra_sources=(source(FA, 88),), entries=("I-5",), rules=("I-5", "INV-6.b"),
        status="未採用", issues=("G-04",), use="R1の外付け。予定pと検出e/再検出を分ける")
_schema("when", "When", "predicate", at=2022, extra_sources=(source(FA, 88),), entries=("I-5",), rules=("I-5", "INV-8"),
        status="未採用", issues=("G-04",), use="R2の外付け。述語True/False/Unknownと仕事の結果を分ける", branches=("True", "False", "Unknown"))
_schema("reservation_due", "ReservationDue", "reservation_id firing_id due detected execution? evidence[]", at=2021,
        extra_sources=(source(FA, 88),), entries=("I-5",), rules=("I-5", "INV-6.b"),
        branches=("trigger.At", "trigger.When", "due.clock", "due.unavailable"), status="未採用", issues=("G-04",),
        use="別runはclock_unaligned。未来の予定を過去の観測へ混ぜない")
_schema("generation_draw_request", "RG", "", at=2030, contract="sui.fb.generation_draw_requested/1 (仮称)",
        entries=("I-8",), rules=("INV-14.c",), status="未採用", issues=("G-04",), use="R10/D6。生成前に固定した要求。生成後input_orderをcontext_keyへ入れない")
_schema("generation_draw_unknown", "DUg", "", at=2030, contract="sui.fb.generation_draw_unknown/1 (仮称)",
        entries=("I-8",), rules=("INV-14.c",), status="未採用", issues=("G-04",), use="Dgの不明をWgのUnknownへ変換しない。DFgだけがWgの入力依存を満たす")

# 以下の固定データはこのファイル作成時の紙から転記する。模型から作らない。
_schema("model_document", "FiniteModel/model.11", "scheme contract units targets states[] states[].id states[].target initial[] kernels[] operations[] policies[] certificate_capabilities",
        at=(479, 484), contract="sui.f.finite_model/2", extra_sources=(source(FA, 275, 289), source("src/sui/f_model.py", 186, 193)),
        use="一次宣言。/1 model.10と分離、semantic_keyは宣言の正解にしない")
_schema("model_document1", "FiniteModel/model.10", "declaration", at=484, contract="sui.f.finite_model/1",
        extra_sources=(source("src/sui/f_model.py", 18, 31), source(FA, 272)), use="旧宣言bytesと旧意味を保持するgoldenの対象")
_schema("action_decl", "FActionDeclaration", "id family args start policy termination termination_kind prediction execution proof", at=1934,
        extra_sources=(source(FA, 277, 289),), branches=("termination.certain", "termination.may_never"),
        rules=("INV-16.b", "INV-16.c", "背骨③"), use="候補の一次宣言。表示別名と測度を分け、同義のID追加で確率を増やさない")
_schema("kernel", "FiniteKernel", "id outcomes[] outcomes[].id outcomes[].elapsed_ns outcomes[].evidence? outcomes[].evidence.slot outcomes[].evidence.kind outcomes[].evidence.value outcomes[].evidence.measurement_contract outcomes[].available.reveal[] outcomes[].available.computation? outcomes[].completion outcomes[].matrix[][]", at=482,
        extra_sources=(source(FA, 279, 289),), branches=("evidence.null", "evidence.measurement", "evidence.coverage", "evidence.gap"),
        use="F-aの有限な共同生成法則。列正規化・静的target・観測セルの核の合算を実値で照合")
_schema("policy", "FinitePolicy", "id entry nodes[]", at=106, extra_sources=(source(FA, 282, 284),),
        branches=("execute", "choose", "end"), rules=("背骨③", "INV-16.b"))
for _branch, _fields in (("execute", "id kernel next{}"), ("choose", "id operations[] rule next{}"), ("end", "id")):
    _schema("policy." + _branch, "FinitePolicy.nodes." + _branch, "kind " + _fields, at=106,
            extra_sources=(source(FA, 282, 284),), rules=("背骨③", "INV-16.b"))
_schema("capability", "CapabilityDeclaration", "kind ref args_contract input_contract output_contract dependencies[] conditions", at=(479, 484),
        extra_sources=(source(FA, 114, 138),), use="宣言と実装identityを別に固定。登録済みだけでは能力の認証成功でない")
_schema("capability_implementation", "CapabilityImplementation", "identity", at=(479, 484),
        extra_sources=(source(FA, 114),), status="未決", issues=("G-05",),
        use="identityの意味は紙。残りの公開欄は今回許された資料に全宣言がなく未列挙。f.pyクラス定義は閲覧範囲外")
_schema("artifact_preflight", "FPreflightFacts", "fixed_parents[] model? required_records[] required_capabilities[] required_capabilities[].kind required_capabilities[].ref required_capabilities[].implementation_required", at=1096,
        extra_sources=(source(FA, 380, 381),), status="未対応", issues=("G-01",), use="artifactのpreflight枝として保持。縦の1本での使用は未接続")
_schema("artifact_bridge", "FLegacyBridgeRequest", "fixed_parents[] model context preferences[] candidates[] adapter", at=1096,
        extra_sources=(source(FA, 382, 383),), status="未対応", issues=("G-01",), use="旧artifactの再読・golden対象。新しい/2入力へ無言で変換しない")
_schema("artifact_limit", "ArtifactInput.limit", "declaration", at=1096,
        extra_sources=(source(FA, 411),), status="未対応", issues=("G-01",), use="独立limitの枝。run/BOOT/FRootを新設しない")
_schema("dependencies", "FFactsDependencies", "points[] points[].point points[].entry_present points[].body_present points[].record? points[].record_digest? models[] models[].point models[].model_ref? capabilities[] capabilities[].kind capabilities[].ref capabilities[].declaration? capabilities[].implemented capabilities[].implementation_id? ref_lookups[] ref_lookups[].ref ref_lookups[].points[] absence_environment? absence_environment.reader_view_key absence_environment.registry_key",
        at=(483, 484), extra_sources=(source(FA, 414, 452),), rules=("INV-8", "INV-16.b", "背骨⑤"),
        use="当時の不足も固定像に結ぶ。Entry不在/本文不在/存在して別内容を分ける")
_schema("registry_old", "builtin_f_registry", "", at=(479, 484), entries=("builtin_f_registry",),
        rules=("背骨⑤", "INV-8"), extra_sources=(source("src/sui/f.py", 2307, 2316),),
        use="旧factoryの集合・実装identity・dispatch・旧registry_keyとgolden全bytesを保持")
_schema("registry_new", "fb_registry_v1 (紙の仮称)", "", at=481, entries=("make_f_registry",),
        rules=("背骨⑤", "INV-8"), status="未決", issues=("G-01",),
        use="旧集合＋新宣言の別不変registry。新/2・checkerの全宣言が未決")


def _relation(key, subject, at, rules, entries, use, negative, legal, *,
              targets=(), status="整理済み", issues=(), extra_sources=()):
    row = _target("T.rel." + key, "relation", subject,
                  sources=(source(FB, at[0], at[-1]) if isinstance(at, tuple) else source(FB, at),) + tuple(extra_sources),
                  rules=rules, entries=entries, use=use, evidence=use,
                  negative=negative, legal=legal, edges=use, consumer=" / ".join(entries),
                  owner="当該対象の原本/実担当と保存済み事実", status=status, issues=issues)
    row["related_targets"] = tuple(targets)
    _rows.append(row)


_relation("receipt", "受信→受付→保存", (463, 467), ("INV-1", "INV-11", "L-RECEIPT"), ("I-1", "I-2", "I-3", "I-6", "I-7", "I-8"),
          "同じ封筒は同じ原本・r・名前。別Postは別受信。acceptは預かりまで。",
          "未知bytesを捨てる/同文の別Postを同じ受信に潰す", "未知bytesでも正しい外形で保存。再受付だけ同じ受信", targets=("T.envelope", "T.received"))
_relation("shape", "外形の拒否と意味の不足", (464, 465), ("I-1", "INV-1.b"), ("accept",),
          "外形誤りのみFbInputError(reason=shape,field)。記録も預かりも作らない。",
          "未知要求・読めない内容をshapeで拒む", "未知要求も原報告を保存し、後の意味使用で待つ")
_relation("storage", "保存の原本固定・読戻し", (305, 308), ("INV-4.a", "INV-4.b", "INV-4.c", "INV-5.c"), ("Ledger.prepare", "Ledger.write", "settle"),
          "record/parents/salt/header/cidを初回から固定。実C/Eでseal/encode/hashを照合。",
          "commit後応答喪失でsalt/親を採り直す、本文なしでSaved", "同じPreparedEntryで再照合。孤立本文は保存完了にしない", targets=("T.prepared_entry", "T.ledger_entry"))
_relation("rebuild", "同プロセスの窓口切替", (1925, 1927), ("INV-1", "INV-2.a", "INV-3", "INV-4", "INV-10.b", "INV-15"), ("rebuild_window",),
          "H/P/C/E/Runnersと原本・札・占有・認証物を保持、切替境界は不可分。旧窓口はRuntimeError。",
          "台帳だけから再構成/旧新窓口が同時に有効/作り直しで再入場", "切替前失敗は旧、切替後応答喪失は新だけが有効。run不変")
_relation("owner", "全後続の所有と未完", (613, 661), ("INV-2.a", "INV-2.b", "INV-2.c"), ("settle", "drain", "status"),
          "必要な計画と全仕事の義務を同じPublishで持つ。drainはP.workの見え方。",
          "drainで取り除き別箱へ移す途中に所有が消える", "2回drainしても同じ仕事の本体入場は1回")
_relation("transfer", "部分ごとのDirect/Transfer/残余目的", (1320, 1358), ("INV-2.a", "INV-2.c", "INV-2.g"), ("settle", "status"),
          "c0/π/a/過程/読み手/像を保持。Transfer対象A以外も所有。pのDirectは今回偽。",
          "{a,b}のaだけ引継いでbを削除/T保存でhandleとpも達成扱い", "aはTransfer、bは元担当で未達保全。T/V/save/stopは独立")
_relation("declared_derive", "δの対象と要求の対応", (623, 627), ("INV-2.d", "L-DERIVE", "INV-8"), ("I-1", "settle"),
          "δを宣言Point/版で固定しoを独立に求めMatchδ/Dischargeδで照合。",
          "全Receivedで必ず更新/発行済みqからδを逆算", "δが定めた対象と合法なまとめ方だけを要求。発行後の受信は別根")
_relation("frozen", "数値の像・認証の像・使用直前の像", (1007, 1009), ("INV-8.a", "INV-8.b", "INV-7.c", "背骨④"), ("I-3", "prepare_f_from_facts", "verify_f_math_result"),
          "Xnumは要求で固定。認証像とXuse、最初の保存計画は別。",
          "仕事が最新headsを読み古い数値入力を更新", "後着は新しい根へ。古い根の答えはその根のまま")
_relation("update_stages", "Q→Wr→R→Wp→P/Cq", (358, 382), ("INV-5.a", "INV-6.a", "INV-9.a", "INV-8"), ("I-3",),
          "WrのDTOと生成を保存。R保存後にWp。proofのためにRの取得を先に要求しない。Cqは1件。",
          "DTOに発行ハンドルを要求/各段でCqを作る/Predictionを親にする", "未認証Rを証明対象に使い、P保存後にQ/R/全Pを結ぶ1件のCq", targets=("T.request", "T.result", "T.proof", "T.completed"))
_relation("acquisition", "生成→取得 (採用なしも対象)", (340, 365), ("INV-9.a", "INV-5", "背骨②"), ("I-3", "read_f_histories_from_facts"),
          "原測定はraw.r≤a、R/全Pは対応Cq.finished_clockのg≤a≤取得通知r≤s。",
          "g=a+1なのに通知rが後だから取得を認める/兄弟取得で採用", "g=aの等号。取得までで止めても同じ条件。採用には実祖先", extra_sources=(source(FA, 188, 192),))
_relation("verify", "対象指定の認証と採用", (374, 379), ("INV-9.a", "INV-7.b", "背骨⑤"), ("I-3",),
          "Q/R/全P/Cq・ρ・bytes/digest・像・registry/checker・実返答を結ぶ。",
          "正常returnだけで成功/別対象の証明/自己申告verifiedを信用", "同一対象の発行済み認証物と実取得・前状態の一致だけ採用",
          targets=("T.target_certificate", "T.verification", "T.adopted"), status="未決", issues=("G-01",))
_relation("stale", "読み手別採用の競争", (342, 342), ("INV-9.b", "INV-6.c"), ("I-3", "settle"),
          "未保存の採用はρごとに1つ。新導出のprevious_resultを現採用のresultと照合。",
          "同じr0からQ1を採用後Q2も採用/Q2のpreviousを変更", "Q2はStale。新しいr1からQ3は進める。同導出の別意図による再採用は別の出来事")
_relation("conflict_use", "食い違いと新しい結論使用", (346, 352), ("INV-7.a", "INV-7.b", "INV-7.c"), ("I-2", "I-3", "I-8", "settle", "drain"),
          "X内の保存済み全報告の比較からClash。UseDepsへ伝播。固定済み保存とEvidenceRefsは区別。",
          "起動済み未入場で上位Conflictを知ってもEnter/小さいCIDを正本", "Conflict前の古い根は保持。Conflict後の新使用だけ止めXc/T/原報告は保存")
_relation("draw", "抽選の同じ権利・目的・値", (333, 334), ("INV-14.a", "INV-14.b", "INV-16.b", "INV-15"), ("I-8", "bind_f_draw", "evaluate_f_from_draw"),
          "generator/stream_id/purpose/context_key/ordinalで同じ権利。law/args/valueも照合。",
          "Unknown後に別WorkIdで引き直す/生成用drawをselectionへ使う", "同じPoint・同じuを保持。別の宣言済み要求は別の権利", extra_sources=(source(FA, 388),), targets=("T.draw_fact", "T.draw_returned"))
_relation("terminal", "最初の終わりと保存順・停止", (801, 809), ("INV-15.a", "INV-15.b", "INV-10.b"), ("I-3", "I-8"),
          "同runの(r,receipt_seq)最小の対応通知。先行Postの受付とfirstの保存を確認。",
          "後の値が先に保存されたのでUnknownを成功へ変更", "先行Unknownを保存後T(Unknown)。遅着は別受信。停止未確認の占有は保持")
_relation("selection", "認証されたSelectedとNoDecision", (335, 377), ("INV-16.a", "INV-16.b", "背骨④"), ("I-3", "I-8"),
          "EQ/PR/DF/EV/根/操作/全artifactが対応。SelectedだけS。NoDecisionは理由とともに保存。",
          "他問題のSelectedを接ぐ/NoDecisionやUnknownからS", "同じ根のSelectedのみS。NoDecision/Failure/Unknownは各自の保存と残務")
_relation("generation", "Qgen→実際のWg→CG→EQ", (1931, 1964), ("INV-2.g", "INV-16.c", "INV-13"), ("I-6", "I-3"),
          "生成用の像と評価用の像は別。CG PublishでEQの義務、EQの発行時だけ実入力を固定。",
          "空候補からCG/EQ/NoDecisionを捏造/後から候補を古い根へ差す", "NoCandidatesはTとpG。非空で合法なCG→別EQ。EQの文脈不足でも義務を保全")
_relation("numeric_update2", "bootstrapの/2数値射影と閉包", (482, 484), ("INV-5", "INV-7.b", "INV-9.a", "背骨⑤"), ("I-2", "I-3"),
          "segment_bindingから原測定・時計・因果・取得・結果・証明・採用・replayまでF-a実値で接続。",
          "observationsとinputsの名前一致だけで合格", "正式な/2宣言で閉包と再計算を満たす合法な実値対 (値は未接続)",
          targets=("T.finite_update2", "T.segment_binding"), status="未決", issues=("G-01",))
_relation("coverage", "contract別Supportと区間の和", (730, 759), ("INV-12.a", "INV-7.b", "INV-8"), ("I-2",),
          "X内の実在証拠と契約から同route/run/k/kindのセル集合を独立に求める。",
          "Claim自身/Started+Endedを全被覆の証拠/後の証拠で旧Xを拡大", "同じ固定Xで契約が認証したSupportの和以下だけ。端点開閉も保持",
          targets=("T.claim", "T.interval"), status="未対応", issues=("G-01",))
_relation("measurement", "8報告の境界・不明・未報告", (736, 744), ("INV-12.a", "INV-12.b", "INV-6.c"), ("I-2",),
          "Frame/Claim等の完了窓はend≤r、Unavailableは時刻を補わない。Unprovedは未来も可。",
          "無報告をGap/0/被覆に変える/Unprovedへ完了窓条件を一律適用", "未報告セルは責務、測れない報告は別の型で保持。等号end=rは合法")
_relation("segment_end", "Endedとrun/handle/stopの分離", (1420, 1454), ("C-O04.run[MeasureSegment]", "INV-12", "INV-10.b"), ("I-2",),
          "firstEndedの保存と対応証拠でrun達成。未報告セルと停止管理は別。",
          "Unavailable全区間/ホストStopだけでrun達成", "必要証拠あるEndedはStarted通知未着だけでは禁じない。未報告セルを残す")
_relation("resource", "占有・開始・解放", (836, 842), ("INV-2.e", "INV-2.f", "INV-3", "INV-10"), ("drain", "status"),
          "Need/Held/Freeを独立に計算。追加量max(Need-Held,0)。停止の実証で一回解放。",
          "同じ確保を再計上/Unknownで解放/無関係なHungで空席の開始を隠す", "保持した占有で確かな未開始の再試行。容量1なら待ち、2で前提が揃えば操作を提供")
_relation("initial_none", "空起動と感覚の独立", (249, 256), ("INV-13.a", "INV-13.b", "背骨①"), ("I-6", "I-1", "I-2"),
          "initial=NoneはWg/Ep等のbootstrap計算0。測定/受信/保存の責務は同じ。",
          "計算0と一緒に測定や受付を止める", "initialあり/なしで同じ口と報告を保持。計算の有無だけ異なる")
_relation("independence", "Hungでも受信サービス", (673, 713), ("INV-11.a", "INV-11.b", "INV-11.c", "L-RECEIPT"), ("I-1", "accept", "settle"),
          "正常性・原本・ホスト順・置き場能力が同じ状態対では計算/証明/占有を変えてもサービスの有効集合は同じ。",
          "計算が終わるまでAccept/保存を止める", "Hungでも受信は保存。置き場能力がない当該段の待ちは合法")
_relation("invariance", "時計・配送・別名・表示階層の変形", (194, 195), ("背骨③", "INV-8", "INV-16.b"), ("I-1", "I-2", "I-3", "I-8"),
          "認証測定・available・o/j・根を同じに保った変形で選び方の確率を比較。",
          "包み方/別名だけで確率が変わる", "受信件数やrは違ってよい。実際の遅着でo/jが違う対に同じ答えを要求しない")
_relation("registry_versions", "旧/1・新/2の四つの道", (479, 484), ("背骨⑤", "INV-8", "INV-16.b"), ("builtin_f_registry", "make_f_registry", "verify_f_math_result"),
          "旧/1旧registry、旧保存artifact旧bundle、新/2新registry、誤った組合せを分ける。",
          "旧不足を新bundleで補う/checker版を差替え/未知keyを現在へ置換", "旧goldenの全bytesと旧reader/registryで再読。同じ新版は新registryで使用")

# データスナップショット、紙の列挙との索引、FBT-02、FBT-03は以下。
_schema("status.receipt", "FStatusの受信の意味", "", at=1911, entries=("status",), rules=("INV-1", "INV-4"),
        branches=("受信済み", "受付済みの預かり", "保存の確認待ち", "Savedと実在Point", "確認不能"),
        use="表示の意味の枝。具体クラスやJSONタグの新規指定ではない")
_schema("status.reading", "FStatusの読みと結果の意味", "", at=1913, entries=("status",), rules=("INV-9", "INV-15", "INV-16"),
        branches=("生成まで", "取得まで", "認証まで", "採用まで", "Rejected", "Insufficient", "NoDecision", "Failure", "Unknown", "Stale", "Selected"),
        use="対象と読み手ごとに区別。確定した返答/実行の成否/未判定を一つのboolにしない")
_schema("status.evidence", "FStatusの証拠の意味", "", at=1914, entries=("status",), rules=("INV-5", "INV-7", "背骨⑤"),
        branches=("未検査", "対象つき証拠待ち", "未宣言契約", "Conflict"),
        use="不足の要求識別子と実在Pointを分ける")
_schema("all_work_stages", "Computeの用途全枝", "", at=(251, 251), entries=("I-3", "drain"),
        rules=("INV-2.c", "INV-3", "INV-15"), branches=("Wg", "Wr", "Wp", "Wv", "Ep", "Ee"),
        use="用途で終わりの後続が違う。DはI-8、MeasureSegmentはI-2で別に扱う")
_schema("receipt_sequence", "受信の順序の対応", "run envelope_number receipt_seq r event", at=1023,
        entries=("post", "accept"), rules=("INV-1.b", "INV-15.a"),
        use="論理対応欄。Envelopeの公開3欄へreceipt_seqを勝手に追加しない。Postで固定した同runの順を保持")

RULES = {
    'INV-1': {'id': 'INV-1', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 392, 'last': 392, 'read_scope': '該当部分'}], 'definition': '| INV-1 受付の保存 | `accepted(e) ⇒ same_envelope_in_P(e) ∨ saved_receipt(e)`。同じ封筒の受信の記録は 1 つ。別の封筒を 1 つに潰さない |', 'status': '採用'},
    'INV-2': {'id': 'INV-2', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 393, 'last': 393, 'read_scope': '該当部分'}], 'definition': '| INV-2 義務の欠けなし | `obligation(o) ∧ ¬settled(o) ⇒ owner(o) ∈ {H, P.receipts, P.work, P.units}`。次の仕事を伴う確定には必ず仕事表の行がある (**全部の Publish で、計画と全後続の仕事の行を同時に P.work へ置く**。P.units の works は参照の一覧で、仕事の唯一の持ち主にしない)。持ち主ゼロを許さない。義務の発生・段階・解消は §2-4-10 (1) の O 表、未完の理由は INV-2.e/2.f |', 'status': '採用'},
    'INV-3': {'id': 'INV-3', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 394, 'last': 394, 'read_scope': '該当部分'}], 'definition': '| INV-3 実行は 1 回 | `∀w: body_entries(w) ≤ 1`。開始の札の使用は 1 回、占有の解放も 1 回。要求の中身は全部の段で不変 |', 'status': '採用'},
    'INV-4': {'id': 'INV-4', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 395, 'last': 395, 'read_scope': '該当部分'}], 'definition': '| INV-4 1 点の整合 | `∀cid∈E: hash(header)=cid ∧ seal(payload,salt)=header.seal`。再試行の記録・親・salt・header は最初の準備と同じ |', 'status': '採用'},
    'INV-5': {'id': 'INV-5', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 396, 'last': 396, 'read_scope': '該当部分'}], 'definition': '| INV-5 実在する参照 | 保存する記録の本文の Point は在る点を指す。Publish の時は全後続の仕事の行を同時に置き、行の計画の中には未解決の `PlanRef` を許すが実在の Point として使わない。**仕事の開始の時**には必要な PlanRef が正しい Point へ解決され、全必要 Point が保存済みで、使用の許可が有効。台帳の親は保存済みの許された出来事で、因果は循環しない |', 'status': '採用'},
    'INV-6': {'id': 'INV-6', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 397, 'last': 397, 'read_scope': '該当部分'}], 'definition': '| INV-6 論理の 1 回 | `∀Q: count(completed(Q)) ≤ 1`。同じ測定の適用・同じ仕事の終わりの処理・同じくじの消費を届け直しで増やさない。取得や再採用の別の出来事まで無条件に 1 件に潰さない |', 'status': '採用'},
    'INV-7': {'id': 'INV-7', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 398, 'last': 398, 'read_scope': '該当部分'}], 'definition': '| INV-7 先着を正本にしない | `Conflict(X,k) ⇒ ¬Usable(X,k)`。k に依存する新しい認証・採用にも当てる。CID の小さい方・保存の早い方で解かない |', 'status': '採用'},
    'INV-8': {'id': 'INV-8', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 399, 'last': 399, 'read_scope': '該当部分'}], 'definition': '| INV-8 根の凍結 | `started(w) ⇒ descriptor(w).numerical_input_view = original_view(w)`。新しい Received は新しい根へ入れ、古い根へ混ぜない |', 'status': '採用'},
    'INV-9': {'id': 'INV-9', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 400, 'last': 400, 'read_scope': '該当部分'}], 'definition': '| INV-9 採用の条件 | `Adopted(d) ⇒ verified(target(d)) ∧ acquired_before(d, {R, proofs, raw_measurements})`。新しい導出なら `args.previous_result = result(previous_adoption)` |', 'status': '採用'},
    'INV-10': {'id': 'INV-10', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 401, 'last': 401, 'read_scope': '該当部分'}], 'definition': '| INV-10 資源 | 各資源で `Σ(Starting・Running・止まったことが未確認の占有) ≤ 有効な割り当て ≤ capacity`。Unknown・窓口の作り直し・遅着は解放の根拠にならない |', 'status': '採用'},
    'INV-11': {'id': 'INV-11', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 402, 'last': 402, 'read_scope': '該当部分'}], 'definition': '| INV-11 受付の独立 | 正常な窓口と形の正しい封筒があれば、`Accept` の有効の条件に「計算の終わり」「証明の完成」「空いた考える席」を含めない。保存できる受信の `PutBody`・`AddEntry` も同じ (背骨 ②) |', 'status': '採用'},
    'INV-12': {'id': 'INV-12', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 403, 'last': 403, 'read_scope': '該当部分'}], 'definition': '| INV-12 区間を偽らない | 認証した被覆は保存済みの区間の証拠の和以下。要求した有限の区間ごとに、記録・未完の報告の責務・証拠の不足のどれかが残り、無記録を値ゼロにしない (背骨 ①) |', 'status': '採用'},
    'INV-13': {'id': 'INV-13', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 404, 'last': 404, 'read_scope': '該当部分'}], 'definition': '| INV-13 空の起動 | `initial=None ⇒ bootstrap 由来の計算の開始の数 = 0`。測定・受信はこれと独立 |', 'status': '採用'},
    'INV-14': {'id': 'INV-14', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 405, 'last': 405, 'read_scope': '該当部分'}], 'definition': '| INV-14 くじは引き直さない | 1 つの抽選の要求につき `Draw` の本体への入場は高々 1 回。`Unknown` の後に同じ要求の仕事を出さない |', 'status': '採用'},
    'INV-15': {'id': 'INV-15', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 406, 'last': 406, 'read_scope': '該当部分'}], 'definition': '| INV-15 終わりは最初の終わりの知らせ | **仕事一般** (Wr・Wp・Wv・Ep・D・Ee)。値と不明の両方の知らせがある仕事の論理の終わりは、受付した終わりの知らせのうち `(r, receipt_seq)` が最も早いものと同じ種類。その最初の知らせの受信の記録が保存され、それより前の Post が受付処理済みであってから決める。仕事ごとの終わりと後続は §2-4-10 (5) の表 |', 'status': '採用'},
    'INV-16': {'id': 'INV-16', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 407, 'last': 407, 'read_scope': '該当部分'}], 'definition': '| INV-16 決められなかったからは選ばない | `selection` の記録は、評価の終わりが `Selected` の時だけ |', 'status': '採用'},
    'INV-1.a': {'id': 'INV-1.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 846, 'last': 846, 'read_scope': '該当部分'}], 'definition': '| INV-1.a〔F〕S:273–274,384；全封筒 | EHの全Post済みe | 状態・前後 | Postから保存まで、毎状態 | EH、EL→4.a | なし | `Post(e) ∧ ¬SavedReceipt(e) ⇒ H保持(e) ∨ P.receipts保持(e)`。Hが手放す歩ではPへの引受けまたは保存を要する |', 'status': '採用'},
    'INV-1.b': {'id': 'INV-1.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 847, 'last': 847, 'read_scope': '該当部分'}], 'definition': '| INV-1.b〔F〕S:297,319,384；再受付 | 同じeの全提示・全受付 | 状態・前後 | 最初の原本から照合情報の寿命全体 | EH、EP→4.c | なし | 同番号なら型・run・全内容・r・receipt_seq・受信記録計画が等しい時だけ同じ受付を返す。不一致なら成功を返さず原本不変 |', 'status': '採用'},
    'INV-1.c': {'id': 'INV-1.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 848, 'last': 848, 'read_scope': '該当部分'}], 'definition': '| INV-1.c〔F〕S:319,384；受信の個数 | 全eと対応する記録の集合 | 状態 | 毎状態、EL | EH、EL→4/5 | 保存途中だけ未完可 | 一般封筒は受信記録計画が1つ。`e1≠e2 ⇒ receiptId(e1)≠receiptId(e2)`。Bootの組は宣言された各slotが各1つ |', 'status': '採用'},
    'INV-2.a': {'id': 'INV-2.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 849, 'last': 849, 'read_scope': '該当部分'}], 'definition': '| INV-2.a〔F〕S:385；O-01〜14 | E0/EH/EW/ELから生じる全oと、実際の全約束 | 状態・前後 | 発生から表の解消まで。削除も対象 | E0、EH/EW、EL→4/5、O表 | 待ちでも所有は免除なし | `Required(o) ∧ ¬Settled(o) ⇒ ResponsibleOwner(o)`。所有の移行は同じ歩で次の持ち主成立。受信の所有は1.aも満たす |', 'status': '採用'},
    'INV-2.b': {'id': 'INV-2.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 850, 'last': 850, 'read_scope': '該当部分'}], 'definition': '| INV-2.b〔F〕S:298,385；全Publish | 全実際のPublishと、規範上の発行可能計画 | 前後 | Publish直後。後続の行の寿命全体 | EUとE0/EH/EW/EL。参照は5 | なし | `Publish(u) ⇒ PlannedRecords(u)=AllowedRecords(u) ∧ PromisedWorks(u)=AllowedWorks(u)`。全wの行が同時に存在し、記述・鍵が対応する |', 'status': '採用'},
    'INV-2.c': {'id': 'INV-2.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 851, 'last': 851, 'read_scope': '該当部分'}], 'definition': "| INV-2.c〔F・差替え〕S:284,333,354–369；終わりと後続の引継ぎ | 全仕事の終わり、必要なT、種類別の記録、元の目的の未完責務。未作成・削除されたものも含む | 状態・前後 | 返答の処理義務発生から、各保存・引継ぎの解消まで毎状態と全遷移 | EWの実返答、EHの最初の通知、EL、INV-4/5/15、終わりの表、O-09.a/b | 待ちは元の目的についてだけ。T等の保存義務を免除しない | `CloseSave(o) ⇒ ∀p∈RequiredEndRecords(o): Saved(p)`。必要なTを明示的に含む。Wvの採るべきInsufficient返答ではTとV(Insufficient)の保存を要する。`HandoffPurpose(o,o') ⇒ 同じ目的・過程・ρ・対象と対応する未完理由 ∧ Owner(o')`。引継ぎは保存済みの代用にならず、元の目的の達成とも数えない。全処理終了には必要な保存と後続の処理/引継ぎをともに要する |", 'status': '採用'},
    'INV-2.d': {'id': 'INV-2.d', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 852, 'last': 852, 'read_scope': '該当部分'}], 'definition': '| INV-2.d〔F・差替え〕S:235,250,298–302,325；要求導出 | δとCutから生じる全O-03のo、および対応u/q | 操作有効・状態 | N/P/Sを毎状態で区別。Nは発行直前のXuse、Pは固定済みuと実保存段 | E0のδ、EH、EL、EUとの照合、INV-4/5/7/8、WIN-PRE/SAVE-PRE | Nは対象に結んだ証拠・許可・食い違いの待ち。Pは当該保存段の前提不足だけ | Nで`ReadyN(o,s) ⇒ Enabled(PublishMatching(o))`。Pでは対応uを保持し、`SAVE-PRE(u,slot,s) ⇒ Enabled(当該slotの次の保存操作)`。NormalWindowや必要な能力がない時に有効性を要求しない。Sによる解消は`Dischargeδ(o,q)`を要する。待ちをSに変更しない |', 'status': '採用'},
    'INV-2.e': {'id': 'INV-2.e', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 853, 'last': 853, 'read_scope': '該当部分'}], 'definition': '| INV-2.e〔F・新設、v0.10 で段ごとに〕S:282,303,385,393,405；開始操作の提供 | 本来存在すべき全未開始w。別の仕事のHung、欠けた行、操作の欠落も対象 | 操作有効 | 毎状態。現在有効な許可・割り当てと独立した占有・EW の段を使用 | E0の仕事記述/資源/割り当て、EL→INV-4/5/7、EW→INV-3/10、EU→INV-2.b | 実行が選ばれないことと、操作を隠すことを分ける。別仕事のHungだけでは免除不可 | 段ごとに要求する操作を固定する: `StartReady(w,s) ∧ Stage=確保前 ∧ Fit(w,s) ⇒ Enabled(ClaimStart(w))` (ここでは Held=0) / `StartReady ∧ Stage=確保済みの起動待ち ⇒ Enabled(Launch(w))` (ClaimStart を再び要求しない) / `StartReady ∧ Stage=未開始を確かめた後の再試行 ⇒ Enabled(Launch(w))` (既存の札と占有を使う。新規の確保を要求しない) / `StartReady(w,s) ∧ Stage=起動済み・入場前 ⇒ Enabled(EnterWorker(w))` (StartReady の「担当の正常」は EnterWorker を行う係 (起動の包み) について判定する。Launch の後・入場の前に上位の食い違いが保存されれば INV-7.b で StartReady が偽になり、未使用の札と包みが残っていても新しい入場は止める。Codex `sui-fb-slip` 6 通目 FBC6-01)。SC-14の席2でDの全前提と空席が揃うのにClaimStart(D)だけがない状態は違反。通常の ClaimStart の直後に再び ClaimStart を要求しない。これはどの段でも操作の選択・完了を要求する公平性ではない (出どころ: Codex `sui-fb-slip` 5 通目 FBC5-01 の指示で Claude が書いた) |', 'status': '採用'},
    'INV-2.f': {'id': 'INV-2.f', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 854, 'last': 854, 'read_scope': '該当部分'}], 'definition': '| INV-2.f〔F・新設〕S:385,393,395,405および未完理由の契約；理由の正当性と効力 | 全未完義務について、実際に使った待ち理由・完了免除とその対象 | 状態・前後 | 理由を採用する各時点と、未完を許す各状態。理由の対象に応じた現在の状態または固定像 | E0/EH/EW/ELから理由を再計算。INV-2.a/e、INV-4/5/7/10/11/12/15 | 免除先は名指した義務の完了条件だけ。所有、T保存、固定値、参照の安全、受信保存へ伝播させない | `UseExcuse(o,b,J) ⇒ Witness(o,b) ∧ J⊆AllowedCompletionConditions(o,b)`。資源待ちなら`∃a∈RequiredResources(w): max(Need(w,a)−Held(w,a),0)>Free(a,s)` (新規の確保の待ちに限る。保持済みの占有を持つ開始前の再試行を資源不足にしない、FBC4-01)を独立に確認。食い違い待ちなら当該結論使用の依存先にConflictが必要。証拠待ちなら当該用途・像で必要なPoint/契約等が実際に不足。報告待ちなら対応仕事と未処理/未受信の報告責務が存在。停止未確認ならEWに停止確認がない。窓口・置き場待ちはWIN-PRE/SAVE-PREの該当条件が不成立。正当な理由でも別義務の完了免除には使わない |', 'status': '採用'},
    'INV-3.a': {'id': 'INV-3.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 855, 'last': 855, 'read_scope': '該当部分'}], 'definition': '| INV-3.a〔F〕S:303–305,386；全仕事 | 発生済みの全WorkId。消えた行も含む | 状態・前後 | 仕事の引受けから遅着照合まで | EWとE0、10 | なし | `body_entries(w)≤1 ∧ consumed_start_token(w)≤1`。実際の入場は有効な同一札を要する |', 'status': '採用'},
    'INV-3.b': {'id': 'INV-3.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 856, 'last': 856, 'read_scope': '該当部分'}], 'definition': '| INV-3.b〔F〕S:284,304,386；記述と再起動 | 全wの各段・起動包み | 状態・前後 | 行設置から全期間 | EU→2.b、EW、EP、8 | なし | 記述の全固定欄が初期記述と等しい。開始前と確かめた再試行だけ許す。開始不明・終わり確定後は同じwを再入場させない |', 'status': '採用'},
    'INV-3.c': {'id': 'INV-3.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 857, 'last': 857, 'read_scope': '該当部分'}], 'definition': '| INV-3.c〔F〕S:386；占有の一回性 | 全wの確保・解放履歴 | 状態・前後 | 全履歴 | EW、10.b | なし | 同じ確保を重複計上せず、同じ占有の解放は高々1回。開始前の再試行が同じ確保を保持する場合も再確保として加算しない |', 'status': '採用'},
    'INV-4.a': {'id': 'INV-4.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 858, 'last': 858, 'read_scope': '該当部分'}], 'definition': '| INV-4.a〔F〕S:300–302,387；保存整合 | 全cid∈Eと参照するCの本文 | 状態 | 毎状態 | C/E実値、E0のseal/encode/hash定義 | なし | `C[header.seal]`が存在し、`seal(payload,salt)=header.seal ∧ encode_header(record,seal,parents)=header ∧ hash(header)=cid` |', 'status': '採用'},
    'INV-4.b': {'id': 'INV-4.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 859, 'last': 859, 'read_scope': '該当部分'}], 'definition': '| INV-4.b〔F〕S:299–302,387；全再試行 | 全PreparedEntryと全再準備/保存/照合 | 状態・前後 | 初回準備から保存確認まで、後の同一書込みも対象 | EP→4.c、EL→4.a | なし | 名前・s・本文bytes・本文内参照・親集合・salt・seal・header・CIDの各欄が初回準備と等しい |', 'status': '採用'},
    'INV-4.c': {'id': 'INV-4.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 860, 'last': 860, 'read_scope': '該当部分'}], 'definition': '| INV-4.c〔F〕S:297–302；初回準備と確認 | 全初回準備、保存成功扱い、準備の削除 | 前後 | 作成/確認/削除の各歩 | E0、EH/EW、EU→2.b、EL→4.a/5 | 準備保持による待ちのみ | 初回準備は許された計画と一致。receiptのrはEH原本、sは実際の生成の読み。`ConfirmWrite/保存済扱い ⇒ C/Eとの全欄照合` |', 'status': '採用'},
    'INV-5.a': {'id': 'INV-5.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 861, 'last': 861, 'read_scope': '該当部分'}], 'definition': '| INV-5.a〔F〕S:299,374,388；記録の参照 | 全計画から準備/保存される記録の全型付きPoint | 前後 | PrepareOneと保存の直前 | EL→4、E0の型別参照一覧 | 参照不足なら当該段を待つ | `PrepareOne/Save(v) ⇒ ∀p∈BodyPoints(v): Saved(p)`。未解決PlanRefを実在Pointとして渡さない |', 'status': '採用'},
    'INV-5.b': {'id': 'INV-5.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 862, 'last': 862, 'read_scope': '該当部分'}], 'definition': '| INV-5.b〔F〕S:282,303–304,388；仕事入力 | 全約束wの必要なPointと許可 | 前後 | ClaimStart・EnterWorkerの直前 | E0の仕事別参照、EL→4/5.a、EU→2.b | 当該依存・許可待ち | `Claim/Enter(w) ⇒ 全必要Point保存済み ∧ 対応する許可が有効`。Q/R/G/PR/DFだけでなく記述の全必要参照を対象 |', 'status': '採用'},
    'INV-5.c': {'id': 'INV-5.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 863, 'last': 863, 'read_scope': '該当部分'}], 'definition': '| INV-5.c〔F〕S:374,388；親と因果 | 全保存点の全親、参照グラフ | 状態・前後 | 各追加時と毎状態 | EL→4、E0の許された出来事型 | なし | 全親が保存済みの許された出来事。結果/証明のPredictionを親にしない。因果グラフに循環なし |', 'status': '採用'},
    'INV-6.a': {'id': 'INV-6.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 864, 'last': 864, 'read_scope': '該当部分'}], 'definition': '| INV-6.a〔F〕S:332,389；completed | 期待する全q、存在する全completed | 状態 | 毎状態、当時の根 | EL→4/5、EW、O-07 | 未完はO-07で保持 | `count(completed(q))≤1`。各CのQ・R・全P・Wr開始・Wp終わりが同じ論理要求に対応 |', 'status': '採用'},
    'INV-6.b': {'id': 'INV-6.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 865, 'last': 865, 'read_scope': '該当部分'}], 'definition': '| INV-6.b〔F〕S:313–338,389；同一性 | 全論理鍵と有効報告、全処理/消費 | 状態・前後 | 各処理時の根と全履歴 | EH/EW/EL、E0比較欄；H-02 | 証拠待ちは当該鍵だけ | 同じ鍵で意味の全欄が同値なら論理処理を増やさない。測定適用、仕事の終わり、くじ消費の各権利単位で回数≤1 |', 'status': '採用'},
    'INV-6.c': {'id': 'INV-6.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 866, 'last': 866, 'read_scope': '該当部分'}], 'definition': '| INV-6.c〔F〕S:315,334,389；区別すべき出来事 | 全区間/MeasurementId/item_slot、全取得・採用意図 | 状態・前後 | 毎状態、各確定時 | EH/EA/EL、E0；H-02 | なし | 別slot・別の実際の取得意図・別読み手を内容一致だけで統合しない。測定の再配送と新しい測定を、rや受信件数で区別しない |', 'status': '採用'},
    'INV-7.a': {'id': 'INV-7.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 867, 'last': 867, 'read_scope': '該当部分'}], 'definition': '| INV-7.a〔F・共通定義に合わせ差替え〕S:313–340,390；食い違い | X内の全有効報告、同じ論理鍵の組、宣言済み排他単位を共有する異なる鍵の組 | 状態・前後 | 毎状態とX記録発行時。指定された固定像Xを使用 | EL→INV-4/5、E0の全比較欄と相互排他規則、H-02 | X保存待ちは使用の免除にしない | `Conflict(X,k) ⇔ ∃c∈Clashes(X): k∈affected(c)`。X記録の発行にはその報告Point・規則・全比較内容の対応を要する。同値再配送だけ、またはUnknown＋値だけではXを作らない。同値の結果でも生成の読み等が異なる場合、および同sample_seq・異MeasurementIdの排他違反を落とさない |', 'status': '採用'},
    'INV-7.b': {'id': 'INV-7.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 868, 'last': 868, 'read_scope': '該当部分'}], 'definition': '| INV-7.b〔F・差替え〕S:342–346,390,401；新しい結論使用 | 全新規Publish/開始/認証使用/取得/採用のUseDepsと、その依存先に影響する排他単位。証拠参照も種類を検査 | 前後 | 新しい使用・確定直前のXuse。固定済み記録の保存再試行と区別 | 更新したINV-7.a、EL→INV-4/5、E0の型付き依存関係、H-02 | 当該結論使用の完了だけ止められる。Xや不足の記録、受信保存まで禁止しない | `∃k∈UseDeps(v): Conflict(Xuse(v),k) ⇒ ¬PermitNewUse(v)`。食い違い・不足を記録するvが当該報告をEvidenceRefsとして指すだけなら、この禁止をその参照だけから適用しない。ただし証拠Pointの保存・内容一致・記録する食い違い/不足の事実は検査する。Wr/Wp/Ep/D等の上位の結論使用依存には禁止を伝える |', 'status': '採用'},
    'INV-7.c': {'id': 'INV-7.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 869, 'last': 869, 'read_scope': '該当部分'}], 'definition': '| INV-7.c〔F〕S:343–344；後着 | 既存の確定と、その後の報告追加 | 前後 | 確定時の根を保持 | EL、EP、8 | なし | 後着で既存記録と固定根を改変しない。古いX0の再読結果を変えない。新しい使用では新しい食い違いを検査 |', 'status': '採用'},
    'INV-8.a': {'id': 'INV-8.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 870, 'last': 870, 'read_scope': '該当部分'}], 'definition': '| INV-8.a〔F〕S:325,391；根の固定 | 全qとそのWr/Wp/Wv、全評価仕事 | 状態・前後 | 要求確定から仕事の全寿命 | E0の本来の入力対応、EU→2.b、EL | なし | 各段の数値入力像がXnum(q)と等しい。要求・入力・前の結果・方法/版の対応を全期間比較 |', 'status': '採用'},
    'INV-8.b': {'id': 'INV-8.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 871, 'last': 871, 'read_scope': '該当部分'}], 'definition': '| INV-8.b〔F〕S:279,391；実際に読む根 | EWの全本体入場・入力読取り | 前後 | 各実読取り時 | EWと8.aの期待値 | なし | `ActualNumericalInput(w)=ExpectedNumericalInput(q,stage)`。新しいReceivedを既存入力へ混入させない。認証証拠像の追加と数値入力変更を区別 |', 'status': '採用'},
    'INV-9.a': {'id': 'INV-9.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 872, 'last': 872, 'read_scope': '該当部分'}], 'definition': '| INV-9.a〔F〕S:335,359,366–371,392；認証返答・V・取得・採用 | 全Vの発行/保存、全Adopted、対応する実認証呼出しと返答、実取得。Vまたは採用が存在する場合に、その対応元の欠落も検査 | 前後・状態 | V発行時と採用確定直前。認証に使った固定像と、採用直前のXuseを区別。保存済みVも対応を保持 | EW/EAで独立に観測した認証の対象と返答、EL→INV-4/5、INV-7/8/15、H-03 | 不足・拒否・Unknownは当該採用を禁止/保留する理由。成功の代用にはならない | `Publish(V) ⇒ Vの返答内容=対応する実認証返答の正準内容`。比較するのはWorkId、Q/R/P/Cと全証明、ρ、対象bytes/digest、入力、根拠閉包、検査像、registry/checker版、返答の種類、結果・理由・不足対象・発行物との対応。`Adopted(d) ⇒ 実認証返答が当該対象について認証成功 ∧ Vも同じ成功内容 ∧ 当該対象に結んだ有効な発行済み認証物 ∧ dの対象との全対応一致 ∧ INV-15の終わりと整合`。さらに元の測定/R/全Pの実取得が当該ρによる採用以前の出来事であり、必要な実祖先を持つことを要する。呼出しが正常終了しただけ、対象が一致するだけ、Vのsuccess印だけでは認証成功としない |', 'status': '採用'},
    'INV-9.b': {'id': 'INV-9.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 873, 'last': 873, 'read_scope': '該当部分'}], 'definition': '| INV-9.b〔F〕S:336,392；系列とStale | 全ρ、全採用計画、前の採用と結果 | 状態・前後 | 計画確定から保存までρごとの予約を保持 | EA/EL、Qの引数→8 | 他のρへ待ちを波及させない | 新導出なら`Q.previous_result=result(current_adoption(ρ))`。不一致ならStaleでAdoptedなし。ρごとの未保存採用単位は高々1 |', 'status': '採用'},
    'INV-10.a': {'id': 'INV-10.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 874, 'last': 874, 'read_scope': '該当部分'}], 'definition': '| INV-10.a〔F〕S:284,393；容量 | 全資源と全wの実際の確保・解放 | 状態 | 毎状態。削除された行の占有も含む | EW、E0の容量/割当、3 | 当該資源不足は開始完了だけ免除 | `占有=実確保−正当な解放`。各資源で`Σ占有≤有効割当≤capacity`。窓口のphaseの数だけで代用しない |', 'status': '採用'},
    'INV-10.b': {'id': 'INV-10.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 875, 'last': 875, 'read_scope': '該当部分'}], 'definition': '| INV-10.b〔F〕S:284,393；解放 | 全解放遷移 | 前後 | 各解放直前 | EWのStop/確かな未開始、3.c | 停止未確認なら占有保持 | `Release(w) ⇒ 停止確認または確かな未開始終了 ∧ 未解放`。Unknown・返答保存・Rebuild・遅着だけでは解放不可 |', 'status': '採用'},
    'INV-11.a': {'id': 'INV-11.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 876, 'last': 876, 'read_scope': '該当部分'}], 'definition': '| INV-11.a〔F〕S:394；受付 | 全正常状態のHostEligibleなe | 操作有効 | 初期と再建後を含む毎状態 | EH、環境の正常性/型、E0 | 後方の封筒はホスト順待ちのみ | `Normal ∧ WellFormed(e) ∧ Eligible(e) ∧ ¬Accepted(e) ⇒ Enabled(Accept(e))`。受付後は必要なHostAckも有効 |', 'status': '採用'},
    'INV-11.b': {'id': 'INV-11.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 877, 'last': 877, 'read_scope': '該当部分'}], 'definition': '| INV-11.b〔F〕S:299–302,394；受信保存 | 全受付済みeと保存段 | 操作有効 | 毎状態、実C/Eと準備状態 | EP/EL→4、環境の能力 | 置き場能力がない当該段だけ | 段階表の前提なら、その段のPrepare/PutBody/Confirm/AddEntryが有効。本文保存前のAddEntryを要求しない |', 'status': '採用'},
    'INV-11.c': {'id': 'INV-11.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 878, 'last': 878, 'read_scope': '該当部分'}], 'definition': '| INV-11.c〔F〕S:394；計算からの独立 | 受信関連状態が等しく計算関連状態だけ違う状態対 | 状態間の関係 | 全該当状態対、または同じガードの構造検査 | 11.a/bの入力射影、E0；H-05 | なし | 受付/保存サービス操作の有効集合が等しい。操作のガードがFinish・証明完成・空席を参照しない |', 'status': '採用'},
    'INV-12.a': {'id': 'INV-12.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 879, 'last': 879, 'read_scope': '該当部分'}], 'definition': '| INV-12.a〔F・差替え〕S:321–338,395；区間・報告・被覆 | 全要求k、全報告、全認証被覆kind、その認証で使うXと証拠参照 | 状態・前後 | 報告結合/被覆認証時と毎状態。既存認証は当時のXで再照合 | X内のEL→INV-4/5、EIによる対応事実の照合、有限対応表、A-13〜15、H-04 | 不足は当該区間・用途の使用だけ保留。原報告の保存と責務の保持は継続 | route/run/要求/slot/MeasurementId/sample_seq/端/開閉/適用/開始/生成/時計を比較。Frameと全Claimは`start≤end≤r`。Frameのactual_timeがUnavailableなら実測時刻を要する使用を許さない。Claimは完了窓条件と契約別生成条件を別々に満たす。`EvidenceRefs⊆VisibleSavedPoints(X)`かつ、被覆は同じXの認証済みSupportの和以下。後から増えたEIだけで古いXのSupportを拡大しない |', 'status': '採用'},
    'INV-12.b': {'id': 'INV-12.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 880, 'last': 880, 'read_scope': '該当部分'}], 'definition': '| INV-12.b〔F〕S:395；未報告部分 | 要求区間の全セル。報告なしも対象 | 状態 | 毎状態。待機状態も同じ | E0/EI、O-04/13、2.a | 実在する報告責務による待ち可 | 全セルに報告・責務・根拠付き不足/食い違いが対応。`NoReport`からGap・ゼロ測定・被覆を作らない |', 'status': '採用'},
    'INV-13.a': {'id': 'INV-13.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 881, 'last': 881, 'read_scope': '該当部分'}], 'definition': '| INV-13.a〔F〕S:250,396；空の起動 | 全bootstrap由来の計算仕事と入場履歴 | 状態・前後 | 全実行 | E0のinitial、EW、2.b | なし | `initial=None ⇒ bootstrap由来の計算仕事の発行/本体入場=0`。MeasureSegmentと受信は計算仕事に混ぜない |', 'status': '採用'},
    'INV-13.b': {'id': 'INV-13.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 882, 'last': 882, 'read_scope': '該当部分'}], 'definition': '| INV-13.b〔F〕S:250,396；測定の独立 | 同じ口/区間/受信でinitialだけ異なる対照 | 状態間の関係 | 初期と各対応状態 | E0/EI、11/12 | 測定自身の理由だけ | initialなしを理由に口・区間要求・受付・保存の責務や有効操作を消さない |', 'status': '採用'},
    'INV-14.a': {'id': 'INV-14.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 883, 'last': 883, 'read_scope': '該当部分'}], 'definition': '| INV-14.a〔F〕S:327,397；Drawの権利 | 全Draw要求。別WorkIdへの付け替えも合算 | 状態・前後 | 要求固定から全期間 | E0のDraw式、EW、EL、3/8 | 報告待ちのみ | 要求のgenerator・stream_id・purpose・context_key・ordinalと法則等の宣言欄が固定。`Σbody_entries(w for same Draw request)≤1` |', 'status': '採用'},
    'INV-14.b': {'id': 'INV-14.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 884, 'last': 884, 'read_scope': '該当部分'}], 'definition': '| INV-14.b〔F〕S:327,397；再抽選禁止 | Unknown/失敗/遅着後の全Draw開始 | 前後 | 各新規開始・計画 | 14.a、15、EW | 不足は再抽選の許可にならない | 同じDraw要求を別WorkId/別札で再発行・再入場しない。同根精密化は同じDraw Pointと値を保持 |', 'status': '採用'},
    'INV-15.a': {'id': 'INV-15.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 885, 'last': 885, 'read_scope': '該当部分'}], 'definition': '| INV-15.a〔F〕S:296–297,327,398；最初の知らせ | Wr/Wp/Wv/Ep/D/Eeの全終わりの知らせ | 状態・前後 | 各終わりの確定直前 | EH→1、EL→4、順序表 | 最初の受信未保存なら待つ | `first(w)=argmin(r,receipt_seq)`。受付前方範囲が確定し、`SavedReceipt(first(w))`。本文のWorkId/要求/段/出どころが対応 |', 'status': '採用'},
    'INV-15.b': {'id': 'INV-15.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 886, 'last': 886, 'read_scope': '該当部分'}], 'definition': '| INV-15.b〔F〕S:333,398；種類の固定 | 全T/R/PR/DF/DU/EVとその後続 | 状態・前後 | 最初の確定から全期間 | 15.a、EW、終わりの表、7 | 当該段の証拠待ち/食い違いのみ | 論理の終わりは最初の知らせの種類と一致し、後着で上書きしない。Unknownから成功記録を生成しない。Xは独立の証拠を要する |', 'status': '採用'},
    'INV-16.a': {'id': 'INV-16.a', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 887, 'last': 887, 'read_scope': '該当部分'}], 'definition': '| INV-16.a〔F〕S:328–329,399；選ぶ | 全selection。存在すべき対応評価も対象 | 前後・状態 | selection確定時と保存後 | EL、EW/EA、15、H-03 | NoDecision等はselectionなしで終了可 | `selection ⇒ 対応する保存済み評価の返答が認証されたSelected`。NoDecision/Unknown/Failure/不足からは生成しない |', 'status': '採用'},
    'INV-16.b': {'id': 'INV-16.b', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 888, 'last': 888, 'read_scope': '該当部分'}], 'definition': '| INV-16.b〔F〕S:326–329,368–369；対象の対応 | 評価要求・PR・artifact・problem・Draw・EV・selection | 前後 | 準備/評価/選択の各確定時の根 | E0、EL、EW、4/5/7/8 | 対応不足は当該段だけ待つ | 要求入力・処理/版・Xnum・artifact bytes/digest・problem_key・Drawのpurpose/context/Point/値が対応。別問題のPR/Draw/Selectedを流用しない |', 'status': '採用'},
    'L-RECEIPT': {'id': 'L-RECEIPT', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 676, 'last': 676, 'read_scope': '該当部分'}], 'definition': '| L-RECEIPT | L-ENV・L-HOST・L-FAIRを満たす全実行で、正常にPostされた各eについて`Post(e) ⇒ F SavedReceipt(e)`。Accept前のeも含む。Bootの受信が記録の組を約束する場合は、その組の保存を結論にする。 |', 'status': '採用'},
    'L-DERIVE': {'id': 'L-DERIVE', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 690, 'last': 690, 'read_scope': '該当部分'}], 'definition': '| L-DERIVEの対象 | O-03の各o。公平性の単位は、要求番号がまだないN段では`PublishMatching(o)`とする。これは`Matchδ(o,u)`を満たす計画を発行する操作群である。許されたGを一度に発行した場合は、Gに属する各oの操作として数える。P段では、固定済みuの各記録slotの準備・保存・確認を単位とする。 |', 'status': '採用'},
    'L-ENV': {'id': 'L-ENV', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 673, 'last': 673, 'read_scope': '該当部分'}], 'definition': '| L-ENV | 同じホストプロセスが続く。窓口の例外は有限回で、最後の例外後に正常な窓口が再建される。必要な置き場は最終的に利用可能になり、その後の書込み・読戻しが永遠に失敗し続けない。模型ではcommit前失敗・応答喪失に有限予算を与え、正常成功は予算0でも可能とする。成功する枝が存在するだけでは、成功を永久に選ばない実行を除けない。 |', 'status': '採用'},
    'L-HOST': {'id': 'L-HOST', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 674, 'last': 674, 'read_scope': '該当部分'}], 'definition': '| L-HOST | 受信順を守って処理する場合、各eの前には有限個の封筒しかなく、先頭の受付・引受け確認・次の封筒への移行が公平に選ばれる。外形不正な先頭を扱う場面では、その拒否処理も対象に含める。拒否処理を未収録なら、その場面の受信進行性は未対応とする。 |', 'status': '採用'},
    'L-FAIR': {'id': 'L-FAIR', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 675, 'last': 675, 'read_scope': '該当部分'}], 'definition': '| L-FAIR | 操作の種類だけでなく、対象を含む単位aごとの弱い公平性を仮定する。`FG Enabled(a) ⇒ GF Taken(a)`。対象は必要に応じて`Accept(e)`、`HostAck(e)`、`PrepareReceipt(e)`、`PutBody(e)`、`ConfirmBody(e)`、`AddEntry(e)`、`ConfirmWrite(e)`。内部段をまとめた模型は、その対応を明記する。 |', 'status': '採用'},
    'L-DERIVE.N': {'id': 'L-DERIVE.N', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 693, 'last': 693, 'read_scope': '該当部分'}], 'definition': '| L-DERIVE.N：発行の保証 | 未発行のoについて、StableNと`PublishMatching(o)`の弱い公平性が成立すれば、対応する合法なPublishがいずれ行われる。一時的に発行可能だったというだけでは保証しない。前提が繰り返し成立するだけの場合も、弱い公平性から発行を要求しない。 |', 'status': '採用'},
    'L-DERIVE.P': {'id': 'L-DERIVE.P', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 695, 'last': 695, 'read_scope': '該当部分'}], 'definition': '| L-DERIVE.P：保存の保証 | 合法な対応計画uをPublish済みなら、その固定した記録列について、必要な依存が保存済みまたは同じ計画内の有限で循環しない保存列として揃い、L-ENVの回復・保存成功の前提と各保存段の弱い公平性が成立する時、対応qはいずれ保存され`Dischargeδ(o,q)`が成立する。 |', 'status': '採用'},
    'C-O01.save[receipt_slot]': {'id': 'C-O01.save[receipt_slot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1534, 'last': 1534, 'read_scope': '該当部分'}], 'definition': '| C-O01.save[receipt_slot] | EH原本に対応する各受信slotのSV。Bootは各2slotを独立判定。 | 済み | 紙、S:572,626,1016,1200。 |', 'status': '採用'},
    'C-O02.issue[initial]': {'id': 'C-O02.issue[initial]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1535, 'last': 1535, 'read_scope': '該当部分'}], 'definition': '| C-O02.issue[initial] | 宣言どおりの初期記録と全初期仕事行のPUB。 | 済み | 紙、S:320,627,651,843,1201。 |', 'status': '採用'},
    'C-O02.save[各slot]': {'id': 'C-O02.save[各slot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1536, 'last': 1536, 'read_scope': '該当部分'}], 'definition': '| C-O02.save[各slot] | 宣言された初期計画の各slotのSV。 | 済み | 紙、S:627,1196,1202。 |', 'status': '採用'},
    'C-O03.issue[Q]': {'id': 'C-O03.issue[Q]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1537, 'last': 1537, 'read_scope': '該当部分'}], 'definition': '| C-O03.issue[Q] | 対応uのPUBかつMatchδ(o,u)。 | 済み | 紙、S:616–619,646,1203。 |', 'status': '採用'},
    'C-O03.save[Q]': {'id': 'C-O03.save[Q]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1538, 'last': 1538, 'read_scope': '該当部分'}], 'definition': '| C-O03.save[Q] | Dischargeδ(o,q)。各oについて個別に判定。 | 済み | 紙、S:620,628,845,1204。 |', 'status': '採用'},
    'C-O04.save[k]': {'id': 'C-O04.save[k]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1539, 'last': 1539, 'read_scope': '該当部分'}], 'definition': '| C-O04.save[k] | 当該route・過程・segment_slotに対応するkのSV。 | 済み | 紙、S:321,629,1019,1205。 |', 'status': '採用'},
    'C-O04.run[MeasureSegment]': {'id': 'C-O04.run[MeasureSegment]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1540, 'last': 1540, 'read_scope': '該当部分'}], 'definition': '| C-O04.run[MeasureSegment] | SegmentEndKnown(k,w)。 | 済み | D1＋紙、S:322,731,794–800,1187–1188。本節第4項。 |', 'status': '採用'},
    'C-O04.handle[cells]': {'id': 'C-O04.handle[cells]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1541, 'last': 1541, 'read_scope': '該当部分'}], 'definition': '| C-O04.handle[cells] | 固定した各セルc@aのDirect/Transfer/未達保全を個別判定して第3項の規則で集約する。残余目的pは別に未達・実所有を保持。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:629,754–763,1207。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O05.run[Wr]': {'id': 'C-O05.run[Wr]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1542, 'last': 1542, 'read_scope': '該当部分'}], 'definition': '| C-O05.run[Wr] | EndKnown(Wr)。 | 済み | 紙、S:1187–1188,1208。 |', 'status': '採用'},
    'C-O05.save[T]': {'id': 'C-O05.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1543, 'last': 1543, 'read_scope': '該当部分'}], 'definition': '| C-O05.save[T] | 最初のWr返答に対応するTのSV。 | 済み | 紙、S:630,769,777,1044,1209。 |', 'status': '採用'},
    'C-O05.handle[Wr]': {'id': 'C-O05.handle[Wr]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1544, 'last': 1544, 'read_scope': '該当部分'}], 'definition': '| C-O05.handle[Wr] | 成功生成ならO-06.issueへ、非成功・不足等なら対応処理と同じ識別のpを保持する担当へTransfer。pのDirectは今回偽。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:630–631,777,786,1209。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O06.issue[R]': {'id': 'C-O06.issue[R]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1545, 'last': 1545, 'read_scope': '該当部分'}], 'definition': '| C-O06.issue[R] | Q・Wr・first・Genに対応するRのPUBと同時Wp行。 | 済み | 紙、S:631,647,1000–1001,1026–1027,1210。 |', 'status': '採用'},
    'C-O06.save[R]': {'id': 'C-O06.save[R]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1546, 'last': 1546, 'read_scope': '該当部分'}], 'definition': '| C-O06.save[R] | RのSVと、同じPublishで設置したWp行の対応。 | 済み | 紙、S:631,647,1211。 |', 'status': '採用'},
    'C-O07.run[Wp]': {'id': 'C-O07.run[Wp]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1547, 'last': 1547, 'read_scope': '該当部分'}], 'definition': '| C-O07.run[Wp] | EndKnown(Wp)。 | 済み | 紙、S:1187–1188,1212。 |', 'status': '採用'},
    'C-O07.save[T]': {'id': 'C-O07.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1548, 'last': 1548, 'read_scope': '該当部分'}], 'definition': '| C-O07.save[T] | 最初のWp返答に対応するTのSV。非成功も対象。 | 済み | 紙、S:632,778,786,1213。 |', 'status': '採用'},
    'C-O07.handle[Wp]': {'id': 'C-O07.handle[Wp]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1549, 'last': 1549, 'read_scope': '該当部分'}], 'definition': '| C-O07.handle[Wp] | 成功生成ならP/Cqのissueへ、非成功等なら対応処理と未完証明目的pの担当へTransfer。未発生P/Cqを作らず、pのDirectは今回偽。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:632,778,786,1213–1215。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O07.issue[P,Cq]': {'id': 'C-O07.issue[P,Cq]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1550, 'last': 1550, 'read_scope': '該当部分'}], 'definition': '| C-O07.issue[P,Cq] | 対応P/Cqの計画のPUB。Q/R・statement/checker・Genを照合し、Cq準備はP保存後。 | 済み | 紙、S:357–358,632,1028–1031,1214。 |', 'status': '採用'},
    'C-O07.save[P]': {'id': 'C-O07.save[P]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1551, 'last': 1551, 'read_scope': '該当部分'}], 'definition': '| C-O07.save[P] | 当該PのSV。 | 済み | 紙、S:632,778,1028–1029,1215。 |', 'status': '採用'},
    'C-O07.save[Cq]': {'id': 'C-O07.save[Cq]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1552, 'last': 1552, 'read_scope': '該当部分'}], 'definition': '| C-O07.save[Cq] | Q/R/全Pと生成時計が対応する、Qにつきただ1つのCqのSV。 | 済み | 紙、S:358,391,1030–1031,1084,1215。 |', 'status': '採用'},
    'C-O08.handle[取得意図]': {'id': 'C-O08.handle[取得意図]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1553, 'last': 1553, 'read_scope': '該当部分'}], 'definition': '| C-O08.handle[取得意図] | 実取得対応と、Gの合法なPUBに伴う所定のG引継ぎ。 | 済み | 紙、S:633–635,648,1216。本節第3項。 |', 'status': '採用'},
    'C-O08.issue[G]': {'id': 'C-O08.issue[G]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1554, 'last': 1554, 'read_scope': '該当部分'}], 'definition': '| C-O08.issue[G] | EAの実取得に対応するGのPUBと同時Wv行。 | 済み | 紙、S:633,648,1032–1033,1216。 |', 'status': '採用'},
    'C-O08.save[G]': {'id': 'C-O08.save[G]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1555, 'last': 1555, 'read_scope': '該当部分'}], 'definition': '| C-O08.save[G] | GのSVと所定のG引継ぎの成立。 | 済み | 紙、S:633–635,1217。 |', 'status': '採用'},
    'C-O09a.run[Wv]': {'id': 'C-O09a.run[Wv]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1556, 'last': 1556, 'read_scope': '該当部分'}], 'definition': '| C-O09a.run[Wv] | EndKnown(Wv)。 | 済み | 紙、S:1187–1188,1218。 |', 'status': '採用'},
    'C-O09a.save[T]': {'id': 'C-O09a.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1557, 'last': 1557, 'read_scope': '該当部分'}], 'definition': '| C-O09a.save[T] | 最初のWv返答に対応するTのSV。 | 済み | 紙、S:634,779,784,1219。 |', 'status': '採用'},
    'C-O09a.save[V]': {'id': 'C-O09a.save[V]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1558, 'last': 1558, 'read_scope': '該当部分'}], 'definition': '| C-O09a.save[V] | Vが発生した実認証返答枝について、EA/EWの返答と全欄対応するVのSV。Insufficientも対象。 | 済み | 紙、S:634,784,865,1034,1219。 |', 'status': '採用'},
    'C-O09b.handle[目的]': {'id': 'C-O09b.handle[目的]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1559, 'last': 1559, 'read_scope': '該当部分'}], 'definition': '| C-O09b.handle[目的] | A/ST/拒否等の対応処理保存は局所Direct。未完目的への移管はTransfer。既発生pはどちらでも解消せず、同じ目的・対象と実所有を保持。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:635,779,784,1220–1221,1272。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O09b.save[処理slot]': {'id': 'C-O09b.save[処理slot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1560, 'last': 1560, 'read_scope': '該当部分'}], 'definition': '| C-O09b.save[処理slot] | 発生した当該処理計画の各slotのSV。W保存は目的達成にしない。 | 済み | 紙、S:635,1036–1037,1045–1046,1221。 |', 'status': '採用'},
    'C-O10.run[Ep]': {'id': 'C-O10.run[Ep]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1561, 'last': 1561, 'read_scope': '該当部分'}], 'definition': '| C-O10.run[Ep] | run自身はEndKnown(Ep)。第3項でこの実体に結び付けた既存O-10の残余目的pは、runと別に未達・実所有を保持。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:636,780,786,844,1187–1188,1222。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O10.save[T]': {'id': 'C-O10.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1562, 'last': 1562, 'read_scope': '該当部分'}], 'definition': '| C-O10.save[T] | 最初のEp返答に対応するTのSV。 | 済み | 紙、S:636,780,1223。 |', 'status': '採用'},
    'C-O10.issue[artifact,PR]': {'id': 'C-O10.issue[artifact,PR]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1563, 'last': 1563, 'read_scope': '該当部分'}], 'definition': '| C-O10.issue[artifact,PR] | 対応する発行物・Ep返答・EQ・根・処理によるartifact/PRのPUB。FProblemだけ同時D行。 | 済み | 紙、S:636,649,652,780,1038,1224。 |', 'status': '採用'},
    'C-O10.save[artifact,PRの各slot]': {'id': 'C-O10.save[artifact,PRの各slot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1564, 'last': 1564, 'read_scope': '該当部分'}], 'definition': '| C-O10.save[artifact,PRの各slot] | 発生したartifact、PRの各slotのSV。 | 済み | 紙、S:636,1196,1225。 |', 'status': '採用'},
    'C-O11.run[D]': {'id': 'C-O11.run[D]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1565, 'last': 1565, 'read_scope': '該当部分'}], 'definition': '| C-O11.run[D] | run自身はEndKnown(D)。第3項でこの実体に結び付けた既存の残余目的pは、runと別に未達・実所有を保持。値の再生成・同Drawの再実行は要求しない。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:637,781,786,844,1187–1188,1226。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O11.save[T]': {'id': 'C-O11.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1566, 'last': 1566, 'read_scope': '該当部分'}], 'definition': '| C-O11.save[T] | 最初のD返答に対応するTのSV。 | 済み | 紙、S:637,781,1227。 |', 'status': '採用'},
    'C-O11.issue[DF/DU]': {'id': 'C-O11.issue[DF/DU]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1567, 'last': 1567, 'read_scope': '該当部分'}], 'definition': '| C-O11.issue[DF/DU] | 値枝は対応DFのPUBと同時Ee行。Unknown枝は対応DUのPUB。各枝の要求全欄・first・発行直前の使用条件を満たす。 | 済み | 紙、S:637,650,781,1039–1041,1228。 |', 'status': '採用'},
    'C-O11.save[DF/DU/別の必須終わりslot]': {'id': 'C-O11.save[DF/DU/別の必須終わりslot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1568, 'last': 1568, 'read_scope': '該当部分'}], 'definition': '| C-O11.save[DF/DU/別の必須終わりslot] | 当該枝で発生した各slotのSV。TだけのFailureに重複記録を要求しない。 | 済み | 紙、S:637,781,1192,1229。 |', 'status': '採用'},
    'C-O12.run[Ee]': {'id': 'C-O12.run[Ee]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1569, 'last': 1569, 'read_scope': '該当部分'}], 'definition': '| C-O12.run[Ee] | EndKnown(Ee)。 | 済み | 紙、S:1187–1188,1230。 |', 'status': '採用'},
    'C-O12.save[T]': {'id': 'C-O12.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1570, 'last': 1570, 'read_scope': '該当部分'}], 'definition': '| C-O12.save[T] | 最初のEe返答に対応するTのSV。 | 済み | 紙、S:638,782,1231。 |', 'status': '採用'},
    'C-O12.handle[評価の終わり]': {'id': 'C-O12.handle[評価の終わり]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1571, 'last': 1571, 'read_scope': '該当部分'}], 'definition': '| C-O12.handle[評価の終わり] | 確定artifactならartifact/EVのissueへ、それ以外の未完は対応処理とpを保持する担当へTransfer。Selectedに限るSへの接続を保持。pは局所解消後も未達。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:638,782,786,1231–1234。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O12.issue[artifact,EV]': {'id': 'C-O12.issue[artifact,EV]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1572, 'last': 1572, 'read_scope': '該当部分'}], 'definition': '| C-O12.issue[artifact,EV] | 対応する確定artifactとEQ/PR/Draw/根によるartifact/EVのPUB。 | 済み | 紙、S:638,782,881,1042,1232。 |', 'status': '採用'},
    'C-O12.issue[S]': {'id': 'C-O12.issue[S]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1573, 'last': 1573, 'read_scope': '該当部分'}], 'definition': '| C-O12.issue[S] | 保存済み対応EV、認証されたSelected、根・Draw・要求が一致するSのPUB。 | 済み | 紙、S:329,880–881,1043,1233。 |', 'status': '採用'},
    'C-O12.save[artifact,EV,Sの各slot]': {'id': 'C-O12.save[artifact,EV,Sの各slot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1574, 'last': 1574, 'read_scope': '該当部分'}], 'definition': '| C-O12.save[artifact,EV,Sの各slot] | 発生した各slotのSV。S不要枝にSを要求しない。 | 済み | 紙、S:638,1196,1234。 |', 'status': '採用'},
    'C-O13.handle[報告/鍵/根]': {'id': 'C-O13.handle[報告/鍵/根]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1575, 'last': 1575, 'read_scope': '該当部分'}], 'definition': '| C-O13.handle[報告/鍵/根] | 対応するB/Xc/不足処理のsave担当または処理責務へTransfer。受け取ったpの発生元・対象を維持し、処理・保存と別に未達・実所有を保持。 | 済み（残余目的の解消枝のみ範囲外★） | 紙、S:639,760–763,1045–1048,1235–1236。本節第2・3項、D3。 |', 'status': '採用'},
    'C-O13.save[処理slot]': {'id': 'C-O13.save[処理slot]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1576, 'last': 1576, 'read_scope': '該当部分'}], 'definition': '| C-O13.save[処理slot] | 対応する処理計画の各slotのSV。 | 済み | 紙、S:639,1045–1048,1236。 |', 'status': '採用'},
    'C-O14.stop[w]': {'id': 'C-O14.stop[w]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1577, 'last': 1577, 'read_scope': '該当部分'}], 'definition': '| C-O14.stop[w] | 今回範囲はStopDone(w)。確保前は条件を保持する。未確保取消しによる解消は★W-45の外付け追加時へ送る。 | 済み。未確保取消し枝のみ範囲外★ | D2＋紙、S:119,640,850,868,1237,1277。本節第5項。 |', 'status': '採用'},
    'C-OG.run[Wg]': {'id': 'C-OG.run[Wg]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1942, 'last': 1942, 'read_scope': '該当部分'}], 'definition': '| C-OG.run[Wg] | 初期計画で Wg を約束した時 | EndKnown(Wg) | 終わりの代わりの Transfer は認めない。Wg 行が保持 | 返答前の元目的。EndKnown で T の保存と handle が同時に発生。停止は O-14 |', 'status': '採用'},
    'C-OG.save[T]': {'id': 'C-OG.save[T]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1943, 'last': 1943, 'read_scope': '該当部分'}], 'definition': '| C-OG.save[T] | EndKnown(Wg) | 対応する T の SV | 保存の担当を移せても未保存を達成扱いにしない | handle、CG/EQ、pG、停止 |', 'status': '採用'},
    'C-OG.handle[Wg]': {'id': 'C-OG.handle[Wg]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1944, 'last': 1944, 'read_scope': '該当部分'}], 'definition': '| C-OG.handle[Wg] | EndKnown(Wg) | 直接の達成の枝を置かず、下の枝の表の Transfer で局所解消 | 非空の成功は CG の発行の実担当へ、非成功・具体的な不足は対象つきの残余目的の実担当へ | T の保存、既発生の issue/save、pG、停止。引受けの前は元の担当が保持 |', 'status': '採用'},
    'C-OG.issue[CG]': {'id': 'C-OG.issue[CG]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1945, 'last': 1945, 'read_scope': '該当部分'}], 'definition': '| C-OG.issue[CG] | 最初の返答と生成の要求が対応し、非空の CG の生成条件が成立した時 | 合法な CG の PUB と、save[CG]・issue[EQ] の同時の所有の成立 | 発行の前は Wg 行か引受け済みの生成の継続の担当 | 前提を後で失っても発生済みの条件は残る |', 'status': '採用'},
    'C-OG.save[CG]': {'id': 'C-OG.save[CG]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1946, 'last': 1946, 'read_scope': '該当部分'}], 'definition': '| C-OG.save[CG] | CG の Publish | 対応する CG の SV | CG の保存の実担当 | issue[EQ]、pG、その他の保存。CG の保存だけで生成側を解消しない |', 'status': '採用'},
    'C-OG.issue[EQ]': {'id': 'C-OG.issue[EQ]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1947, 'last': 1947, 'read_scope': '該当部分'}], 'definition': '| C-OG.issue[EQ] | 合法な CG の Publish (CG 未保存・文脈不足の時点を含む) | 合法な EQ の PUB と、Ep 行・C-O10.run・元目的の引受けの同時の成立 | 発行の前は生成の継続の P.units | save[EQ]、Ep 以降、既発生の pG。発行できない間も条件を消さない |', 'status': '採用'},
    'C-OG.save[EQ]': {'id': 'C-OG.save[EQ]', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1948, 'last': 1948, 'read_scope': '該当部分'}], 'definition': '| C-OG.save[EQ] | EQ の Publish | 対応する EQ の SV | EQ の保存の実担当 | Ep の実行・返答・後続、pG、停止 |', 'status': '採用'},
    '背骨①': {'id': '背骨①', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 192, 'last': 192, 'read_scope': '該当部分'}], 'definition': '| ① 感じ続ける | 開いている口ごとに、測る過程が動いている区間は、どの時刻も「測定 (値あり、変わらなかったを含む)・測れなかった・欠け・被覆を証明できない」のどれかの記録に入る (区間が記録の外に落ちない)。測る過程は評価・選択を待たずに続く。止まるのは sui が選んだ口の変更か、記録に残る故障だけ |', 'status': '採用'},
    '背骨②': {'id': '背骨②', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 193, 'last': 193, 'read_scope': '該当部分'}], 'definition': '| ② 受信・反映・選択を分ける | どの仕事 (評価・導出・手) が止まっていても、受信・受付・保存成功は進む。受信の r は保存や採用の時刻に引きずられない。反映していない事実があっても受信は止まらない |', 'status': '採用'},
    '背骨③': {'id': '背骨③', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 194, 'last': 194, 'read_scope': '該当部分'}], 'definition': '| ③ 過程の網 | 確定ごとに対象と効力の範囲を記録する。方針は過程ごと。資源の割り当ては容量を守れる案の上の選択で、来た順や独立のくじで決めない。**不変** (2026-10-13 FBR-08 で比べる対象を直した): 時計の刻みの細かさ・配送の包み方 (1 件ずつか束か)・候補の別名・表示の階層を変えても、**認証した測定・使える時刻 (available)・文脈の o と j・根** が同じなら、選び方の確率は同じ。比べるのは知らせの記録 (受信の r や知らせの数は包み方で変わる) ではなく、そこから導いた事実。実際の遅着で使える事実や o・j が変わった時は同じ答えを求めない |', 'status': '採用'},
    '背骨④': {'id': '背骨④', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 195, 'last': 195, 'read_scope': '該当部分'}], 'definition': '| ④ 根の凍結 | 評価の答え・選択は、使った根 (事実の CID の集合と文脈の o・j) を持つ。後から事実が増えても元の答えは元の根について正しいまま。追いつきは新しい根の新しい評価 |', 'status': '採用'},
    '背骨⑤': {'id': '背骨⑤', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 196, 'last': 196, 'read_scope': '該当部分'}], 'definition': '| ⑤ 事実が正 | 信念・選択に使うものは、台帳の事実から F-a の事実の入口で作り直す。預かり箱・状態の写し・仕事の札は数学の入力にしない |', 'status': '採用'},
    'I-1': {'id': 'I-1', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 172, 'last': 172, 'read_scope': '該当部分'}], 'definition': '| **I-1** | 受け口への受信 | ① 世界 | 口 (`route_epoch`)・bytes・media type・送り手の主張 (送り手の付けた契約の名前・時刻・ID はまとめて中身の一部) → `Observed` (受け口の契約、`received_ns` = r) | 中身の読み方 (どの契約で読むか、P6)。送り手の主張が正しいか。同じ便の配達し直しか | 受信ごとに新しい記録の名前 (P7 ②)。送り手の ID で重ねない | r はホストの M の読み。送り手の時刻は u (W-08) |', 'status': '採用'},
    'I-2': {'id': 'I-2', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 173, 'last': 173, 'read_scope': '該当部分'}], 'definition': '| **I-2** | 測る係の報告 | ② 仕事 | 測定 / 測れなかった / 欠け / 被覆の主張 (`measurement/1`・`coverage/1`) と、係が宣言した時計で読んだ読み | 被覆が認証できるか・「何も来なかった」と言えるか (使う時に F-a A-14・A-15 で認証) | 報告は生成の証拠 (どの口の設定・どの過程が生んだか) を指す。sample_seq や名前だけで同じ測定と決めない | 測定の区間 i と e ≤ 受信 r ≤ 記録 s (F-a A-13・A-14)。生成の祖先は 2-3 の Q1 |', 'status': '採用'},
    'I-3': {'id': 'I-3', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 174, 'last': 174, 'read_scope': '該当部分'}], 'definition': '| **I-3** | 計算の仕事の完了 | ② 仕事 | 結果の内容・生成の読み・失敗/不明を知った根拠を原報告として受け取る。信念の更新の R/P/Cq、候補の生成の T/CG、評価の artifact と終わりは用途ごとの契約で導く (すべての返答から `computation_completed/1` を作るわけではない、v0.17 §2-4-11 M3) | 結果が正しいか・使えるか (F-a A-10・E-06 の再読で中で確かめる)。係の「検証済み」の札 | 結びつきは用途ごとに固定した要求の Point と契約の版 (信念の更新は `computation_requested/1`、候補の生成は `sui.fb.candidate_request/1` の Qgen、評価は評価の要求 EQ) の CID。仕事の名前の文字列で結ばない。旧 Q や completed への変換で合わせない | 完了の読み g ≤ 取得 a ≤ … (A-10)。要求が完了の祖先 |', 'status': '採用'},
    'I-4': {'id': 'I-4', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 175, 'last': 175, 'read_scope': '該当部分'}], 'definition': '| **I-4** | 手の報告 | ② 仕事 | 受け取り・送出・結果の報告 (S4b の `RECEIPT`・`DISPATCH`・`REPORT`・`ENDED`) | 作用が世界で効いたか (観測として後で読む) | `caused_by` の試みの CID | 開始 ≤ 受け取り ≤ 送出 ≤ 報告の受信 |', 'status': '採用'},
    'I-5': {'id': 'I-5', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 176, 'last': 176, 'read_scope': '該当部分'}], 'definition': '| **I-5** | 予約の満了・条件の検出 | ③ ホスト | ホストが読んだ時計の読みと、どの予約の何の検出か → 検出の記録 (形は 2-3 Q6) | 考え始めるか・作用を出すか (その過程の方針で決める) | 予約の記録の CID + 満了の予定から決まる発火の名前 (同じ発火の再配送は同じ名前) | 予定 p と検出 e を分ける。別 run の予定は `clock_unaligned` |', 'status': '採用'},
    'I-6': {'id': 'I-6', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 177, 'last': 177, 'read_scope': '該当部分'}], 'definition': '| **I-6** | 起動・口の開閉 | ③ ホスト | 起動の事実 (`sui.s4.boot/1`)・起動の環境 (1 回)・口の設定の適用 (`route_config/1`、最初の口は `origin=bootstrap`) | 起動の環境をどう読むか | 起動は run の原点。口は `route_epoch` | 起動 → 適用の実効の読み ≤ その口の測定 |', 'status': '採用'},
    'I-7': {'id': 'I-7', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 178, 'last': 178, 'read_scope': '該当部分'}], 'definition': '| **I-7** | 時計の出どころの宣言 | ③ ホスト | `sui.clock.source/1` (宣言 d、実測精度の証明ではない) | 時計の精度 | run | 同じ run の中だけで比べる |', 'status': '採用'},
    'I-8': {'id': 'I-8', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 474, 'last': 474, 'read_scope': '該当部分'}], 'definition': '- I-8 `DrawReturned(work: WorkId, outcome: DrawValue | DrawFailure | DrawUnknown)` → `sui.fb.draw_report/1`。D の終わりの知らせはどれもこれで受ける (D を名乗る `WorkFinished` は原報告として保存するが D の終わりにしない)。原報告を保存したうえで、要求との対応・最初の終わり・使用の条件が揃った枝だけ `draw_fact/1` か `sui.fb.draw_unknown/1` を出す (v0.17 §2-4-11 M4)', 'status': '採用'},
    'INV-2.g': {'id': 'INV-2.g', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1962, 'last': 1962, 'read_scope': '該当部分'}], 'definition': '- 足す確かめの行の候補: **INV-2.g** 生成から評価までの所有の連続 (各枝の Required・Direct・Transfer・残る pG を独立の宣言・返答・保存から求め、CG の保存の後の issue[EQ] や担当の移行の後の pG を消したら違反。合法な対照 = 文脈不足で EQ を発行せず issue[EQ] と pG を実所有して待つ) / **INV-16.c** 生成の要求 → 実際の生成 → CG → EQ の全対応。Wg の追加で INV-2.a/b/c/e/f・3・4・5・6.b・7・8・10・11・13・15 の当たる母集団が広がる。(R10 を足す時は INV-14.c 生成用のくじの根拠と使用)', 'status': '採用'},
    'INV-16.c': {'id': 'INV-16.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1962, 'last': 1962, 'read_scope': '該当部分'}], 'definition': '- 足す確かめの行の候補: **INV-2.g** 生成から評価までの所有の連続 (各枝の Required・Direct・Transfer・残る pG を独立の宣言・返答・保存から求め、CG の保存の後の issue[EQ] や担当の移行の後の pG を消したら違反。合法な対照 = 文脈不足で EQ を発行せず issue[EQ] と pG を実所有して待つ) / **INV-16.c** 生成の要求 → 実際の生成 → CG → EQ の全対応。Wg の追加で INV-2.a/b/c/e/f・3・4・5・6.b・7・8・10・11・13・15 の当たる母集団が広がる。(R10 を足す時は INV-14.c 生成用のくじの根拠と使用)', 'status': '採用'},
    'INV-14.c': {'id': 'INV-14.c', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 2030, 'last': 2030, 'read_scope': '該当部分'}], 'definition': '| **R10 生成用のくじ** (v0.18、D6) | 生成方法が要る生成用のくじの要求の記録 RG (`sui.fb.generation_draw_requested/1` 仮称)、くじの仕事 Dg (FWork の Draw の用途)、値 DFg (`draw_fact/1`)・不明 DUg (`sui.fb.generation_draw_unknown/1` 仮称) | 背骨 ②〜⑤。Qgen を含む初期計画の Publish で宣言した各 draw slot に RG の発行の責務、RG の Publish と同時に Dg 行。Dg の終わりは I-8 `DrawReturned` (M4)。DFg は Ee を約束せず、Wg の宣言した入力 slot への依存 (固定した PlanRef、保存済みの Point へ 1 度だけ解決) を満たす。Wg は要る DFg が全部保存され対応と許可が確かめられてから開始。CG の generation.draws に使った DFg の Point を載せる。PR/FProblem や選択用の D の権利は使わない。context_key は F-a M-13 の式 (生成後の input_order・CG・評価の problem_key を混ぜない) | **書ける (契約の追加 A14、選択用の D → Ee と同じ形の Dg → Wg)**。Wg の開始の前に要るくじの要求を全部固定できる生成契約まで。**生成の途中で新しいくじを要求する方式は別の未接続** (事前の抽選や固定の個数に近似しない) | O-GD の 7 条件 (issue[RG]・save[RG]・run[Dg]・save[T]・handle[Dg]・issue[DFg/DUg]・save[DFg/DUg]) で 58。新しい行 INV-14.c (RG・Dg・DFg・Wg の実入力の対応、PR を捏造せず別用途や DUg を値に使わない)。Dg の Unknown・Failure では値の無い依存と元目的の未達を Wg 側が引き受け、Wg は未開始のまま (Wg の Unknown や NoCandidates を捏造しない) | 宣言した draw が 0・1・複数、一部だけ保存、Dg の値・Failure・Unknown が最初、Dg が Hung でも受信・保存が進む、容量 1 で Wg が未保存の DFg を待って先に席を取らない、生成用と選択用の取り違え |', 'status': '未採用'},
}

ENTRY_POINTS = {
    'I-1': {'id': 'I-1', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 172, 'last': 172, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '受け口への受信'},
    'I-2': {'id': 'I-2', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 173, 'last': 173, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '測る係の報告'},
    'I-3': {'id': 'I-3', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 174, 'last': 174, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '計算の仕事の完了'},
    'I-4': {'id': 'I-4', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 175, 'last': 175, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '手の報告'},
    'I-5': {'id': 'I-5', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 176, 'last': 176, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '予約の満了・条件の検出'},
    'I-6': {'id': 'I-6', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 177, 'last': 177, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '起動・口の開閉'},
    'I-7': {'id': 'I-7', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 178, 'last': 178, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '時計の出どころの宣言'},
    'I-8': {'id': 'I-8', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 474, 'last': 474, 'read_scope': '該当部分'}], 'kind': 'F-b外から核への入口', 'shape': '- I-8 `DrawReturned(work: WorkId, outcome: DrawValue | DrawFailure | DrawUnknown)` → `sui.fb.draw_report/1`。D の終わりの知らせはどれもこれで受ける (D を名乗る `WorkFinished` は原報告として保存するが D の終わりにしない)。原報告を保存したうえで、要求との対応・最初の終わり・使用の条件が揃った枝だけ `draw_fact/1` か `sui.fb.draw_unknown/1` を出す (v0.17 §2-4-11 M4)'},
    'post': {'id': 'post', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 461, 'last': 461, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- ホスト: 今の `ThreadHost` の形 (`post(event)`・`run_until(done, timeout=)`・封筒 `Envelope(number, event, received_ns)`) を保つ。ただし未開始の箱は仕事表の見え方にする (§2-4-1)'},
    'run_until': {'id': 'run_until', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 461, 'last': 461, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- ホスト: 今の `ThreadHost` の形 (`post(event)`・`run_until(done, timeout=)`・封筒 `Envelope(number, event, received_ns)`) を保つ。ただし未開始の箱は仕事表の見え方にする (§2-4-1)'},
    'accept': {'id': 'accept', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 462, 'last': 462, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- 窓口: `FWindow.accept(envelope) -> None`・`settle() -> None`・`status() -> FStatus` (読み取り専用の公開の像、意味は §2-4-11 M1)・`drain() -> tuple[FWork, ...]` (**列挙で、取り除かない**)。`FWork = MeasureSegment | Compute | Draw` (`Act` は外付け)。旧 `Window`・旧 `Drive` は旧モデルの道として変えない'},
    'settle': {'id': 'settle', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 462, 'last': 462, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- 窓口: `FWindow.accept(envelope) -> None`・`settle() -> None`・`status() -> FStatus` (読み取り専用の公開の像、意味は §2-4-11 M1)・`drain() -> tuple[FWork, ...]` (**列挙で、取り除かない**)。`FWork = MeasureSegment | Compute | Draw` (`Act` は外付け)。旧 `Window`・旧 `Drive` は旧モデルの道として変えない'},
    'status': {'id': 'status', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 462, 'last': 462, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- 窓口: `FWindow.accept(envelope) -> None`・`settle() -> None`・`status() -> FStatus` (読み取り専用の公開の像、意味は §2-4-11 M1)・`drain() -> tuple[FWork, ...]` (**列挙で、取り除かない**)。`FWork = MeasureSegment | Compute | Draw` (`Act` は外付け)。旧 `Window`・旧 `Drive` は旧モデルの道として変えない'},
    'drain': {'id': 'drain', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 462, 'last': 462, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- 窓口: `FWindow.accept(envelope) -> None`・`settle() -> None`・`status() -> FStatus` (読み取り専用の公開の像、意味は §2-4-11 M1)・`drain() -> tuple[FWork, ...]` (**列挙で、取り除かない**)。`FWork = MeasureSegment | Compute | Draw` (`Act` は外付け)。旧 `Window`・旧 `Drive` は旧モデルの道として変えない'},
    'rebuild_window': {'id': 'rebuild_window', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 1926, 'last': 1926, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- `ThreadHost.rebuild_window() -> FWindow`: 同じプロセスの中で有効な窓口を作り直して返す。保持する H・P・C・E と動いている Runners はそのまま使い、受信の列・処理中の封筒・保存の準備・仕事の記述・開始の札・占有・停止の知識・生きた認証物を台帳だけから作り直さない (§2-4-1)。有効な窓口の切替は、窓口が共有状態を変える歩との間で不可分。切替の前の失敗では旧窓口が有効、切替の後に応答が失われても新旧 2 つを同時に有効にしない。旧窓口への操作は失効を示す `RuntimeError` (入力の shape の誤りと分ける)。作り直し自身は Boot・Post・くじの消費・仕事の再入場・占有の解放をしない。新しい run を作らない。計算の終わりを待たない。並行する本当の受信・停止がなければ、作り直しの前後の公開の像の意味の内容は同じ。プロセスの再起動 (S5、D4) には広げない'},
    'Ledger.prepare': {'id': 'Ledger.prepare', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 468, 'last': 468, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- 保存の準備: `Ledger.prepare(record, parents) -> PreparedEntry(record, parents, salt, header, cid)` と `Ledger.write(prepared)`。`write` は書く前と既に点がある時に `seal(payload,salt)`・`encode_header(record,seal,parents)`・`hash(header)` の 3 つの結びつきを確かめる'},
    'Ledger.write': {'id': 'Ledger.write', 'sources': [{'path': 'specs/関所F_Fb_今の約束.md', 'first': 468, 'last': 468, 'read_scope': '該当部分'}], 'kind': '公開操作 (I系入力とは区別)', 'shape': '- 保存の準備: `Ledger.prepare(record, parents) -> PreparedEntry(record, parents, salt, header, cid)` と `Ledger.write(prepared)`。`write` は書く前と既に点がある時に `seal(payload,salt)`・`encode_header(record,seal,parents)`・`hash(header)` の 3 つの結びつきを確かめる'},
    'prepare_f_from_facts': {'id': 'prepare_f_from_facts', 'sources': [{'path': 'src/sui/f_facts.py', 'first': 38, 'last': 38, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'prepare_f_from_facts(reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point, candidate_ref: Point, preference_refs: tuple[Point, ...], scope_request: EvaluationScope, context_ref: Point, registry: FRegistry, method: ContractRef, budget: RateBudget) -> FMathArtifact[FProblem | NoDecision]', 'docstring': '§3-10-16-7: 一次CID/宣言から問題または根なしNoDecisionを作る。\n\n親の閉包と実CID/header/seal/本文を読み、E/K/context/好み/正準候補/\nworldを共通compiler内で導く。派生物を入力として受け取らず、現在heads・\nbuiltin能力・壁時計で補わない。reader/registryを不変に捕捉する。\nbudgetは価値/H/problem_keyではない。取得と採用を混同しない。\n形不正FInputError、改変FReplayMismatch、必須原記録欠落FReplayUnavailable。\n意味不足/能力不足/証明不足/予算不足は既存の低/高水準診断を保つ。\nID/時計/乱数の取得、台帳書込み、受付の実施は行わない。'},
    'bind_f_draw': {'id': 'bind_f_draw', 'sources': [{'path': 'src/sui/f_facts.py', 'first': 73, 'last': 73, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'bind_f_draw(prepared: FMathArtifact[FProblem], draw_record_ref: Point, *, reader: FReader, budget: RateBudget) -> FMathArtifact[FRoot]', 'docstring': '§3-10-16-8: 発行問題へselection drawの実CID/本文を結ぶ。\n\n用途/law/u/問題キーとdrawの実祖先を検査。数学のfixed_parentsは変更せず、\n後続の測定/紙/計算を加えない。同根精密化は同Point/同u。\n一回の乱数消費や実行の時系列はF-b。手組み問題を受理しない。'},
    'evaluate_f_from_draw': {'id': 'evaluate_f_from_draw', 'sources': [{'path': 'src/sui/f_facts.py', 'first': 110, 'last': 110, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'evaluate_f_from_draw(prepared: FMathArtifact[FProblem], draw_record_ref: Point, *, reader: FReader, budget: RateBudget) -> FMathArtifact[Selected | NoDecision]', 'docstring': '固定問題と認証drawから既存数学を評価する。§3-10-16-7/8。\n\nbindと同じfactoryを通し、根と数学手順/予算を出力へ結合する。\n出力のattempt_idはnull。実際の保存/作用/受付を数学の成功と呼ばない。\n予期しないPython例外は元の例外。'},
    'read_f_histories_from_facts': {'id': 'read_f_histories_from_facts', 'sources': [{'path': 'src/sui/f_facts.py', 'first': 124, 'last': 124, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'read_f_histories_from_facts(reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point, context_ref: Point, registry: FRegistry, budget: RateBudget) -> FHistoriesFromFacts', 'docstring': '狭い原記録reader。§3-10-16-4/5/7。\n\nKnowledgeOrigin/取得/計算/証明/採用/時計からE/K/context/観測を導く。\navailable/incorporated/belief/proofs/祖先表を引数にしない。\n取得はavailableだけを進め、K未読を推測で補わず競合採用を勝手に選ばない。\nFRoot/候補/draw不要。補7: got.modelは発行専用FFiniteUpdateModelで、\ninitial_finite_belief/got.observationsのapply_f_observationへ渡せる契約。\n宣言DTO/同authority_keyの復号物で代用しない。導出は共通compilerで行う。'},
    'verify_f_math_result': {'id': 'verify_f_math_result', 'sources': [{'path': 'src/sui/f_facts.py', 'first': 327, 'last': 327, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'verify_f_math_result(data: bytes, *, reader: FReader, registry: FRegistry, budget: RateBudget) -> VerifiedMathResult', 'docstring': '正準数学結果を事実から再構築して照合する発行専用入口。\n\n§3-10-16-10/11。検証budgetと保存された実行budgetを分け、当時の\n不足のreader/registry像を失えばFReplayUnavailable。全一致後だけ発行。\nticket/受付/保存成功/乱数消費の証明は含めない。'},
    'make_f_registry': {'id': 'make_f_registry', 'sources': [{'path': 'src/sui/f.py', 'first': 2284, 'last': 2284, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'make_f_registry(*, declarations: tuple[CapabilityDeclaration, ...], implementations: tuple[CapabilityImplementation, ...]) -> FRegistry', 'docstring': 'F-a で不変 registry を作る。対応宣言なし・同 kind/ref 二重登録は FInputError。\n宣言のみは登録可能。使用時に意味不足 FSpecificationMissing / 能力不足 FIncomplete。\nグローバル登録や JSON から任意関数を import せず、登録だけで認証しない。'},
    'builtin_f_registry': {'id': 'builtin_f_registry', 'sources': [{'path': 'src/sui/f.py', 'first': 2307, 'last': 2307, 'read_scope': '該当部分'}], 'kind': 'F-a公開署名だけ', 'shape': 'builtin_f_registry() -> FRegistry', 'docstring': 'F-a で §3-10-13-3 の28行の七欄と共通 CapabilityCallable を不変 registry にする。\n元データは同モジュールの _BUILTIN_DECLARATIONS/_BUILTIN_IMPLEMENTATIONS。\nS(T) は sui.f.schema. + snake(T)。既存 ContractRef の制約に従う。\nS/A は wire schema であり能力として再帰登録しない。条件名や登録だけを認証にしない。\n意味宣言欠落 FSpecificationMissing(missing_contract)、実装欠落 FIncomplete(algorithm_unavailable)、\n返り値不正 FInputError(capability_output_shape)。method と proof を分ける。'},
}

VOCABULARY = (
    {'id': 'W-01', 'line': 62, 'subject': '口 (route)', 'meaning': '膜の外から何かが入る経路。版つきの設定 (`route_epoch`・測り方の契約・時計の契約・欠けの契約・引数) を持つ。設定には由来がある: 最初から置いた (`bootstrap`) / sui が選んで変えた・足した (`selected`、選んだ記録と実行の記録を指す)', 'distinction': '時計の刻みではない。配送の包み方 (何件まとめて届くか) でもない', 'targets': ['T.route_config'], 'rules': ['I-6', 'INV-12'], 'entries': ['I-6']},
    {'id': 'W-02', 'line': 63, 'subject': '受け口', 'meaning': '届いたものを**種類を問わず**、bytes と media type のまま残す口。中身の意味を決めない (中身を読む契約を後から足すのは sui の側)', 'distinction': '中身を限定した口 (例: 「手紙だけ」) ではない。受け口があることは、何かが届くことの約束ではない', 'targets': ['T.received'], 'rules': ['I-1'], 'entries': ['I-1']},
    {'id': 'W-03', 'line': 64, 'subject': '測定', 'meaning': '口で、ある区間について値を得た出来事。区間 (i: 始め・終わり・閉じ方) と、測った出来事 (e) を持つ。**「変わらなかった」も値のある測定**', 'distinction': '「測れなかった」は測定ではない (W-04)。受信 (W-06) とも別: 測った時と届いた時は違う', 'targets': ['T.frame'], 'rules': ['INV-12'], 'entries': ['I-2']},
    {'id': 'W-04', 'line': 65, 'subject': '測れなかった・欠け・被覆', 'meaning': '測れなかった = その区間について値を得られなかった報告 (`MeasurementUnavailable`)。欠け = 測定の列の抜け (`Gap`)。被覆 = 「その区間を見張っていた」という主張と証拠 (`CoverageClaim`)。被覆を証明できない = `CoverageUnproved`', 'distinction': '見張り役が生きていたことだけで被覆を主張しない。「何も来なかった」は被覆の証拠がある区間についてだけ (F-a A-15)', 'targets': ['T.coverage'], 'rules': ['INV-12'], 'entries': ['I-2']},
    {'id': 'W-05', 'line': 66, 'subject': '到着', 'meaning': '外のものが口に来たこと。**sui からは直接見えない**。見えるのは受信 (W-06) と、送り手の主張 (W-08) だけ', 'distinction': '受信の時刻を到着の時刻と呼ばない', 'targets': [], 'rules': ['I-1'], 'entries': ['I-1']},
    {'id': 'W-06', 'line': 67, 'subject': '受信 (r)', 'meaning': 'ホストが届いたものを封筒に入れ、同じ run の単調時計 (M) の読みを押した出来事', 'distinction': '受付 (W-10)・保存 (W-12)・信念に入ること (W-23) を含まない', 'targets': ['T.envelope'], 'rules': ['INV-1'], 'entries': ['I-1']},
    {'id': 'W-07', 'line': 68, 'subject': '時計の読み', 'meaning': '宣言した時計 (時計の契約・run) で読んだ値 (`ClockReading`)。読みの証拠は、どの時計をどの run で読んだかの記録', 'distinction': '通知の中に書いてある時刻 (W-08) と取り換えない', 'targets': ['T.clock_source', 'T.reading'], 'rules': ['I-7'], 'entries': ['I-7']},
    {'id': 'W-08', 'line': 69, 'subject': '通知の内容', 'meaning': '届いたものに書いてあること。中の時刻は送り手の主張 (u、領域 U)', 'distinction': '時計の読みの証拠ではない。F-a A-12 の例外 (D2) をここで広げない', 'targets': ['T.received.claims'], 'rules': ['I-1'], 'entries': ['I-1']},
    {'id': 'W-09', 'line': 70, 'subject': '3 つの役割', 'meaning': '最初の感覚の 3 つ: **外を見る窓** (W-01〜W-03 の口と受け口) / **いつどこまで見えたかの札** (各測定の区間・被覆・受信の読み。独立の口にせず、各記録の欄で担う) / **自分がしたことの記録** (§1-5 の確定と実行の記録)。起動の環境は起動時の 1 回の記録、計算の資源は宣言した容量 (W-38) と仕事の記録で担う', 'distinction': '「5 つのセンサー」ではない。時刻・口の具合を別の口として常設しない', 'targets': ['T.boot_decl'], 'rules': ['背骨①'], 'entries': ['I-6']},
    {'id': 'W-10', 'line': 78, 'subject': '受付', 'meaning': '窓口が封筒から記録を**1 度だけ**作り、預かり箱に預けた出来事。失敗したら同じ封筒で受付をやり直す (同じ記録の名前を使う)', 'distinction': '書いていない (保存 W-12 は別)。記録の中身が正しいことの認証ではない (認証は F-a の事実の入口)', 'targets': ['T.rel.receipt'], 'rules': ['INV-1'], 'entries': ['I-1']},
    {'id': 'W-11', 'line': 79, 'subject': '預かり', 'meaning': '引き受けたがまだ済んでいない約束 (書く・始める・知らせる・依頼する)。窓口を作り直しても捨てない', 'distinction': '信念の途中の値は預けない。プロセスをまたいで残す約束ではない (それは S5)', 'targets': ['T.rel.owner'], 'rules': ['INV-2'], 'entries': ['I-3']},
    {'id': 'W-12', 'line': 80, 'subject': '保存成功', 'meaning': '記録の本文、続けて台帳の点 (CID) が置き場に確定し、プロセスが強制終了しても残る (k2) ところまで行った出来事', 'distinction': '記録の時刻 s (`Record.at`) は記録を作った時に押したもので、保存成功の時刻ではない。保存は信念に入ったことを含まない', 'targets': ['T.rel.storage'], 'rules': ['INV-4'], 'entries': ['I-1']},
    {'id': 'W-13', 'line': 81, 'subject': '保存の再試行', 'meaning': '保存が失敗した後、**同じ預かりの同じ記録**で書き直すこと。新しい記録を作らない', 'distinction': '受付のやり直し (W-10) とは段が違う', 'targets': ['T.rel.storage'], 'rules': ['INV-4'], 'entries': ['I-1']},
    {'id': 'W-14', 'line': 82, 'subject': '窓口', 'meaning': '台帳に書く唯一の係 (書く接続は 1 つ)。受付・保存・反映・依頼の受け取りを順に進める', 'distinction': '考えたり作用したりしない (それは仕事 W-31)。「窓口が 1 つ」は保存の上の直列化で、sui の活動を 1 本にする意味ではない (背骨 ③)', 'targets': ['T.rel.owner'], 'rules': ['INV-11'], 'entries': ['I-3']},
    {'id': 'W-15', 'line': 83, 'subject': 'ホスト', 'meaning': '受信の時刻を押し、仕事をスレッドで走らせ、窓口を作り直す係', 'distinction': '選ばない', 'targets': ['T.rel.rebuild'], 'rules': ['INV-3'], 'entries': ['I-3']},
    {'id': 'W-20', 'line': 91, 'subject': '読み手', 'meaning': '事実を取得して信念を作る主体の部分 (F-a の origin)。**知識は仕切らない**: 届いた事実はどの読み手も取得できる。届く前から知っていたとは扱わない', 'distinction': '読み手が複数あっても、隠す・見せないの設計はしない (0-2 の (あ))', 'targets': ['T.origin'], 'rules': ['INV-9'], 'entries': ['I-3']},
    {'id': 'W-21', 'line': 92, 'subject': '取得 (a)', 'meaning': 'ある読み手が事実の内容を手に取った出来事。F-a A-09・A-10・A-11 のまま', 'distinction': '参照しただけ・内容を使っただけと同一視しない (F-a A-07)', 'targets': ['T.rel.acquisition'], 'rules': ['INV-9'], 'entries': ['I-3']},
    {'id': 'W-22', 'line': 93, 'subject': '導出', 'meaning': '取得した事実から信念 (核・事後) を計算すること。窓口の外の仕事 (W-31) で行う', 'distinction': '採用 (W-23) を含まない', 'targets': ['T.rel.update_stages'], 'rules': ['INV-9'], 'entries': ['I-3']},
    {'id': 'W-23', 'line': 94, 'subject': '採用 (d)', 'meaning': 'ある読み手が計算結果を自分の信念として使うと決めた出来事。F-a A-10・A-16 のまま (同じ導出の再採用は新しい観測の適用ではない)', 'distinction': '保存成功 (W-12) を含意しない。採用は §1-5 の確定の 1 つ', 'targets': ['T.rel.stale'], 'rules': ['INV-9'], 'entries': ['I-3']},
    {'id': 'W-24', 'line': 95, 'subject': '反映', 'meaning': '背骨 ② の段の名前 = 「受信した事実が、ある読み手の採用まで届いた」こと。**反映という別の出来事は作らない** (出来事としては採用が担う)', 'distinction': 'どの読み手にも反映済み、を 1 つの印で表さない (読み手ごと)', 'targets': ['T.status'], 'rules': ['背骨②'], 'entries': ['I-3']},
    {'id': 'W-30', 'line': 103, 'subject': '過程', 'meaning': '続いていく活動のひとまとまり (例: ある口の測定を続ける / ある根の評価 / 外へ出ている手 / ある予約の見張り)。ほかの過程と因果・共有する資源・証拠で結ばれる。**全部を 1 本の列に並べない**', 'distinction': '「今の思考」は 1 つではない。過程の数を 1 に固定しない', 'targets': ['T.descriptor'], 'rules': ['背骨③'], 'entries': ['I-3']},
    {'id': 'W-31', 'line': 104, 'subject': '仕事', 'meaning': 'ホストが窓口の外のスレッドで走らせる 1 回分の計算か作用 (考える・導出する・評価する・手を動かす)。過程は仕事を何回も含みうる。仕事は台帳・主体・書く接続を持たない', 'distinction': '過程 (W-30) と同じではない', 'targets': ['T.fwork'], 'rules': ['INV-3'], 'entries': ['I-3']},
    {'id': 'W-32', 'line': 105, 'subject': 'きっかけ', 'meaning': '過程を始める・変える元になったもの。**外の事実** (受信した記録) か、**内の理由** (自分の信念・好み・能力から出た候補)。どちらも候補の由来の札で、考え始める入口がこの 2 つだけという意味ではない', 'distinction': '時計の刻み (`Tick`) だけでは選び方を変えない。満了 (W-43) は約束の配送で、無条件に考え始める合図ではない', 'targets': ['T.qgen', 'T.rel.declared_derive'], 'rules': ['INV-2.d'], 'entries': ['I-3']},
    {'id': 'W-33', 'line': 106, 'subject': '根', 'meaning': '評価に固定した入力一式 (モデル・好み・E/K・文脈・候補と測度・評価の範囲・継続・方法と契約の版、F-a P-07)。**根の凍結** = 答えに「何時までの事実で」の札をつけること (背骨 ④): その根の K が含む事実の集合と文脈の判断境界 j', 'distinction': '計算中に事実が増えても元の根の答えは有効 (B8)。新しい事実への追いつきは別の根の別の評価', 'targets': ['T.rel.frozen'], 'rules': ['INV-8'], 'entries': ['I-3']},
    {'id': 'W-34', 'line': 107, 'subject': '評価', 'meaning': '根を固定して G・方策を計算する仕事。答えが出ても作用の許可ではない', 'distinction': '選ぶ (W-41) を含まない', 'targets': ['T.eq'], 'rules': ['INV-16'], 'entries': ['I-3']},
    {'id': 'W-35', 'line': 108, 'subject': '生成 (g)', 'meaning': '計算の結果や候補を作り終えた出来事 (F-a A-10 の `finished_clock`)', 'distinction': '候補の生成と結果の生成を分ける。生成済みであることと、使えること (取得・採用) を分ける', 'targets': ['T.generation'], 'rules': ['INV-15'], 'entries': ['I-3']},
    {'id': 'W-36', 'line': 109, 'subject': '方針', 'meaning': 'ある過程が選んで持ち続けている**選び方の法則** (手の上の確率、方策)。持続し、きっかけで見直される。**過程ごとに持つ**。全体で 1 本の「今の方針」や、その世代番号は置かない', 'distinction': '見込み (W-37) ではない。実際に起きたこと (W-38) でもない', 'targets': ['T.policy'], 'rules': ['背骨③'], 'entries': ['I-3']},
    {'id': 'W-37', 'line': 110, 'subject': '見込み', 'meaning': '世界や自分についての確率 (信念・予測)。未確定の選択肢とともに、**つながりを保った分布**で持つ (1 つの点にまとめない)', 'distinction': '方針 (選び方) と取り換えない', 'targets': ['T.model_document'], 'rules': ['背骨③'], 'entries': ['I-3']},
    {'id': 'W-38', 'line': 111, 'subject': '実際の過程と記録', 'meaning': '起きたこと・出した作用。**1 つで、分布ではない** (P1)。靄なのは見込み・方針・過程の側', 'distinction': '記録の意味に限る (記録の解釈は見込み)', 'targets': ['T.record'], 'rules': ['背骨⑤'], 'entries': ['I-3']},
    {'id': 'W-39', 'line': 112, 'subject': '容量・配り方', 'meaning': '容量 = 宣言した資源の上限 (考える席・手・置き場など)。配り方 = 考える力や資源をどの過程に割くかで、**容量を守れる案の上の分布**として、ほかの手と同じ G で比べる', 'distinction': '仕事ごとに独立のくじで配らない (容量を超えうる)。来た順の開始は開発者の規則で、sui の選択ではない', 'targets': ['T.rel.resource'], 'rules': ['INV-10'], 'entries': ['I-3']},
    {'id': 'W-40', 'line': 120, 'subject': '確定', 'meaning': '分布や未確定の選択肢から 1 つに決まる出来事。種類は **選ぶ・意図・予約・取得・採用・実行**。どれも**対象** (何について) と**効力の範囲** (どの過程・どの根・いつまで) を持つ', 'distinction': '「1 つに決まるのは作用の瞬間だけ」ではない。無関係な確定を同じ列に並べない', 'targets': ['T.selection', 'T.acquired', 'T.adopted'], 'rules': ['背骨③'], 'entries': ['I-3']},
    {'id': 'W-41', 'line': 121, 'subject': '選ぶ', 'meaning': '方策と抽選から手が 1 つに決まる出来事 (`Selected`)。決められなかった (`NoDecision`) とは別。永久に待つ手を選ぶことも選ぶに入る (F-a P-06)', 'distinction': '評価 (W-34) を含まない。選んだことは作用の開始ではない', 'targets': ['T.rel.selection'], 'rules': ['INV-16'], 'entries': ['I-3']},
    {'id': 'W-42', 'line': 122, 'subject': '意図', 'meaning': '選んだ手をやると引き受けた出来事。確かめた・取り下げた・やった の状態を持つ (`Intention`)', 'distinction': '実行 (W-44) とは別', 'targets': ['T.body.intention'], 'rules': ['I-4'], 'entries': ['I-4']},
    {'id': 'W-43', 'line': 123, 'subject': '予約', 'meaning': '未来の条件 (ある時刻 / ある条件) で作用を出すと登録した出来事。**満了** (p: 予定の時刻が来た)・**検出** (条件が成り立ったと気づいた)・**実行** は別々の出来事', 'distinction': '満了は登録済みの約束の配送で、新しい評価や抽選を無条件に起こす Tick ではない。別 run の期限は時計が揃っていない (`clock_unaligned`)', 'targets': ['T.reservation_due'], 'rules': ['I-5'], 'entries': ['I-5']},
    {'id': 'W-44', 'line': 124, 'subject': '実行', 'meaning': '作用を外へ出すこと。段は **開始** (試みの記録) → **受け取り** (手の係が受け取った) → **送出** (外へ出た点を手の係が確かめた) → **報告** (結果か終わり)。「実行した」と言うのは送出の確かめがある時だけ', 'distinction': '送出した作用を取り消せたと推定しない。開始の記録だけで実行したとは言わない', 'targets': ['T.body.attempt'], 'rules': ['I-4'], 'entries': ['I-4']},
    {'id': 'W-45', 'line': 125, 'subject': '取りやめ', 'meaning': '待つのをやめる・予約を取り消す出来事。それも選ぶ手の 1 つ (評価を経る)', 'distinction': '動いている手・使用中の資源・遅れて来る結果を消さない (r4)。送出済みの作用は取り消せない', 'targets': ['T.purpose_part'], 'rules': ['INV-2.c'], 'entries': ['I-4']},
)

EXTERNAL_ROWS = (
    {'id': 'R1', 'line': 2021, 'subject': 'W-43 の予約、時計による検出の原報告、同じ引受けの配送権利とその処理記録 (見張りは W-31)。「満了」を選択や実行にしない', 'constraints': '背骨 ②〜⑤。H の受信 → P.units の配送権利 → 必要なら P.work。鍵 = 予約 Point + 1 回分の slot、再検出の読みは鍵に入れない。同じ run の M で予定 p と検出 e を比べる、別 run は clock_unaligned', 'disposition': '**書ける (契約の追加 A01)**', 'conditions': 'INV-6.b/c、7、8、16 の予約の枝。**新しい条件**: 予約登録の issue/save、満了配送の handle/save、配送権利の 1 回性と許可の照合。新しい行「有効な予約の同じ配送権利しか消費しない」。満了から作用までを 1 条件にしない', 'examples': '同じ満了を違う時刻に 2 度検出 → 1 回の配送 → 復元 → 二重検出・保存応答の喪失・取消しとの競争・別 run の期限', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R2', 'line': 2022, 'subject': 'W-43 の条件予約。条件の宣言・固定した証拠の像・確かめる仕事 (W-31/W-35)・True/False/Unknown・検出・配送権利を別に', 'constraints': '背骨 ②〜⑤。述語の True/False/Unknown は仕事の実行の成否と別。確かめの鍵 = 対象述語・意味の入力像・契約版。証拠が増えたら別の確かめ (新しい予約権利ではない)。F-a M-11 の不変 snapshot', 'disposition': '**書ける (A02)**', 'conditions': 'INV-2.a/b/c/e/f、6.b/c、7、8、15、16。**新しい条件**: 述語の仕事の run・終わりの save・検出の handle/save。新しい行「True の対象像と権利の対応」「同じ確かめの自己再発行なし」(自分の T の保存だけで同じ確かめを呼び直さない。待つ時間・回数の上限ではない)', 'examples': '不足の像で確かめ → Unknown と不足を保存 → 復元後も同じ不足 → 関係する証拠の追加で別の確かめ、無関係な通知・自分の終わりの通知では増やさない', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R3', 'line': 2023, 'subject': 'W-31 の Act、W-42 の引受け、W-44 の開始・受け取り・送出・報告・止まった確認を別の記録に。結果不明を「作用していない」にしない', 'constraints': '背骨 ②〜⑤。許可の鎖、2 つの軸、Claim/Launch/Enter/Stop/Deliver。受け取り・送出を Running/Stopped の代わりにしない。世界で効いたかは観測で後から読む', 'disposition': '**書ける (A03)**', 'conditions': 'INV-3、5.b、6、7、10、11、15 の Act の枝。C-O14.stop はそのまま。**新しい条件**: 意図・試みの保存、Act の run、報告の保存と処理、結果不明の保全。新しい行「開始・受け取り・送出・結果・停止を混同しない」', 'examples': '1 回の試み → 送出の証拠と結果を別に保存 → 復元 → 送出後の返事の喪失・Unknown 後の遅着・停止なし・重複報告', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R4', 'line': 2024, 'subject': 'W-42 の意図の確認・取下げ、W-43 の予約変更、W-01 の版つき設定と適用。口の変更の選択と適用 (RouteApplied) は別', 'constraints': '背骨 ①〜⑤。対象ごとの前状態の照合 (`Stale` の形)、開始直前の照合。仕事の旧記述を書き換えず、新しい意図・要求を作る。全体の policy_generation は作らない', 'disposition': '**書ける (A04)**', 'conditions': 'INV-2、3.b、5.b、7、8、12.a/b。Stale は INV-9.b を流用せず、**許可の変更専用の新しい行**。**新しい条件**: 変更計画の issue/save、適用の確認、旧対象の残務の引継ぎ。D1 は維持。口を閉じる選択は sui に残し、帳簿の未完を閉口の禁止に使わない', 'examples': '旧許可を持つ Pending と変更を競わせる → 変更と適用を別に保存 → 復元 → 古い許可での Enter・遅着の Frame・同じ前状態から 2 つの変更', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R5', 'line': 2025, 'subject': 'W-39 の共同の配り方の案を選ぶ W-41、適用または Stale の記録。既存の占有と今後の開始に使える配分を分ける', 'constraints': '背骨 ③〜⑤。Need/Occ/Held/Fit、占有 ≤ 割当 ≤ 容量。評価の根は凍結、適用時に前状態と実占有を照合し直す', 'disposition': '**書ける (A05)**', 'conditions': 'INV-2.e/f、3.b/c、5.b、7、8、10、14〜16。**新しい条件**: 割当の適用の handle/save、Stale の処理の保存。新しい行「前の割当との一致・実占有を保つ適用・Pending の旧許可を無断で更新しない」。最低配分や割り当て専用の席は足さない', 'examples': '同じ前割当から 2 案 → 一方を適用 → 復元 → 後の案は Stale、Hung の占有を残す', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R6', 'line': 2026, 'subject': '複数の範囲を対象にする 1 つの共同の案と選択の Point、資源の組を持つ仕事、共同の適用の結果', 'constraints': '背骨 ③〜⑤ (§2-4-0 の表)。同じホストの共有状態の中では、1 歩で全対象の比較と適用の予約を成立させられる。保存は 1 件ずつでよく、共同の適用が確定する前に部分の配分を有効にしない', 'disposition': '**書ける (共同の適用の契約 A06)**。「割り当ての範囲は 1 つ」(§0-2 (a)) は進め方の絞り込みで、背骨の約束ではない。範囲ごとの独立のくじに分けると元の分布に無い組が出る (二範囲 a/b で「x に両方」「y に両方」が各 1/2 なら、分けると「x に a・y に b」が 1/4) ので分けない。**独立のホスト・保存係の間の分散した確定は未接続 (S13)**', 'conditions': 'R5 の枝に INV-2.b、3.c、5.b、6.b、10.a の全資源の同時照合。**新しい条件**: 共同の適用の issue/save/handle。新しい行「部分の適用なし・前状態の組の全件一致・共同の選択との相関を保つ」', 'examples': '二範囲・二仕事の競争、適用の途中で復元、一方の前状態の変更・部分保存・二重適用・範囲ごとのくじ (対照)', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R7', 'line': 2027, 'subject': 'W-35 の候補生成の仕事と版つきの生成宣言、W-30 の新しい過程。候補を作ったことと、その過程を始めると選んだことを分ける', 'constraints': '背骨 ①〜⑤。P.work の種類を広げ、descriptor を各仕事で固定。全後続の同時所有。生成用と選択用のくじを分ける。読み手ごとの採用、知識は仕切らない', 'disposition': '**書ける (族と契約の追加 A07)**。具体的な生成器の意味は別に要る', 'conditions': 'INV-2、3、5〜8、9、10、13〜16 と、宣言した導出に限る 2.d/L-DERIVE。C-O02 は bootstrap だけ。新しい生成の仕事と bootstrap でない過程に**独自の issue/run/save/handle の条件**。新しい行「候補生成の来歴・測度と過程生成の許可の対応」。過程の数の固定上限・動機の一覧・優先順位・最低配分は置かない (有限模型の個数上限は試験の Cut で、sui の選択肢の制限に移さない)', 'examples': '版つきの生成器から候補 → sui が新しい過程を選ぶ → 復元 → 同値の再配送・別名の重複・不足の生成・資源ゼロ・複数の読み手', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R8', 'line': 2028, 'subject': '新しいホストの run の起動事実、旧 run の所有・開始・未保存の計画との復元の対応、外部の実行・停止の照合', 'constraints': '背骨 ②〜⑤を保つには、§2-4-1 の H/P/Runners の寿命・§2-4-2 の歩の境目・§2-4-5 の不変の適用範囲・L-ENV を作り直す必要がある', 'disposition': '**書けない (背骨へ戻す必要)。ゆうの決定 D4 で ★ S5**。原理 5 つは弱めないが、今の H/P が残ることに頼る証明は使い回せない (反例は §3-3)', 'conditions': 'S5 で INV-1〜8、10〜11、14〜15、L-RECEIPT/L-DERIVE の落ちる境目と 44 条件の全実体と p を復元の前後で追う。今の模型の成功はこの行に流用しない', 'examples': '未完の受信・計画・仕事 → 一部を進める → 本文だけ・点まで等で保存 → 再起動 (S5 で)', 'status': '未対応', 'issues': ['G-04']},
    {'id': 'R9', 'line': 2029, 'subject': '評価を経た W-41 の Abandon の選択、対象を固定した取消しの適用、元の p の取りやめによる終わり、別要求による達成の対応の証拠。取りやめは実行の成功・物理的な停止・目的の達成と別', 'constraints': '背骨 ②〜⑤。取消しの適用は短い共有の更新と保存の計画に分け、対象の開始禁止と残務の所有を同じ歩で確立。p の意味と履歴は変えない', 'disposition': '**未確保取消しと目的の取りやめは書ける (A11・A12)。「叶った」の扱いはゆうの決定 D5 で W-45 を実際に足す時に選ぶ ★** (§3-4)', 'conditions': 'INV-2.a/c/e/f、3、5.b、6、7、8、10、15〜16 の枝。C-O14.stop に未確保取消しの枝、★ の 8 条件 (C-O04/05/07/09b/12/13.handle・C-O10/11.run) に p の 2 つの解消の道。全 save と既存の run の結論は維持。**新しい条件**: 取消しの適用の保存、p の終わりの判定と証拠の保存。新しい行「対象・許可・競争の境目・残務の保全、達成と取りやめの区別」', 'examples': 'Abandon を評価して選ぶ・別要求で証拠を得る → 選択と適用・達成の証拠を別に保存 → 復元して同じ p と残務を照合 → Claim が先・選択の対象違い・部分の取消し・実所有なし・遅着・別 q の成功だけ', 'status': '未採用', 'issues': ['G-04']},
    {'id': 'R10', 'line': 2030, 'subject': '生成方法が要る生成用のくじの要求の記録 RG (`sui.fb.generation_draw_requested/1` 仮称)、くじの仕事 Dg (FWork の Draw の用途)、値 DFg (`draw_fact/1`)・不明 DUg (`sui.fb.generation_draw_unknown/1` 仮称)', 'constraints': '背骨 ②〜⑤。Qgen を含む初期計画の Publish で宣言した各 draw slot に RG の発行の責務、RG の Publish と同時に Dg 行。Dg の終わりは I-8 `DrawReturned` (M4)。DFg は Ee を約束せず、Wg の宣言した入力 slot への依存 (固定した PlanRef、保存済みの Point へ 1 度だけ解決) を満たす。Wg は要る DFg が全部保存され対応と許可が確かめられてから開始。CG の generation.draws に使った DFg の Point を載せる。PR/FProblem や選択用の D の権利は使わない。context_key は F-a M-13 の式 (生成後の input_order・CG・評価の problem_key を混ぜない)', 'disposition': '**書ける (契約の追加 A14、選択用の D → Ee と同じ形の Dg → Wg)**。Wg の開始の前に要るくじの要求を全部固定できる生成契約まで。**生成の途中で新しいくじを要求する方式は別の未接続** (事前の抽選や固定の個数に近似しない)', 'conditions': 'O-GD の 7 条件 (issue[RG]・save[RG]・run[Dg]・save[T]・handle[Dg]・issue[DFg/DUg]・save[DFg/DUg]) で 58。新しい行 INV-14.c (RG・Dg・DFg・Wg の実入力の対応、PR を捏造せず別用途や DUg を値に使わない)。Dg の Unknown・Failure では値の無い依存と元目的の未達を Wg 側が引き受け、Wg は未開始のまま (Wg の Unknown や NoCandidates を捏造しない)', 'examples': '宣言した draw が 0・1・複数、一部だけ保存、Dg の値・Failure・Unknown が最初、Dg が Hung でも受信・保存が進む、容量 1 で Wg が未保存の DFg を待って先に席を取らない、生成用と選択用の取り違え', 'status': '未採用', 'issues': ['G-04']},
)

USAGE_ROWS = (
    {'id': 'B1', 'line': 2095, 'precondition': '同じ run、空の置き場、bootstrap の口、`initial=None` (対照で有り)', 'steps': 'Boot と ClockDeclared を post → accept → settle / 未知の bytes の Received / settle 中の保存の障害 (commit 前・本文の後の応答の喪失・点の後の応答の喪失) / `rebuild_window` → 同じ原本を再受付・保存 / 同文の新しい post / 外形の誤り・同番号の改変・r > s / `initial` 有りの対照', 'expected': 'Boot は 2 点が揃って保存完了、`initial=None` で bootstrap の Compute は出ない。未知の bytes でも受理し観測を捏造しない。本文だけでは受信の点は未保存。再受付は同じ名前・r・s・本文・親・salt・CID (新しい受信を増やさない)、新しい post は別の受信。shape は記録も預かりも作らない。`initial` 有りでも測定・受信の責務は同じで計算の有無だけ変わる'},
    {'id': 'B2', 'line': 2096, 'precondition': 'B1 から、保存済みの区間の要求 k と公開の MeasureSegment。読み方・時計・対象のセルを先に固定', 'steps': '`drain` を 2 回 / Started より先の Frame / RouteApplied・Started / Gap・Unavailable・Claim・Unproved を別ケース / 保存の途中の障害と作り直し / 同 slot の再配送と別 slot / 同 slot の Gap と Unavailable (食い違い) / Ended / end > r の Frame・Claim と未来の Unproved の対照', 'expected': '`drain` は読むだけで仕事を消さない。開始の証拠の無い結びつきは待つ。Gap・Unavailable を値 0 にしない、Claim は独立の Support、Unproved は未証明。同 slot 同内容は受信だけ増える、別 slot は別の論理報告。Ended でも未報告のセルと停止の管理は残る (D1)。無報告から Gap を作らない'},
    {'id': 'B3', 'line': 2097, 'precondition': '`initial` 有り、宣言した δ、固定の読み手 ρ、容量 2、旧根 X0 の評価が進行中', 'steps': '`status`・`drain` で旧評価の対象を記録 / Received と測定の報告 → 保存 / δ の前提が揃って新根 X1 の Q → Wr / Wr の WorkFinished → R / R の保存の境目で障害・作り直し → Wp / Wp → T・P・Cq / 取得の意図 → G → Wv / 認証の成功 → T・V・採用 A / 旧評価の返答 / 別 Q の R・兄弟に見えるだけの取得の負のケース', 'expected': '旧評価の根は X0 のまま (新しい受信で書き換えない)。受信は旧評価が終わらなくても保存できる。`accept` の None は正しさの認証ではない。R の保存の前に Wp を始めない。Cq は 1 つ。採用には取得の実祖先・前状態・直前の使用の条件が要る。旧評価は X0 の答え、新しい採用は X1 の系列 (1 本の全体の系列にまとめない)。誤った対応から Cq・認証成功・採用を作らない'},
    {'id': 'B4', 'line': 2098, 'precondition': '保存済みの採用 d0 と結果 r0、別々の意図から Q1・Q2 (どちらも previous_result = r0)', 'steps': 'Q1/Q2 を保存 / 各 Wr/Wp/Wv を認証まで / Q1 の採用 → d1/r1 / 作り直し後に status と台帳 / Q2 の処理 / d1 の後の Q3 (previous_result = r1) / 別の採用の意図による同じ Cq の再採用 / Wv の Rejected・Insufficient・Unknown / 不足の後に証拠が増えた枝', 'expected': 'd1 は保たれ Q2 の previous_result を書き換えない。Q2 は Stale (例外や Conflict にしない、逆順も対照)。Q3 は進める (永久に拒む検査にしない)。Rejected は拒否の処理、Insufficient は T + V と未完の目的、Unknown は T と未完、採用しない。旧 w の終わりや既発生の p は変えない (D3)'},
    {'id': 'B5', 'line': 2099, 'precondition': '`initial` 有り。生成用のくじを要しない生成の方法・版・根・測度を宣言 (D6。どの候補を選ぶかは固定しない)', 'steps': 'Boot → Qgen・Wg (§2-4-11 M3) / Wg の WorkFinished → T・CG (または NoCandidates) / EQ と Ep / Ep の FProblem → T・artifact・PR → D / Ep の正規の NoDecision (D なし) / `DrawReturned(DrawValue)` → T・DF → Ee / DF の保存の途中の作り直し / Ee の Selected → T・artifact・EV → selection / Ee の NoDecision / `DrawReturned(DrawFailure)` が最初の枝 (T だけ、DF・Ee なし) / D を名乗る `WorkFinished` を保存しても D の終わりにしない枝 / problem_key・purpose・Draw・artifact を 1 つずつ差し替えた報告', 'expected': '初期計画は bootstrap の事実 (sui が選んだ記録にしない)。NoCandidates では CG・FProblem・D を作らない。`drain` の再読はくじの引き直しではない。Selected の後も作用は出さない。NoDecision・Unknown・Failure を Selected に置き換えない。誤った組み合わせから評価の成功・selection を作らない'},
    {'id': 'B6', 'line': 2100, 'precondition': 'Wr/Wp/Wv/Ep/D/Ee/Wg を仕事の種類ごとに別ケース、同じ run・同じ r の通知も使う', 'steps': '最初の Unknown (D は `DrawReturned(DrawUnknown)`、D の Failure が先・Unknown が後の対照も) を accept / 次の値の通知を先に保存 / 作り直し / 最初の受信を保存 / 同値の遅着 / 両立しない値 B / 停止の確認なしで Received / 外の係の実際の停止の確認', 'expected': '後の点があっても最初の受信が未保存なら終わりを決めない。受信の順と未保存の先行通知を作り直しで変えない。最初が Unknown なら T は Unknown (D なら DU で Ee なし、Wr なら成功 R/Wp なし…)。同値の遅着は受信だけ、Unknown と値が並んだだけでは Conflict にしない。A/B で Conflict、既存の T は残り新しい使用を止める。停止未確認の占有は残る、正当な解放は 1 回'},
    {'id': 'B7', 'line': 2101, 'precondition': '合法な計算 1 つが Hung、D が未開始。容量 1/2 を別の宣言で比べる', 'steps': '仕事を開始 (終わらず停止の報告もない) / Received を accept / settle で保存 / 保存の応答の喪失と作り直し / 容量 1 と 2 での D の開始の観察 / 確保済み・起動待ち・確かな未開始の失敗の枝 / 有限の障害の後に正常化', 'expected': '考える席が埋まっていても受信を預かり保存できる。Hung の占有は残る。容量 1 で席が無ければ D 待ちは合法、容量 2 で条件と空席があれば他の仕事の Hung だけで D の開始を隠さない (必ず選ばれるとは言わない)。`run_until` の timeout は試験の未完で、計算の Failure・締め切り・目的の放棄に変えない'},
)

SOURCE_ENUMERATION = (
    {'id': 'W-01', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 62, 'last': 62, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-01'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-02', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 63, 'last': 63, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-02'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-03', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 64, 'last': 64, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-03'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-04', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 65, 'last': 65, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-04'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-05', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 66, 'last': 66, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-05'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-06', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 67, 'last': 67, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-06'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-07', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 68, 'last': 68, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-07'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-08', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 69, 'last': 69, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-08'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-09', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 70, 'last': 70, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-09'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-10', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 78, 'last': 78, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-10'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-11', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 79, 'last': 79, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-11'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-12', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 80, 'last': 80, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-12'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-13', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 81, 'last': 81, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-13'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-14', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 82, 'last': 82, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-14'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-15', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 83, 'last': 83, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-15'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-20', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 91, 'last': 91, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-20'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-21', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 92, 'last': 92, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-21'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-22', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 93, 'last': 93, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-22'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-23', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 94, 'last': 94, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-23'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-24', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 95, 'last': 95, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-24'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-30', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 103, 'last': 103, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-30'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-31', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 104, 'last': 104, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-31'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-32', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 105, 'last': 105, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-32'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-33', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 106, 'last': 106, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-33'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-34', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 107, 'last': 107, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-34'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-35', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 108, 'last': 108, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-35'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-36', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 109, 'last': 109, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-36'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-37', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 110, 'last': 110, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-37'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-38', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 111, 'last': 111, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-38'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-39', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 112, 'last': 112, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-39'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-40', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 120, 'last': 120, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-40'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-41', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 121, 'last': 121, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-41'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-42', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 122, 'last': 122, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-42'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-43', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 123, 'last': 123, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-43'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-44', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 124, 'last': 124, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-44'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'W-45', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 125, 'last': 125, 'read_scope': '該当部分'}, 'targets': ['T.vocab.W-45'], 'disposition': '列挙', 'reason': '語彙の意味と使わない意味を保持'},
    {'id': 'I-1', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 172, 'last': 172, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-1'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-2', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 173, 'last': 173, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-2'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-3', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 174, 'last': 174, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-3'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-4', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 175, 'last': 175, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-4'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-5', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 176, 'last': 176, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-5'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-6', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 177, 'last': 177, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-6'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-7', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 178, 'last': 178, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-7'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'I-8', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 474, 'last': 474, 'read_scope': '該当部分'}, 'targets': ['T.entry.I-8'], 'disposition': '列挙', 'reason': '入口の外形と原報告/後段の意味使用を区別'},
    {'id': 'SHAPE-461', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 461, 'last': 461, 'read_scope': '該当部分'}, 'targets': ['T.paper.461'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-462', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 462, 'last': 462, 'read_scope': '該当部分'}, 'targets': ['T.paper.462'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-463', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 463, 'last': 463, 'read_scope': '該当部分'}, 'targets': ['T.paper.463'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-464', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 464, 'last': 464, 'read_scope': '該当部分'}, 'targets': ['T.paper.464'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-465', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 465, 'last': 465, 'read_scope': '該当部分'}, 'targets': ['T.paper.465'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-466', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 466, 'last': 466, 'read_scope': '該当部分'}, 'targets': ['T.paper.466'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-467', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 467, 'last': 467, 'read_scope': '該当部分'}, 'targets': ['T.paper.467'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-468', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 468, 'last': 468, 'read_scope': '該当部分'}, 'targets': ['T.paper.468'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-469', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 469, 'last': 469, 'read_scope': '該当部分'}, 'targets': ['T.paper.469'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-470', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 470, 'last': 470, 'read_scope': '該当部分'}, 'targets': ['T.paper.470'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-471', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 471, 'last': 471, 'read_scope': '該当部分'}, 'targets': ['T.paper.471'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-472', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 472, 'last': 472, 'read_scope': '該当部分'}, 'targets': ['T.paper.472'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-473', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 473, 'last': 473, 'read_scope': '該当部分'}, 'targets': ['T.paper.473'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-474', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 474, 'last': 474, 'read_scope': '該当部分'}, 'targets': ['T.paper.474'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'SHAPE-475', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 475, 'last': 475, 'read_scope': '該当部分'}, 'targets': ['T.paper.475'], 'disposition': '列挙', 'reason': '公開入口の独立した列挙元'},
    {'id': 'BOUNDARY-479', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 479, 'last': 479, 'read_scope': '該当部分'}, 'targets': ['T.paper.479'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-480', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 480, 'last': 480, 'read_scope': '該当部分'}, 'targets': ['T.paper.480'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-481', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 481, 'last': 481, 'read_scope': '該当部分'}, 'targets': ['T.paper.481'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-482', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 482, 'last': 482, 'read_scope': '該当部分'}, 'targets': ['T.paper.482'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-483', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 483, 'last': 483, 'read_scope': '該当部分'}, 'targets': ['T.paper.483'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-484', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 484, 'last': 484, 'read_scope': '該当部分'}, 'targets': ['T.paper.484'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-485', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 485, 'last': 485, 'read_scope': '該当部分'}, 'targets': ['T.paper.485'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'BOUNDARY-486', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 486, 'last': 486, 'read_scope': '該当部分'}, 'targets': ['T.paper.486'], 'disposition': '列挙', 'reason': '版/新契約/互換の列挙元'},
    {'id': 'FIX-1911', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1911, 'last': 1911, 'read_scope': '該当部分'}, 'targets': ['T.paper.1911'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1912', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1912, 'last': 1912, 'read_scope': '該当部分'}, 'targets': ['T.paper.1912'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1913', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1913, 'last': 1913, 'read_scope': '該当部分'}, 'targets': ['T.paper.1913'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1914', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1914, 'last': 1914, 'read_scope': '該当部分'}, 'targets': ['T.paper.1914'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1915', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1915, 'last': 1915, 'read_scope': '該当部分'}, 'targets': ['T.paper.1915'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1916', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1916, 'last': 1916, 'read_scope': '該当部分'}, 'targets': ['T.paper.1916'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1917', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1917, 'last': 1917, 'read_scope': '該当部分'}, 'targets': ['T.paper.1917'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1918', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1918, 'last': 1918, 'read_scope': '該当部分'}, 'targets': ['T.paper.1918'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1919', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1919, 'last': 1919, 'read_scope': '該当部分'}, 'targets': ['T.paper.1919'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1920', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1920, 'last': 1920, 'read_scope': '該当部分'}, 'targets': ['T.paper.1920'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1921', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1921, 'last': 1921, 'read_scope': '該当部分'}, 'targets': ['T.paper.1921'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1925', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1925, 'last': 1925, 'read_scope': '該当部分'}, 'targets': ['T.paper.1925'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1926', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1926, 'last': 1926, 'read_scope': '該当部分'}, 'targets': ['T.paper.1926'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1927', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1927, 'last': 1927, 'read_scope': '該当部分'}, 'targets': ['T.paper.1927'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1931', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1931, 'last': 1931, 'read_scope': '該当部分'}, 'targets': ['T.paper.1931'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1932', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1932, 'last': 1932, 'read_scope': '該当部分'}, 'targets': ['T.paper.1932'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1933', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1933, 'last': 1933, 'read_scope': '該当部分'}, 'targets': ['T.paper.1933'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1934', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1934, 'last': 1934, 'read_scope': '該当部分'}, 'targets': ['T.paper.1934'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1935', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1935, 'last': 1935, 'read_scope': '該当部分'}, 'targets': ['T.paper.1935'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1936', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1936, 'last': 1936, 'read_scope': '該当部分'}, 'targets': ['T.paper.1936'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1937', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1937, 'last': 1937, 'read_scope': '該当部分'}, 'targets': ['T.paper.1937'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1938', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1938, 'last': 1938, 'read_scope': '該当部分'}, 'targets': ['T.paper.1938'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1942', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1942, 'last': 1942, 'read_scope': '該当部分'}, 'targets': ['T.paper.1942'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1943', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1943, 'last': 1943, 'read_scope': '該当部分'}, 'targets': ['T.paper.1943'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1944', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1944, 'last': 1944, 'read_scope': '該当部分'}, 'targets': ['T.paper.1944'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1945', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1945, 'last': 1945, 'read_scope': '該当部分'}, 'targets': ['T.paper.1945'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1946', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1946, 'last': 1946, 'read_scope': '該当部分'}, 'targets': ['T.paper.1946'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1947', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1947, 'last': 1947, 'read_scope': '該当部分'}, 'targets': ['T.paper.1947'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1948', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1948, 'last': 1948, 'read_scope': '該当部分'}, 'targets': ['T.paper.1948'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1952', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1952, 'last': 1952, 'read_scope': '該当部分'}, 'targets': ['T.paper.1952'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1953', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1953, 'last': 1953, 'read_scope': '該当部分'}, 'targets': ['T.paper.1953'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1954', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1954, 'last': 1954, 'read_scope': '該当部分'}, 'targets': ['T.paper.1954'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1955', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1955, 'last': 1955, 'read_scope': '該当部分'}, 'targets': ['T.paper.1955'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1956', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1956, 'last': 1956, 'read_scope': '該当部分'}, 'targets': ['T.paper.1956'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1957', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1957, 'last': 1957, 'read_scope': '該当部分'}, 'targets': ['T.paper.1957'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1958', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1958, 'last': 1958, 'read_scope': '該当部分'}, 'targets': ['T.paper.1958'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1960', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1960, 'last': 1960, 'read_scope': '該当部分'}, 'targets': ['T.paper.1960'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1961', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1961, 'last': 1961, 'read_scope': '該当部分'}, 'targets': ['T.paper.1961'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1962', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1962, 'last': 1962, 'read_scope': '該当部分'}, 'targets': ['T.paper.1962'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1963', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1963, 'last': 1963, 'read_scope': '該当部分'}, 'targets': ['T.paper.1963'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1964', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1964, 'last': 1964, 'read_scope': '該当部分'}, 'targets': ['T.paper.1964'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1968', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1968, 'last': 1968, 'read_scope': '該当部分'}, 'targets': ['T.paper.1968'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1970', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1970, 'last': 1970, 'read_scope': '該当部分'}, 'targets': ['T.paper.1970'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'FIX-1972', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 1972, 'last': 1972, 'read_scope': '該当部分'}, 'targets': ['T.paper.1972'], 'disposition': '列挙', 'reason': 'M1/M2/M3/M4/M10の意味・枝・条件を保持'},
    {'id': 'EXTERNAL-2021', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2021, 'last': 2021, 'read_scope': '該当部分'}, 'targets': ['T.paper.2021'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2022', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2022, 'last': 2022, 'read_scope': '該当部分'}, 'targets': ['T.paper.2022'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2023', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2023, 'last': 2023, 'read_scope': '該当部分'}, 'targets': ['T.paper.2023'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2024', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2024, 'last': 2024, 'read_scope': '該当部分'}, 'targets': ['T.paper.2024'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2025', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2025, 'last': 2025, 'read_scope': '該当部分'}, 'targets': ['T.paper.2025'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2026', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2026, 'last': 2026, 'read_scope': '該当部分'}, 'targets': ['T.paper.2026'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2027', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2027, 'last': 2027, 'read_scope': '該当部分'}, 'targets': ['T.paper.2027'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2028', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2028, 'last': 2028, 'read_scope': '該当部分'}, 'targets': ['T.paper.2028'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2029', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2029, 'last': 2029, 'read_scope': '該当部分'}, 'targets': ['T.paper.2029'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2030', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2030, 'last': 2030, 'read_scope': '該当部分'}, 'targets': ['T.paper.2030'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2064', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2064, 'last': 2064, 'read_scope': '該当部分'}, 'targets': ['T.paper.2064'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2065', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2065, 'last': 2065, 'read_scope': '該当部分'}, 'targets': ['T.paper.2065'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2066', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2066, 'last': 2066, 'read_scope': '該当部分'}, 'targets': ['T.paper.2066'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2067', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2067, 'last': 2067, 'read_scope': '該当部分'}, 'targets': ['T.paper.2067'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2068', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2068, 'last': 2068, 'read_scope': '該当部分'}, 'targets': ['T.paper.2068'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2069', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2069, 'last': 2069, 'read_scope': '該当部分'}, 'targets': ['T.paper.2069'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2070', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2070, 'last': 2070, 'read_scope': '該当部分'}, 'targets': ['T.paper.2070'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2071', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2071, 'last': 2071, 'read_scope': '該当部分'}, 'targets': ['T.paper.2071'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2072', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2072, 'last': 2072, 'read_scope': '該当部分'}, 'targets': ['T.paper.2072'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2073', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2073, 'last': 2073, 'read_scope': '該当部分'}, 'targets': ['T.paper.2073'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2074', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2074, 'last': 2074, 'read_scope': '該当部分'}, 'targets': ['T.paper.2074'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2075', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2075, 'last': 2075, 'read_scope': '該当部分'}, 'targets': ['T.paper.2075'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2048', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2048, 'last': 2048, 'read_scope': '該当部分'}, 'targets': ['T.paper.2048'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2052', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2052, 'last': 2052, 'read_scope': '該当部分'}, 'targets': ['T.paper.2052'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2053', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2053, 'last': 2053, 'read_scope': '該当部分'}, 'targets': ['T.paper.2053'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2054', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2054, 'last': 2054, 'read_scope': '該当部分'}, 'targets': ['T.paper.2054'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'EXTERNAL-2056', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2056, 'last': 2056, 'read_scope': '該当部分'}, 'targets': ['T.paper.2056'], 'disposition': '未採用', 'reason': '外付けの案。今回採用した契約に昇格しない'},
    {'id': 'USAGE-2095', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2095, 'last': 2095, 'read_scope': '該当部分'}, 'targets': ['T.usage.B1'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'USAGE-2096', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2096, 'last': 2096, 'read_scope': '該当部分'}, 'targets': ['T.usage.B2'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'USAGE-2097', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2097, 'last': 2097, 'read_scope': '該当部分'}, 'targets': ['T.usage.B3'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'USAGE-2098', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2098, 'last': 2098, 'read_scope': '該当部分'}, 'targets': ['T.usage.B4'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'USAGE-2099', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2099, 'last': 2099, 'read_scope': '該当部分'}, 'targets': ['T.usage.B5'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'USAGE-2100', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2100, 'last': 2100, 'read_scope': '該当部分'}, 'targets': ['T.usage.B6'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'USAGE-2101', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2101, 'last': 2101, 'read_scope': '該当部分'}, 'targets': ['T.usage.B7'], 'disposition': '列挙', 'reason': '紙の利用例。実行済みではない'},
    {'id': 'DISTINCTION-133', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 133, 'last': 133, 'read_scope': '該当部分'}, 'targets': ['T.paper.133'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-134', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 134, 'last': 134, 'read_scope': '該当部分'}, 'targets': ['T.paper.134'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-135', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 135, 'last': 135, 'read_scope': '該当部分'}, 'targets': ['T.paper.135'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-136', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 136, 'last': 136, 'read_scope': '該当部分'}, 'targets': ['T.paper.136'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-137', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 137, 'last': 137, 'read_scope': '該当部分'}, 'targets': ['T.paper.137'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-138', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 138, 'last': 138, 'read_scope': '該当部分'}, 'targets': ['T.paper.138'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-139', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 139, 'last': 139, 'read_scope': '該当部分'}, 'targets': ['T.paper.139'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-140', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 140, 'last': 140, 'read_scope': '該当部分'}, 'targets': ['T.paper.140'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-141', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 141, 'last': 141, 'read_scope': '該当部分'}, 'targets': ['T.paper.141'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-145', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 145, 'last': 145, 'read_scope': '該当部分'}, 'targets': ['T.paper.145'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-146', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 146, 'last': 146, 'read_scope': '該当部分'}, 'targets': ['T.paper.146'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-147', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 147, 'last': 147, 'read_scope': '該当部分'}, 'targets': ['T.paper.147'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-148', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 148, 'last': 148, 'read_scope': '該当部分'}, 'targets': ['T.paper.148'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-149', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 149, 'last': 149, 'read_scope': '該当部分'}, 'targets': ['T.paper.149'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-150', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 150, 'last': 150, 'read_scope': '該当部分'}, 'targets': ['T.paper.150'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-182', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 182, 'last': 182, 'read_scope': '該当部分'}, 'targets': ['T.paper.182'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-183', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 183, 'last': 183, 'read_scope': '該当部分'}, 'targets': ['T.paper.183'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-184', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 184, 'last': 184, 'read_scope': '該当部分'}, 'targets': ['T.paper.184'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-2085', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2085, 'last': 2085, 'read_scope': '該当部分'}, 'targets': ['T.paper.2085'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-2089', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2089, 'last': 2089, 'read_scope': '該当部分'}, 'targets': ['T.paper.2089'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-2117', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2117, 'last': 2117, 'read_scope': '該当部分'}, 'targets': ['T.paper.2117'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-2119', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2119, 'last': 2119, 'read_scope': '該当部分'}, 'targets': ['T.paper.2119'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
    {'id': 'DISTINCTION-2121', 'source': {'path': 'specs/関所F_Fb_今の約束.md', 'first': 2121, 'last': 2121, 'read_scope': '該当部分'}, 'targets': ['T.paper.2121'], 'disposition': '列挙', 'reason': '境界/禁止/非対象も理由とともに保持'},
)

PAPER_FRAGMENTS = {
    62: '| **W-01** | 口 (route) | 膜の外から何かが入る経路。版つきの設定 (`route_epoch`・測り方の契約・時計の契約・欠けの契約・引数) を持つ。設定には由来がある: 最初から置いた (`bootstrap`) / sui が選んで変えた・足した (`selected`、選んだ記録と実行の記録を指す) | 時計の刻みではない。配送の包み方 (何件まとめて届くか) でもない | `Arrived.route` の文字列だけ。設定と版は無い |',
    63: '| **W-02** | 受け口 | 届いたものを**種類を問わず**、bytes と media type のまま残す口。中身の意味を決めない (中身を読む契約を後から足すのは sui の側) | 中身を限定した口 (例: 「手紙だけ」) ではない。受け口があることは、何かが届くことの約束ではない | 無い (`Arrived` は契約を送り手が付ける) |',
    64: '| **W-03** | 測定 | 口で、ある区間について値を得た出来事。区間 (i: 始め・終わり・閉じ方) と、測った出来事 (e) を持つ。**「変わらなかった」も値のある測定** | 「測れなかった」は測定ではない (W-04)。受信 (W-06) とも別: 測った時と届いた時は違う | 無い (`MeasurementFrame` は履歴の型だけ) |',
    65: '| **W-04** | 測れなかった・欠け・被覆 | 測れなかった = その区間について値を得られなかった報告 (`MeasurementUnavailable`)。欠け = 測定の列の抜け (`Gap`)。被覆 = 「その区間を見張っていた」という主張と証拠 (`CoverageClaim`)。被覆を証明できない = `CoverageUnproved` | 見張り役が生きていたことだけで被覆を主張しない。「何も来なかった」は被覆の証拠がある区間についてだけ (F-a A-15) | 型は F-a の和型 (`sui.f.coverage/1`) にある。運用は無い |',
    66: '| **W-05** | 到着 | 外のものが口に来たこと。**sui からは直接見えない**。見えるのは受信 (W-06) と、送り手の主張 (W-08) だけ | 受信の時刻を到着の時刻と呼ばない | — |',
    67: '| **W-06** | 受信 (r) | ホストが届いたものを封筒に入れ、同じ run の単調時計 (M) の読みを押した出来事 | 受付 (W-10)・保存 (W-12)・信念に入ること (W-23) を含まない | `ThreadHost.post` が `Envelope.received_ns` を押す → `Observed.received_ns` |',
    68: '| **W-07** | 時計の読み | 宣言した時計 (時計の契約・run) で読んだ値 (`ClockReading`)。読みの証拠は、どの時計をどの run で読んだかの記録 | 通知の中に書いてある時刻 (W-08) と取り換えない | `Clock.mono_ns()`・`ClockSource` (S4c) |',
    69: '| **W-08** | 通知の内容 | 届いたものに書いてあること。中の時刻は送り手の主張 (u、領域 U) | 時計の読みの証拠ではない。F-a A-12 の例外 (D2) をここで広げない | `Observed.content`・`source_time_ns` |',
    70: '| **W-09** | 3 つの役割 | 最初の感覚の 3 つ: **外を見る窓** (W-01〜W-03 の口と受け口) / **いつどこまで見えたかの札** (各測定の区間・被覆・受信の読み。独立の口にせず、各記録の欄で担う) / **自分がしたことの記録** (§1-5 の確定と実行の記録)。起動の環境は起動時の 1 回の記録、計算の資源は宣言した容量 (W-38) と仕事の記録で担う | 「5 つのセンサー」ではない。時刻・口の具合を別の口として常設しない | `Boot`・`Listen` (開いた・閉じた) の記録がある |',
    78: '| **W-10** | 受付 | 窓口が封筒から記録を**1 度だけ**作り、預かり箱に預けた出来事。失敗したら同じ封筒で受付をやり直す (同じ記録の名前を使う) | 書いていない (保存 W-12 は別)。記録の中身が正しいことの認証ではない (認証は F-a の事実の入口) | `Window.accept` → `Pledges.items` |',
    79: '| **W-11** | 預かり | 引き受けたがまだ済んでいない約束 (書く・始める・知らせる・依頼する)。窓口を作り直しても捨てない | 信念の途中の値は預けない。プロセスをまたいで残す約束ではない (それは S5) | `Pledges` |',
    80: '| **W-12** | 保存成功 | 記録の本文、続けて台帳の点 (CID) が置き場に確定し、プロセスが強制終了しても残る (k2) ところまで行った出来事 | 記録の時刻 s (`Record.at`) は記録を作った時に押したもので、保存成功の時刻ではない。保存は信念に入ったことを含まない | `contents.put` → `EntryStore.add` (`ledger.append`)。保存成功の時刻は今は記録しない |',
    81: '| **W-13** | 保存の再試行 | 保存が失敗した後、**同じ預かりの同じ記録**で書き直すこと。新しい記録を作らない | 受付のやり直し (W-10) とは段が違う | r5 (窓口を作り直しても同じ預かり) |',
    82: '| **W-14** | 窓口 | 台帳に書く唯一の係 (書く接続は 1 つ)。受付・保存・反映・依頼の受け取りを順に進める | 考えたり作用したりしない (それは仕事 W-31)。「窓口が 1 つ」は保存の上の直列化で、sui の活動を 1 本にする意味ではない (背骨 ③) | `Window` (`accept`・`settle`・`status`・`drain`) |',
    83: '| **W-15** | ホスト | 受信の時刻を押し、仕事をスレッドで走らせ、窓口を作り直す係 | 選ばない | `ThreadHost` |',
    91: '| **W-20** | 読み手 | 事実を取得して信念を作る主体の部分 (F-a の origin)。**知識は仕切らない**: 届いた事実はどの読み手も取得できる。届く前から知っていたとは扱わない | 読み手が複数あっても、隠す・見せないの設計はしない (0-2 の (あ)) | F-a の `origin` |',
    92: '| **W-21** | 取得 (a) | ある読み手が事実の内容を手に取った出来事。F-a A-09・A-10・A-11 のまま | 参照しただけ・内容を使っただけと同一視しない (F-a A-07) | F-a `content_acquired/1` |',
    93: '| **W-22** | 導出 | 取得した事実から信念 (核・事後) を計算すること。窓口の外の仕事 (W-31) で行う | 採用 (W-23) を含まない | 今は `Agent.adopt` の中で同期に計算 |',
    94: '| **W-23** | 採用 (d) | ある読み手が計算結果を自分の信念として使うと決めた出来事。F-a A-10・A-16 のまま (同じ導出の再採用は新しい観測の適用ではない) | 保存成功 (W-12) を含意しない。採用は §1-5 の確定の 1 つ | F-a の adopted。S3 の `Window._adopt` は台帳の先端を信念に入れる旧経路で、F-a の採用の認証を通らない |',
    95: '| **W-24** | 反映 | 背骨 ② の段の名前 = 「受信した事実が、ある読み手の採用まで届いた」こと。**反映という別の出来事は作らない** (出来事としては採用が担う) | どの読み手にも反映済み、を 1 つの印で表さない (読み手ごと) | `Status` に印は無い (履歴の `PerceptionStatus`・`BeliefStatus` は案) |',
    103: '| **W-30** | 過程 | 続いていく活動のひとまとまり (例: ある口の測定を続ける / ある根の評価 / 外へ出ている手 / ある予約の見張り)。ほかの過程と因果・共有する資源・証拠で結ばれる。**全部を 1 本の列に並べない** | 「今の思考」は 1 つではない。過程の数を 1 に固定しない | 無い (S3 は思考の席 `think` と手を別々に数えるだけ) |',
    104: '| **W-31** | 仕事 | ホストが窓口の外のスレッドで走らせる 1 回分の計算か作用 (考える・導出する・評価する・手を動かす)。過程は仕事を何回も含みうる。仕事は台帳・主体・書く接続を持たない | 過程 (W-30) と同じではない | `Think`・`Act` → `Thought`・`Done`・`Failed`・`ActionDone` |',
    105: '| **W-32** | きっかけ | 過程を始める・変える元になったもの。**外の事実** (受信した記録) か、**内の理由** (自分の信念・好み・能力から出た候補)。どちらも候補の由来の札で、考え始める入口がこの 2 つだけという意味ではない | 時計の刻み (`Tick`) だけでは選び方を変えない。満了 (W-43) は約束の配送で、無条件に考え始める合図ではない | `Drive.react(status, event)` (S3)。`Tick` は時計の読みを届けるだけ |',
    106: '| **W-33** | 根 | 評価に固定した入力一式 (モデル・好み・E/K・文脈・候補と測度・評価の範囲・継続・方法と契約の版、F-a P-07)。**根の凍結** = 答えに「何時までの事実で」の札をつけること (背骨 ④): その根の K が含む事実の集合と文脈の判断境界 j | 計算中に事実が増えても元の根の答えは有効 (B8)。新しい事実への追いつきは別の根の別の評価 | F-a `FRoot` 相当 (数学の側) |',
    107: '| **W-34** | 評価 | 根を固定して G・方策を計算する仕事。答えが出ても作用の許可ではない | 選ぶ (W-41) を含まない | F-a の数学の入口 (`f.py`) |',
    108: '| **W-35** | 生成 (g) | 計算の結果や候補を作り終えた出来事 (F-a A-10 の `finished_clock`) | 候補の生成と結果の生成を分ける。生成済みであることと、使えること (取得・採用) を分ける | F-a `computation_result/1` |',
    109: '| **W-36** | 方針 | ある過程が選んで持ち続けている**選び方の法則** (手の上の確率、方策)。持続し、きっかけで見直される。**過程ごとに持つ**。全体で 1 本の「今の方針」や、その世代番号は置かない | 見込み (W-37) ではない。実際に起きたこと (W-38) でもない | 無い (S3 は毎回 `Reconsider` で考え直す) |',
    110: '| **W-37** | 見込み | 世界や自分についての確率 (信念・予測)。未確定の選択肢とともに、**つながりを保った分布**で持つ (1 つの点にまとめない) | 方針 (選び方) と取り換えない | 信念の記録・`Prediction` |',
    111: '| **W-38** | 実際の過程と記録 | 起きたこと・出した作用。**1 つで、分布ではない** (P1)。靄なのは見込み・方針・過程の側 | 記録の意味に限る (記録の解釈は見込み) | 台帳の事実 |',
    112: '| **W-39** | 容量・配り方 | 容量 = 宣言した資源の上限 (考える席・手・置き場など)。配り方 = 考える力や資源をどの過程に割くかで、**容量を守れる案の上の分布**として、ほかの手と同じ G で比べる | 仕事ごとに独立のくじで配らない (容量を超えうる)。来た順の開始は開発者の規則で、sui の選択ではない | `capacity`・`used`。S3 は来た順に始める (`runtime.py` の `settle`) |',
    120: '| **W-40** | 確定 | 分布や未確定の選択肢から 1 つに決まる出来事。種類は **選ぶ・意図・予約・取得・採用・実行**。どれも**対象** (何について) と**効力の範囲** (どの過程・どの根・いつまで) を持つ | 「1 つに決まるのは作用の瞬間だけ」ではない。無関係な確定を同じ列に並べない | 種類ごとに別の記録 (下) |',
    121: '| **W-41** | 選ぶ | 方策と抽選から手が 1 つに決まる出来事 (`Selected`)。決められなかった (`NoDecision`) とは別。永久に待つ手を選ぶことも選ぶに入る (F-a P-06) | 評価 (W-34) を含まない。選んだことは作用の開始ではない | `Decided` (S1〜)、F-a `Selected` |',
    122: '| **W-42** | 意図 | 選んだ手をやると引き受けた出来事。確かめた・取り下げた・やった の状態を持つ (`Intention`) | 実行 (W-44) とは別 | 今は 2 つの形がある: `JobOpened` (決定から開いた用事、区分は事実) と `Intention` (区分は意図、確かめた・取り下げた・やったを supersedes でつなぐ)。F-b の意図をどちらで表すかは §2 で決める |',
    123: '| **W-43** | 予約 | 未来の条件 (ある時刻 / ある条件) で作用を出すと登録した出来事。**満了** (p: 予定の時刻が来た)・**検出** (条件が成り立ったと気づいた)・**実行** は別々の出来事 | 満了は登録済みの約束の配送で、新しい評価や抽選を無条件に起こす Tick ではない。別 run の期限は時計が揃っていない (`clock_unaligned`) | S4b の `RESERVATION` (送出の待ち)。予約の型は履歴だけ |',
    124: '| **W-44** | 実行 | 作用を外へ出すこと。段は **開始** (試みの記録) → **受け取り** (手の係が受け取った) → **送出** (外へ出た点を手の係が確かめた) → **報告** (結果か終わり)。「実行した」と言うのは送出の確かめがある時だけ | 送出した作用を取り消せたと推定しない。開始の記録だけで実行したとは言わない | `AttemptStarted` → `DispatchNotice(receipt / dispatch)` → `REPORT`・`ENDED` |',
    125: '| **W-45** | 取りやめ | 待つのをやめる・予約を取り消す出来事。それも選ぶ手の 1 つ (評価を経る) | 動いている手・使用中の資源・遅れて来る結果を消さない (r4)。送出済みの作用は取り消せない | `Abandon` → `ABANDON` の `Decided` |',
    172: '| **I-1** | 受け口への受信 | ① 世界 | 口 (`route_epoch`)・bytes・media type・送り手の主張 (送り手の付けた契約の名前・時刻・ID はまとめて中身の一部) → `Observed` (受け口の契約、`received_ns` = r) | 中身の読み方 (どの契約で読むか、P6)。送り手の主張が正しいか。同じ便の配達し直しか | 受信ごとに新しい記録の名前 (P7 ②)。送り手の ID で重ねない | r はホストの M の読み。送り手の時刻は u (W-08) |',
    173: '| **I-2** | 測る係の報告 | ② 仕事 | 測定 / 測れなかった / 欠け / 被覆の主張 (`measurement/1`・`coverage/1`) と、係が宣言した時計で読んだ読み | 被覆が認証できるか・「何も来なかった」と言えるか (使う時に F-a A-14・A-15 で認証) | 報告は生成の証拠 (どの口の設定・どの過程が生んだか) を指す。sample_seq や名前だけで同じ測定と決めない | 測定の区間 i と e ≤ 受信 r ≤ 記録 s (F-a A-13・A-14)。生成の祖先は 2-3 の Q1 |',
    174: '| **I-3** | 計算の仕事の完了 | ② 仕事 | 結果の内容・生成の読み・失敗/不明を知った根拠を原報告として受け取る。信念の更新の R/P/Cq、候補の生成の T/CG、評価の artifact と終わりは用途ごとの契約で導く (すべての返答から `computation_completed/1` を作るわけではない、v0.17 §2-4-11 M3) | 結果が正しいか・使えるか (F-a A-10・E-06 の再読で中で確かめる)。係の「検証済み」の札 | 結びつきは用途ごとに固定した要求の Point と契約の版 (信念の更新は `computation_requested/1`、候補の生成は `sui.fb.candidate_request/1` の Qgen、評価は評価の要求 EQ) の CID。仕事の名前の文字列で結ばない。旧 Q や completed への変換で合わせない | 完了の読み g ≤ 取得 a ≤ … (A-10)。要求が完了の祖先 |',
    175: '| **I-4** | 手の報告 | ② 仕事 | 受け取り・送出・結果の報告 (S4b の `RECEIPT`・`DISPATCH`・`REPORT`・`ENDED`) | 作用が世界で効いたか (観測として後で読む) | `caused_by` の試みの CID | 開始 ≤ 受け取り ≤ 送出 ≤ 報告の受信 |',
    176: '| **I-5** | 予約の満了・条件の検出 | ③ ホスト | ホストが読んだ時計の読みと、どの予約の何の検出か → 検出の記録 (形は 2-3 Q6) | 考え始めるか・作用を出すか (その過程の方針で決める) | 予約の記録の CID + 満了の予定から決まる発火の名前 (同じ発火の再配送は同じ名前) | 予定 p と検出 e を分ける。別 run の予定は `clock_unaligned` |',
    177: '| **I-6** | 起動・口の開閉 | ③ ホスト | 起動の事実 (`sui.s4.boot/1`)・起動の環境 (1 回)・口の設定の適用 (`route_config/1`、最初の口は `origin=bootstrap`) | 起動の環境をどう読むか | 起動は run の原点。口は `route_epoch` | 起動 → 適用の実効の読み ≤ その口の測定 |',
    178: '| **I-7** | 時計の出どころの宣言 | ③ ホスト | `sui.clock.source/1` (宣言 d、実測精度の証明ではない) | 時計の精度 | run | 同じ run の中だけで比べる |',
    474: '- I-8 `DrawReturned(work: WorkId, outcome: DrawValue | DrawFailure | DrawUnknown)` → `sui.fb.draw_report/1`。D の終わりの知らせはどれもこれで受ける (D を名乗る `WorkFinished` は原報告として保存するが D の終わりにしない)。原報告を保存したうえで、要求との対応・最初の終わり・使用の条件が揃った枝だけ `draw_fact/1` か `sui.fb.draw_unknown/1` を出す (v0.17 §2-4-11 M4)',
    461: '- ホスト: 今の `ThreadHost` の形 (`post(event)`・`run_until(done, timeout=)`・封筒 `Envelope(number, event, received_ns)`) を保つ。ただし未開始の箱は仕事表の見え方にする (§2-4-1)',
    462: '- 窓口: `FWindow.accept(envelope) -> None`・`settle() -> None`・`status() -> FStatus` (読み取り専用の公開の像、意味は §2-4-11 M1)・`drain() -> tuple[FWork, ...]` (**列挙で、取り除かない**)。`FWork = MeasureSegment | Compute | Draw` (`Act` は外付け)。旧 `Window`・旧 `Drive` は旧モデルの道として変えない',
    463: '- 受付 = 1 封筒 → 1 受信の記録 `Observed(writer=MEMBRANE, route, contract, content, caused_by=null, source_id=null, source_time_ns=null, received_ns=r)`。知らせの本文はまだ保存していない記録の CID を含まない (含めるのは前に保存した Point だけ)',
    464: '- 受理条件: 出来事の型がこの節のどれかで、外側 (型・欄の型・nullable) が正しいこと。中身の bytes・送り手の主張・報告の値の正しさ・知らない要求や区間への言及では断らない (P1: 事実は先に残す。結びつかない知らせは論理の出来事の材料にならないだけ)',
    465: '- 拒否条件: 外側の形の誤りだけ `FbInputError(reason="shape", field=…)`。記録も預かりも作らず、ホストは同じ封筒を持ったまま例外を上げる',
    466: '- 返す主張: `accept` の成功で言えるのは「この封筒の受信の記録を 1 回だけ作り、預かった」まで。保存成功・完了・採用・認証は言わない',
    467: '- 時間: r = `envelope.received_ns` (ホストの run の M)、s = `Record.at`。r ≤ s を窓口が確かめ、破れたらホストの時計の故障として例外 (入力の誤りではない)。s は保存成功の時刻ではない (保存はその後)',
    468: '- 保存の準備: `Ledger.prepare(record, parents) -> PreparedEntry(record, parents, salt, header, cid)` と `Ledger.write(prepared)`。`write` は書く前と既に点がある時に `seal(payload,salt)`・`encode_header(record,seal,parents)`・`hash(header)` の 3 つの結びつきを確かめる',
    469: '- I-6 `Boot(declaration: BootDeclaration(capacity, scope: ResourceScope, routes, initial: InitialProcess | None, environment))` (範囲は 1 つ)。知らせは `sui.s4.boot/1` と `sui.fb.boot_declaration/1` の 2 つで、**今の `Boot` (記録 1 つ) とは違う新しい道の例外** (v0.5 の「今の Boot と同じ」は誤り)',
    470: '- I-7 `ClockDeclared(declaration: ClockSource)` → `sui.clock.source/1` の受信の記録 1 つ (Boot は 2 slot のまま)。同じプロセスの中の窓口の作り直しは `ThreadHost.rebuild_window() -> FWindow` (v0.17 §2-4-11 M2)',
    471: '- I-1 `Received(route_epoch, media_type, data, claims)` → `sui.fb.received/1`',
    472: '- I-2 `SegmentReport(segment, item_slot, item)` → `sui.fb.segment_report/1`、結びつき `sui.fb.segment_binding/1`',
    473: '- I-3 `WorkFinished(work: WorkId, started, finished, outcome: WorkOutputs | WorkFailure | WorkUnknown)` → `sui.fb.work_report/1`。Compute の用途 (候補の生成 Wg を含む) の終わり。用途と段は §2-4-4、候補の生成は §2-4-11 M3',
    475: '- **読み手の更新のきっかけ** (Claude の見立て、未レビュー): 「新しい結びつきが保存されたら更新を頼む」は条件の起動 (When) と同じ形なので、縦の 1 本では起動の宣言の `initial` に書いた読み手の過程の方法 (`origin=bootstrap`、差し替えられる、P9) が決める。Q5 の ★ (最初の過程を人が置くか) と同じ扱いで、F-b の後に動かして決める',
    479: '- **`finite_update/2` は別の registry に足す** (追記 FBR3 の registry_key): registry_key は使った能力だけでなく全部の宣言と実装の識別を含み (`_f_world.py:199〜207`)、artifact の bytes に入る (`f_facts.py:657〜659`)。旧の不足の artifact の読み直しは当時の reader と registry の一致を求める (`f_facts.py:847〜859`)。だから:',
    480: '  1. 旧の factory (`builtin_f_registry()`、`f.py:2307〜2316`) の宣言の集合・実装の識別・dispatch を固定する。新しい能力を旧 `_BUILTIN_DECLARATIONS` に足さない',
    481: '  2. 新しい factory (名前は仮に `fb_registry_v1()`) が旧の集合と新しい宣言で別の不変の registry を返す (`make_f_registry` は明示の宣言と実装を受け取れる、`f.py:2284〜2304`)',
    482: '  3. `/1` と `/2` を入口から読み直しまで分ける。`/2` には segment_binding の読み方・数値の入力の閉包・時計・因果・食い違い・元の測定の取得・計算し直し・証明と checker・採用・replay の対応が要る。旧 `/1` の Binding が試みを求める条件は緩めない (`_f_invariants.py:243〜257`)。数学の共通部分は共有し、入力の読み方・証明の意味・registry の組み立てを版で分ける',
    483: '  4. 旧の artifact は旧の環境へ戻して読む (保存された compiler・registry_key を検索の鍵に、旧の bundle と読み手の像を渡して計算し直し・照合。key の自己申告を認証にしない。未知の key を今の registry に黙って置きかえない)',
    484: '  5. **確かめる道を 4 つに分ける**: 旧 `/1` + 旧 registry (旧 registry_key・旧 golden の全 bytes) / 保存済みの旧 artifact + 旧 bundle (正の結果の再認証と、当時の不足を今の能力で埋めないこと) / 新 `/2` + 新 registry (bootstrap の結びつきを取得・更新・証明・採用まで) / 誤った組み合わせ (`/2` を旧の道へ・旧の不足の artifact を新 bundle へ・checker の版の付けかえ・元の入力の欠け)',
    485: '- **新しく足す F-a の入口**: 対象を指定した認証物 (§2-4-4)、評価の要求・終わりの F-b の契約、`segment_binding/1` と名前の無い枝の `item_slot`',
    486: '- 新しい契約にはどれも F-a V-08 と同じ形の全欄・Body/Role/Category・版の宣言と、A-01〜A-06 の同一性・参照・因果の共通の規則を当てる。既存の `/1` の意味は変えない',
    1911: '  1. **受信・受付・保存**: 封筒と記録の slot ごとに 受信済み / 受付済みの預かり / 保存の確認待ち / Saved と実在の Point。本文だけ・点の応答の喪失・未照合を保存成功に丸めない。「未確認」を「存在しない」にもしない',
    1912: '  2. **仕事・開始・占有**: WorkId と要求・段に結んだ実行の段、開始できるかと阻んでいる対象、結果の知識、停止の確認、持っている占有。Unknown・終わりの保存・停止を分ける',
    1913: '  3. **読み・反映・選択**: 対象と読み手ごとに 生成まで / 取得まで / 認証まで / 採用まで。確定返答の Rejected・Insufficient・NoDecision、実行の Failure、結果の Unknown を分ける。今の採用の Point、Stale、Selected との対応',
    1914: '  4. **未判定・不足・食い違い**: 未検査、対象つきの証拠待ち、未宣言の契約、Conflict。不足の対象は要求された識別子として示し、実在の Point に偽装しない',
    1915: '  5. **測定の区間・部分**: 区間と対象のセルごとに 未報告 / 報告された Frame・Gap・Unavailable・Claim・Unproved など / Ended。Claim の受信と被覆の認証を分ける。無報告をゼロや Gap にしない',
    1916: '  6. **未完の目的と引継ぎ**: 元の条件・目的・過程・読み手・対象部分を保った識別、局所の処理の達成・引継ぎと残る未達。**引受け先の表示は Owner の独立の証明ではない**',
    1917: '- 各項目に、その対象の完全な識別・判定に使った像・根拠の保存済み Point か未保存の預かりとの対応を付ける。未保存の対象は計画・封筒などの識別で示し、Point と型を分ける。表示名だけで読み手・要求・段・目的部分をまとめない',
    1918: '- 1 回の返答は窓口の公開の操作の境目でとった整合した局所の像。世界全体の同時刻や複数 run の全順序を表さない。状態が進んだ後の別の照会で値が変わったことだけを矛盾にしない',
    1919: '- Saved と表示するには本文・header・CID の照合が要る。確認できない時は「確認不能・待ち」と返し、保存していないとも成功したとも断定しない',
    1920: '- `status` は受付・保存・仕事の開始・取得・採用・くじの消費をしない。重い F-a の検査を照会の中に隠さない (必要な検査が未完ならその対象と未判定を示す)。照会の成否や回数で預かりを消費しない。P の辞書・可変オブジェクト・生きた認証ハンドルを公開しない',
    1921: '- 試験の期待値は、宣言・外から渡した封筒・仕事の係で観測した入場・返答・停止・置き場の実体から独立に作る。`FStatus` を期待値の生成元にも、内部の P を読む代わりの全量ダンプにもしない (H-05・E0-02 の独立性)',
    1925: '- I-7 `ClockDeclared(declaration: ClockSource)` をホストの `post` へ渡す。`ClockSource` の欄は F-a の `sui.clock.source/1` に合わせる (`run, provider, implementation, python_version, resolution_s, monotonic, adjustable, measurement`)。1 通知 → 宣言内容を持つ `Observed` 1 つ (契約 `sui.clock.source/1`)。外側の受理・拒否・再受付・保存は §2-4-7 の共通の規則。別の Post は同じ内容でも別の受信。得るのは**時計の出どころの宣言**で、実測の精度や他の時計との整合の認証ではない。宣言の r・s を、過去の時計の読みの下限にしない。**Boot は 2 slot のまま** (時計の宣言を要する使用は、その実在の Point が揃うまで待つ。未保存の宣言の CID を入力に捏造しない)',
    1926: '- `ThreadHost.rebuild_window() -> FWindow`: 同じプロセスの中で有効な窓口を作り直して返す。保持する H・P・C・E と動いている Runners はそのまま使い、受信の列・処理中の封筒・保存の準備・仕事の記述・開始の札・占有・停止の知識・生きた認証物を台帳だけから作り直さない (§2-4-1)。有効な窓口の切替は、窓口が共有状態を変える歩との間で不可分。切替の前の失敗では旧窓口が有効、切替の後に応答が失われても新旧 2 つを同時に有効にしない。旧窓口への操作は失効を示す `RuntimeError` (入力の shape の誤りと分ける)。作り直し自身は Boot・Post・くじの消費・仕事の再入場・占有の解放をしない。新しい run を作らない。計算の終わりを待たない。並行する本当の受信・停止がなければ、作り直しの前後の公開の像の意味の内容は同じ。プロセスの再起動 (S5、D4) には広げない',
    1927: '- 名前 (`ClockDeclared`・`rebuild_window`) は名前だけの仮定 (今のコードにあるという主張ではない)',
    1931: '- `initial` がある枝では、その宣言が指す版つきの生成方法への**生成の要求 Qgen** と**候補生成の仕事 Wg** を初期計画として約束する。Wg は Compute の用途の 1 つで、`FWork` の和型は増やさない。`initial=None` では Qgen・Wg・Ep を含む bootstrap 由来の計算の仕事を出さない',
    1932: '- Qgen は候補を作る前に固定する: process・trigger・reader・purpose・stage_slot・方法と出力の契約の版・全引数・入力の Point と適用の順・生成に使う固定の像・割り当て・許可 (Desc の契約、:1003)。外から完成済みの信念や候補の束を正解として受け取らない',
    1933: '- Qgen の保存の前から Wg の義務を持ち、要る Point と許可が揃ってから開始できる。重い生成は容量に数える。生成中も測定・受信・保存は続く。**開始できることは、すぐ始める義務や他の仕事への優先にしない**',
    1934: '- Wg の返答は I-3 `WorkFinished` で受け、原報告を保存する。候補の内容が返っただけで数学的に正しいとは認めない。最初の対応する終わりと固定の要求・生成の読み・出力の全内容を照合し、T と**候補宣言 CG** を出して保存する責務を持つ。CG は F-a の `candidate_declaration/1` の全欄 (生成器・引数・basis・draws・候補の順・測度・継続) を省かない。CG は信念の completed ではない',
    1935: '- 生成器が候補を出さなかった時は、確定返答 **NoCandidates** (この生成器がこの固定入力から候補を出さなかった、まで。「候補は世界に無い」「選ばないことを sui が選んだ」とは言わない) として T に保存し、架空の候補宣言・FProblem・NoDecision・D を作らない。非空の候補が出るまで再実行する義務を足さない。Failure・Unknown と混ぜない (F-a の候補宣言は入力の順が空にできないので、空を黙って生成器任せにしない)',
    1936: '- CG の保存の後、**評価の要求 EQ** を別に固定する (その候補宣言と、実際に使えるモデル・好み・文脈・o/j を参照)。Qgen の生成用の像と EQ の評価用の像を同じとみなさない。生成後の候補を生成前に固定した FRoot へ後から差し込まない。EQ の Publish と同時に Ep の義務を置き、その後は既存の Ep → D → Ee',
    1937: '- **生成用のくじ (ゆうの決定 D6、2026-10-16 21:5x)**: この版の縦の 1 本は、**生成用のくじを要しない生成方法**で確かめる (信念・好み・能力から内部で候補を作る方法であって、人の候補の一覧を外から渡す抜け道にしない、:1930・:1939)。くじを要する生成方法は外付けの表の **R10** (§3-2) として、足す時の契約 (要求の記録 RG・くじの仕事 Dg・O-GD の 7 条件・Wg の入力への受け渡し) を残し、**未接続として分母から消さない**。乱数を要する宣言を空の draws や固定値に読み替えない (それをすると人が選択肢と分布を縛る ⚑)。生成用と選択用のくじを分けること (生成前の context_key に生成後の input_order を含めない、F-a A:68・314) は R10 でもそのまま。理由 (ゆう「本番に使わない or 本番では別の形にする必要があることが見込まれたりするなら、1 で今は置いといて」→ Claude の確認): 本番の候補の生成は S9 の LLM で、そのばらつきは係の中で起き sui のくじではない。sui のくじを LLM に渡すかは S9 で決まる。生成用のくじは確かめ済みの「選択用 D → Ee」と同じ形 (Dg → Wg) なので、後で足しても今の段と所有のつながりは書き換えない',
    1938: '- **所有と完了の条件 (O-G、7 条件)**。発生は窓口の行の作成の印から逆算せず、独立の事実から定める。初期の Qgen の発行・保存は既存の C-O02、Wg の停止は既存の C-O14、Ep の run は既存の C-O10。**`C-OG.issue[EQ]` は CG の Publish で発生させ、EQ を発行できる条件 (CG の保存・評価に要る文脈・o/j・モデル・好み・使用の許可) と分ける** (責務の発生と操作の有効性の分離 :1191、待ちでも所有を消さない :659・:1482。発生点の選択は技術の選択で、他の issue を一律に前倒ししない)。EQ の発行の前は、生成から評価へ渡す継続を担当する P.units が Qgen・候補 slot か保存済みの CG・読み手・元目的・未達の条件とその根拠を保持する (単なる owner 欄ではなく、照合して処理を再開できる保持)。EQ を発行できる時にだけ実際に使える入力・文脈・o/j を固定して EQ を Publish し、その歩で Ep の行・C-O10.run[Ep]・渡すべき元目的の所有を成立させる。発行の責務があることは直ちに発行・実行する義務ではない',
    1942: '| C-OG.run[Wg] | 初期計画で Wg を約束した時 | EndKnown(Wg) | 終わりの代わりの Transfer は認めない。Wg 行が保持 | 返答前の元目的。EndKnown で T の保存と handle が同時に発生。停止は O-14 |',
    1943: '| C-OG.save[T] | EndKnown(Wg) | 対応する T の SV | 保存の担当を移せても未保存を達成扱いにしない | handle、CG/EQ、pG、停止 |',
    1944: '| C-OG.handle[Wg] | EndKnown(Wg) | 直接の達成の枝を置かず、下の枝の表の Transfer で局所解消 | 非空の成功は CG の発行の実担当へ、非成功・具体的な不足は対象つきの残余目的の実担当へ | T の保存、既発生の issue/save、pG、停止。引受けの前は元の担当が保持 |',
    1945: '| C-OG.issue[CG] | 最初の返答と生成の要求が対応し、非空の CG の生成条件が成立した時 | 合法な CG の PUB と、save[CG]・issue[EQ] の同時の所有の成立 | 発行の前は Wg 行か引受け済みの生成の継続の担当 | 前提を後で失っても発生済みの条件は残る |',
    1946: '| C-OG.save[CG] | CG の Publish | 対応する CG の SV | CG の保存の実担当 | issue[EQ]、pG、その他の保存。CG の保存だけで生成側を解消しない |',
    1947: '| C-OG.issue[EQ] | 合法な CG の Publish (CG 未保存・文脈不足の時点を含む) | 合法な EQ の PUB と、Ep 行・C-O10.run・元目的の引受けの同時の成立 | 発行の前は生成の継続の P.units | save[EQ]、Ep 以降、既発生の pG。発行できない間も条件を消さない |',
    1948: '| C-OG.save[EQ] | EQ の Publish | 対応する EQ の SV | EQ の保存の実担当 | Ep の実行・返答・後続、pG、停止 |',
    1952: '| 非空の成功 (EndKnown と出力の全内容・要求・生成・契約の対応) | handle から C-OG.issue[CG] の実担当へ Transfer (元目的と、CG の発行で EQ の責務を生じさせる対応も渡す) | CG の存在だけで認証成功・Selected・採用にしない | T の保存、CG の issue/save、発生後の EQ の責務、停止。成功だけを理由に pG を作らない |',
    1953: '| NoCandidates (確定返答) | T に返答を残し、handle は元の「比較まで」の未達 pG を持つ担当へ Transfer | CG・EQ・Ep・選択用の D を作らない。非空になるまで再実行する義務を足さない | pG は Wg の保持域で引き受ける。返答の処理の完了と元の処理の未達を分ける |',
    1954: '| 確定した Failure | 種類と根拠を持つ pG の担当へ Transfer | 成功の CG・EQ・同じ Wg の再入場を作らない | T、pG、既存の記録、後着、停止 |',
    1955: '| Unknown | 不明の根拠を持つ pG の担当へ Transfer | CG・NoCandidates・EQ を捏造しない。後着の値で最初の終わりを変えない | T、pG、後着の受信の保存、停止未確認の占有 |',
    1956: '| 対応の証拠の不足 (EndKnown 前) | run を未達のまま持つ。未発生の handle や T へ移さない | 不足を Wg の Unknown にしない | Wg 行が run と元目的を持つ |',
    1957: '| 対応の証拠の不足 (EndKnown 後、CG か EQ の使用の条件の不足) | CG の前は handle か既発生の issue の担当、CG の発行の後は issue[EQ] の担当が保持。許された Transfer が成立した部分だけ局所解消 | 未発生の成功の issue、架空の文脈・Point を作らない | T、既発生の issue/save、対象つきの不足と pG |',
    1958: '| 独立の Conflict | 新しい使用を止め、該当する handle/issue と pG を実担当が保持 (Clash は O-13) | Conflict に依存する新しい CG・EQ・Ep の入場。Xc 未保存を許可の理由にしない | T、原報告、発行済みの計画の保存、既存の CG/EQ、pG、停止。既存の事実を巻き戻さない |',
    1960: '- **残余目的 pG** = `PurposePart(c0, π, a)` で、c0 = その C-OG.run[Wg] の実体、π = `initial` で引き受けた「候補を作って比べる」処理、a = その Qgen の対象全体。CG・EQ・担当・引継ぎの回数が変わっても c0 を付け替えない。NoCandidates・Failure・Unknown・元の処理を妨げる具体的な不足や Conflict で生成から比較への処理が未完となる枝でだけ、独立の事実から必要性を判定する (単なる未配送・先行の保存待ちで作らない)。pG は「非空の候補を必ず作れ」「Selected まで進め」という新しい目的ではなく、元の処理の未達と来歴の保全。**D3 により今の模型では Direct(pG) は偽**、後で EQ が発行されてもそれだけで既発生の pG を解消しない',
    1961: '- **条件の数: 44 + O-G の 7 = 51 の種類** (接続した条件の種類の数で、確かめ済みの件数ではない。旧 44 の確認状況を 51 にコピーしない。目的部分・draw の個数・slot の実体の数は種類に足さない、:1577)。R10 を足す時は O-GD の 7 で 58',
    1962: '- 足す確かめの行の候補: **INV-2.g** 生成から評価までの所有の連続 (各枝の Required・Direct・Transfer・残る pG を独立の宣言・返答・保存から求め、CG の保存の後の issue[EQ] や担当の移行の後の pG を消したら違反。合法な対照 = 文脈不足で EQ を発行せず issue[EQ] と pG を実所有して待つ) / **INV-16.c** 生成の要求 → 実際の生成 → CG → EQ の全対応。Wg の追加で INV-2.a/b/c/e/f・3・4・5・6.b・7・8・10・11・13・15 の当たる母集団が広がる。(R10 を足す時は INV-14.c 生成用のくじの根拠と使用)',
    1963: '- 契約名の仮称: `sui.fb.candidate_request/1` (Qgen)・`sui.fb.candidate_generation/1` (Wg の出力)。既存の信念の更新用の Q に名前だけ付け替える案ではない',
    1964: '- 人が置くのは生成方法の宣言と差し替え口だけ。候補の固定の一覧・時刻の格子・再生成の周期・最低配分・生成を必ず優先する規則は置かない。矢印は対象を渡す因果の依存で、sui 全体を一列に並べる順ではない',
    1968: '- **D の終わりの知らせ (値・確定した失敗・不明) はどれも I-8 `DrawReturned(work, outcome: DrawValue | DrawFailure | DrawUnknown)` で受ける**。`WorkFinished` は Compute の用途 (Wg を含む) の終わりに使う。D を名乗る `WorkFinished` は外側が正しければ原報告として保存するが、この版では D の終わりに対応付けない',
    1970: '- 原報告を保存したうえで、要求との対応・最初の終わり・使用の条件が揃った枝だけ DF か DU を出す。後着・未対応・不足・拒否・Conflict の枝では原報告の保存と論理の発行を分ける。Failure/Rejected では T を保存し DF・Ee を作らない。同じ Draw を引き直さない',
    1972: '**M10 終わりの記録 T の「7 項目」と 8 欄**: (5) の列挙は意味の上で 7 組で、「要求と段」を request と stage の 2 欄に分けるので記録の欄は 8 つ (`work, request, stage, first_receipt, terminal_kind, returned, basis, view`)。欄は増減しない (:772・:1878 を直した)',
    2021: '| **R1 I-5 予約 At** | W-43 の予約、時計による検出の原報告、同じ引受けの配送権利とその処理記録 (見張りは W-31)。「満了」を選択や実行にしない | 背骨 ②〜⑤。H の受信 → P.units の配送権利 → 必要なら P.work。鍵 = 予約 Point + 1 回分の slot、再検出の読みは鍵に入れない。同じ run の M で予定 p と検出 e を比べる、別 run は clock_unaligned | **書ける (契約の追加 A01)** | INV-6.b/c、7、8、16 の予約の枝。**新しい条件**: 予約登録の issue/save、満了配送の handle/save、配送権利の 1 回性と許可の照合。新しい行「有効な予約の同じ配送権利しか消費しない」。満了から作用までを 1 条件にしない | 同じ満了を違う時刻に 2 度検出 → 1 回の配送 → 復元 → 二重検出・保存応答の喪失・取消しとの競争・別 run の期限 |',
    2022: '| **R2 I-5 条件 When** | W-43 の条件予約。条件の宣言・固定した証拠の像・確かめる仕事 (W-31/W-35)・True/False/Unknown・検出・配送権利を別に | 背骨 ②〜⑤。述語の True/False/Unknown は仕事の実行の成否と別。確かめの鍵 = 対象述語・意味の入力像・契約版。証拠が増えたら別の確かめ (新しい予約権利ではない)。F-a M-11 の不変 snapshot | **書ける (A02)** | INV-2.a/b/c/e/f、6.b/c、7、8、15、16。**新しい条件**: 述語の仕事の run・終わりの save・検出の handle/save。新しい行「True の対象像と権利の対応」「同じ確かめの自己再発行なし」(自分の T の保存だけで同じ確かめを呼び直さない。待つ時間・回数の上限ではない) | 不足の像で確かめ → Unknown と不足を保存 → 復元後も同じ不足 → 関係する証拠の追加で別の確かめ、無関係な通知・自分の終わりの通知では増やさない |',
    2023: '| **R3 I-4 手** | W-31 の Act、W-42 の引受け、W-44 の開始・受け取り・送出・報告・止まった確認を別の記録に。結果不明を「作用していない」にしない | 背骨 ②〜⑤。許可の鎖、2 つの軸、Claim/Launch/Enter/Stop/Deliver。受け取り・送出を Running/Stopped の代わりにしない。世界で効いたかは観測で後から読む | **書ける (A03)** | INV-3、5.b、6、7、10、11、15 の Act の枝。C-O14.stop はそのまま。**新しい条件**: 意図・試みの保存、Act の run、報告の保存と処理、結果不明の保全。新しい行「開始・受け取り・送出・結果・停止を混同しない」 | 1 回の試み → 送出の証拠と結果を別に保存 → 復元 → 送出後の返事の喪失・Unknown 後の遅着・停止なし・重複報告 |',
    2024: '| **R4 意図・予約・口の変更** | W-42 の意図の確認・取下げ、W-43 の予約変更、W-01 の版つき設定と適用。口の変更の選択と適用 (RouteApplied) は別 | 背骨 ①〜⑤。対象ごとの前状態の照合 (`Stale` の形)、開始直前の照合。仕事の旧記述を書き換えず、新しい意図・要求を作る。全体の policy_generation は作らない | **書ける (A04)** | INV-2、3.b、5.b、7、8、12.a/b。Stale は INV-9.b を流用せず、**許可の変更専用の新しい行**。**新しい条件**: 変更計画の issue/save、適用の確認、旧対象の残務の引継ぎ。D1 は維持。口を閉じる選択は sui に残し、帳簿の未完を閉口の禁止に使わない | 旧許可を持つ Pending と変更を競わせる → 変更と適用を別に保存 → 復元 → 古い許可での Enter・遅着の Frame・同じ前状態から 2 つの変更 |',
    2025: '| **R5 同じ範囲の割り当ての選び直し** | W-39 の共同の配り方の案を選ぶ W-41、適用または Stale の記録。既存の占有と今後の開始に使える配分を分ける | 背骨 ③〜⑤。Need/Occ/Held/Fit、占有 ≤ 割当 ≤ 容量。評価の根は凍結、適用時に前状態と実占有を照合し直す | **書ける (A05)** | INV-2.e/f、3.b/c、5.b、7、8、10、14〜16。**新しい条件**: 割当の適用の handle/save、Stale の処理の保存。新しい行「前の割当との一致・実占有を保つ適用・Pending の旧許可を無断で更新しない」。最低配分や割り当て専用の席は足さない | 同じ前割当から 2 案 → 一方を適用 → 復元 → 後の案は Stale、Hung の占有を残す |',
    2026: '| **R6 範囲をまたぐ割り当て** | 複数の範囲を対象にする 1 つの共同の案と選択の Point、資源の組を持つ仕事、共同の適用の結果 | 背骨 ③〜⑤ (§2-4-0 の表)。同じホストの共有状態の中では、1 歩で全対象の比較と適用の予約を成立させられる。保存は 1 件ずつでよく、共同の適用が確定する前に部分の配分を有効にしない | **書ける (共同の適用の契約 A06)**。「割り当ての範囲は 1 つ」(§0-2 (a)) は進め方の絞り込みで、背骨の約束ではない。範囲ごとの独立のくじに分けると元の分布に無い組が出る (二範囲 a/b で「x に両方」「y に両方」が各 1/2 なら、分けると「x に a・y に b」が 1/4) ので分けない。**独立のホスト・保存係の間の分散した確定は未接続 (S13)** | R5 の枝に INV-2.b、3.c、5.b、6.b、10.a の全資源の同時照合。**新しい条件**: 共同の適用の issue/save/handle。新しい行「部分の適用なし・前状態の組の全件一致・共同の選択との相関を保つ」 | 二範囲・二仕事の競争、適用の途中で復元、一方の前状態の変更・部分保存・二重適用・範囲ごとのくじ (対照) |',
    2027: '| **R7 一般の候補の生成・過程の増殖** | W-35 の候補生成の仕事と版つきの生成宣言、W-30 の新しい過程。候補を作ったことと、その過程を始めると選んだことを分ける | 背骨 ①〜⑤。P.work の種類を広げ、descriptor を各仕事で固定。全後続の同時所有。生成用と選択用のくじを分ける。読み手ごとの採用、知識は仕切らない | **書ける (族と契約の追加 A07)**。具体的な生成器の意味は別に要る | INV-2、3、5〜8、9、10、13〜16 と、宣言した導出に限る 2.d/L-DERIVE。C-O02 は bootstrap だけ。新しい生成の仕事と bootstrap でない過程に**独自の issue/run/save/handle の条件**。新しい行「候補生成の来歴・測度と過程生成の許可の対応」。過程の数の固定上限・動機の一覧・優先順位・最低配分は置かない (有限模型の個数上限は試験の Cut で、sui の選択肢の制限に移さない) | 版つきの生成器から候補 → sui が新しい過程を選ぶ → 復元 → 同値の再配送・別名の重複・不足の生成・資源ゼロ・複数の読み手 |',
    2028: '| **R8 S5 のプロセスの再起動** | 新しいホストの run の起動事実、旧 run の所有・開始・未保存の計画との復元の対応、外部の実行・停止の照合 | 背骨 ②〜⑤を保つには、§2-4-1 の H/P/Runners の寿命・§2-4-2 の歩の境目・§2-4-5 の不変の適用範囲・L-ENV を作り直す必要がある | **書けない (背骨へ戻す必要)。ゆうの決定 D4 で ★ S5**。原理 5 つは弱めないが、今の H/P が残ることに頼る証明は使い回せない (反例は §3-3) | S5 で INV-1〜8、10〜11、14〜15、L-RECEIPT/L-DERIVE の落ちる境目と 44 条件の全実体と p を復元の前後で追う。今の模型の成功はこの行に流用しない | 未完の受信・計画・仕事 → 一部を進める → 本文だけ・点まで等で保存 → 再起動 (S5 で) |',
    2029: '| **R9 W-45 取りやめ + ★ 3 つ** | 評価を経た W-41 の Abandon の選択、対象を固定した取消しの適用、元の p の取りやめによる終わり、別要求による達成の対応の証拠。取りやめは実行の成功・物理的な停止・目的の達成と別 | 背骨 ②〜⑤。取消しの適用は短い共有の更新と保存の計画に分け、対象の開始禁止と残務の所有を同じ歩で確立。p の意味と履歴は変えない | **未確保取消しと目的の取りやめは書ける (A11・A12)。「叶った」の扱いはゆうの決定 D5 で W-45 を実際に足す時に選ぶ ★** (§3-4) | INV-2.a/c/e/f、3、5.b、6、7、8、10、15〜16 の枝。C-O14.stop に未確保取消しの枝、★ の 8 条件 (C-O04/05/07/09b/12/13.handle・C-O10/11.run) に p の 2 つの解消の道。全 save と既存の run の結論は維持。**新しい条件**: 取消しの適用の保存、p の終わりの判定と証拠の保存。新しい行「対象・許可・競争の境目・残務の保全、達成と取りやめの区別」 | Abandon を評価して選ぶ・別要求で証拠を得る → 選択と適用・達成の証拠を別に保存 → 復元して同じ p と残務を照合 → Claim が先・選択の対象違い・部分の取消し・実所有なし・遅着・別 q の成功だけ |',
    2030: '| **R10 生成用のくじ** (v0.18、D6) | 生成方法が要る生成用のくじの要求の記録 RG (`sui.fb.generation_draw_requested/1` 仮称)、くじの仕事 Dg (FWork の Draw の用途)、値 DFg (`draw_fact/1`)・不明 DUg (`sui.fb.generation_draw_unknown/1` 仮称) | 背骨 ②〜⑤。Qgen を含む初期計画の Publish で宣言した各 draw slot に RG の発行の責務、RG の Publish と同時に Dg 行。Dg の終わりは I-8 `DrawReturned` (M4)。DFg は Ee を約束せず、Wg の宣言した入力 slot への依存 (固定した PlanRef、保存済みの Point へ 1 度だけ解決) を満たす。Wg は要る DFg が全部保存され対応と許可が確かめられてから開始。CG の generation.draws に使った DFg の Point を載せる。PR/FProblem や選択用の D の権利は使わない。context_key は F-a M-13 の式 (生成後の input_order・CG・評価の problem_key を混ぜない) | **書ける (契約の追加 A14、選択用の D → Ee と同じ形の Dg → Wg)**。Wg の開始の前に要るくじの要求を全部固定できる生成契約まで。**生成の途中で新しいくじを要求する方式は別の未接続** (事前の抽選や固定の個数に近似しない) | O-GD の 7 条件 (issue[RG]・save[RG]・run[Dg]・save[T]・handle[Dg]・issue[DFg/DUg]・save[DFg/DUg]) で 58。新しい行 INV-14.c (RG・Dg・DFg・Wg の実入力の対応、PR を捏造せず別用途や DUg を値に使わない)。Dg の Unknown・Failure では値の無い依存と元目的の未達を Wg 側が引き受け、Wg は未開始のまま (Wg の Unknown や NoCandidates を捏造しない) | 宣言した draw が 0・1・複数、一部だけ保存、Dg の値・Failure・Unknown が最初、Dg が Hung でも受信・保存が進む、容量 1 で Wg が未保存の DFg を待って先に席を取らない、生成用と選択用の取り違え |',
    2064: '| A01 | R1 | 検出事実と配送権利の比較の族、権利の消費と後続の所有 | 契約の追加 |',
    2065: '| A02 | R2 | 固定した意味の入力像による確かめの識別・再検査・自己再発行の防止 | 契約の追加 |',
    2066: '| A03 | R3 | Act の段ごとの報告・終端の候補・実行と停止の証拠・照会 | 契約の追加 |',
    2067: '| A04 | R4 | 対象単位の変更の確定と開始の許可の競争、Stale | 契約の追加 |',
    2068: '| A05 | R5 | 占有を保った割当の適用、旧許可を持つ仕事の扱い | 契約の追加 |',
    2069: '| A06 | R6 | 前割当の組の共同照合と部分の適用を見せない確定 | 同じ共有状態の中の契約の追加 |',
    2070: '| A07 | R7 | 一般の生成の来歴・測度・新しい過程の許可と全後続の所有 | 契約の追加 (生成器の意味は別) |',
    2071: '| A08〜A10 | R8 | §3-3 | ★ S5 (背骨の状態・歩の境目) |',
    2072: '| A11 | R9 | ChosenAbandon と未確保取消し | D2 の ★ を開く契約の追加 |',
    2073: '| A12 | R9 | p の取りやめを達成と別の終わりに | D3 の ★ を開く終わりの契約の追加 |',
    2074: '| A13 | R9 | 「叶った」の扱い (C / D) | D5 で W-45 を足す時に選ぶ |',
    2075: '| A14 | R10 | 生成用のくじ (RG・Dg・O-GD の 7 条件・Wg の入力への受け渡し) | D6 で外付け、足す時の契約 |',
    2048: '共通の選択の許可 `ChosenAbandon(d,t,Xuse)` (Codex 案 A11、未採用): ① d は保存済みで、認証済みの Selected が Abandon を選んだ記録 (INV-16 で EQ・PR・Draw・EV・根を照合。NoDecision や未認証では成立しない) ② t は d が選んだ対象そのもの (予約の引受け・仕事の権利・p の c0・π・a と、過程・読み手・効力の範囲。自由な文字列の同名では成立しない) ③ 意図の引受けと使用の許可が対応し、適用の直前にも有効 (前状態が違えば Stale、対象を差し替えない) ④ 新しい結論の使用に要る UseDeps が使える。**緊急性・時間切れ・再試行回数・価値の閾値・人の許可は足さない。選ぶかどうかは sui。**',
    2052: '| D2 C-O14.stop の未確保取消し | `CancelBeforeClaim(w,d)`: ChosenAbandon が w の権利に対応し、独立の履歴で一度も確保していない・本体未入場・札未使用・開始不明でない。ClaimStart と同じ調停の境目で照合し直し、以後同じ権利で Claim/Launch/Enter できない状態と残務の実所有を同じ歩で確立。適用の記録が Saved で `NoClaimCancelDone(w)` | Held=0 だけ・Pending の札だけ・ABANDON の保存だけ。先に ClaimStart が通った仕事を未確保扱い。確保の無い枝に架空の Release | C-O14.stop = `StopDone(w) または NoClaimCancelDone(w)`。確保済みの枝は変えない。「取消しが先」「ClaimStart が先」の 2 つの対照を必ず置く。取消しで C-O14.stop が済んでも C-O05.run 等は EndKnown のまま (返答に偽装しない) |',
    2053: '| D3 別要求・別認証による達成 | **D5 (ゆう 2026-10-16 20:15) で W-45 を実際に足す時に選ぶ**。候補 **C** = 「叶った」は sui のモデルが (元の p・後の結果・観測) から読む派生物 (P1・P7)、読みで暫定解消し、読み違いに気づけば同じ p が未達へ戻る / **D** = 読みは更新し、目的を閉じるには評価を経る sui の「閉じる」選択を要する (閉じた選択は後の読みだけでは取り消さない)。D で sui が読みに合わせると C と同じ動き (おもちゃの模型、2026-10-16)。**A** (元の宣言の達成基準だけ) は LLM 由来の自由な目的が未達に偏るので採らない。どれでも読み違いはゼロにできない (同じ材料と両立する世界が 2 つあれば、どの仕組みも必ずは正しく読めない = 原理の限界) | 別 q の成功・同じ数値・同じ目的名・後の新しい根の成功だけ。「LLM が完了と言った」文を目的達成の事実へ昇格。原観測・要約・説明を独立の 3 つの証拠に数える。古い Unknown を Success に変える | 元の p (c0・π・a・目的・過程・ρ・対象)・事実・当時の Unknown・保存と停止の責務。読みはモデル・版・事実の集合・対象の時点 (一度叶った / 今も続く) と対応させ、読み直しを原本の改変にしない。未達へ戻っても再開や再実行を強制しない |',
    2054: '| D3 取りやめによる終わり | `Abandoned(p,d)` (A12): ChosenAbandon が同じ p の対象部分を名指しし、原 p・対象・未達の履歴を保持したまま取りやめの適用と保存の責務を実所有へ置く。Saved で「**未達のまま取りやめで終わり**」(達成と呼ばない) | p の削除・別名への付替え・owner 欄だけ・ABANDON の保存だけ・局所の handle の引継ぎだけ | p の識別・旧意味・未達だった事実・選択・適用の根拠。動く仕事・占有・遅着・全 save・独立した run/stop は別に追う。{a,b} の a だけ取りやめても b を消さない |',
    2056: '**今の模型との関係**: 上のどれも今の模型 (D3 で `Direct(p)=偽`) を変えない。`Direct(p)=偽` は「現実で p が叶っていない」という信念ではなく「今回の模型では p を解消する枝を使わない」という定義で、sui が世界を読む答えにそのまま渡さない。',
    2095: '| **B1 起動・読めない受信・保存の失敗・作り直し** | 同じ run、空の置き場、bootstrap の口、`initial=None` (対照で有り) | Boot と ClockDeclared を post → accept → settle / 未知の bytes の Received / settle 中の保存の障害 (commit 前・本文の後の応答の喪失・点の後の応答の喪失) / `rebuild_window` → 同じ原本を再受付・保存 / 同文の新しい post / 外形の誤り・同番号の改変・r > s / `initial` 有りの対照 | Boot は 2 点が揃って保存完了、`initial=None` で bootstrap の Compute は出ない。未知の bytes でも受理し観測を捏造しない。本文だけでは受信の点は未保存。再受付は同じ名前・r・s・本文・親・salt・CID (新しい受信を増やさない)、新しい post は別の受信。shape は記録も預かりも作らない。`initial` 有りでも測定・受信の責務は同じで計算の有無だけ変わる | INV-1、4、11、13、L-RECEIPT | SC-01・02・03・20、SC-03-RETRY・FIRST |',
    2096: '| **B2 測った・測れない・まだ分からない・終わった** | B1 から、保存済みの区間の要求 k と公開の MeasureSegment。読み方・時計・対象のセルを先に固定 | `drain` を 2 回 / Started より先の Frame / RouteApplied・Started / Gap・Unavailable・Claim・Unproved を別ケース / 保存の途中の障害と作り直し / 同 slot の再配送と別 slot / 同 slot の Gap と Unavailable (食い違い) / Ended / end > r の Frame・Claim と未来の Unproved の対照 | `drain` は読むだけで仕事を消さない。開始の証拠の無い結びつきは待つ。Gap・Unavailable を値 0 にしない、Claim は独立の Support、Unproved は未証明。同 slot 同内容は受信だけ増える、別 slot は別の論理報告。Ended でも未報告のセルと停止の管理は残る (D1)。無報告から Gap を作らない | INV-2.a/c/f、5、6.b/c、7、12 | SC-11・12・17、SC-11-FAMILY・CROSS-M、SC-17-FAMILY |',
    2097: '| **B3 評価の途中の受信から結果・証明・認証・採用へ** | `initial` 有り、宣言した δ、固定の読み手 ρ、容量 2、旧根 X0 の評価が進行中 | `status`・`drain` で旧評価の対象を記録 / Received と測定の報告 → 保存 / δ の前提が揃って新根 X1 の Q → Wr / Wr の WorkFinished → R / R の保存の境目で障害・作り直し → Wp / Wp → T・P・Cq / 取得の意図 → G → Wv / 認証の成功 → T・V・採用 A / 旧評価の返答 / 別 Q の R・兄弟に見えるだけの取得の負のケース | 旧評価の根は X0 のまま (新しい受信で書き換えない)。受信は旧評価が終わらなくても保存できる。`accept` の None は正しさの認証ではない。R の保存の前に Wp を始めない。Cq は 1 つ。採用には取得の実祖先・前状態・直前の使用の条件が要る。旧評価は X0 の答え、新しい採用は X1 の系列 (1 本の全体の系列にまとめない)。誤った対応から Cq・認証成功・採用を作らない | INV-2.a/b/c/d、3、4、5、6、8、9.a、11、L-DERIVE | SC-04・05・06・08・21、SC-05-PARENT・COMPLETE、SC-06-ANCESTOR |',
    2098: '| **B4 同じ前状態からの競争・Stale・不足と拒否** | 保存済みの採用 d0 と結果 r0、別々の意図から Q1・Q2 (どちらも previous_result = r0) | Q1/Q2 を保存 / 各 Wr/Wp/Wv を認証まで / Q1 の採用 → d1/r1 / 作り直し後に status と台帳 / Q2 の処理 / d1 の後の Q3 (previous_result = r1) / 別の採用の意図による同じ Cq の再採用 / Wv の Rejected・Insufficient・Unknown / 不足の後に証拠が増えた枝 | d1 は保たれ Q2 の previous_result を書き換えない。Q2 は Stale (例外や Conflict にしない、逆順も対照)。Q3 は進める (永久に拒む検査にしない)。Rejected は拒否の処理、Insufficient は T + V と未完の目的、Unknown は T と未完、採用しない。旧 w の終わりや既発生の p は変えない (D3) | INV-2.a/c/f、6.c、7.b、8.a、9 | SC-06・07a・07b、SC-15-WP/VERIFY |',
    2099: '| **B5 候補の生成からくじ・選ぶ / 決められない** | `initial` 有り。生成用のくじを要しない生成の方法・版・根・測度を宣言 (D6。どの候補を選ぶかは固定しない) | Boot → Qgen・Wg (§2-4-11 M3) / Wg の WorkFinished → T・CG (または NoCandidates) / EQ と Ep / Ep の FProblem → T・artifact・PR → D / Ep の正規の NoDecision (D なし) / `DrawReturned(DrawValue)` → T・DF → Ee / DF の保存の途中の作り直し / Ee の Selected → T・artifact・EV → selection / Ee の NoDecision / `DrawReturned(DrawFailure)` が最初の枝 (T だけ、DF・Ee なし) / D を名乗る `WorkFinished` を保存しても D の終わりにしない枝 / problem_key・purpose・Draw・artifact を 1 つずつ差し替えた報告 | 初期計画は bootstrap の事実 (sui が選んだ記録にしない)。NoCandidates では CG・FProblem・D を作らない。`drain` の再読はくじの引き直しではない。Selected の後も作用は出さない。NoDecision・Unknown・Failure を Selected に置き換えない。誤った組み合わせから評価の成功・selection を作らない | INV-2.b/c、5、8、14、15、16 (と §2-4-11 の INV-16.c 候補) | SC-09・10・21 (生成の段は模型に足す、§2-4-11) |',
    2100: '| **B6 最初の終わり・後着・食い違い・停止** | Wr/Wp/Wv/Ep/D/Ee/Wg を仕事の種類ごとに別ケース、同じ run・同じ r の通知も使う | 最初の Unknown (D は `DrawReturned(DrawUnknown)`、D の Failure が先・Unknown が後の対照も) を accept / 次の値の通知を先に保存 / 作り直し / 最初の受信を保存 / 同値の遅着 / 両立しない値 B / 停止の確認なしで Received / 外の係の実際の停止の確認 | 後の点があっても最初の受信が未保存なら終わりを決めない。受信の順と未保存の先行通知を作り直しで変えない。最初が Unknown なら T は Unknown (D なら DU で Ee なし、Wr なら成功 R/Wp なし…)。同値の遅着は受信だけ、Unknown と値が並んだだけでは Conflict にしない。A/B で Conflict、既存の T は残り新しい使用を止める。停止未確認の占有は残る、正当な解放は 1 回 | INV-2.a/c/f、3、6.b/c、7、10、14、15 | SC-15・16・17・18、SC-04-RELEASE |',
    2101: '| **B7 仕事が止まっていても受付は続く** | 合法な計算 1 つが Hung、D が未開始。容量 1/2 を別の宣言で比べる | 仕事を開始 (終わらず停止の報告もない) / Received を accept / settle で保存 / 保存の応答の喪失と作り直し / 容量 1 と 2 での D の開始の観察 / 確保済み・起動待ち・確かな未開始の失敗の枝 / 有限の障害の後に正常化 | 考える席が埋まっていても受信を預かり保存できる。Hung の占有は残る。容量 1 で席が無ければ D 待ちは合法、容量 2 で条件と空席があれば他の仕事の Hung だけで D の開始を隠さない (必ず選ばれるとは言わない)。`run_until` の timeout は試験の未完で、計算の Failure・締め切り・目的の放棄に変えない | INV-2.d/e/f、3.b/c、10、11、13.b、L-RECEIPT、L-DERIVE | SC-04・13・14・19・21、SC-14-LIMIT |',
    133: '| 到着 / 受信 | 到着は sui に見えない。見えるのは受信 r と送り手の主張 u |',
    134: '| 受信 / 受付 / 保存成功 / 反映 | 順に: 時刻を押した / 預かった / 消えなくなった / 読み手の採用まで届いた。どれも前のものを含意しない方向には言わない (受信したから保存した、とは言わない) |',
    135: '| 時計の読み / 通知の内容 | M の読みの証拠と、送り手の主張 U |',
    136: '| 測定 / 測れなかった / 何も来なかった | 値のある測定 / 値を得られなかった報告 / 被覆の証拠がある区間で到着が無かった主張 |',
    137: '| 過程 / 仕事 | 続くまとまり / 1 回分の計算か作用 |',
    138: '| 方針 / 見込み / 実際の記録 | 選び方の確率 / 世界の確率 / 起きた 1 つのこと |',
    139: '| 評価 / 選ぶ / 意図 / 実行 | 計算した / 1 つに決めた / やると引き受けた / 外へ出した |',
    140: '| 満了 / 検出 / 実行 (予約) | 予定の時刻が来た / 条件に気づいた / 作用を出した |',
    141: '| 窓口が 1 つ / 活動が 1 本 | 前者は保存の直列化、後者は採らない |',
    145: '- 「今の方針」「方針の世代」(全体で 1 本を前提にする、背骨 ③)',
    146: '- 「起こす」を時計の刻みの意味で (Tick は時計の読みの配送だけ)',
    147: '- 「考え始める入口は 2 つ」(入口は候補の由来の札、W-32)',
    148: '- 「到着時刻」を受信の読みの意味で',
    149: '- 「靄になった」(約束 9。F-b は限られた並行と分布の保持まで)',
    150: '- 「反映した」を出来事の名前として (出来事は採用、W-24)',
    182: '- **外から「これを選べ」「これを考えろ」と渡す入口** (旧 `Drive.react` の返事に当たるもの) は F-b の新しい道に作らない。選ぶ・評価を頼むは sui の過程の方針から中で出る確定 (§1-5) で、事実から導く。旧の `Drive` は旧のモデルの互換の道として残す (履歴 §3-10-6 の旧入口の互換)',
    183: '- **信念・事後・核・好みの解決・候補の束・状態の写しを受け取る入口** (F-a の E-07 と同じ理由)',
    184: '- **「保存した」「採用した」と係が名乗る入口**。保存成功は窓口自身が置き場への書き込みで知る。採用は窓口が記録する確定',
    2085: 'F3 の定義 (`開発フロー_2026-10-08.md` の採用の表): 「作る → 使う → 保存 → 復元 → 失敗 の短い筋書きを、契約と一緒に試験の係にも読ませる」(空打ちを減らすため)。**対象はこれから実装する縦の 1 本の公開の入口** (§2-4-7・§2-4-11: ホスト `post`・`run_until`・`rebuild_window`、窓口 `accept`・`settle`・`status`・`drain`、`Ledger.prepare`・`write`、I-1・I-2・I-3・I-6・I-7・I-8)。外付けの行の利用例は、その行を足す時に書く (§2-4-0 :255「詳しい契約は足す時に書く」)。「復元」は同じプロセスの中の窓口の作り直しまで (S5 は D4 で ★)。',
    2089: '**読み方**: 各番号は利用者から見た操作のまとまりで、不可分の内部の遷移ではない (`post` → `accept` → `settle` の間、本文と点の保存の間に故障を置ける)。`settle` を何回呼べば終わるか、`run_until` の timeout 以内に終わるかは約束しない。枝を差し替える時は、同じ合法な公開の前段から別の実行にし、窓口の内部の値を書き換えた状態を前提にしない。外から見る答えは 呼び出しの返り (`accept`・`settle` の成功は None で「預かった」まで) / 台帳の点と本文 / `drain` (列挙で、取り除かない) / `status` (§2-4-11 M1 の 6 つの意味) / 例外 (shape は `FbInputError`、同番号の改変と r > s はホストの故障、保存の障害の例外クラスは紙で決めない)。各筋書きに共通で当てる F2 の欄は 受理条件・検査範囲・返す主張・拒否条件・未判定・失敗後の状態・変形時の関係・正の対照例・同一性と結びつき (P7)・時間の順序と因果の祖先。',
    2117: '範囲の外: プロセスの再起動 (D4 ★ S5) / 独立のホストの間の分散した確定 (S13) / 「これを選べ・考えろ」・完成済みの信念・候補の束・状態の写しを外から入れる入口 (:177〜:181 で作らない) / F-a の数学の入口を直接呼ぶ例 / 残余目的の解消 (D3・D5) / 任意の大きさの証明・固定秒数以内の完了・最低配分。',
    2119: '**外付けの行を足す時の材料** (今の利用例と混ぜない): Codex `sui-fb-usage` 1 通目が §3-2 の右の列から R1〜R7・R9 の条件付きの筋書き (各 6〜8 歩) を書いた (全文は `~/.claude/codex-dialogues/sui-fb-usage.md` の 1 通目)。要点だけ: R1 同じ満了の 2 度の検出で配送は 1 回・別 run は clock_unaligned / R2 述語の Unknown と仕事の Unknown を分け、無関係な通知・自分の終わりで同じ確かめを再発行しない / R3 受け取り・送出・結果・停止を別の記録に、送出後の Unknown で自動再送しない / R4 旧許可の Pending と変更の競争、旧区間の遅着 Frame を新しい口に付け替えない / R5 前割当の Stale、Hung の占有を減らさない / R6 部分の適用を見せない、範囲ごとのくじに分けない / R7 生成と過程を始める選択を分ける、別名で測度を増やさない / R9 取消しが先・ClaimStart が先、a だけ取りやめて b を残す。',
    2121: '**試験の係が迷う所** (Codex 1 通目の M1〜M11 のうち、§2-4-11 で直さなかったもの): M5 原報告の中の未知の Point の名指しは主張として保存し意味の使用の時に解決 (内部の記録の型つき Point の規則を受付に横流ししない、紙と P1/P7 から) / M6 shape の例外・ホストの故障・保存の障害・正規の NoDecision・Stale・Rejected・Insufficient・Unknown・未接続を 1 つの success/failure に丸めない / M7 δ の対象・まとめ方・更新のきっかけを利用例が勝手に固定しない (「全 Received ですぐ計算」「一定時間で必ず計算」は ⚑ で採らない) / M9 予約の取消し・口の変更・割当の変更の競争を採用の Stale (INV-9.b) で済ませない (外付けの行) / M11 古い節の「全 SC 未実行」は時点つきの記録として読む。',
}

PROVENANCE = {
    'version': '1',
    'spec_version': 'v0.19',
    'spec_lines': 2125,
    'spec_sha256_lf': 'd2223e40033908ea3527fbff6f854425c1a4d18582de642aca8c551f86ddcc14',
    'phase_order': ['紙と公開宣言でFBT-01/02を固定', 'その後に模型の場面の記述だけをFBT-03に照合'],
    'read_limits': 'srcの許可された型・署名・docstringだけをASTで分離。f.pyは公開関数の署名/docstringだけ。内部関数・模型本体・既存試験の期待値は読まない。',
    'execution': '実装の検証not_run',
    'log': '今回の書込み許可は新規2ファイルのみ。Obsidian Sessions/Projects/Heatは未更新。最終報告を転記材料とする。',
    'knowledge_reuse': '有効: 独立の母集団・環境の事実と期待の分離。Knowledge/確かめる係の設計_すり抜けの型と環境の真実_2026-10-13.md を該当部分参照。',
}


GAPS = {
    "G-01": {"classification": "BLOCKER", "status": "未決", "message": "finite_update/2の数値入力・射影・証明/checker・対象指定認証物と契約別Support/artifact全閉包が未確定/未接続。意味を/1や模型から補わない。", "sources": (source(FB, 479, 486), source(FB, 1088, 1103))},
    "G-02": {"classification": "BLOCKER", "status": "未決", "message": "新契約のBody/Role/Category、全wire欄・nullable・最小親集合、InitialProcess/ResourceScope、Work/Draw返答の内側型、Started/Endedの全宣言が未決。論理欄link.*を既存DTOの欄に追加しない。", "sources": (source(FB, 469, 486), source(FB, 1006), source(FB, 1100, 1103), source(FB, 1963))},
    "G-03": {"classification": "直すべき", "status": "未決", "message": "合格候補の『知覚の更新が続く』『2つの仕事が進む』の量化/前提と、最初の表示で『生き続ける子を見る』の判定規則が無い。実装都合の周期・最低配分・必ず考える条件を足さない。", "sources": (source(FB, 17), source(FB, 192, 196), source(FB, 698), source(FA, 667, 672))},
    "G-04": {"classification": "後で", "status": "未採用", "message": "外付けR1〜R10/A01〜A14は今回採用する契約ではない。R8はD4/S5、R9の達成はD5で追加時に判断、R10はD6。分母に未採用のまま残す。", "sources": (source(FB, 2002), source(FB, 2021, 2030), source(FB, 2064, 2077))},
    "G-05": {"classification": "直すべき", "status": "未対応", "message": "許された公開宣言資料と紙に全欄がないF-aの入れ子型は未列挙部分を残す (CapabilityImplementation/CapabilityContext、RateBudget、PredicateRef等の全args、Selected/NoDecision等)。f.pyは公開関数の署名/docstringだけを参照し、クラス宣言や実装へ範囲を広げていない。宣言だけの資料が必要。", "sources": (source(FA, 114), source(FB, 373, 381), source("src/sui/f_facts.py", 38, 61))},
}
MISMATCHES = (
    {"id": "D-01", "classification": "直すべき", "subject": "Instant.wall_ns", "paper": "int|null (nullのキーも省略不可)", "declaration": "int", "sources": (source(FA, 28), source("src/sui/clock.py", 13, 18)), "action": "期待値を決めず、この欄をTARGETSへ入れない。実行時の受理は未確認。"},
)

# 紙の各列挙元と具体的な対象の対応。引用は規則の追加でない。
_paper_links = {
    461: ("T.envelope",), 462: ("T.fwork", "T.status"), 463: ("T.body.observed", "T.rel.receipt"),
    464: ("T.rel.shape",), 465: ("T.rel.shape",), 466: ("T.rel.receipt",), 467: ("T.envelope.received_ns",),
    468: ("T.prepared_entry", "T.rel.storage"), 469: ("T.boot_decl", "T.initial", "T.resource_scope"),
    470: ("T.clock_declared", "T.rel.rebuild"), 471: ("T.received",), 472: ("T.segment_report", "T.segment_binding"),
    473: ("T.work_finished",), 474: ("T.draw_returned",), 475: ("T.rel.declared_derive",),
    479: ("T.registry_old", "T.registry_new"), 480: ("T.registry_old",), 481: ("T.registry_new",),
    482: ("T.finite_update2", "T.old_binding"), 483: ("T.rel.registry_versions",), 484: ("T.rel.registry_versions",),
    485: ("T.target_certificate", "T.eq", "T.evaluated", "T.segment_binding"), 486: ("T.contract_declaration",),
    1925: ("T.clock_source",), 1926: ("T.rel.rebuild",), 1927: ("T.clock_declared", "T.rel.rebuild"),
    1931: ("T.qgen", "T.rel.initial_none"), 1932: ("T.qgen",), 1933: ("T.rel.resource", "T.rel.generation"),
    1934: ("T.candidate", "T.work_finished"), 1935: ("T.candidate_generation.branch.NoCandidates",),
    1936: ("T.eq", "T.rel.generation"), 1937: ("T.generation_draw_request",), 1938: ("T.rel.generation", "T.rel.owner"),
    1960: ("T.purpose_part", "T.rel.generation"), 1961: ("T.rel.owner",), 1962: ("T.rel.generation",),
    1963: ("T.qgen", "T.candidate_generation"), 1964: ("T.rel.generation",), 1968: ("T.draw_returned",),
    1970: ("T.rel.draw", "T.terminal"), 1972: ("T.terminal",),
    2048: ("T.external.R9",), 2052: ("T.external.R9",), 2053: ("T.external.R9",), 2054: ("T.external.R9",), 2056: ("T.purpose_part",),
    2085: ("T.rel.rebuild", "T.rel.receipt"), 2089: ("T.rel.shape", "T.rel.receipt"),
    2117: ("T.external.R8", "T.external.R9"), 2119: ("T.external.R1", "T.external.R2", "T.external.R3", "T.external.R4", "T.external.R5", "T.external.R6", "T.external.R7", "T.external.R9"),
    2121: ("T.rel.receipt", "T.rel.declared_derive", "T.external.R4"),
}
for _n in range(1911, 1922):
    _paper_links[_n] = ("T.status",)
for _n in range(1942, 1949):
    _paper_links[_n] = ("T.rel.generation", "T.rel.owner", "T.purpose_part")
for _n in range(1952, 1959):
    _paper_links[_n] = ("T.rel.generation", "T.candidate_generation", "T.purpose_part")
for _n in range(2021, 2031):
    _paper_links[_n] = ("T.external.R" + str(_n - 2020),)
for _n, _r in zip(range(2064, 2076), (1,2,3,4,5,6,7,8,9,9,9,10)):
    _paper_links[_n] = ("T.external.R" + str(_r),)
for _n in range(133, 142):
    _paper_links[_n] = {133:("T.envelope",), 134:("T.rel.receipt", "T.rel.acquisition"), 135:("T.clock_source", "T.received.claims"),
                       136:("T.rel.measurement",), 137:("T.descriptor", "T.fwork"), 138:("T.policy", "T.model_document", "T.record"),
                       139:("T.eq", "T.selection", "T.body.intention", "T.body.attempt"), 140:("T.reservation_due",), 141:("T.rel.owner",)}[_n]
for _n in range(145, 151):
    _paper_links[_n] = ("T.rel.invariance", "T.rel.declared_derive")
for _n in (182, 183, 184):
    _paper_links[_n] = ("T.rel.receipt", "T.rel.selection", "T.rel.verify")

for _v in VOCABULARY:
    _rows.append(_target("T.vocab."+_v["id"], "relation", _v["subject"], sources=(source(FB,_v["line"]),),
                        rules=_v["rules"], entries=_v["entries"], use=_v["meaning"], evidence=_v["meaning"],
                        negative=_v["distinction"], legal="この語の意味と対象・効力を保つ: "+_v["meaning"],
                        status="未採用" if _v["id"] in ("W-42","W-43","W-44","W-45") else "整理済み",
                        issues=("G-04",) if _v["id"] in ("W-42","W-43","W-44","W-45") else (),
                        not_applicable_reason="適用外: 到着そのものは直接観測できず公開入口を作らない" if _v["id"]=="W-05" else "適用外ではない"))
    _rows[-1]["related_targets"]=tuple(_v["targets"])

for _ext in EXTERNAL_ROWS:
    _i=int(_ext["id"][1:]); _entry=("I-5",) if _i in (1,2) else ("I-4",) if _i==3 else ("I-6",) if _i in (4,8) else ("I-8",) if _i==10 else ("I-3",)
    _rows.append(_target("T.external."+_ext["id"], "relation", _ext["subject"], sources=(source(FB,_ext["line"]),),
                        rules=("背骨③", "INV-2", "INV-8") + (("INV-14.c",) if _i==10 else ()), entries=_entry,
                        use=_ext["constraints"], evidence=_ext["conditions"], negative="未採用の契約を採用済みとして縦の合格に含める", legal=_ext["examples"],
                        status=_ext["status"], issues=("G-04",), not_applicable_reason="未採用: 詳しい契約は追加時。R8はS5で背骨の状態を開け直す"))

_entry_targets={"I-1":"T.received","I-2":"T.segment_report","I-3":"T.work_finished","I-4":"T.external.R3","I-5":"T.external.R1","I-6":"T.boot_decl","I-7":"T.clock_source","I-8":"T.draw_returned"}
for _entry,_tid in _entry_targets.items():
    _rows.append(_target("T.entry."+_entry,"relation",_entry,sources=ENTRY_POINTS[_entry]["sources"],rules=(_entry,),entries=(_entry,),
                        use=ENTRY_POINTS[_entry]["shape"],evidence=ENTRY_POINTS[_entry]["shape"],negative="原報告を受けることを意味の認証成功と同一視",legal="正しい外形の原報告を保存、意味の使用を別に照合",
                        status="未採用" if _entry in ("I-4","I-5") else "整理済み",issues=("G-04",) if _entry in ("I-4","I-5") else ()))
    _rows[-1]["related_targets"]=(_tid,)

_usage_targets={"B1":("T.rel.receipt","T.rel.storage","T.rel.rebuild","T.rel.initial_none"),
                "B2":("T.rel.measurement","T.rel.coverage","T.rel.segment_end"),
                "B3":("T.rel.frozen","T.rel.update_stages","T.rel.acquisition","T.rel.verify"),
                "B4":("T.rel.stale","T.rel.transfer","T.rel.verify"),
                "B5":("T.rel.generation","T.rel.draw","T.rel.selection"),
                "B6":("T.rel.terminal","T.rel.conflict_use","T.rel.resource"),
                "B7":("T.rel.independence","T.rel.resource", "T.rel.declared_derive")}
_by_id={r["id"]:r for r in _rows}
for _u in USAGE_ROWS:
    _related=[_by_id[t] for t in _usage_targets[_u["id"]]]
    _rows.append(_target("T.usage."+_u["id"],"relation",_u["id"],sources=(source(FB,_u["line"]),),
                        rules=sorted({v for t in _related for v in t["rules"]}), entries=sorted({v for t in _related for v in t["entries"]}),
                        use=_u["steps"], evidence=_u["precondition"], negative="この筋書きだけを分母にして他の枝を免除する",legal=_u["expected"]))
    _rows[-1]["related_targets"]=_usage_targets[_u["id"]]
_by_id={r["id"]:r for r in _rows}
for _unit in SOURCE_ENUMERATION:
    _n=_unit["source"]["first"]
    if _unit["targets"][0].startswith("T.paper."):
        _related=[_by_id[t] for t in _paper_links[_n]]
        _rows.append(_target("T.paper."+str(_n),"relation",_unit["id"],sources=(_unit["source"],),
                            rules=sorted({v for t in _related for v in t["rules"]}),entries=sorted({v for t in _related for v in t["entries"]}),
                            use=PAPER_FRAGMENTS[_n],evidence=PAPER_FRAGMENTS[_n],negative="この列挙元の対象または区別を落とす",legal="関連対象ごとの最近傍の合法例を保つ",
                            status="未採用" if _unit["disposition"]=="未採用" else "未決" if any(t["status"]=="未決" for t in _related) else "未対応" if any(t["status"]=="未対応" for t in _related) else "整理済み",
                            issues=sorted({v for t in _related for v in t["issues"]})))
        _rows[-1]["related_targets"]=_paper_links[_n]

# 条件IDの51種類はルールの出典であり、対象一覧の唯一の分母ではない。
_schema("capability_context", "CapabilityContext (外部実装が依存できる欄)", "registry resources? model_ref? budget?", at=486,
        extra_sources=(source(FA,114),), use="外部契約の4欄。numeric_work等の内部運搬欄は独立の公開入力として扱わず、移設はF-bの★未決")
_schema("predicate", "PredicateRef", "name version args", at=2022, contract="sui.f.predicate/1", body="Prediction", role="model / prediction",
        extra_sources=(source(FA,84),source(FA,297)), entries=("I-5",), status="未採用", issues=("G-04",),
        branches=("constant", "policy_end", "fact_present", "interval_compare", "and", "or", "not"))
for _name,_fields in (("constant","value"),("policy_end",""),("fact_present","fact history"),
                      ("interval_compare","left.key relation right.key provenance[]"),("and","terms[]"),("or","terms[]"),("not","term")):
    _schema("predicate_args."+_name,"PredicateRef.args."+_name,_fields,at=2022,
            extra_sources=(source(FA,297),),entries=("I-5",),status="未採用",issues=("G-04",),
            use="R2追加時。現在の縦の1本に述語の新しい実行入口を追加しない")
_schema("predicate_result","PredicateResult","value basis[] missing[] work?",at=2022,
        extra_sources=(source(FA,297),),branches=("true","false","unknown"),entries=("I-5",),status="未採用",issues=("G-04",))
_schema("predicate_snapshot","PredicateSnapshot","model_ref? E K quantities[] quantities[].key quantities[].value dependencies[] policy_position? policy_position.policy policy_position.node",at=2022,
        extra_sources=(source(FA,297),),entries=("I-5",),status="未採用",issues=("G-04",))
for _key,_name,_fields,_contract,_line,_body in (
    ("measurement_requested","measurement_requested","plan step","sui.f.measurement_requested/1",69,"Decided"),
    ("measurement_job","measurement_job","plan step","sui.f.measurement_job/1",70,"JobOpened"),
    ("measurement_run","measurement_run","","sui.f.measurement_run/1",74,"Observed"),
    ("style","FStyle","kind scope.name scope.version scope.H_ns gamma","sui.f.style/1",82,"Preference"),
    ("old_style","旧style","","sui.s4d.preference/1",82,"Preference"),
    ("quantity","quantity_declaration","kind","sui.f.quantity_declaration/1",83,"Prediction"),
    ("limit","FLimitProblem","","sui.f.limit_declaration/1",85,"Prediction"),
    ("world","FWorldManifest3","contract compiler request dependencies preference_causality","sui.f.world_manifest/3",422,NA),
    ("preparation","FPreparationInput2","contract compiler input dependencies preference_causality? budget","sui.f.preparation_input/2",429,NA),
    ("math_problem","FProblem3","contract problem_key world_key world_manifest model_ref parents[] facts[] E K context preferences[] style? scope gamma candidates continuation measurement_contracts[] execution_contracts[] method","sui.f.problem/3",435,NA),
    ("math_root","FRoot3","contract problem_key world_key world_manifest model_ref parents[] facts[] E K context preferences[] style? scope gamma candidates continuation measurement_contracts[] execution_contracts[] method root_key selection_draw draw_point draw_record_digest","sui.f.root/3",445,NA),
):
    _schema(_key,_name,_fields,at=(479,486),contract=_contract,body=_body,
            extra_sources=(source(FA,_line,448 if _key in ("world","preparation","math_problem","math_root") else _line),),
            status="未対応" if _key in ("limit","old_style","measurement_run") else "整理済み",
            issues=("G-05",) if _key in ("limit","old_style","measurement_run") else (),
            use="F-aの公開契約を使う/旧版を保持する対象。入れ子の未列挙部分はT.missing.*へ。measurement_runの未定codecは作らない")
_schema("quantity.rational_constant","quantity.rational_constant","value unit provenance[]",at=2022,
        extra_sources=(source(FA,83),),branches=("nat","dimensionless"))
_schema("quantity.evaluation","quantity.evaluation","result field candidate?",at=1096,
        extra_sources=(source(FA,83),source(FA,313)),branches=("expected_cost","already_received","additional","total_information","G","J","q_star","Z"))
for _name,_line in (("RateBudget",433),("Selected",391),("NoDecision",391),("FEvaluation",391),
                    ("EvidenceHistory",439),("KnowledgeHistory",439),("FContext",439),
                    ("FPreferenceCausality",427),("CandidateSet",441),("FContinuation",441),
                    ("DrawRecord",446),("PredicateWork",297),("FLimitProblem",85)):
    _schema("missing."+_name,_name,"未列挙の欄と枝",at=(479,486),extra_sources=(source(FA,_line),),
            status="未対応",issues=("G-05",),use="公開の入れ子型の全宣言は許可資料に未収録。名前だけから欄や全枝を作らない。宣言資料を受けて追加列挙が必要")

COMPLETION_CONDITIONS=tuple(k for k in RULES if k.startswith("C-O"))
TARGETS=tuple(_rows)
TARGET_BY_ID={row["id"]:row for row in TARGETS}

_acceptance=[]
_fb_criteria=(
    ("何も変わらない間も実測と知覚の更新が続く",("T.rel.measurement","T.rel.coverage","T.rel.declared_derive"),"紙に規則が無い: 知覚更新の無条件の継続。L-DERIVEは開始/終了/採用を保証しない (698)。"),
    ("重い考えごとを止めても受信時刻・記録が保たれる",("T.rel.independence","T.rel.receipt","T.rel.storage"),""),
    ("2つの仕事が進む",("T.rel.resource","T.rel.owner","T.rel.frozen"),"紙に規則が無い: 無条件の2仕事の進行保証。前提が揃う開始操作の提供と、実行の選択/終了を分ける (853・698)。"),
    ("比較と配送の分割の不変",("T.rel.invariance","T.action_decl","T.rel.frozen"),""),
    ("未決定を記録",("T.rel.selection","T.terminal","T.rel.terminal"),""),
)
for _prefix,_src in (("AC-FB",source(FB,17)),("AC-FA",source(FA,667))):
    for _i,(_meaning,_targets,_gap) in enumerate(_fb_criteria,1):
        _acceptance.append(dict(id=f"{_prefix}-{_i:02}",meaning=_meaning,sources=(_src,),targets=_targets,unconnected=_gap,issue="G-03" if _gap else None))
for _i,(_meaning,_targets) in enumerate((
    ("感じ続ける",("T.rel.measurement","T.rel.coverage","T.rel.segment_end","T.rel.initial_none")),
    ("受信・反映・選択の分離",("T.rel.receipt","T.rel.acquisition","T.rel.verify","T.rel.selection","T.rel.independence")),
    ("過程の網",("T.rel.invariance","T.rel.resource","T.descriptor","T.policy","T.rel.transfer")),
    ("根の凍結",("T.rel.frozen","T.rel.registry_versions")),
    ("事実が正",("T.rel.numeric_update2","T.rel.verify","T.rel.registry_versions","T.status")),
),1):
    _acceptance.append(dict(id=f"AC-SPINE-{_i}",meaning=_meaning,sources=(source(FB,191+_i),),targets=_targets,unconnected="",issue=None))
_acceptance.extend((
    dict(id="AC-STAR-01",meaning="おもちゃの世界で生き続ける子を見る (F-bの最初の表示から)",sources=(source(FA,671),),targets=("T.status",),unconnected="紙に規則が無い: FStatusの意味は定義済みだが、表示の形・観察範囲・見ることの合格判定は未定。FStatusだけで★の達成としない。",issue="G-03"),
    dict(id="AC-STAR-02",meaning="計算の未完了の棚卸しはF-bから理由別の記録",sources=(source(FA,672),),targets=("T.status","T.terminal","T.waiting","T.purpose_part","T.rel.transfer"),unconnected="",issue=None),
))
ACCEPTANCE=tuple(_acceptance)
ACCEPTANCE_LINKS=tuple(
    dict(acceptance=c["id"],target=t,rule=rule,use=TARGET_BY_ID[t]["use"],entry=entry,
         sources=c["sources"]+TARGET_BY_ID[t]["sources"],execution="not_run")
    for c in ACCEPTANCE for t in c["targets"]
    for rule in TARGET_BY_ID[t]["rules"] for entry in TARGET_BY_ID[t]["entries"]
)
SECTION_DISPOSITIONS=(
    dict(section="§1",sources=(source(FB,46,152),),enumerated="W-01〜15/20〜24/30〜45、対9行、使わない語6行",remaining="見出し/表見出し/たとえ/語の決め方は独立したBodyを作らない。51〜54の継承は共通型の行へ。"),
    dict(section="§2-1",sources=(source(FB,166,186),),enumerated="I-1〜7と作らない入口3行。I-8は§2-4-7:474",remaining="導き方・たとえは独立の入力でない。"),
    dict(section="§2-4-7",sources=(source(FB,457,475),),enumerated="15項目全部",remaining="見出しと過去版の導入のみ。"),
    dict(section="§2-4-8",sources=(source(FB,477,488),),enumerated="479〜486全部",remaining="たとえのみ。"),
    dict(section="§2-4-11",sources=(source(FB,1901,1998),),enumerated="M1の6意味と共通条件、M2、M3の7条件/7枝、M4、M10",remaining="1903〜1905/1969/1974〜1998は経緯・模型の実施報告と将来の点検。新しい独立Bodyは無い。模型の結果を本一覧の確認済みにコピーしない。"),
    dict(section="§3",sources=(source(FB,2000,2081),),enumerated="R1〜R10、A01〜A14、D2/D3/D5の枝",remaining="共通の形2008〜2013は各関係行。S5-1〜3はR8の未対応理由。経緯/たとえは対象を増やさない。"),
    dict(section="§4",sources=(source(FB,2083,2125),),enumerated="B1〜B7、入口の網羅表、範囲外と迷う所",remaining="2107〜2115はI系/B系への索引、実行結果ではない。2123〜2125は時点付きの次工程/たとえ。"),
)

def summary_counts():
    return {
        "targets":len(TARGETS), "kinds":dict(Counter(r["kind"] for r in TARGETS)),
        "statuses":dict(Counter(r["status"] for r in TARGETS)),
        "source_units":len(SOURCE_ENUMERATION), "conditions":len(COMPLETION_CONDITIONS),
        "acceptance":{c["id"]:{"targets":len(c["targets"]),"rules":len({x["rule"] for x in ACCEPTANCE_LINKS if x["acceptance"]==c["id"]}),"unconnected":c["unconnected"]} for c in ACCEPTANCE},
    }


# 移管材料は名前/docstringだけの照合。分母/期待値の出典にしない。
TRANSFERRED_TEST_NAMES = ({'name': 'test_FA18_one_firing_one_draw_100_deliveries',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 61,
             'last': 61,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_FA19_draw_source_consumption',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 84,
             'last': 84,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_extra09_started_without_root_same_prepared_retry',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 107,
             'last': 107,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.frozen', 'T.rel.storage'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_extra09_selected_links_validation_retry_and_replay',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 130,
             'last': 130,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.selection', 'T.rel.verify', 'T.rel.frozen'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_extra03_draw_before_fixed_problem_cannot_consume_source',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 177,
             'last': 177,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_03_firing_full_lifecycle_distinct_requests_and_conflicts',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 186,
             'last': 186,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.external.R1', 'T.external.R2'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_03_conflicting_firing_registration',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 249,
             'last': 249,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.external.R1', 'T.external.R2'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_03_predicate_work_registration_retains_content',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 274,
             'last': 274,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.external.R1', 'T.external.R2'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_04_draw_sources_must_be_separate',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 297,
             'last': 297,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_04_source_exception_is_not_retried',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 308,
             'last': 308,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_04_draw_identity_request_and_nonconsuming_replay',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 332,
             'last': 332,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_05_rootless_preflight_finish_commit_twice_and_cid_replay',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 357,
             'last': 357,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.artifact_preflight', 'T.rel.storage', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_extra09_selected_links_commit_preserves_prepared_parents_after_late_fact',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 438,
             'last': 438,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.selection', 'T.rel.verify', 'T.rel.frozen'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_05_rootless_commit_preserves_prepared_parents_after_late_fact',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 461,
             'last': 461,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.artifact_preflight', 'T.rel.storage', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_05_rootless_rechecks_reason_against_capability_availability',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 491,
             'last': 491,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.artifact_preflight', 'T.rel.storage', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F15_unrelated_rootless_result_cannot_finish_bound_problem',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 522,
             'last': 522,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.artifact_preflight', 'T.rel.storage', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F15_finished_rootless_operation_sequences_never_create_work_or_draws',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 536,
             'last': 536,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.artifact_preflight', 'T.rel.storage', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F15_finished_selected_receipt_only_returns_the_existing_root',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 569,
             'last': 569,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.selection', 'T.rel.verify', 'T.rel.frozen'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_structure_B_verify_save_replay_recompile_with_explicit_fixed_dependencies',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 585,
             'last': 585,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_structure_B_foreign_result_verification_cannot_authorize_save',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 608,
             'last': 608,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F20_started_digest_binds_full_record_and_survives_public_restore',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 623,
             'last': 623,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.frozen', 'T.rel.storage'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F20_started_record_claim_must_match_actual_ledger',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 644,
             'last': 644,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.frozen', 'T.rel.storage'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F21_commit_rechecks_destination_dependency_content_before_writing',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 665,
             'last': 665,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F22_finished_actual_parents_must_match_frozen_attempt',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 677,
             'last': 677,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F23_same_attempt_id_different_firing_cannot_finish_receipt',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 691,
             'last': 691,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F23_own_result_finish_retry_and_redelivery_succeed',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 709,
             'last': 709,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F21_legitimate_save_retry_redelivery_copy_and_late_fact',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 722,
             'last': 722,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F21_partial_storage_failure_retries_the_same_prepared_bytes',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 751,
             'last': 751,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F23_P7_same_label_different_contents_never_authenticates',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 783,
             'last': 783,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.storage', 'T.rel.frozen', 'T.rel.verify'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_extra03_problem_draw_acquisition_consumes_source_twice',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 812,
             'last': 812,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.rel.draw',),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_v010_07_union_input_assembly_fb',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 823,
             'last': 823,
             'read_scope': '名前・docstringのみ'},
  'targets': (),
  'status': '未対応',
  'reason': '名前/docstringだけでは和型の対象を特定できない。期待値・試験本体は未読。'},
 {'name': 'test_v010_07_union_canonical_roundtrip_fb',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 841,
             'last': 841,
             'read_scope': '名前・docstringのみ'},
  'targets': (),
  'status': '未対応',
  'reason': '名前/docstringだけでは和型の対象を特定できない。期待値・試験本体は未読。'},
 {'name': 'test_v010_07_unknown_tag_or_double_wrapper_rejected_fb',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 859,
             'last': 859,
             'read_scope': '名前・docstringのみ'},
  'targets': (),
  'status': '未対応',
  'reason': '名前/docstringだけでは和型の対象を特定できない。期待値・試験本体は未読。'},
 {'name': 'test_structure_preference_conflict_saved_attempt_replays_same_rejection',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 875,
             'last': 875,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.style', 'T.rel.storage'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F19_saved_missing_implementation_binding_commit_and_replay',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 894,
             'last': 894,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.dependencies', 'T.artifact'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'},
 {'name': 'test_review_F19_tampered_saved_dependency_rejected_by_binding',
  'docstring': None,
  'source': {'path': 'C:/Users/you11/Desktop/sui_fb_material_20261012/tests_fb/test_gate_f_fb.py',
             'first': 932,
             'last': 932,
             'read_scope': '名前・docstringのみ'},
  'targets': ('T.dependencies', 'T.artifact'),
  'status': '名前からの照合候補・未確認',
  'reason': '期待値を転記していない。名前の一致は仕様への適合を証明しない。'})
TRANSFERRED_COUNT_NOTE = '指定29件に対しtests_fb/test_gate_f_fb.pyのtest_関数は36。29件の選別単位は未確認。全36を保持し期待値は未読。'

# この行より上を場面/誤実装の閲覧前に固定した。橋から対象/規則を足さない。
DENOMINATOR_KEYS = ('TARGETS', 'RULES', 'ENTRY_POINTS', 'SOURCE_ENUMERATION', 'ACCEPTANCE', 'ACCEPTANCE_LINKS', 'GAPS', 'MISMATCHES')
DENOMINATOR_SHA256 = '4cbabdea70d8f841f889af9f3e36de3c1d714d415531378994355e1162a71b9e'

SESSION_NOTE = {
    "date": "2026-10-17", "project": "sui", "tool": "codex",
    "session_id": "01a14886-c9a3-7ab3-8251-ce0a5c6f7d91",
    "artifact_version": "FBT draft 1 / paper v0.19",
    "decision": "紙と公開宣言の分母を固定した後に橋を作成。未決・未対応を成功扱いせず、実装試験は実装の段へ。",
    "verification": "新規tests/test_fb_targets.pyのみ12件通過。Python 3.12.10 / pytest 9.1.1。実装の確認ではない。",
    "failed_attempts": "標準Python 3.14にはpytestなし。既存.venvを使用。初回自己点検の空欄2件は追加未接続枝の残存範囲を明記して修正。",
    "read_scope": "紙は指定節と根拠の該当部分。公開コードはASTで宣言/署名/docstringのみ。模型本体は未読。外部Web資料なし。",
    "other_agent": "今回の別AIへの連絡なし。Claudeの集計は依頼文の情報で、独立集計と照合した。",
    "reuse": "有効: 独立の分母、期待と環境の事実を分離する共有知見。利用の結果は分母ハッシュと別の橋データ。",
    "not_done": "src/specs/既存testsの変更、commit、模型/実装試験、Obsidian Sessions/Projects/Heat更新はしていない。",
    "next": "G-01/G-02/G-05の宣言資料、D-01の型不一致、G-03の合格判定を確認し、後続版で全欄を再照合する。",
    "scope_note": "成果物内のIDと索引用キーは管理用。新契約/新規則を採用する紙に無い仮定は0（名前だけ0/意味を変える0）。",
}


# ---- FBT-03: 固定済み分母への橋。以下からTARGETS/RULESを変更しない。 ----
BRIDGE_EXTRACTION = {'method': 'ASTでSceneの欄、宣言組立ループ、scope分類だけを抽出評価。E0構築と模型importはしない。E0の有無を保持したsentinelで分類し、内側partsも別集計。試験や模型は実行していない。',
 'observed_counts': {'structural_a': 79,
                     'scene_b': 107,
                     'mutant_outside': 7,
                     'nested_scene_b': 2,
                     'additional_unconnected_a': 2},
 'claude_counts': {'scene_b': 107, 'mutant_outside': 7, 'structural_a': 79},
 'differences': {'scene_b': 0, 'mutant_outside': 0, 'structural_a': 0},
 'top_level_scenes': 239,
 'folded_b_counts': {'SC-06': 4,
                     'SC-07a': 2,
                     'SC-07b': 2,
                     'SC-08': 7,
                     'SC-09': 3,
                     'SC-10': 4,
                     'SC-11': 20,
                     'SC-12': 5,
                     'SC-13': 1,
                     'SC-14': 2,
                     'SC-15': 27,
                     'SC-16': 6,
                     'SC-17': 5,
                     'SC-18': 16,
                     'SC-21': 3},
 'source_sha256': {'tests/fb_scenes.py': 'c41cbcabca0a372bc42f18514fbb74ed5c41853580192a04bf43efda53249dd9',
                   'tests/fb_mutants.py': '6a528194a84c527f413a6af30c42c193e1e160bca8df9e1b503d5bf18c3f89f0'},
 'supplemental_note': '指定3種以外にpartsのb枝2件と、STRUCTURAL_LIMITを持たない未接続a枝2件も橋へ保持。指定107/7/79へ混ぜない。',
 'inherited_assumptions': '模型側の仮定は期待値へ輸入しない。構造だけの範囲と将来の実値検証を分離。',
 'result_json_scope': 'fb_scenes_results.jsonはキーと記録構造のみ。fb_mutants_results.jsonはdenominators/row_totalsとrowsの範囲外7 '
                      'IDだけを照合。過去の成功は再検証扱いにしない。'}
STRUCTURAL_NUMERIC_REMAINDER = '範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。'
BRIDGE_RECIPES = {'update': {'targets': ('T.rel.update_stages',
                        'T.rel.numeric_update2',
                        'T.finite_result',
                        'T.finite_statement',
                        'T.completed'),
            'checks': ('F-aの実物の値', '固定値', '新しい試験'),
            'method': '紙の有限な入力から独立に計算した値と実F-aのR/P/Cを比べる。局所構造の成功で数値を代用しない。'},
 'verify': {'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'),
            'checks': ('F-aの実物の値', '変異', '新しい試験'),
            'method': '合法な同一Q/R/P/Cの実取得と発行認証を前置にし、対象/返答/祖先を一つだけ交換した負例を置く。'},
 'stale': {'targets': ('T.rel.stale',
                       'T.stale',
                       'T.adopted.previous',
                       'T.finite_update1.previous_result',
                       'T.rel.numeric_update2'),
           'checks': ('F-aの実物の値', '固定値', '新しい試験'),
           'method': '同前状態の二要求/新前状態の逐次要求/再採用を別に作る。固定previous_resultと現在の採用を独立照合する。'},
 'derive': {'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'),
            'checks': ('F-aの実物の値', '固定値', '新しい試験'),
            'method': '紙で宣言した導出方法で受信ごとの責務とQを照合し、/2の実際の射影値を独立計算する。まとめるδを無条件に追加しない。'},
 'evaluation': {'targets': ('T.eq',
                            'T.prepared',
                            'T.evaluated',
                            'T.rel.selection',
                            'T.artifact',
                            'T.math_problem',
                            'T.math_root'),
                'checks': ('F-aの実物の値', '固定値', '変異', '新しい試験'),
                'method': '実F-aのprepare/bind/evaluate/verifyを同じ固定入力へ接続する。全artifactの閉包とSelected/NoDecisionの違いを確認する。'},
 'draw': {'targets': ('T.rel.draw',
                      'T.draw_fact',
                      'T.draw_returned',
                      'T.prepared',
                      'T.draw_unknown',
                      'T.terminal',
                      'T.artifact'),
          'checks': ('F-aの実物の値', '固定値', '変異', '新しい試験'),
          'method': '合法な実PR/固定Draw要求から始める。消費回数と同じPoint/uを別に記録し、Unknownで再抽選せず元終端を保つ。'},
 'coverage': {'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'),
              'checks': ('F-aの実物の値', '固定値', '変異', '新しい試験'),
              'method': 'contract別の合法な測定/生成証拠をX内に持つ正例から一つだけ変更し、被覆の端点・開閉・Support・時計を照合する。'},
 'independence': {'targets': ('T.rel.independence', 'T.rel.receipt', 'T.rel.resource', 'T.rel.coverage'),
                  'checks': ('F-aの実物の値', '新しい試験'),
                  'method': '実計算を占有中に保ち、受信/測定の前提を同じにして公開受付と保存の提供を比較する。'},
 'capacity': {'targets': ('T.rel.resource', 'T.rel.draw', 'T.prepared', 'T.artifact', 'T.rel.independence'),
              'checks': ('F-aの実物の値', '固定値', '新しい試験'),
              'method': '合法なPRを実F-aで作り、他仕事の占有1と容量1/2の各対照を保つ。独立の受付も残す。'},
 'terminal': {'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'),
              'checks': ('F-aの実物の値', '固定値', '変異', '新しい試験'),
              'method': 'そのstageの実F-a値を持つ同じ前段から、元枝の停止/未停止・同r/seq・未保存先着・遅着順を再現する。'},
 'conflict': {'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner'),
              'checks': ('F-aの実物の値', '変異', '新しい試験'),
              'method': '同じ対象のA/A/BまたはUnknown/A/Bを原本で保ち、Conflict保存前から使用を止め既存確定と責務を保持する。'},
 'generation': {'targets': ('T.rel.generation',
                            'T.qgen',
                            'T.candidate_generation',
                            'T.candidate',
                            'T.eq',
                            'T.model_document',
                            'T.artifact'),
                'checks': ('F-aの実物の値', '固定値', '変異', '新しい試験'),
                'method': '固定したQgenと実生成全出力（順序/測度含む）からCG/EQを作る。記号候補/不透明測度を実F-aの合法な値へ置換し、Wg像とEp像を分ける。'},
 'generation_draw': {'targets': ('T.external.R10',
                                 'T.generation_draw_request',
                                 'T.generation_draw_unknown',
                                 'T.rel.generation'),
                     'checks': ('新しい試験', '固定値'),
                     'method': '未採用R10/D6の契約が決まった後に作る。現在はMissingContractを成功抽選やdraws=[]へ読み替えない。'}}
BRIDGE_SOURCE_ITEMS = (
    {'id': 'SC-05', 'group': 'structural_a', 'paper_id': 'SC-05', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/C→実取得→G/Wv', 'goals': ({'id': 'wp-before-r', 'text': 'R保存前にWp行があり開始待ち'}, {'id': 'wp-after-r', 'text': 'R保存後にWpを開始'}, {'id': 'completed', 'text': 'P保存後にCqを1件保存'}, {'id': 'g-wv', 'text': 'G発行後、G未保存からWv行を保持'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1724, 2640), 'legacy_paper_lines': (933,)},
    {'id': 'SC-06-Success', 'group': 'structural_a', 'paper_id': 'SC-06', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/C→実取得→G/Wv', 'goals': ({'id': 'issued', 'text': '返答とは別の認証物発行ポート'}, {'id': 'verify', 'text': '実認証返答ポート'}, {'id': 'adopt', 'text': '実祖先Gを持つ採用'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1726, 2640), 'legacy_paper_lines': (934, 1362)},
    {'id': 'SC-06-Rejected', 'group': 'scene_b', 'paper_id': 'SC-06', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IC→IG', 'goals': ({'id': 'paper-required', 'text': '実際の取得前の採用禁止、対象違いの認証、返答とVの対応、正しい採用'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1726, 2661), 'legacy_paper_lines': (934, 1362)},
    {'id': 'SC-06-Insufficient', 'group': 'scene_b', 'paper_id': 'SC-06', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IC→IG', 'goals': ({'id': 'paper-required', 'text': '実際の取得前の採用禁止、対象違いの認証、返答とVの対応、正しい採用'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1726, 2661), 'legacy_paper_lines': (934, 1362)},
    {'id': 'SC-06-Unknown', 'group': 'scene_b', 'paper_id': 'SC-06', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IC→IG', 'goals': ({'id': 'paper-required', 'text': '実際の取得前の採用禁止、対象違いの認証、返答とVの対応、正しい採用'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1726, 2661), 'legacy_paper_lines': (934, 1362)},
    {'id': 'SC-06-wrong-target', 'group': 'scene_b', 'paper_id': 'SC-06', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IC→IG', 'goals': ({'id': 'paper-required', 'text': '実際の取得前の採用禁止、対象違いの認証、返答とVの対応、正しい採用'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1726, 2661), 'legacy_paper_lines': (934, 1362)},
    {'id': 'SC-07a-q1-first', 'group': 'scene_b', 'paper_id': 'SC-07a', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IA', 'goals': ({'id': 'paper-required', 'text': 'q1由来のr1を採用した後、q2のprevious_resultはr0のままでStaleになる。逆順も対照にする。この2要求をそのまま順に新導出として採用することを到達目標にしない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1730, 2661), 'legacy_paper_lines': (935,)},
    {'id': 'SC-07a-q2-first', 'group': 'scene_b', 'paper_id': 'SC-07a', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IA', 'goals': ({'id': 'paper-required', 'text': 'q1由来のr1を採用した後、q2のprevious_resultはr0のままでStaleになる。逆順も対照にする。この2要求をそのまま順に新導出として採用することを到達目標にしない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1730, 2661), 'legacy_paper_lines': (935,)},
    {'id': 'SC-07b-sequential', 'group': 'scene_b', 'paper_id': 'SC-07b', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IA', 'goals': ({'id': 'paper-required', 'text': "d1の後にq2由来のd2を正常に採用できる。再採用を確かめる枝は別ケースとし、同じ導出C1に対する別の採用意図d1'を作り、previousはその時の実際の採用を指す。元のq1.previous_resultは書き換えず、測定の適用数も増やさない"},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1730, 2661), 'legacy_paper_lines': (936,)},
    {'id': 'SC-07b-readopt', 'group': 'scene_b', 'paper_id': 'SC-07b', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IA', 'goals': ({'id': 'paper-required', 'text': "d1の後にq2由来のd2を正常に採用できる。再採用を確かめる枝は別ケースとし、同じ導出C1に対する別の採用意図d1'を作り、previousはその時の実際の採用を指す。元のq1.previous_resultは書き換えず、測定の適用数も増やさない"},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1730, 2661), 'legacy_paper_lines': (936,)},
    {'id': 'SC-08-e1-only', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-e2-only', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-group', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-no-group', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-other-trigger-slot', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-conflict-N', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-conflict-P', 'group': 'scene_b', 'paper_id': 'SC-08', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0/IX', 'goals': ({'id': 'paper-required', 'text': 'Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1733, 2661), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-09-FProblem-Selected', 'group': 'scene_b', 'paper_id': 'SC-09', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0→IE→ID', 'goals': ({'id': 'paper-required', 'text': 'PR前D行、DF前Ee行、NoDecisionで後続禁止、Selectedでselection'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1735, 2661), 'legacy_paper_lines': (938,)},
    {'id': 'SC-09-FProblem-NoDecision', 'group': 'scene_b', 'paper_id': 'SC-09', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0→IE→ID', 'goals': ({'id': 'paper-required', 'text': 'PR前D行、DF前Ee行、NoDecisionで後続禁止、Selectedでselection'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1735, 2661), 'legacy_paper_lines': (938,)},
    {'id': 'SC-09-Ep-NoDecision', 'group': 'scene_b', 'paper_id': 'SC-09', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'I0→IE→ID', 'goals': ({'id': 'paper-required', 'text': 'PR前D行、DF前Ee行、NoDecisionで後続禁止、Selectedでselection'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1735, 2661), 'legacy_paper_lines': (938,)},
    {'id': 'SC-10-problem_key', 'group': 'scene_b', 'paper_id': 'SC-10', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IE/ID', 'goals': ({'id': 'paper-required', 'text': '別problem_key、別purpose、別Draw Point、別artifactが拒まれる状態'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1737, 2661), 'legacy_paper_lines': (939,)},
    {'id': 'SC-10-purpose', 'group': 'scene_b', 'paper_id': 'SC-10', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IE/ID', 'goals': ({'id': 'paper-required', 'text': '別problem_key、別purpose、別Draw Point、別artifactが拒まれる状態'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1737, 2661), 'legacy_paper_lines': (939,)},
    {'id': 'SC-10-draw-point', 'group': 'scene_b', 'paper_id': 'SC-10', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IE/ID', 'goals': ({'id': 'paper-required', 'text': '別problem_key、別purpose、別Draw Point、別artifactが拒まれる状態'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1737, 2661), 'legacy_paper_lines': (939,)},
    {'id': 'SC-10-artifact', 'group': 'scene_b', 'paper_id': 'SC-10', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IE/ID', 'goals': ({'id': 'paper-required', 'text': '別problem_key、別purpose、別Draw Point、別artifactが拒まれる状態'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1737, 2661), 'legacy_paper_lines': (939,)},
    {'id': 'SC-11-Frame', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-Started', 'group': 'structural_a', 'paper_id': 'SC-11', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2640), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-Ended', 'group': 'structural_a', 'paper_id': 'SC-11', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2640), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-RouteApplied', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-Gap', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-Unavailable', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-Claim', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-Unproved', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-report-before-start', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-same-seq-other-id', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-same-content-other-slot', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-end-equals-r', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-end-after-r', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-open-closed-neighbor', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-actual-time-unavailable', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-claim-window', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-claim-generation', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-unknown-kind', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-future-unproved', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-11-evidence-outside-X', 'group': 'scene_b', 'paper_id': 'SC-11', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1742, 2661), 'legacy_paper_lines': (940, 1364)},
    {'id': 'SC-12-positive-claim', 'group': 'scene_b', 'paper_id': 'SC-12', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '過大被覆禁止、無報告をGapにしない、責務を持つ合法な待ち'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2661), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-12-started-only', 'group': 'structural_a', 'paper_id': 'SC-12', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}, {'id': 'unreported', 'text': 'Started/Endedだけで未報告責務を解消しない'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2640), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-12-ended-only', 'group': 'structural_a', 'paper_id': 'SC-12', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}, {'id': 'unreported', 'text': 'Started/Endedだけで未報告責務を解消しない'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2640), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-12-Gap', 'group': 'scene_b', 'paper_id': 'SC-12', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '過大被覆禁止、無報告をGapにしない、責務を持つ合法な待ち'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2661), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-12-Unavailable', 'group': 'scene_b', 'paper_id': 'SC-12', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '過大被覆禁止、無報告をGapにしない、責務を持つ合法な待ち'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2661), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-12-partial-report', 'group': 'scene_b', 'paper_id': 'SC-12', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '過大被覆禁止、無報告をGapにしない、責務を持つ合法な待ち'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2661), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-12-evidence-wait', 'group': 'scene_b', 'paper_id': 'SC-12', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '過大被覆禁止、無報告をGapにしない、責務を持つ合法な待ち'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1744, 2661), 'legacy_paper_lines': (941, 1364)},
    {'id': 'SC-13-measure-report', 'group': 'scene_b', 'paper_id': 'SC-13', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wr)/IK', 'goals': ({'id': 'paper-required', 'text': '占有を保持したままAccept/PutBody/AddEntryが可能'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1745, 2661), 'legacy_paper_lines': (942,)},
    {'id': 'SC-14-capacity1', 'group': 'scene_b', 'paper_id': 'SC-14', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IE+IT(Hung)', 'goals': ({'id': 'paper-required', 'text': '席1ではD の資源待ちが正当、席2では空席があるのに同じ理由でDを免除しない。受信は双方で進む'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1747, 2661), 'legacy_paper_lines': (943, 1365)},
    {'id': 'SC-14-capacity2', 'group': 'scene_b', 'paper_id': 'SC-14', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IE+IT(Hung)', 'goals': ({'id': 'paper-required', 'text': '席1ではD の資源待ちが正当、席2では空席があるのに同じ理由でDを免除しない。受信は双方で進む'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1747, 2661), 'legacy_paper_lines': (943, 1365)},
    {'id': 'SC-15-Wr-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wr)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wr-no-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wr)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wr-lost-reply-capacity2', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wr)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wr-tie-unknown-first', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': 'a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IT(Wr): 同r通知2件受付/再受付・後着Saved・先行bodyのみ (全前置履歴付き)', 'goals': ({'id': 'same-r-seq', 'text': '同じrun/r・異なる番号/seqでE0の通知順を再現'}, {'id': 'accept-retry', 'text': '再Acceptでも番号/r/seqと受信計画が不変'}, {'id': 'first-unsaved', 'text': '後のseqを先に保存、先行通知未保存では終端を発行しない'}, {'id': 'first-terminal', 'text': '先行通知保存後、E0で指定した先着の種類/受信PointでTを保存'}), 'remaining': ('K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2723, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2723), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wr-tie-value-first', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': 'a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IT(Wr): 同r通知2件受付/再受付・後着Saved・先行bodyのみ (全前置履歴付き)', 'goals': ({'id': 'same-r-seq', 'text': '同じrun/r・異なる番号/seqでE0の通知順を再現'}, {'id': 'accept-retry', 'text': '再Acceptでも番号/r/seqと受信計画が不変'}, {'id': 'first-unsaved', 'text': '後のseqを先に保存、先行通知未保存では終端を発行しない'}, {'id': 'first-terminal', 'text': '先行通知保存後、E0で指定した先着の種類/受信PointでTを保存'}), 'remaining': ('K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2723, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2723), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-16-Wr-Unknown-A-B', 'group': 'scene_b', 'paper_id': 'SC-16', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wr)', 'goals': ({'id': 'paper-required', 'text': 'Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1753, 2661), 'legacy_paper_lines': (945,)},
    {'id': 'SC-15-Wp-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wp)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wp-no-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wp)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wp-lost-reply-capacity2', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wp)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wp-tie-unknown-first', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': 'a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IT(Wp): 同r通知2件受付/再受付・後着Saved・先行bodyのみ (全前置履歴付き)', 'goals': ({'id': 'same-r-seq', 'text': '同じrun/r・異なる番号/seqでE0の通知順を再現'}, {'id': 'accept-retry', 'text': '再Acceptでも番号/r/seqと受信計画が不変'}, {'id': 'first-unsaved', 'text': '後のseqを先に保存、先行通知未保存では終端を発行しない'}, {'id': 'first-terminal', 'text': '先行通知保存後、E0で指定した先着の種類/受信PointでTを保存'}), 'remaining': ('K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2723, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2723), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wp-tie-value-first', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': 'a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IT(Wp): 同r通知2件受付/再受付・後着Saved・先行bodyのみ (全前置履歴付き)', 'goals': ({'id': 'same-r-seq', 'text': '同じrun/r・異なる番号/seqでE0の通知順を再現'}, {'id': 'accept-retry', 'text': '再Acceptでも番号/r/seqと受信計画が不変'}, {'id': 'first-unsaved', 'text': '後のseqを先に保存、先行通知未保存では終端を発行しない'}, {'id': 'first-terminal', 'text': '先行通知保存後、E0で指定した先着の種類/受信PointでTを保存'}), 'remaining': ('K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2723, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2723), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-16-Wp-Unknown-A-B', 'group': 'scene_b', 'paper_id': 'SC-16', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wp)', 'goals': ({'id': 'paper-required', 'text': 'Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1753, 2661), 'legacy_paper_lines': (945,)},
    {'id': 'SC-15-Wv-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wv)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wv-no-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wv)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wv-lost-reply-capacity2', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wv)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wv-tie-unknown-first', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': 'a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IT(Wv): 同r通知2件受付/再受付・後着Saved・先行bodyのみ (全前置履歴付き)', 'goals': ({'id': 'same-r-seq', 'text': '同じrun/r・異なる番号/seqでE0の通知順を再現'}, {'id': 'accept-retry', 'text': '再Acceptでも番号/r/seqと受信計画が不変'}, {'id': 'first-unsaved', 'text': '後のseqを先に保存、先行通知未保存では終端を発行しない'}, {'id': 'first-terminal', 'text': '先行通知保存後、E0で指定した先着の種類/受信PointでTを保存'}), 'remaining': ('K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2723, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2723), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Wv-tie-value-first', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': 'a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IP(T): 同r先行未保存を経て先行Saved・T/V発行・V Saved・T未準備 (全前置履歴付き)', 'goals': ({'id': 'same-r-seq', 'text': '同じrun/r・異なる番号/seqでE0の通知順を再現'}, {'id': 'accept-retry', 'text': '再Acceptでも番号/r/seqと受信計画が不変'}, {'id': 'first-unsaved', 'text': '後のseqを先に保存、先行通知未保存では終端を発行しない'}, {'id': 'first-terminal', 'text': '先行通知保存後、E0で指定した先着の種類/受信PointでTを保存'}, {'id': 'verification-saved', 'text': '発行したVの保存を前置に残す'}), 'remaining': ('K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。', 'V保存を合法な前置に局所化。T/V全保存順序の直積は未検査。先行通知未保存は前置で確認し、T準備後にVを保存する逆順はP-10回帰で別途確認。'), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2723, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2723), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-16-Wv-Unknown-A-B', 'group': 'scene_b', 'paper_id': 'SC-16', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wv)', 'goals': ({'id': 'paper-required', 'text': 'Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1753, 2661), 'legacy_paper_lines': (945,)},
    {'id': 'SC-15-Ep-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ep)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ep-no-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ep)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ep-lost-reply-capacity2', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ep)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ep-tie-unknown-first', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Epの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。', 'implementation_scope': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Epの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'initial': 'IT(Ep)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2709, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2709), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ep-tie-value-first', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Epの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。', 'implementation_scope': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Epの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'initial': 'IT(Ep)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2709, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2709), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-16-Ep-Unknown-A-B', 'group': 'scene_b', 'paper_id': 'SC-16', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ep)', 'goals': ({'id': 'paper-required', 'text': 'Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1753, 2661), 'legacy_paper_lines': (945,)},
    {'id': 'SC-15-D-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-D-no-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-D-lost-reply-capacity2', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-D-tie-unknown-first', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Dの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。', 'implementation_scope': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Dの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2709, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2709), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-D-tie-value-first', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Dの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。', 'implementation_scope': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Dの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2709, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2709), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-16-D-Unknown-A-B', 'group': 'scene_b', 'paper_id': 'SC-16', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': 'Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1753, 2661), 'legacy_paper_lines': (945,)},
    {'id': 'SC-15-Ee-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ee)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ee-no-stop', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ee)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ee-lost-reply-capacity2', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ee)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2661), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ee-tie-unknown-first', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Eeの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。', 'implementation_scope': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Eeの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'initial': 'IT(Ee)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2709, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2709), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-Ee-tie-value-first', 'group': 'scene_b', 'paper_id': 'SC-15', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Eeの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。', 'implementation_scope': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Eeの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'initial': 'IT(Ee)', 'goals': ({'id': 'paper-required', 'text': '基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2709, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1751, 2709), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-16-Ee-Unknown-A-B', 'group': 'scene_b', 'paper_id': 'SC-16', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Ee)', 'goals': ({'id': 'paper-required', 'text': 'Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1753, 2661), 'legacy_paper_lines': (945,)},
    {'id': 'SC-17-Wr-A-A-B', 'group': 'scene_b', 'paper_id': 'SC-17', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wr)', 'goals': ({'id': 'paper-required', 'text': '受信3件、同値だけでは論理処理増加なし、BでConflict、X前から使用禁止'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1756, 2661), 'legacy_paper_lines': (946,)},
    {'id': 'SC-17-Wp-A-A-B', 'group': 'scene_b', 'paper_id': 'SC-17', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(Wp)', 'goals': ({'id': 'paper-required', 'text': '受信3件、同値だけでは論理処理増加なし、BでConflict、X前から使用禁止'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1756, 2661), 'legacy_paper_lines': (946,)},
    {'id': 'SC-17-D-A-A-B', 'group': 'scene_b', 'paper_id': 'SC-17', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(D)', 'goals': ({'id': 'paper-required', 'text': '受信3件、同値だけでは論理処理増加なし、BでConflict、X前から使用禁止'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1756, 2661), 'legacy_paper_lines': (946,)},
    {'id': 'SC-17-interval-slot-A-A-B', 'group': 'scene_b', 'paper_id': 'SC-17', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IT(interval-slot)', 'goals': ({'id': 'paper-required', 'text': '受信3件、同値だけでは論理処理増加なし、BでConflict、X前から使用禁止'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1756, 2661), 'legacy_paper_lines': (946,)},
    {'id': 'SC-18-Wr-Wp-pre-publish', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wr-Wp-published-unprepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wr-Wp-prepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wr-Wp-launched-not-entered', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wp-acquire-pre-publish', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wp-acquire-published-unprepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wp-acquire-prepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Wp-acquire-launched-not-entered', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Ep-D-pre-publish', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Ep-D-published-unprepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Ep-D-prepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-Ep-D-launched-not-entered', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-D-Ee-pre-publish', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-D-Ee-published-unprepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-D-Ee-prepared', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-18-D-Ee-launched-not-entered', 'group': 'scene_b', 'paper_id': 'SC-18', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IX/IP/IT', 'goals': ({'id': 'paper-required', 'text': '既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1760, 2661), 'legacy_paper_lines': (947, 1367)},
    {'id': 'SC-21-interval-receipt-Q', 'group': 'scene_b', 'paper_id': 'SC-21', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': '前段からの実到達状態', 'goals': ({'id': 'paper-required', 'text': '各接続の正の到達証拠。別に「評価の実行中に受信保存・更新」が重なる短い橋渡し場面'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1765, 2661), 'legacy_paper_lines': (950, 1369)},
    {'id': 'SC-21-Q-R-P-C', 'group': 'structural_a', 'paper_id': 'SC-21', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所Q/R/P/時計/C（合法IC未確認）', 'goals': ({'id': 'completed', 'text': '同じQ/R/PからCを1件保存'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2645, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1765, 2640, 2645), 'legacy_paper_lines': (950, 1369)},
    {'id': 'SC-21-acquire-verify-adopt', 'group': 'structural_a', 'paper_id': 'SC-21', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/C→実取得→G/Wv', 'goals': ({'id': 'issued', 'text': '返答とは別の認証物発行ポート'}, {'id': 'verify', 'text': '実認証返答ポート'}, {'id': 'adopt', 'text': '実祖先Gを持つ採用'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2645, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1765, 2640, 2645), 'legacy_paper_lines': (950, 1369)},
    {'id': 'SC-21-Ep-D-Ee-selection', 'group': 'scene_b', 'paper_id': 'SC-21', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': '前段からの実到達状態', 'goals': ({'id': 'paper-required', 'text': '各接続の正の到達証拠。別に「評価の実行中に受信保存・更新」が重なる短い橋渡し場面'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1765, 2661), 'legacy_paper_lines': (950, 1369)},
    {'id': 'SC-21-evaluation-hung-receive-update', 'group': 'scene_b', 'paper_id': 'SC-21', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': '前段からの実到達状態', 'goals': ({'id': 'paper-required', 'text': '各接続の正の到達証拠。別に「評価の実行中に受信保存・更新」が重なる短い橋渡し場面'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1765, 2661), 'legacy_paper_lines': (950, 1369)},
    {'id': 'SC-05-PARENT', 'group': 'structural_a', 'paper_id': 'SC-05-PARENT', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/Cの親対照', 'goals': ({'id': 'parents', 'text': 'R/PはPredictionを親にせず保存済みQを親に持つ'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1780, 2640), 'legacy_paper_lines': (1383,)},
    {'id': 'SC-05-COMPLETE', 'group': 'structural_a', 'paper_id': 'SC-05-COMPLETE', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所構造:p-clocks-saved（合法IC未確認）', 'goals': ({'id': 'p-saved', 'text': '時計保存後にP保存'}, {'id': 'c-before-p', 'text': '時計保存済みでもP未保存中はCのPublish/準備を提供しない'}, {'id': 'completed', 'text': 'P保存後Cが1件'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1780, 2640), 'legacy_paper_lines': (1385,)},
    {'id': 'SC-06-ANCESTOR', 'group': 'structural_a', 'paper_id': 'SC-06-ANCESTOR', 'scope_class': 'a', 'scope_reason': 'a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/C→実取得→G/Wv→認証返答', 'goals': ({'id': 'issued', 'text': '返答とは別の認証物発行ポート'}, {'id': 'verify', 'text': '実認証返答ポート'}, {'id': 'adopt', 'text': '実祖先Gを持つ採用'}), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2640, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1780, 2640), 'legacy_paper_lines': (1386,)},
    {'id': 'SC-11-FAMILY', 'group': 'scene_b', 'paper_id': 'SC-11-FAMILY', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '同じsegment/slotで同じGapを再配送'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1780, 2661), 'legacy_paper_lines': (1388,)},
    {'id': 'SC-17-FAMILY', 'group': 'scene_b', 'paper_id': 'SC-17-FAMILY', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '同slotのGap A・同値A・Unavailable Bを3通知として保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1780, 2661), 'legacy_paper_lines': (1389,)},
    {'id': 'SC-11-CROSS-M', 'group': 'scene_b', 'paper_id': 'SC-11-CROSS-M', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IK', 'goals': ({'id': 'paper-required', 'text': '二つの適合する区間k1/k2へ、同じMeasurementId・全本体欄が同じ原Frameを結ぶ'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1780, 2661), 'legacy_paper_lines': (1390,)},
    {'id': 'SC-15-WP-VERIFY-Wp-Failure', 'group': 'scene_b', 'paper_id': 'SC-15-WP/VERIFY', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IP(result/G)→IT(Wp-Failure)', 'goals': ({'id': 'paper-required', 'text': 'result/GのPublish直後から、それぞれWp/Wvのrunを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1777, 2661), 'legacy_paper_lines': (1391,)},
    {'id': 'SC-15-WP-VERIFY-Wp-Unknown', 'group': 'scene_b', 'paper_id': 'SC-15-WP/VERIFY', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IP(result/G)→IT(Wp-Unknown)', 'goals': ({'id': 'paper-required', 'text': 'result/GのPublish直後から、それぞれWp/Wvのrunを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1777, 2661), 'legacy_paper_lines': (1391,)},
    {'id': 'SC-15-WP-VERIFY-Wv-Insufficient', 'group': 'scene_b', 'paper_id': 'SC-15-WP/VERIFY', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'initial': 'IP(result/G)→IT(Wv-Insufficient)', 'goals': ({'id': 'paper-required', 'text': 'result/GのPublish直後から、それぞれWp/Wvのrunを保持'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 1574, 'last': 2661, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (1574, 1718, 1777, 2661), 'legacy_paper_lines': (1391,)},
    {'id': 'SC-05-structure-r-published', 'group': 'structural_a', 'paper_id': 'SC-05', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所構造:r-published（合法IC未確認）', 'goals': ({'id': 'wp-before-r', 'text': 'R未保存でWp行あり・まだ開始不可'}, {'id': 'r-saved', 'text': 'R保存後Wp開始可能'}), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2463, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2463, 2664), 'legacy_paper_lines': (933, 1330, 1341)},
    {'id': 'SC-05-structure-p-published', 'group': 'structural_a', 'paper_id': 'SC-05', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所構造:p-published（合法IC未確認）', 'goals': ({'id': 'p-saved', 'text': 'Pと時計証拠保存'},), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2463, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2463, 2664), 'legacy_paper_lines': (933, 1330, 1341)},
    {'id': 'SC-05-structure-p-saved', 'group': 'structural_a', 'paper_id': 'SC-05', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所構造:p-saved（合法IC未確認）', 'goals': ({'id': 'completed', 'text': 'P後にCqがただ1件保存'},), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2463, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2463, 2664), 'legacy_paper_lines': (933, 1330, 1341)},
    {'id': 'SC-05-structure-p-clocks-saved', 'group': 'structural_a', 'paper_id': 'SC-05', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所構造:p-clocks-saved（合法IC未確認）', 'goals': ({'id': 'p-saved', 'text': '時計保存後にP保存'}, {'id': 'c-before-p', 'text': '時計保存済みでもP未保存中はCのPublish/準備を提供しない'}, {'id': 'completed', 'text': 'P保存後Cが1件'}), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2463, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2463, 2664), 'legacy_paper_lines': (933, 1330, 1341)},
    {'id': 'SC-06-structure-acquire', 'group': 'structural_a', 'paper_id': 'SC-06', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/C保存→実取得（合法IC未確認）', 'goals': ({'id': 'acquire', 'text': '同じ読み手がR/Pを実取得'},), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2467, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2467, 2664), 'legacy_paper_lines': (934, 1330, 1331, 1341)},
    {'id': 'SC-06-structure-verification-pending', 'group': 'structural_a', 'paper_id': 'SC-06', 'scope_class': 'a', 'scope_reason': 'a: 上限200を保持。旧200未完はWvの発行/返答/通知保存/停止/採用保存の直積。今回は返答保存まで実行して局所化し、停止・採用・保存の残る全順序を探索。前置の別順序は未検査。紙925/1341/1347。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IG→Wv実発行/返答保存済み・Stop前 (前置履歴付き)', 'goals': ({'id': 'issued', 'text': '返答とは別の認証物発行ポート'}, {'id': 'verify', 'text': '実認証返答ポート'}, {'id': 'adopt', 'text': '実祖先Gを持つ採用'}), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。', 'Rejected/Insufficient/Unknown/対象違い・Staleは未実行。'), 'source': {'path': 'tests/fb_scenes.py', 'first': 2472, 'last': 2666, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2472, 2664, 2666), 'legacy_paper_lines': (934, 1085, 1086, 1341)},
    {'id': 'SC-06-structure-verification-adopt', 'group': 'structural_a', 'paper_id': 'SC-06', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/C→実取得→G/Wv→認証返答', 'goals': ({'id': 'issued', 'text': '返答とは別の認証物発行ポート'}, {'id': 'verify', 'text': '実認証返答ポート'}, {'id': 'adopt', 'text': '実祖先Gを持つ採用'}), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。', 'Rejected/Insufficient/Unknown/対象違い・Staleは未実行。'), 'source': {'path': 'tests/fb_scenes.py', 'first': 2472, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2472, 2664), 'legacy_paper_lines': (934, 1085, 1086, 1341)},
    {'id': 'SC-08-structure-e1-then-other', 'group': 'structural_a', 'paper_id': 'SC-08', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→先行受信とQ保存、他方未Post', 'goals': ({'id': 'two-received', 'text': '独立な2原本の保存'}, {'id': 'two-requests', 'text': '先行Qの後も別受信用Qを保存'}), 'remaining': ('SC-08全体のまとめたQ・他trigger-slot・Conflictと数値射影は未実行。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2484, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2484, 2664), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-08-structure-e2-then-other', 'group': 'structural_a', 'paper_id': 'SC-08', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→先行受信とQ保存、他方未Post', 'goals': ({'id': 'two-received', 'text': '独立な2原本の保存'}, {'id': 'two-requests', 'text': '先行Qの後も別受信用Qを保存'}), 'remaining': ('SC-08全体のまとめたQ・他trigger-slot・Conflictと数値射影は未実行。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2484, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2484, 2664), 'legacy_paper_lines': (937, 1363)},
    {'id': 'SC-09-structure-artifact-port', 'group': 'structural_a', 'paper_id': 'SC-09', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'EQ/Ep入場の局所構造（合法IE未確認）', 'goals': ({'id': 'issued', 'text': 'EQの同じ入力から独立した実artifact発行'},), 'remaining': ('PR/D/Ee/selectionと実F-a artifact閉包は未接続。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2493, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2493, 2664), 'legacy_paper_lines': (938, 1025, 1089, 1341)},
    {'id': 'SC-12-structure-measure-row', 'group': 'structural_a', 'paper_id': 'SC-12', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '区間引受け→k Publish（局所構造）', 'goals': ({'id': 'measure-row', 'text': 'k未保存からMeasureSegment行を保持'}, {'id': 'measure-enter', 'text': 'k保存後に測る仕事へ入場'}, {'id': 'unreported', 'text': '報告なしをGapへ変えず未報告責務を保持'}), 'remaining': ('実IK/Support/型別報告の意味は未確認。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2501, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2501, 2664), 'legacy_paper_lines': (941, 1205, 1206, 1207, 1334)},
    {'id': 'SC-11-structure-MeasurementStarted', 'group': 'structural_a', 'paper_id': 'SC-11', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}), 'remaining': ('Supportや被覆達成とは数えない。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2508, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2508, 2664), 'legacy_paper_lines': (940, 1334, 1364)},
    {'id': 'SC-11-structure-MeasurementEnded', 'group': 'structural_a', 'paper_id': 'SC-11', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}), 'remaining': ('Supportや被覆達成とは数えない。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2508, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2508, 2664), 'legacy_paper_lines': (940, 1334, 1364)},
    {'id': 'SC-12-structure-Monitored', 'group': 'structural_a', 'paper_id': 'SC-12', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'k保存→EIと保存証拠（局所構造）', 'goals': ({'id': 'evidence', 'text': '事前宣言した証拠slotの保存'}, {'id': 'actual', 'text': '保存証拠とは独立した実EI出来事'}), 'remaining': ('Supportや被覆達成とは数えない。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2508, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2508, 2664), 'legacy_paper_lines': (941, 1334, 1364)},
    {'id': 'SC-15-structure-Wr-no-stop', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→Wr入場→Unknown Post、後着値あり', 'goals': ({'id': 'unknown-held', 'text': 'Unknown原本の時点で占有を保持'}, {'id': 'late-saved', 'text': 'Unknownと後着値の受信保存'}), 'remaining': ('T/種類別後続・r同着対照は未確認。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2519, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2519, 2664), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-15-structure-Wr-stop', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→Wr入場→Unknown Post、後着値あり', 'goals': ({'id': 'unknown-held', 'text': 'Unknown原本の時点で占有を保持'}, {'id': 'late-saved', 'text': 'Unknownと後着値の受信保存'}), 'remaining': ('T/種類別後続・r同着対照は未確認。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 2519, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2519, 2664), 'legacy_paper_lines': (944, 1366)},
    {'id': 'SC-21-structure-Q-R-P-C', 'group': 'structural_a', 'paper_id': 'SC-21', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'IQ→局所Q/R/P/時計/C（合法IC未確認）', 'goals': ({'id': 'completed', 'text': '同じQ/R/PからCを1件保存'},), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。', '他の縦接続は未実行。'), 'source': {'path': 'tests/fb_scenes.py', 'first': 2524, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2524, 2664), 'legacy_paper_lines': (950, 1369)},
    {'id': 'SC-05-PARENT-structure-positive', 'group': 'structural_a', 'paper_id': 'SC-05-PARENT', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': '局所Q/R/P/Cの親対照', 'goals': ({'id': 'parents', 'text': 'R/PはPredictionを親にせず保存済みQを親に持つ'},), 'remaining': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。', '負のPrediction親候補は未実行。'), 'source': {'path': 'tests/fb_scenes.py', 'first': 2528, 'last': 2664, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2528, 2664), 'legacy_paper_lines': (1383, 1341)},
    {'id': 'SC-03-M3-initial-precommit', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-initial-body-lost', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-initial-entry-lost', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-candidate-precommit', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-candidate-body-lost', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-candidate-entry-lost', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-evaluation-precommit', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-evaluation-body-lost', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-03-M3-evaluation-entry-lost', 'group': 'structural_a', 'paper_id': 'SC-03', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'fault', 'text': '指定slotの保存障害と再建'}, {'id': 'saved', 'text': '同じ準備から対象slot保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3110, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3110), 'legacy_paper_lines': (937, 1931, 1933, 1935, 1979)},
    {'id': 'SC-04-M3-Qgen-Wg', 'group': 'structural_a', 'paper_id': 'SC-04', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'publish', 'text': 'Qgen未保存でWgとrun所有が同じ歩に成立'}, {'id': 'entered', 'text': 'Qgen保存後Wgが開始'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3114, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3114), 'legacy_paper_lines': (938, 1930, 1932, 1941)},
    {'id': 'SC-04-M3-EQ-Ep', 'group': 'structural_a', 'paper_id': 'SC-04', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'publish', 'text': 'EQ未保存でEpとrun所有が同じ歩に成立'}, {'id': 'entered', 'text': 'EQ保存後にEpが開始'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3117, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3117), 'legacy_paper_lines': (938, 1935, 1946)},
    {'id': 'SC-09-M3-generation-evaluation', 'group': 'structural_a', 'paper_id': 'SC-09', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'linked', 'text': 'Qgen・実生成・CG全内容・EQの参照対応'}, {'id': 'no-pG', 'text': '成功と保存待ちだけではpGを作らない'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3121, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3121), 'legacy_paper_lines': (944, 1931, 1933, 1935, 1951, 1959)},
    {'id': 'SC-09-M3-context-missing', 'group': 'structural_a', 'paper_id': 'SC-09', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'waiting', 'text': 'CG保存後もissue[EQ]を実保持しEQは未発行'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3125, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3125), 'legacy_paper_lines': (1937, 1946, 1956, 1959)},
    {'id': 'SC-09-M3-context-save-wait', 'group': 'structural_a', 'paper_id': 'SC-09', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'waiting', 'text': 'CG保存後もissue[EQ]を実保持しEQは未発行'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3125, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3125), 'legacy_paper_lines': (1937, 1946, 1956, 1959)},
    {'id': 'SC-09-M3-pG-after-EQ', 'group': 'structural_a', 'paper_id': 'SC-09', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'waiting', 'text': '不足中にissue[EQ]とpGを保持'}, {'id': 'retained', 'text': 'EQ後も同じ起源pGは未達で保持'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3128, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3128), 'legacy_paper_lines': (1937, 1946, 1959)},
    {'id': 'SC-15-M3-no-candidates', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'terminal', 'text': '指定の最初のTを保存しCG/EQを作らずpGを保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3134, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3134), 'legacy_paper_lines': (950, 1952, 1953, 1954)},
    {'id': 'SC-15-M3-failure', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'terminal', 'text': '指定の最初のTを保存しCG/EQを作らずpGを保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3134, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3134), 'legacy_paper_lines': (950, 1952, 1953, 1954)},
    {'id': 'SC-15-M3-unknown', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'terminal', 'text': '指定の最初のTを保存しCG/EQを作らずpGを保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3134, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3134), 'legacy_paper_lines': (950, 1952, 1953, 1954)},
    {'id': 'SC-15-M3-evidence-before-end', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'pending', 'text': '未配送でrun保持、T/handle/pGを先取りしない'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3137, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3137), 'legacy_paper_lines': (1955, 1959)},
    {'id': 'SC-10-M3-generator-exchange', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'rejected', 'text': '全返答/固定要求と違うCGを公開入口が拒む'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3162, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3162), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-generator-redelivery', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'full-output', 'text': '返答の候補順/測度を含む全内容をCGへ保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3162, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3162), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-input-view-exchange', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'rejected', 'text': '全返答/固定要求と違うCGを公開入口が拒む'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3162, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3162), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-input-view-redelivery', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'full-output', 'text': '返答の候補順/測度を含む全内容をCGへ保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3162, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3162), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-candidate-order-exchange', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'negative-control', 'text': '実返答を保ちCGの一欄だけ交換して保存'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3151, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3145, 3151), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-candidate-order-redelivery', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'full-output', 'text': '返答の候補順/測度を含む全内容をCGへ保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3162, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3162), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-measure-exchange', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'negative-control', 'text': '実返答を保ちCGの一欄だけ交換して保存'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3151, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3145, 3151), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-10-M3-measure-redelivery', 'group': 'structural_a', 'paper_id': 'SC-10', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'full-output', 'text': '返答の候補順/測度を含む全内容をCGへ保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3162, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3162), 'legacy_paper_lines': (945, 1933, 1961)},
    {'id': 'SC-13-M3-Hung-cap1', 'group': 'structural_a', 'paper_id': 'SC-13', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'held', 'text': 'Wg Hungの占有を保持したまま受信保存'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3164, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3164), 'legacy_paper_lines': (948, 1932)},
    {'id': 'SC-13-M3-Hung-cap2', 'group': 'structural_a', 'paper_id': 'SC-13', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'held', 'text': 'Wg Hungの占有を保持したまま受信保存'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3164, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3164), 'legacy_paper_lines': (948, 1932)},
    {'id': 'SC-14-M3-occupation', 'group': 'structural_a', 'paper_id': 'SC-14', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'held', 'text': 'Wgの実占有1が停止未確認で保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3167, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3167), 'legacy_paper_lines': (949, 1932)},
    {'id': 'SC-15-M3-stop-false', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'held-or-release', 'text': 'Unknownは解放の根拠でなく実停止時だけ解放'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3170, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3170), 'legacy_paper_lines': (950, 1954)},
    {'id': 'SC-15-M3-stop-true', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'held-or-release', 'text': 'Unknownは解放の根拠でなく実停止時だけ解放'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3170, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3170), 'legacy_paper_lines': (950, 1954)},
    {'id': 'SC-16-M3-unknown-late-value', 'group': 'structural_a', 'paper_id': 'SC-16', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'first', 'text': '後着値でも最初のUnknownとpGを維持'}, {'id': 'late-saved', 'text': '後着を含む2報告を保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3173, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3173), 'legacy_paper_lines': (951, 1954)},
    {'id': 'SC-16-M3-unknown-A-B', 'group': 'structural_a', 'paper_id': 'SC-16', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'first', 'text': 'Unknown/A/Bの全報告保存後も最初のTとpGを保持'}, {'id': 'reports', 'text': 'Unknown/A/Bの3件を保存'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3177, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3177), 'legacy_paper_lines': (951, 1954, 1957)},
    {'id': 'SC-17-M3-A-A-B', 'group': 'structural_a', 'paper_id': 'SC-17', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'reports', 'text': '同値再配送と異値を含む3報告を保存'}, {'id': 'conflict', 'text': '既存CG/Tを保ちConflictで新EQを止める'}), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3181, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3181), 'legacy_paper_lines': (952, 1957)},
    {'id': 'SC-18-M3-upstream-Conflict', 'group': 'structural_a', 'paper_id': 'SC-18', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'kept', 'text': 'Ep確保・起動後の上流Conflictで入場を止め既存EQ/CG/Tを保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3187, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3187), 'legacy_paper_lines': (953, 1957)},
    {'id': 'SC-20-M3-empty', 'group': 'structural_a', 'paper_id': 'SC-20', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'empty', 'text': 'initial=NoneでWg/Epゼロ、受信2件と区間の責務を保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3191, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3191), 'legacy_paper_lines': (955, 1930)},
    {'id': 'SC-21-M3-receive-during-generation', 'group': 'structural_a', 'paper_id': 'SC-21', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'receive', 'text': 'Wg進行中のReceivedを保存し生成用の固定像を保持'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3195, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3195), 'legacy_paper_lines': (956, 1932)},
    {'id': 'SC-21-M3-update-during-generation', 'group': 'structural_a', 'paper_id': 'SC-21', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'update', 'text': 'Wgの固定像/占有を残したまま受信由来の新Q/更新を開始'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3198, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3198), 'legacy_paper_lines': (943, 956, 1932)},
    {'id': 'SC-09-M3-D6-generation-draw', 'group': 'structural_a', 'paper_id': 'SC-09', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から公開操作の全前置履歴', 'goals': ({'id': 'R10', 'text': '生成用のくじはMissingContract、R10未接続'},), 'remaining': ('局所保存の探索。前置の別順序・後続の評価/抽選/選択・全体進行性は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3099, 'last': 3210, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3099, 3210), 'legacy_paper_lines': (1936, 2017)},
    {'id': 'SC-15-M4-D-workfinished', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から宣言Dの終端境界まで', 'goals': ({'id': 'terminal-shape', 'text': 'I-8のみ終端。Failureが先ならT(Failure)を保持'},), 'remaining': ('終わりの外形/保存/順序の構造だけ。合法PRの数学とDF/DU/Eeの全接続は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3256, 'last': 3256, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3256,), 'legacy_paper_lines': (787, 950, 951, 952, 1967, 1969)},
    {'id': 'SC-15-M4-D-failure', 'group': 'structural_a', 'paper_id': 'SC-15', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から宣言Dの終端境界まで', 'goals': ({'id': 'terminal-shape', 'text': 'I-8のみ終端。Failureが先ならT(Failure)を保持'},), 'remaining': ('終わりの外形/保存/順序の構造だけ。合法PRの数学とDF/DU/Eeの全接続は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3256, 'last': 3256, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3256,), 'legacy_paper_lines': (787, 950, 951, 952, 1967, 1969)},
    {'id': 'SC-16-M4-D-failure-unknown', 'group': 'structural_a', 'paper_id': 'SC-16', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から宣言Dの終端境界まで', 'goals': ({'id': 'terminal-shape', 'text': 'I-8のみ終端。Failureが先ならT(Failure)を保持'},), 'remaining': ('終わりの外形/保存/順序の構造だけ。合法PRの数学とDF/DU/Eeの全接続は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3256, 'last': 3256, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3256,), 'legacy_paper_lines': (787, 950, 951, 952, 1967, 1969)},
    {'id': 'SC-17-M4-D-late-workfinished', 'group': 'structural_a', 'paper_id': 'SC-17', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'initial': 'I0から宣言Dの終端境界まで', 'goals': ({'id': 'terminal-shape', 'text': 'I-8のみ終端。Failureが先ならT(Failure)を保持'},), 'remaining': ('終わりの外形/保存/順序の構造だけ。合法PRの数学とDF/DU/Eeの全接続は未検証。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3256, 'last': 3256, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3256,), 'legacy_paper_lines': (787, 950, 951, 952, 1967, 1969)},
    {'id': 'INV-7.b', 'group': 'mutant_outside', 'paper_id': 'INV-7.b', 'source': {'path': 'tests/fb_mutants.py', 'first': 36, 'last': 36, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': '範囲外 (実装の段へ): enter-after-conflict proposal retained for the implementation stage', 'nearest_legal': 'legal IC/IG/IA and UseDeps correspondence require the real F-a boundary', 'scene': 'all 16 SC-18 branches have E0=None and are implementation-stage'},
    {'id': 'INV-9.b', 'group': 'mutant_outside', 'paper_id': 'INV-9.b', 'source': {'path': 'tests/fb_mutants.py', 'first': 41, 'last': 41, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': 'Adopt after previous_result no longer matches current adoption', 'nearest_legal': 'Stale, no adoption; real legal IA is implementation-stage', 'scene': 'SC-07a'},
    {'id': 'INV-12.a', 'group': 'mutant_outside', 'paper_id': 'INV-12.a', 'source': {'path': 'tests/fb_mutants.py', 'first': 47, 'last': 47, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': 'treat Started alone as positive coverage', 'nearest_legal': 'Started contributes no covered cells; Support meaning implementation-stage', 'scene': 'SC-12-started-only'},
    {'id': 'INV-14.a', 'group': 'mutant_outside', 'paper_id': 'INV-14.a', 'source': {'path': 'tests/fb_mutants.py', 'first': 51, 'last': 51, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': 'enter same Draw request body twice', 'nearest_legal': 'one request, one entry; real IE/ID legality implementation-stage', 'scene': 'minimal declared D'},
    {'id': 'INV-14.b', 'group': 'mutant_outside', 'paper_id': 'INV-14.b', 'source': {'path': 'tests/fb_mutants.py', 'first': 52, 'last': 52, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': 'reissue same Draw after Unknown', 'nearest_legal': 'retain unknown; no redraw; numerical refinement implementation-stage', 'scene': 'minimal declared D Unknown'},
    {'id': 'INV-16.a', 'group': 'mutant_outside', 'paper_id': 'INV-16.a', 'source': {'path': 'tests/fb_mutants.py', 'first': 55, 'last': 55, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': 'publish selection for NoDecision', 'nearest_legal': 'save terminal only; authenticated Selected implementation-stage', 'scene': 'SC-09 structural evaluation'},
    {'id': 'INV-16.b', 'group': 'mutant_outside', 'paper_id': 'INV-16.b', 'source': {'path': 'tests/fb_mutants.py', 'first': 56, 'last': 56, 'read_scope': '該当部分: 母集団表/範囲外の説明だけ'}, 'proposal': 'substitute another problem in selection', 'nearest_legal': 'same EQ/PR/Draw/artifact; real artifact closure implementation-stage', 'scene': 'SC-10'},
    {'id': 'SC-04-publish-PR-D', 'group': 'nested_scene_b', 'paper_id': 'SC-04', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IEのFProblem/Draw/artifactの数値的な生成・全閉包を実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。', 'implementation_scope': ('範囲外 (実装の段へ): IEのFProblem/Draw/artifactの数値的な生成・全閉包を実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。',), 'initial': 'IE', 'goals': ({'id': 'paper-required', 'text': 'Publish直後で依存未保存かつ仕事行あり、保存後開始、二重列挙、二重起動包み'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 2602, 'last': 2628, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2602, 2628), 'legacy_paper_lines': (932, 1361, 1332, 1333, 1509)},
    {'id': 'SC-04-publish-DF-Ee', 'group': 'nested_scene_b', 'paper_id': 'SC-04', 'scope_class': 'b', 'scope_reason': '範囲外 (実装の段へ): IDのFProblem/Draw/artifactの数値的な生成・全閉包を実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。', 'implementation_scope': ('範囲外 (実装の段へ): IDのFProblem/Draw/artifactの数値的な生成・全閉包を実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。',), 'initial': 'ID', 'goals': ({'id': 'paper-required', 'text': 'Publish直後で依存未保存かつ仕事行あり、保存後開始、二重列挙、二重起動包み'},), 'remaining': (), 'source': {'path': 'tests/fb_scenes.py', 'first': 2602, 'last': 2628, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (2602, 2628), 'legacy_paper_lines': (932, 1361, 1332, 1333, 1509)},
    {'id': 'SC-14-M3-Hung-D-cap1', 'group': 'additional_unconnected_a', 'paper_id': 'SC-14', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': (), 'initial': 'IT(Wg)+PR Saved', 'goals': ({'id': 'capacity', 'text': 'Wg占有とDの開始/資源待ち'},), 'remaining': ('未接続: Wg Hungと合法なPR→Dの席1の接続。現行の構造的artifact口では合法FProblem/PRの全対応を確かめられない。Wg単独の占有をこの対照の合格へ流用しない。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3206, 'last': 3206, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3206,), 'legacy_paper_lines': (949, 1932, 1979)},
    {'id': 'SC-14-M3-Hung-D-cap2', 'group': 'additional_unconnected_a', 'paper_id': 'SC-14', 'scope_class': 'a', 'scope_reason': '紙の構造を模型で確かめる。', 'implementation_scope': (), 'initial': 'IT(Wg)+PR Saved', 'goals': ({'id': 'capacity', 'text': 'Wg占有とDの開始/資源待ち'},), 'remaining': ('未接続: Wg Hungと合法なPR→Dの席2の接続。現行の構造的artifact口では合法FProblem/PRの全対応を確かめられない。Wg単独の占有をこの対照の合格へ流用しない。',), 'source': {'path': 'tests/fb_scenes.py', 'first': 3206, 'last': 3206, 'read_scope': '該当部分: 宣言組立のメタデータだけ; E0生成/模型import/実行なし'}, 'declaration_lines': (3206,), 'legacy_paper_lines': (949, 1932, 1979)},
)
BRIDGES = (
    {'id': 'BR.structural_a.SC-05', 'source_id': 'SC-05', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-06-Success', 'source_id': 'SC-06-Success', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-Success', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-06-Rejected', 'source_id': 'SC-06-Rejected', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-Rejected', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-06-Insufficient', 'source_id': 'SC-06-Insufficient', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-Insufficient', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-06-Unknown', 'source_id': 'SC-06-Unknown', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-Unknown', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-06-wrong-target', 'source_id': 'SC-06-wrong-target', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-wrong-target', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-07a-q1-first', 'source_id': 'SC-07a-q1-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.stale', 'T.stale', 'T.adopted.previous', 'T.finite_update1.previous_result', 'T.rel.numeric_update2', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験', '変異'), 'recipes': ('stale', 'verify'), 'branch_constraint': 'SC-07a-q1-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-07a-q2-first', 'source_id': 'SC-07a-q2-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.stale', 'T.stale', 'T.adopted.previous', 'T.finite_update1.previous_result', 'T.rel.numeric_update2', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験', '変異'), 'recipes': ('stale', 'verify'), 'branch_constraint': 'SC-07a-q2-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-07b-sequential', 'source_id': 'SC-07b-sequential', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.stale', 'T.stale', 'T.adopted.previous', 'T.finite_update1.previous_result', 'T.rel.numeric_update2', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験', '変異'), 'recipes': ('stale', 'verify'), 'branch_constraint': 'SC-07b-sequential', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-07b-readopt', 'source_id': 'SC-07b-readopt', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.stale', 'T.stale', 'T.adopted.previous', 'T.finite_update1.previous_result', 'T.rel.numeric_update2', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験', '変異'), 'recipes': ('stale', 'verify'), 'branch_constraint': 'SC-07b-readopt', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-e1-only', 'source_id': 'SC-08-e1-only', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-e1-only', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-e2-only', 'source_id': 'SC-08-e2-only', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-e2-only', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-group', 'source_id': 'SC-08-group', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-group', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-no-group', 'source_id': 'SC-08-no-group', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-no-group', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-other-trigger-slot', 'source_id': 'SC-08-other-trigger-slot', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-other-trigger-slot', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-conflict-N', 'source_id': 'SC-08-conflict-N', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-conflict-N', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-08-conflict-P', 'source_id': 'SC-08-conflict-P', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-conflict-P', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-09-FProblem-Selected', 'source_id': 'SC-09-FProblem-Selected', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.evaluated.branch.Selected', 'T.selection', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-09-FProblem-Selected', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-09-FProblem-NoDecision', 'source_id': 'SC-09-FProblem-NoDecision', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.evaluated.branch.NoDecision', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-09-FProblem-NoDecision', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-09-Ep-NoDecision', 'source_id': 'SC-09-Ep-NoDecision', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.prepared.branch.NoDecision', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-09-Ep-NoDecision', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-10-problem_key', 'source_id': 'SC-10-problem_key', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.math_problem.problem_key', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-10-problem_key', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-10-purpose', 'source_id': 'SC-10-purpose', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.draw_fact.request.purpose', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-10-purpose', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-10-draw-point', 'source_id': 'SC-10-draw-point', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.math_root.draw_point', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-10-draw-point', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-10-artifact', 'source_id': 'SC-10-artifact', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.artifact', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-10-artifact', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-Frame', 'source_id': 'SC-11-Frame', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.frame', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Frame', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-11-Started', 'source_id': 'SC-11-Started', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.segment.Started', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Started', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-11-Ended', 'source_id': 'SC-11-Ended', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.segment.Ended', 'T.rel.segment_end', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Ended', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-RouteApplied', 'source_id': 'SC-11-RouteApplied', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.route_applied', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-RouteApplied', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-Gap', 'source_id': 'SC-11-Gap', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.gap', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Gap', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-Unavailable', 'source_id': 'SC-11-Unavailable', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.measurement_unavailable', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Unavailable', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-Claim', 'source_id': 'SC-11-Claim', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.claim', 'T.rel.coverage', 'T.rel.measurement', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Claim', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-Unproved', 'source_id': 'SC-11-Unproved', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.unproved', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-Unproved', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-report-before-start', 'source_id': 'SC-11-report-before-start', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.segment_report', 'T.segment.Started', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-report-before-start', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-same-seq-other-id', 'source_id': 'SC-11-same-seq-other-id', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.measurement_id', 'T.frame.sample_seq', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-same-seq-other-id', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-same-content-other-slot', 'source_id': 'SC-11-same-content-other-slot', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.segment_report.item_slot', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-same-content-other-slot', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-end-equals-r', 'source_id': 'SC-11-end-equals-r', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.interval.end_ns', 'T.envelope.received_ns', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-end-equals-r', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-end-after-r', 'source_id': 'SC-11-end-after-r', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.interval.end_ns', 'T.envelope.received_ns', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-end-after-r', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-open-closed-neighbor', 'source_id': 'SC-11-open-closed-neighbor', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.interval.closure', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-open-closed-neighbor', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-actual-time-unavailable', 'source_id': 'SC-11-actual-time-unavailable', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.frame.actual_time', 'T.unavailable', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-actual-time-unavailable', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-claim-window', 'source_id': 'SC-11-claim-window', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.claim', 'T.interval', 'T.rel.coverage', 'T.rel.measurement', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-claim-window', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-claim-generation', 'source_id': 'SC-11-claim-generation', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.claim', 'T.rel.coverage', 'T.rel.measurement', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-claim-generation', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-unknown-kind', 'source_id': 'SC-11-unknown-kind', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.shape', 'T.coverage', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-unknown-kind', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-future-unproved', 'source_id': 'SC-11-future-unproved', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.unproved', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-future-unproved', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-evidence-outside-X', 'source_id': 'SC-11-evidence-outside-X', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-evidence-outside-X', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-12-positive-claim', 'source_id': 'SC-12-positive-claim', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.claim', 'T.rel.coverage', 'T.rel.measurement', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-positive-claim', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-12-started-only', 'source_id': 'SC-12-started-only', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.segment.Started', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-started-only', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-12-ended-only', 'source_id': 'SC-12-ended-only', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.segment.Ended', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-ended-only', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-12-Gap', 'source_id': 'SC-12-Gap', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.gap', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-Gap', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-12-Unavailable', 'source_id': 'SC-12-Unavailable', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.measurement_unavailable', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-Unavailable', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-12-partial-report', 'source_id': 'SC-12-partial-report', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-partial-report', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-12-evidence-wait', 'source_id': 'SC-12-evidence-wait', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.waiting', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-evidence-wait', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-13-measure-report', 'source_id': 'SC-13-measure-report', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.independence', 'T.rel.receipt', 'T.rel.resource', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '新しい試験', '固定値', '変異'), 'recipes': ('independence', 'coverage'), 'branch_constraint': 'SC-13-measure-report', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-14-capacity1', 'source_id': 'SC-14-capacity1', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.draw', 'T.prepared', 'T.artifact', 'T.rel.independence'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('capacity',), 'branch_constraint': 'SC-14-capacity1', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-14-capacity2', 'source_id': 'SC-14-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.draw', 'T.prepared', 'T.artifact', 'T.rel.independence'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('capacity',), 'branch_constraint': 'SC-14-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wr-stop', 'source_id': 'SC-15-Wr-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wr-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wr-no-stop', 'source_id': 'SC-15-Wr-no-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wr-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wr-lost-reply-capacity2', 'source_id': 'SC-15-Wr-lost-reply-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wr-lost-reply-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-Wr-tie-unknown-first', 'source_id': 'SC-15-Wr-tie-unknown-first', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wr-tie-unknown-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-Wr-tie-value-first', 'source_id': 'SC-15-Wr-tie-value-first', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wr-tie-value-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-16-Wr-Unknown-A-B', 'source_id': 'SC-16-Wr-Unknown-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'update'), 'branch_constraint': 'SC-16-Wr-Unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wp-stop', 'source_id': 'SC-15-Wp-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wp-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wp-no-stop', 'source_id': 'SC-15-Wp-no-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wp-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wp-lost-reply-capacity2', 'source_id': 'SC-15-Wp-lost-reply-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wp-lost-reply-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-Wp-tie-unknown-first', 'source_id': 'SC-15-Wp-tie-unknown-first', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wp-tie-unknown-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-Wp-tie-value-first', 'source_id': 'SC-15-Wp-tie-value-first', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-Wp-tie-value-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-16-Wp-Unknown-A-B', 'source_id': 'SC-16-Wp-Unknown-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'update'), 'branch_constraint': 'SC-16-Wp-Unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wv-stop', 'source_id': 'SC-15-Wv-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'verify'), 'branch_constraint': 'SC-15-Wv-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wv-no-stop', 'source_id': 'SC-15-Wv-no-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'verify'), 'branch_constraint': 'SC-15-Wv-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Wv-lost-reply-capacity2', 'source_id': 'SC-15-Wv-lost-reply-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'verify'), 'branch_constraint': 'SC-15-Wv-lost-reply-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-Wv-tie-unknown-first', 'source_id': 'SC-15-Wv-tie-unknown-first', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'verify'), 'branch_constraint': 'SC-15-Wv-tie-unknown-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-Wv-tie-value-first', 'source_id': 'SC-15-Wv-tie-value-first', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'verify'), 'branch_constraint': 'SC-15-Wv-tie-value-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-16-Wv-Unknown-A-B', 'source_id': 'SC-16-Wv-Unknown-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'verify'), 'branch_constraint': 'SC-16-Wv-Unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ep-stop', 'source_id': 'SC-15-Ep-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ep-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ep-no-stop', 'source_id': 'SC-15-Ep-no-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ep-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ep-lost-reply-capacity2', 'source_id': 'SC-15-Ep-lost-reply-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ep-lost-reply-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ep-tie-unknown-first', 'source_id': 'SC-15-Ep-tie-unknown-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ep-tie-unknown-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Epの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ep-tie-value-first', 'source_id': 'SC-15-Ep-tie-value-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ep-tie-value-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Epの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-16-Ep-Unknown-A-B', 'source_id': 'SC-16-Ep-Unknown-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'evaluation'), 'branch_constraint': 'SC-16-Ep-Unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-D-stop', 'source_id': 'SC-15-D-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'draw'), 'branch_constraint': 'SC-15-D-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-D-no-stop', 'source_id': 'SC-15-D-no-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'draw'), 'branch_constraint': 'SC-15-D-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-D-lost-reply-capacity2', 'source_id': 'SC-15-D-lost-reply-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'draw'), 'branch_constraint': 'SC-15-D-lost-reply-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-D-tie-unknown-first', 'source_id': 'SC-15-D-tie-unknown-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'draw'), 'branch_constraint': 'SC-15-D-tie-unknown-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Dの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-D-tie-value-first', 'source_id': 'SC-15-D-tie-value-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'draw'), 'branch_constraint': 'SC-15-D-tie-value-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Dの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-16-D-Unknown-A-B', 'source_id': 'SC-16-D-Unknown-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'draw'), 'branch_constraint': 'SC-16-D-Unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ee-stop', 'source_id': 'SC-15-Ee-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ee-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ee-no-stop', 'source_id': 'SC-15-Ee-no-stop', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ee-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ee-lost-reply-capacity2', 'source_id': 'SC-15-Ee-lost-reply-capacity2', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ee-lost-reply-capacity2', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ee-tie-unknown-first', 'source_id': 'SC-15-Ee-tie-unknown-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ee-tie-unknown-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Eeの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-Ee-tie-value-first', 'source_id': 'SC-15-Ee-tie-value-first', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'evaluation'), 'branch_constraint': 'SC-15-Ee-tie-value-first', 'scope_to_preserve': ('範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。Eeの元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-16-Ee-Unknown-A-B', 'source_id': 'SC-16-Ee-Unknown-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'evaluation'), 'branch_constraint': 'SC-16-Ee-Unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-17-Wr-A-A-B', 'source_id': 'SC-17-Wr-A-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'update'), 'branch_constraint': 'SC-17-Wr-A-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-17-Wp-A-A-B', 'source_id': 'SC-17-Wp-A-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'update'), 'branch_constraint': 'SC-17-Wp-A-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-17-D-A-A-B', 'source_id': 'SC-17-D-A-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'draw'), 'branch_constraint': 'SC-17-D-A-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-17-interval-slot-A-A-B', 'source_id': 'SC-17-interval-slot-A-A-B', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'coverage'), 'branch_constraint': 'SC-17-interval-slot-A-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wr-Wp-pre-publish', 'source_id': 'SC-18-Wr-Wp-pre-publish', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wr-Wp-pre-publish', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wr-Wp-published-unprepared', 'source_id': 'SC-18-Wr-Wp-published-unprepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wr-Wp-published-unprepared', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wr-Wp-prepared', 'source_id': 'SC-18-Wr-Wp-prepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wr-Wp-prepared', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wr-Wp-launched-not-entered', 'source_id': 'SC-18-Wr-Wp-launched-not-entered', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wr-Wp-launched-not-entered', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wp-acquire-pre-publish', 'source_id': 'SC-18-Wp-acquire-pre-publish', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wp-acquire-pre-publish', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wp-acquire-published-unprepared', 'source_id': 'SC-18-Wp-acquire-published-unprepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wp-acquire-published-unprepared', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wp-acquire-prepared', 'source_id': 'SC-18-Wp-acquire-prepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wp-acquire-prepared', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Wp-acquire-launched-not-entered', 'source_id': 'SC-18-Wp-acquire-launched-not-entered', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update'), 'branch_constraint': 'SC-18-Wp-acquire-launched-not-entered', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Ep-D-pre-publish', 'source_id': 'SC-18-Ep-D-pre-publish', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-Ep-D-pre-publish', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Ep-D-published-unprepared', 'source_id': 'SC-18-Ep-D-published-unprepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-Ep-D-published-unprepared', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Ep-D-prepared', 'source_id': 'SC-18-Ep-D-prepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-Ep-D-prepared', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-Ep-D-launched-not-entered', 'source_id': 'SC-18-Ep-D-launched-not-entered', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-Ep-D-launched-not-entered', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-D-Ee-pre-publish', 'source_id': 'SC-18-D-Ee-pre-publish', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-D-Ee-pre-publish', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-D-Ee-published-unprepared', 'source_id': 'SC-18-D-Ee-published-unprepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-D-Ee-published-unprepared', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-D-Ee-prepared', 'source_id': 'SC-18-D-Ee-prepared', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-D-Ee-prepared', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-18-D-Ee-launched-not-entered', 'source_id': 'SC-18-D-Ee-launched-not-entered', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'evaluation', 'draw'), 'branch_constraint': 'SC-18-D-Ee-launched-not-entered', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-21-interval-receipt-Q', 'source_id': 'SC-21-interval-receipt-Q', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験', '変異'), 'recipes': ('derive', 'coverage'), 'branch_constraint': 'SC-21-interval-receipt-Q', 'scope_to_preserve': ('範囲外 (実装の段へ): /2数値射影・生成契約別閉包を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-21-Q-R-P-C', 'source_id': 'SC-21-Q-R-P-C', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-21-Q-R-P-C', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-21-acquire-verify-adopt', 'source_id': 'SC-21-acquire-verify-adopt', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-21-acquire-verify-adopt', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-21-Ep-D-Ee-selection', 'source_id': 'SC-21-Ep-D-Ee-selection', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation', 'draw'), 'branch_constraint': 'SC-21-Ep-D-Ee-selection', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-21-evaluation-hung-receive-update', 'source_id': 'SC-21-evaluation-hung-receive-update', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root', 'T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.draw_unknown', 'T.terminal', 'T.rel.independence', 'T.rel.receipt', 'T.rel.resource', 'T.rel.coverage', 'T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation', 'draw', 'independence', 'derive'), 'branch_constraint': 'SC-21-evaluation-hung-receive-update', 'scope_to_preserve': ('範囲外 (実装の段へ): IE/ID・artifact全閉包・FProblem/Drawの数値対応を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-PARENT', 'source_id': 'SC-05-PARENT', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-PARENT', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-COMPLETE', 'source_id': 'SC-05-COMPLETE', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-COMPLETE', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-06-ANCESTOR', 'source_id': 'SC-06-ANCESTOR', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-ANCESTOR', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-FAMILY', 'source_id': 'SC-11-FAMILY', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.gap', 'T.measurement_unavailable', 'T.rel.conflict_use', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-FAMILY', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-17-FAMILY', 'source_id': 'SC-17-FAMILY', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'conflict', 'coverage'), 'branch_constraint': 'SC-17-FAMILY', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-11-CROSS-M', 'source_id': 'SC-11-CROSS-M', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.measurement_id', 'T.frame', 'T.rel.conflict_use', 'T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-CROSS-M', 'scope_to_preserve': ('範囲外 (実装の段へ): 区間のcontract別Supportと実測・生成の意味を実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-WP-VERIFY-Wp-Failure', 'source_id': 'SC-15-WP-VERIFY-Wp-Failure', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-WP-VERIFY-Wp-Failure', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-WP-VERIFY-Wp-Unknown', 'source_id': 'SC-15-WP-VERIFY-Wp-Unknown', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-WP-VERIFY-Wp-Unknown', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.scene_b.SC-15-WP-VERIFY-Wv-Insufficient', 'source_id': 'SC-15-WP-VERIFY-Wv-Insufficient', 'group': 'scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'verify'), 'branch_constraint': 'SC-15-WP-VERIFY-Wv-Insufficient', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさを実装の段でF-aの実物に繋いで確かめる。紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-structure-r-published', 'source_id': 'SC-05-structure-r-published', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-structure-r-published', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-structure-p-published', 'source_id': 'SC-05-structure-p-published', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-structure-p-published', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-structure-p-saved', 'source_id': 'SC-05-structure-p-saved', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-structure-p-saved', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-structure-p-clocks-saved', 'source_id': 'SC-05-structure-p-clocks-saved', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-structure-p-clocks-saved', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-06-structure-acquire', 'source_id': 'SC-06-structure-acquire', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-structure-acquire', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-06-structure-verification-pending', 'source_id': 'SC-06-structure-verification-pending', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-structure-verification-pending', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-06-structure-verification-adopt', 'source_id': 'SC-06-structure-verification-adopt', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-06-structure-verification-adopt', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-08-structure-e1-then-other', 'source_id': 'SC-08-structure-e1-then-other', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-structure-e1-then-other', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-08-structure-e2-then-other', 'source_id': 'SC-08-structure-e2-then-other', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('derive',), 'branch_constraint': 'SC-08-structure-e2-then-other', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-09-structure-artifact-port', 'source_id': 'SC-09-structure-artifact-port', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'SC-09-structure-artifact-port', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-12-structure-measure-row', 'source_id': 'SC-12-structure-measure-row', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-structure-measure-row', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-11-structure-MeasurementStarted', 'source_id': 'SC-11-structure-MeasurementStarted', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-structure-MeasurementStarted', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-11-structure-MeasurementEnded', 'source_id': 'SC-11-structure-MeasurementEnded', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-11-structure-MeasurementEnded', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-12-structure-Monitored', 'source_id': 'SC-12-structure-Monitored', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'SC-12-structure-Monitored', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-structure-Wr-no-stop', 'source_id': 'SC-15-structure-Wr-no-stop', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-structure-Wr-no-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-structure-Wr-stop', 'source_id': 'SC-15-structure-Wr-stop', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('terminal', 'update'), 'branch_constraint': 'SC-15-structure-Wr-stop', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-21-structure-Q-R-P-C', 'source_id': 'SC-21-structure-Q-R-P-C', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.acquisition', 'T.rel.verify', 'T.target_certificate', 'T.verification', 'T.adopted', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('verify', 'update'), 'branch_constraint': 'SC-21-structure-Q-R-P-C', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-05-PARENT-structure-positive', 'source_id': 'SC-05-PARENT-structure-positive', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験'), 'recipes': ('update',), 'branch_constraint': 'SC-05-PARENT-structure-positive', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01',), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-initial-precommit', 'source_id': 'SC-03-M3-initial-precommit', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-initial-precommit', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-initial-body-lost', 'source_id': 'SC-03-M3-initial-body-lost', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-initial-body-lost', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-initial-entry-lost', 'source_id': 'SC-03-M3-initial-entry-lost', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-initial-entry-lost', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-candidate-precommit', 'source_id': 'SC-03-M3-candidate-precommit', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-candidate-precommit', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-candidate-body-lost', 'source_id': 'SC-03-M3-candidate-body-lost', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-candidate-body-lost', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-candidate-entry-lost', 'source_id': 'SC-03-M3-candidate-entry-lost', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-candidate-entry-lost', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-evaluation-precommit', 'source_id': 'SC-03-M3-evaluation-precommit', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-evaluation-precommit', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-evaluation-body-lost', 'source_id': 'SC-03-M3-evaluation-body-lost', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-evaluation-body-lost', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-03-M3-evaluation-entry-lost', 'source_id': 'SC-03-M3-evaluation-entry-lost', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.storage', 'T.prepared_entry', 'T.rel.rebuild', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-03-M3-evaluation-entry-lost', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-04-M3-Qgen-Wg', 'source_id': 'SC-04-M3-Qgen-Wg', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-04-M3-Qgen-Wg', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-04-M3-EQ-Ep', 'source_id': 'SC-04-M3-EQ-Ep', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-04-M3-EQ-Ep', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-09-M3-generation-evaluation', 'source_id': 'SC-09-M3-generation-evaluation', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-09-M3-generation-evaluation', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-09-M3-context-missing', 'source_id': 'SC-09-M3-context-missing', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-09-M3-context-missing', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-09-M3-context-save-wait', 'source_id': 'SC-09-M3-context-save-wait', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-09-M3-context-save-wait', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-09-M3-pG-after-EQ', 'source_id': 'SC-09-M3-pG-after-EQ', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-09-M3-pG-after-EQ', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M3-no-candidates', 'source_id': 'SC-15-M3-no-candidates', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-15-M3-no-candidates', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M3-failure', 'source_id': 'SC-15-M3-failure', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-15-M3-failure', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M3-unknown', 'source_id': 'SC-15-M3-unknown', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-15-M3-unknown', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M3-evidence-before-end', 'source_id': 'SC-15-M3-evidence-before-end', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-15-M3-evidence-before-end', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-generator-exchange', 'source_id': 'SC-10-M3-generator-exchange', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.qgen.method', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-generator-exchange', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-generator-redelivery', 'source_id': 'SC-10-M3-generator-redelivery', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.qgen.method', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-generator-redelivery', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-input-view-exchange', 'source_id': 'SC-10-M3-input-view-exchange', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.qgen.numerical_view', 'T.eq.numerical_view', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-input-view-exchange', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-input-view-redelivery', 'source_id': 'SC-10-M3-input-view-redelivery', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.qgen.numerical_view', 'T.eq.numerical_view', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-input-view-redelivery', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-candidate-order-exchange', 'source_id': 'SC-10-M3-candidate-order-exchange', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.candidate.input_order[]', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-candidate-order-exchange', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-candidate-order-redelivery', 'source_id': 'SC-10-M3-candidate-order-redelivery', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.candidate.input_order[]', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-candidate-order-redelivery', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-measure-exchange', 'source_id': 'SC-10-M3-measure-exchange', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.candidate.measure', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-measure-exchange', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-10-M3-measure-redelivery', 'source_id': 'SC-10-M3-measure-redelivery', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.candidate.measure', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-10-M3-measure-redelivery', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-13-M3-Hung-cap1', 'source_id': 'SC-13-M3-Hung-cap1', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.independence', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-13-M3-Hung-cap1', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-13-M3-Hung-cap2', 'source_id': 'SC-13-M3-Hung-cap2', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.independence', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-13-M3-Hung-cap2', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-14-M3-occupation', 'source_id': 'SC-14-M3-occupation', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.independence', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-14-M3-occupation', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M3-stop-false', 'source_id': 'SC-15-M3-stop-false', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.independence', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-15-M3-stop-false', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M3-stop-true', 'source_id': 'SC-15-M3-stop-true', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.resource', 'T.rel.independence', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-15-M3-stop-true', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-16-M3-unknown-late-value', 'source_id': 'SC-16-M3-unknown-late-value', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-16-M3-unknown-late-value', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-16-M3-unknown-A-B', 'source_id': 'SC-16-M3-unknown-A-B', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.purpose_part', 'T.rel.transfer', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal'), 'branch_constraint': 'SC-16-M3-unknown-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-17-M3-A-A-B', 'source_id': 'SC-17-M3-A-A-B', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.terminal', 'T.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use', 'T.conflict', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'terminal', 'conflict'), 'branch_constraint': 'SC-17-M3-A-A-B', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-18-M3-upstream-Conflict', 'source_id': 'SC-18-M3-upstream-Conflict', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'conflict'), 'branch_constraint': 'SC-18-M3-upstream-Conflict', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-20-M3-empty', 'source_id': 'SC-20-M3-empty', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.initial_none', 'T.rel.measurement', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-20-M3-empty', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-21-M3-receive-during-generation', 'source_id': 'SC-21-M3-receive-during-generation', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.receipt', 'T.rel.frozen', 'T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation',), 'branch_constraint': 'SC-21-M3-receive-during-generation', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-21-M3-update-during-generation', 'source_id': 'SC-21-M3-update-during-generation', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.declared_derive', 'T.rel.numeric_update2', 'T.received', 'T.request', 'T.rel.owner', 'T.rel.update_stages', 'T.finite_result', 'T.finite_statement', 'T.completed'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'derive', 'update'), 'branch_constraint': 'SC-21-M3-update-during-generation', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-09-M3-D6-generation-draw', 'source_id': 'SC-09-M3-D6-generation-draw', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.external.R10', 'T.generation_draw_request', 'T.generation_draw_unknown', 'T.rel.generation'), 'verification_kinds': ('新しい試験', '固定値'), 'recipes': ('generation_draw',), 'branch_constraint': 'SC-09-M3-D6-generation-draw', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-04',), 'readiness': '未採用', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M4-D-workfinished', 'source_id': 'SC-15-M4-D-workfinished', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.work_finished', 'T.draw_returned', 'T.rel.draw', 'T.draw_fact', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact', 'T.rel.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw', 'terminal'), 'branch_constraint': 'SC-15-M4-D-workfinished', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-15-M4-D-failure', 'source_id': 'SC-15-M4-D-failure', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.work_finished', 'T.draw_returned', 'T.rel.draw', 'T.draw_fact', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact', 'T.rel.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw', 'terminal'), 'branch_constraint': 'SC-15-M4-D-failure', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-16-M4-D-failure-unknown', 'source_id': 'SC-16-M4-D-failure-unknown', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.work_finished', 'T.draw_returned', 'T.rel.draw', 'T.draw_fact', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact', 'T.rel.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw', 'terminal'), 'branch_constraint': 'SC-16-M4-D-failure-unknown', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.structural_a.SC-17-M4-D-late-workfinished', 'source_id': 'SC-17-M4-D-late-workfinished', 'group': 'structural_a', 'disposition': '対応先あり', 'targets': ('T.work_finished', 'T.draw_returned', 'T.rel.draw', 'T.draw_fact', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact', 'T.rel.terminal', 'T.receipt_sequence', 'T.rel.resource', 'T.rel.conflict_use'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw', 'terminal'), 'branch_constraint': 'SC-17-M4-D-late-workfinished', 'scope_to_preserve': ('範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-7.b', 'source_id': 'INV-7.b', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.rel.conflict_use', 'T.conflict', 'T.rel.terminal', 'T.rel.owner', 'T.rel.update_stages', 'T.rel.numeric_update2', 'T.finite_result', 'T.finite_statement', 'T.completed', 'T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '変異', '新しい試験', '固定値'), 'recipes': ('conflict', 'update', 'evaluation'), 'branch_constraint': 'INV-7.b', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-9.b', 'source_id': 'INV-9.b', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.rel.stale', 'T.stale', 'T.adopted.previous', 'T.finite_update1.previous_result', 'T.rel.numeric_update2'), 'verification_kinds': ('F-aの実物の値', '固定値', '新しい試験', '変異'), 'recipes': ('stale',), 'branch_constraint': 'INV-9.b', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-12.a', 'source_id': 'INV-12.a', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.rel.coverage', 'T.rel.measurement', 'T.claim', 'T.interval', 'T.segment_binding'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('coverage',), 'branch_constraint': 'INV-12.a', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-14.a', 'source_id': 'INV-14.a', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw',), 'branch_constraint': 'INV-14.a', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-14.b', 'source_id': 'INV-14.b', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw',), 'branch_constraint': 'INV-14.b', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-16.a', 'source_id': 'INV-16.a', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'INV-16.a', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.mutant_outside.INV-16.b', 'source_id': 'INV-16.b', 'group': 'mutant_outside', 'disposition': '対応先あり', 'targets': ('T.eq', 'T.prepared', 'T.evaluated', 'T.rel.selection', 'T.artifact', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('evaluation',), 'branch_constraint': 'INV-16.b', 'scope_to_preserve': ('母集団表の狙った単一違反と同じ合法前段',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.nested_scene_b.SC-04-publish-PR-D', 'source_id': 'SC-04-publish-PR-D', 'group': 'nested_scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact', 'T.eq', 'T.evaluated', 'T.rel.selection', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw', 'evaluation'), 'branch_constraint': 'SC-04-publish-PR-D', 'scope_to_preserve': ('範囲外 (実装の段へ): IEのFProblem/Draw/artifactの数値的な生成・全閉包を実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.nested_scene_b.SC-04-publish-DF-Ee', 'source_id': 'SC-04-publish-DF-Ee', 'group': 'nested_scene_b', 'disposition': '対応先あり', 'targets': ('T.rel.draw', 'T.draw_fact', 'T.draw_returned', 'T.prepared', 'T.draw_unknown', 'T.terminal', 'T.artifact', 'T.eq', 'T.evaluated', 'T.rel.selection', 'T.math_problem', 'T.math_root'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('draw', 'evaluation'), 'branch_constraint': 'SC-04-publish-DF-Ee', 'scope_to_preserve': ('範囲外 (実装の段へ): IDのFProblem/Draw/artifactの数値的な生成・全閉包を実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.additional_unconnected_a.SC-14-M3-Hung-D-cap1', 'source_id': 'SC-14-M3-Hung-D-cap1', 'group': 'additional_unconnected_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.resource', 'T.rel.draw', 'T.prepared', 'T.rel.independence'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'capacity'), 'branch_constraint': 'SC-14-M3-Hung-D-cap1', 'scope_to_preserve': ('未接続: Wg Hungと合法なPR→Dの席1の接続。現行の構造的artifact口では合法FProblem/PRの全対応を確かめられない。Wg単独の占有をこの対照の合格へ流用しない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
    {'id': 'BR.additional_unconnected_a.SC-14-M3-Hung-D-cap2', 'source_id': 'SC-14-M3-Hung-D-cap2', 'group': 'additional_unconnected_a', 'disposition': '対応先あり', 'targets': ('T.rel.generation', 'T.qgen', 'T.candidate_generation', 'T.candidate', 'T.eq', 'T.model_document', 'T.artifact', 'T.rel.resource', 'T.rel.draw', 'T.prepared', 'T.rel.independence'), 'verification_kinds': ('F-aの実物の値', '固定値', '変異', '新しい試験'), 'recipes': ('generation', 'capacity'), 'branch_constraint': 'SC-14-M3-Hung-D-cap2', 'scope_to_preserve': ('未接続: Wg Hungと合法なPR→Dの席2の接続。現行の構造的artifact口では合法FProblem/PRの全対応を確かめられない。Wg単独の占有をこの対照の合格へ流用しない。',), 'prerequisite_issues': ('G-01', 'G-02'), 'readiness': '未接続', 'reason': '対象への対応のみ。紙の未決を解消し合法な実値の前段を作るまで検証済みへ進めない。', 'disappearance_reason': '適用外: 消えた項目ではない', 'execution': 'not_run'},
)


# FBT draft 2 — v0.22 の保存宣言と公開クラスだけによる追記。
# 元の分母/橋を保持し、旧論理欄から新しい保存先への対応を別に記録する。
def _copy_tree(value):
    if isinstance(value, dict):
        return {k: _copy_tree(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_copy_tree(v) for v in value)
    if isinstance(value, list):
        return [_copy_tree(v) for v in value]
    return value

DRAFT1_DENOMINATOR = {key: _copy_tree(globals()[key]) for key in DENOMINATOR_KEYS}
DRAFT1_DENOMINATOR_SHA256 = DENOMINATOR_SHA256
DRAFT1_SUMMARY = _copy_tree(summary_counts())
DRAFT1_BRIDGES = _copy_tree(BRIDGES)
DRAFT1_SOURCE_ITEMS = _copy_tree(BRIDGE_SOURCE_ITEMS)
DRAFT1_SESSION_NOTE = _copy_tree(SESSION_NOTE)
DRAFT1_PROVENANCE = _copy_tree(PROVENANCE)
DRAFT1_AFFECTED = tuple(row['id'] for row in TARGETS
                        if set(row['issues']) & {'G-02', 'G-05', 'D-01'})

# 紙そのものの該当節のスナップショット。別の係の数えを分母にしない。
WIRE_SECTION_LINES = {
    2005: '### 2-5. 保存の形 — 縦の 1 本の契約の全宣言 (v0.20、Codex `sui-fb-wire` 1〜3 通目の下書き + Claude の決定)',
    2006: '',
    2007: '保存の形 (欄・型・Body・親・r の取り方) について §2-4 の表とこの節が食い違って読める所は、この節が正 (食い違いの一覧は §2-5-18)。',
    2008: '',
    2009: '経緯: 独立の対象一覧 (§0-3 の 5、Codex `sui-fb-targets` 1 通目) が、:486「F-a V-08 と同じ形の全欄・Body/Role/Category・版の宣言を当てる」の宣言そのものが無いこと (G-02) を見つけた。紙は論理の表 (E0・参照用途・CMP・PATH) までで、保存の形が無かった。下書きは紙と F-a の公開の型だけを読む係 (模型は見せない) に頼み、技術の未決 Q1〜Q8・U1〜U6 は Claude が原理と F-a の前例から決めた (ゆうの了承 2026-10-17 16:22「進めていいよ〜」、価値の問いは含まない)。この節の `B:n` は v0.19 の行番号 (§3 以降はこの節を足したぶんずれる)、`A:n` は F-a 今の約束の行番号。',
    2010: '',
    2011: '#### 2-5-0. この追記の位置と読み方',
    2012: '',
    2013: 'A は [F-a 今の約束](C:/Users/you11/Desktop/iku/sui/specs/関所F_今の約束.md)、B は [F-b 今の約束 v0.19](C:/Users/you11/Desktop/iku/sui/specs/関所F_Fb_今の約束.md)。行番号は今回読んだ版を指す。この追記は B:486 の「全欄・Body/Role/Category・版の宣言」を具体化する。',
    2014: '',
    2015: 'Q1〜Q8 は今回の契約宣言について Claude が決めた受信・起動・区間・和型・候補生成・Body・親・要求の決定を指す。B:220 以降にある以前の難所の Q1〜Q7 とは別である。',
    2016: '',
    2017: '`?T` は T または null。ほかの欄は非 nullable。`List[T]` は順序のある列、`Set[T]` は重複のない集合。`◆G-01` は未定義の型・意味であり、Any・自由 JSON・null に置き換えてよい印ではない。`★` は今回の縦の一本の外。',
    2018: '',
    2019: '各表の本文に加えて、共通の Record・Body の全欄を持つ。本文を短くした行でも、参照先の認証・必要閉包・実祖先の検査を省略しない。',
    2020: '',
    2021: '> たとえ: PC の中で言うと、この節は部品の説明書と接続表で、まだ動かして合格したという成績表ではない。',
    2022: '',
    2023: '#### 2-5-1. 共通の宣言：Body・参照・親・固定像・時刻',
    2024: '',
    2025: 'Record は A:28・38 の schema 3 をそのまま使う。外側は `id:Ref, at:{run:Ref,run_index:int,seq:int,mono_ns:int,wall_ns:int}, writer:Role, producer:{component:str,code_version:str,state:{lineage,revision}またはnull}, body, schema:3`。producer.state の型は既存宣言を継承する。wall_ns は int であり nullable にしない。',
    2026: '',
    2027: '正準 JSON・Payload・Ref/Point・ContractRef・和型は A:27〜32 に従う。Point は Entry の CID、Ref は Record の名前。契約名、環境キー、数学の根のキー、順番、slot を Point と交換しない。',
    2028: '',
    2029: '| R-BODY | 分類 | Body / Role / Category | この追記での対象 |',
    2030: '|---|---|---|---|',
    2031: '| 1 | 膜の外から届いた原報告 | Observed / MEMBRANE / FACT | received、boot_declaration、segment_report、work_report、draw_report、既存 clock.source |',
    2032: '| 2 | sui の要求・選択・採用・引受けの確定 | Decided / MODEL / FACT | 各要求、取得意図、採用意図、selection。既存 Q/A の分類も維持 |',
    2033: '| 3 | 計算の生成物 | Prediction / MODEL / PREDICTION | 既存 R・P・CG・math_artifact |',
    2034: '| 4 | 窓口が独立証拠と固定規則から成立を確かめた論理の出来事 | Observed / MEMBRANE / FACT | T・DF・DU・V・B・Xc・ST・PR・EV・W |',
    2035: '',
    2036: 'R-BODY 4 の保存は「窓口がその成立を確かめた」という記録であり、真の証明の代用品ではない。使う側は原報告・契約・必要な独立証拠から確かめ直す。同一プロセス内では台帳に加え H/EH・EW・EA を入力にできる。数値入力や固定像の証拠を、現在の H/P 全体へ広げる許可ではない。',
    2037: '',
    2038: 'W は R-BODY 4 とする。B:642・646・1053・1146 は実在する未完目的、不足、引継ぎを照合して残すことを要求する。W の owner 欄を書くだけで引受けを成立させる契約にはしない。九つ目の Body、および Interpretation・Preference・Job・Attempt・Intention の新しい用途は足さない。',
    2039: '',
    2040: '| Body の外側 | 全欄・値 | 適用 |',
    2041: '|---|---|---|',
    2042: "| 新しい原報告 O | `route='fb', content:Payload, contract:ContractRef, caused_by=null, source_id=null, source_time_ns=null, received_ns:int` | r は元の封筒の received_ns。route='fb' は N3 の識別名で、本文の route_epoch とは別 |",
    2043: '| 新しい論理 O | 同じ全欄。`received_ns:int` は下記の論理成立の読み | T・DU・V・B・Xc・ST・PR・EV・W。既存 DF への生成でも U2 の r を使い、既存の本文・Body は変更しない |',
    2044: '| 新しい D | `inputs:List[Ref], content:Payload, contract:ContractRef` | inputs はその確定で実際に使った対象。本文の Point と認証済み Record.id を照合 |',
    2045: '| 既存 P | `target:str, about:List[Ref], basis:List[Ref], content:Payload, contract:ContractRef` | 既存 A-04 を維持。target/about は説明対象、basis は宣言された使用根拠 |',
    2046: '',
    2047: 'O/D/P は以降この表の分類の略記とする。既存契約の route、外側の対応、符号化を新しい共通値に一括変更しない。',
    2048: '',
    2049: '参照用途は E＝対象・証拠として指す、U＝結論や次段の根拠として使用する、UE＝両方。E も実在・型・内容・出どころの検査を免れない。親は因果の証拠 E であり、親であることだけで結論使用を許さない（B:1017、1061）。',
    2050: '',
    2051: '親の式では、用途記号 E と区別して `Ev(x)` を使う。x が必要な O/D の出来事ならその Point、x が P なら A-03 に従い、その用途で必要な basis と実親から得る出来事を表す。説明対象として指しただけの P を自動で使用依存へ展開しない。',
    2052: '',
    2053: '`Front(S)` は列挙された必要出来事 S のうち、ほかの必要出来事を通じて既に実祖先になるものを除いた直接の境界。T の親は紙の明示どおり `{request, first_receipt}` とする。Prediction は直接の親にしない。因果の候補が一意に決まらない場合に CID 順で選ばない。固定像の境界を丸ごと親へ追加しない（A:149〜150、B:382、1882、Q7、S5）。',
    2054: '',
    2055: '`FixedView={boundary:Set[Point],environment:{reader_view_key:str,registry_key:?str}}`。boundary は保存済み Point の境界で、その実祖先と宣言された追加閉包を読む。registry_key=null は registry を使わない操作の宣言上の枝だけに許し、未知の registry の代用にはしない。reader_view_key は保存の読み手の像の識別であり、knowledge_origin の Point とは別。',
    2056: '',
    2057: '数値入力の Xnum、認証呼出しの check_view、使用直前の Xuse、保存再試行の PreparedEntry を区別する。H/EW/EA は FixedView の新しい隠れた数値入力にしない（B:1009）。',
    2058: '',
    2059: '時刻は V-04 の e/r/s/u/i/o/j/d/p に従う。seq・sample_seq・ordinal・slot は時刻ではない。',
    2060: '',
    2061: '| 記録・段 | r の取り方と固定 | ほかの時刻との関係 |',
    2062: '|---|---|---|',
    2063: '| 原報告 | Post がホスト M から読んだ封筒の r を使う。再受付で読み直さない | r≤s。送り手の時刻 u、生成 e、区間 i と別 |',
    2064: '| T・DF・DU・V・B・Xc・ST・PR・EV・W | 窓口が当該論理の成立を確かめた時に、ホストの run の M を一度読み、その r を当該記録の計画に保持する | r≤s。原報告の r は原報告への参照から辿る。r を原報告の r、生成の読み、s で代用しない |',
    2065: '| 保存の再試行 | 同じ論理記録の r、固定した計画、PreparedEntry を保持する | 同じ記録の保存・応答確認を理由に r を採り直さない。新しい証拠・像による別の論理記録とは区別 |',
    2066: '| 既存の G・Cq・clock_reading 等 | 既存契約の取得・生成・時計の通知の意味を維持する | G の a、Cq の g、clock_reading の reading と、その通知 r を交換しない |',
    2067: '',
    2068: '論理成立の M の読みは内部計画の値である。封筒番号・receipt_seq・Post・Accept・HostAck・受信 slot を新設しない。内部計画は従来どおり SAVE-3 から入り、PrepareOne で s・本文・親・salt・CID を固定する。このため U2 は B:1677 と矛盾しない。時計の読みと共有計画の保持の境界は、同じ記録の計画が成立した後の再試行で r を変えないよう扱う（B:298〜305、1677〜1690）。',
    2069: '',
    2070: '> たとえ: PC の中で言うと、メールの到着時刻と、アプリが内容を確認して処理結果を知った時刻を別々に残す。保存のやり直しでは、その時刻を書き換えない。',
    2071: '',
    2072: '#### 2-5-2. U1・C1：台帳と同じプロセス内の独立証拠',
    2073: '',
    2074: '封筒の原本・番号・receipt_seq・r は**同じプロセスの中だけ**に持ち、台帳に保存しない。持ち主は紙の既存の引き継ぎのまま: Accept までは H、Accept の歩で P.receipts が原本・r/seq・全受信 slot の責務を引き受け、H は引受け確認 (HostAck) まで同じ e を持つ (B:280、303、633、1682)。保存済みの記録から封筒の番号との対応は作らない。',
    2075: '',
    2076: '原報告の r 自体は Observed.received_ns として保存するが、封筒番号・receipt_seq・受付済み前方範囲は保存しない。〔C1 の訂正 (2026-10-17 Claude): 下書きの依頼で Claude が「原本は H、P はそれを指す」と頼んだのは、紙の H → P.receipts の引き継ぎ (B:303・633・1682) を読み落とした誤り。Q1 の意味は「台帳に置かない」だけで、同じプロセスの中の持ち主は変えない〕',
    2077: '',
    2078: '| 台帳だけでは再確認できない事項 | 独立の入力 | 保存済み記録の役割・限界 | 根拠 |',
    2079: '|---|---|---|---|',
    2080: '| 封筒の同一性、同番号再受付、Boot 二 slot の同封対応 | H/P.receipts の原本、P の対応計画 | 原報告全文・r・二件の保存は照合できるが、ホストの封筒との対応は台帳だけでは復元しない | B:279〜280、325、633、1123 |',
    2081: '| first の順序と受付済み前方範囲 | H/P.receipts の (r,receipt_seq)、受付の進み、原本 | first_receipt の自己申告、保存順、CID 順を順序の証明にしない | B:801〜807 |',
    2082: '| 実際の開始、入場回数、開始札、起動失敗の未入場確認 | EW、ホスト・起動包みの独立観測 | 要求の保存・WorkId・phase の印だけでは証明しない | B:309〜311、1657 以降 |',
    2083: '| 原報告が当該実行から返ったこと | EW と H/EH、要求の全内容 | 同じ WorkId を名乗る raw があるだけでは provenance が成立しない | B:1008、1099 |',
    2084: '| 実停止、確保・解放・Held・Occ | EW の実履歴 | T・Unknown・Ended・Rebuild を停止や一回の解放の証明にしない | B:647、836〜840 |',
    2085: '| 実取得と認証呼出し・返答 | EA、保存済みの意図・G・V・対象 | G/V の自己申告だけで実行済みとはしない | B:1039〜1042、1100 |',
    2086: '| 生きた発行済み認証物 | EA と P.work に保持する発行物・対応 | 保存された JSON・digest・V は生きた認証物を復元しない | A:32、B:374〜381、282 |',
    2087: '| 未保存計画、PlanRef の解決、salt、応答不明の再試行 | H/P と保持済み PreparedEntry | 保存前に台帳から同じ計画を作り直せるとはしない | B:281、304〜308、1683〜1687 |',
    2088: '| 元目的・未達・実所有・引継ぎ途中 | H/P の完全な識別と実保持、独立した引継ぎの対応 | W は保存可能な証拠の投影。owner 欄だけで所有は成立しない | B:1320〜1333、U5 |',
    2089: '| 論理成立時のホスト時計の実読取り | 当該計画に保持した M の読みとホストの時計契約 | 保存 r は記録値。窓口が実際に一度読んだことの実行照合は別 | U2、B:298〜305 |',
    2090: '',
    2091: '独立証拠は窓口の出力から正解を逆算した控えではない。実行や取得の正解を P.work の phase、V の成功印、W の owner 名から生成しない。必要な過去の対応を失った場合は再確認不能・不足を区別し、現在の状態で過去を補わない。',
    2092: '',
    2093: '区間の EI は B:752〜756 の既存の制限に従う。固定像内の証拠が実出来事を表すことの照合に使い、像の外の監視履歴・後着報告を Support の追加証拠へ混ぜない。',
    2094: '',
    2095: 'この再確認の範囲は同じプロセス内の窓口の作り直しまで。H/P/Runners が失われる再起動をまたぐ再確認は **★S5** として残す。今回そのための台帳欄やイベントを足さない（B:162、275〜292、1926、U1）。',
    2096: '',
    2097: '> たとえ: PC の中で言うと、アプリ画面を開き直しても裏の処理表は残るが、保存ファイルだけから送受信中の順番や動いているスレッドを復元できるとは限らない。',
    2098: '',
    2099: '#### 2-5-3. 共通値・Boot の入れ子・資源の量',
    2100: '',
    2101: '| 型 | 全欄・nullable | 用途・出どころ |',
    2102: '|---|---|---|',
    2103: '| ContractRef | `{name:str,version:str}` | 既存 A:28 |',
    2104: '| ContractValue | `{contract:ContractRef,value:JSON}` | 既存 A:31。意味は指定契約で閉じる |',
    2105: '| MethodCall | `{contract:ContractRef,args:JSON}` | 方法と全引数。args の意味・参照経路はその版付き方法の宣言に従う。B:1007、U4 |',
    2106: '| SlotValue<T> | `{slot:str,declaration:{contract:ContractRef,value:T}}` | Boot 内の版付き宣言値。独立 Record ではない。T1 |',
    2107: '| SlottedMethod | `{slot:str,method:MethodCall}` | Boot 内の δ の宣言位置。独立 Record ではない |',
    2108: '| BootSlot | `{declaration:Point,slot:str}` | 保存した boot_declaration とその宣言位置。Q2・U4 |',
    2109: '| QuantityValue | `{contract:ContractRef,value:非負整数}` | 今回は contract=sui.fb.seats/1。一般の別量型へ無断で拡張しない。U3 |',
    2110: '| FixedView | `{boundary:Set[Point],environment:{reader_view_key:str,registry_key:?str}}` | 第1節のとおり。親と別の型 |',
    2111: '',
    2112: 'Boot 内の slot は、当該宣言内で一意に解決できる宣言位置を指す。process_slot・reader_slot もその宣言が定義する位置である。曖昧な slot を名前や並び順で選ばない。原報告の保持と、初期計画として使用できる宣言の検査は別に行う。',
    2113: '',
    2114: '| 入れ子の契約・版 | 値の全欄 | 根拠・意味 |',
    2115: '|---|---|---|',
    2116: '| sui.fb.seats/1 | 非負整数一つ。bool は整数として受け取らない | 考える席の量。零=0、比較は整数の通常の比較、加算は通常の加算。減算は通常の整数差を計算し、資源量として保存する値は非負を要する。負の Free/割当を0へ丸めて合法化しない。Fit の max は B:840 の式だけ。U3、A:27 |',
    2117: '| sui.fb.resource_scope/1 | `{quantity_contract:ContractRef,need:MethodCall}` | 今回 quantity_contract=seats/1。need は固定された仕事記述と資源宣言から必要量を求める版付き方法。返値は同じ QuantityValue。phase・待ち理由・現在の空席を Need の正解にしない。U3、B:836 |',
    2118: '| sui.fb.allocation/1 | `{scope_slot:str,amount:QuantityValue}` | 同じ Boot の資源範囲を指す。capacity と同じ量契約で照合。U3、B:228、401 |',
    2119: '| sui.fb.bootstrap_route/1 | `{config:RouteConfig,process_slot:str,allocation:SlotValue<Allocation>}` | 設定全文、測る過程、初期割当。initial=null でも残る。Q2、U4、B:177、250、256、327 |',
    2120: '| sui.fb.initial_process/1 | `{process_slot:str,reader_slot:str,model:Point,generator:MethodCall,method:MethodCall,allocation:SlotValue<Allocation>,derivation:SlottedMethod}` | 最初の過程・読み手・モデル・生成方法・評価方法・割当・更新の導出方法。宣言の位置は外側 SlotValue.slot。Q2、U4、B:326、475、1124、1931 |',
    2121: '| sui.fb.environment/1 | `{data:JSON}` | ホストが渡した起動環境の宣言原文。data は明示的に自由 JSON とし、内包文字列を Point や registry の認証済み識別へ読み替えない。実際の数学環境は FixedView と既存 FMathEnvironment で別に照合。P1、B:177・469、T5 |',
    2122: '',
    2123: 'これらは入れ子の値契約であり、単独の Body/Role/Category・親を持たない。Boot の原報告として保存され、初期計画に使う時に契約と全内容を確かめる。',
    2124: '',
    2125: '`BootDeclaration={capacity:QuantityValue,scope:SlotValue<ResourceScope>,routes:List[SlotValue<BootstrapRoute>],initial:?SlotValue<InitialProcess>,environment:SlotValue<Environment>}`。',
    2126: '',
    2127: '今回の合法な縦の一本は資源範囲一つ、量契約一つ、bootstrap の口・測る過程一つ。capacity の実値は宣言で受け取り、実機の既定値を2にしない。Need=1、最低割当、計算の優先順位もこの宣言から足さない。重い仕事の必要量はその版付き資源・仕事契約から照合する。複数資源・別量型は **★外付け**。',
    2128: '',
    2129: '初期の過程・割当を指す側は BootSlot を使う。新しい適用済み過程・適用済み割当の Record は作らない。実際に保存する適用の記録は既存 route_config/1 の bootstrap 枝と knowledge_origin/1 に限る。宣言の存在を実開始・実適用・実取得の証明にはしない。',
    2130: '',
    2131: '> たとえ: PC の中で言うと、起動設定の中に名前付きの設定項目を置き、仕事はその設定ファイルと項目名を指す。設定があるだけで、その処理がもう動いたとはしない。',
    2132: '',
    2133: '#### 2-5-4. 縦の一本で使う δ の宣言',
    2134: '',
    2135: 'δ の契約名を **sui.fb.received_update/1** とする。これは条件言語ではなく、差し替え可能な MethodCall を束ね、Received から信念更新要求への対応を定める契約である。Boot.initial.derivation.method に置き、その contract をこの名前・版、args を次の全欄とする。独立 Record は作らない（U4、T2）。',
    2136: '',
    2137: '| args の欄 | 型 | 契約が要求する役割・根拠 |',
    2138: '|---|---|---|',
    2139: '| process_slot | str | 同じ Boot の対象過程。B:623〜624 |',
    2140: '| reader_slot | str | 同じ Boot の読み手の宣言位置。実使用時は対応する knowledge_origin と照合。B:623〜626 |',
    2141: '| purpose | belief_result | この版の δ が出す更新要求の用途。候補生成・評価の要求へ付け替えない |',
    2142: '| condition | MethodCall | どの保存済み Received を対象にするかと、その根拠を定める。未知の bytes をそのまま数値観測にしない。B:249、623 |',
    2143: '| trigger_slots | MethodCall | 対象 Received に対する trigger_slot の付け方を定める。B:623〜625 |',
    2144: '| inputs | MethodCall | 必要な入力・根拠、固定する Xnum、前の結果、引数の全内容を定める。/2 の数値意味は G-01 に従う。B:623・626 |',
    2145: '| stage_slots | MethodCall | 許されたきっかけ集合から要求の stage_slot への対応を定める。B:623・626 |',
    2146: '| grouping | MethodCall | まとめてよいきっかけの条件を定める。同じ過程・読み手・用途の条件を守り、まとめた各義務を個別に追えること。B:625・627 |',
    2147: '| request | MethodCall | 発行する要求の方法・出力契約・割当・許可と、上記の入力・slot との対応を定める。B:626、1007 |',
    2148: '',
    2149: '各 MethodCall は名前・版・全 args に加え、その方法の宣言で入力、返値、参照用途、意味を閉じる。この表は未宣言の方法を動かせる一般実行入口ではない。実際の Boot が指定した方法を解決できなければ、その意味を要する境界で missing_contract とし、原報告と元の義務を保持する。',
    2150: '',
    2151: 'δ の実行に渡す根拠は、Boot の宣言、対象 Received、対応する読み手、固定した保存像、必要な独立の受信対応である。結果の要求 Q、窓口の済み印、後から増えた受信を δ の期待値の根にしない。要求の発行時に Desc と Q の全内容を照合し、まとめた各義務について Matchδ/Dischargeδ を個別に検査する。',
    2152: '',
    2153: 'この型は条件の言語、対象を選ぶ具体的方法、まとめ方の方針を固定しない。具体的な MethodCall の値は Boot が宣言する設定であり、その方法の未宣言部分を自由 JSON だから許すことはない。周期、一定時間待つ規則、全 Received で必ず即時に考える規則を足さない。',
    2154: '',
    2155: '> たとえ: PC の中で言うと、「どの通知で、どの入力を使う処理を作るか」の設定をプラグイン名と引数で指定し、出来上がった仕事から設定を逆算しない。',
    2156: '',
    2157: '#### 2-5-5. 仕事の要求と Desc の入れ子',
    2158: '',
    2159: '`Trigger={point:Point,slot:str}`。point は保存済みのきっかけ、slot は δ または当該初期計画が定める役割。WorkId・slot は不透明な名札であり、同一性の証明ではない。',
    2160: '',
    2161: '`Stage=measure_segment/candidate_generation/belief_result/belief_proof/verification/evaluation_prepare/selection_draw/evaluation`。',
    2162: '',
    2163: '`Desc={work_id:str,process:BootSlot,trigger:Set[Trigger],purpose:Stage,stage_slot:str,reader:?Point,method:ContractRef,output_contract:ContractRef,args:用途別型,input_points:Set[Point],numerical_view:?FixedView,allocation:BootSlot,permissions:Set[BootSlot]}`。',
    2164: '',
    2165: 'Desc は **13欄**。全欄の根拠は B:1007。reader=null は読み手を使わない測定用途、numerical_view=null は数値入力の像を使わない用途に限る。計算の必要な読み手・像が欠けた場合を null で通さない。permissions は初期宣言の実内容と対象・方法・範囲を照合し、slot が存在するだけで許可にしない。',
    2166: '',
    2167: '| 用途別 args | 全欄 | 対応と根拠 |',
    2168: '|---|---|---|',
    2169: '| SegmentArgs | `{route:Point,requested_interval:MeasurementInterval,start_reason:str}` | route から設定全文・測る契約・時計契約。process/segment_slot/permission は Desc。B:327、1026、1125 |',
    2170: '| CandidateArgs | `{model:Point,generator_args:JSON,basis:List[Point]}` | generator は Desc.method。完成済み候補を入力として受け取らない。生成器の追加参照・適用順はその版付き args で宣言。B:1931〜1937 |',
    2171: '| ResultArgs | `{request:Point}` | 旧 Q を指す。数値引数・origin・入力・出力契約は Q が正本。B:360〜361、1031 |',
    2172: '| ProofArgs | `{request:Point,result:Point,checker:ProofRef}` | Q/R を未認証の証明対象として指す。R の取得や未来 Cq/V を前提にしない。B:362〜369 |',
    2173: '| VerificationArgs | `{target:{request:Point,result:Point,proofs:Set[Point],completion:Point},check_view:FixedView,checker:ProofRef,acquisitions:Set[Point]}` | origin は Desc.reader、Xnum は Desc.numerical_view。対象 bytes/digest・閉包は独立に求める。B:1040、1137 |',
    2174: '| EvaluationPrepareArgs | `{input:FFactsRequest,compiler:ContractRef}` | EQ の入力全文。Desc.method は実行操作、input.method は評価方法。B:1032、1139、1936 |',
    2175: '| DrawArgs | `{prepared:Point,stream_id:str,request:DrawRequest}` | generator は Desc.method。problem_key は認証した PR/FProblem から求める。B:1046、1140 |',
    2176: '| EvaluationArgs | `{evaluation_request:Point,prepared:Point,draw:Point}` | EQ/PR/DF の対応を固定。入力全文を複製しない。B:1049、1141 |',
    2177: '',
    2178: '一仕事につき Desc を持つ F-b 要求は一つ。新用途は論理要求と仕事要求を同じ記録に置く。旧 Q を使う Wr/Wp 等では F-b 要求から旧 Q を指す。旧 /1 DTO に link や Desc を足さない（Q8、S1）。',
    2179: '',
    2180: 'Desc.input_points は実入力集合の固定であり、必須閉包の正解ではない。必要集合は方法・用途・args から独立に求める。集合を整列しても、args 内の観測適用順を変えない。保存前の PlanRef 解決表は H/P に保持し、将来 Point を本文へ入れない。',
    2181: '',
    2182: '> たとえ: PC の中で言うと、一つのジョブに一枚の実行指示書を作り、以前からある計算要求はその指示書から参照する。設定や入力を別々の写しで食い違わせない。',
    2183: '',
    2184: '#### 2-5-6. 原報告・返答・終わりの入れ子',
    2185: '',
    2186: '| 型 | 全欄・枝・nullable | 時刻・意味・根拠 |',
    2187: '|---|---|---|',
    2188: '| ClockReading | `{run:Ref,time_ns:int}` | 既存。単独ではタグなし。A:30〜31 |',
    2189: '| Unavailable | `{reason:str,basis:List[Ref]}` | 既存。不足の根拠 E。時刻・数値へ変換しない |',
    2190: '| ReadingEvidence | clock 枝＝`{source:Point,reading:ClockReading}`、unavailable 枝＝Unavailable | source は以前に保存した clock.source の名指し。原報告保存後、使用時に実在と時計を照合。Q3、B:463、1883 |',
    2191: '| GenerationPair | `{started:ReadingEvidence,finished:ReadingEvidence}` | 生成 e。r/s と別。Unavailable の reason/basis も保持。B:1008 |',
    2192: '| FailureInfo | `{failure_kind:str,content:JSON,readings:List[ReadingEvidence],basis:List[Ref]}` | 失敗の種類・内容・読み・知った根拠。provenance=true 等を足さない。B:174、339、1144 |',
    2193: '| UnknownInfo | `{reason:str,basis:List[Ref]}` | 不明を知った根拠。Unknown と後着値だけで Conflict にしない。B:797 |',
    2194: '| WorkOutcome | outputs＝ContractValue、failure＝FailureInfo、unknown＝UnknownInfo | WorkOutputs/WorkFailure/WorkUnknown。outputs.contract は要求の output_contract と照合。Q4 |',
    2195: '| DrawOutcome | value＝JSON、failure＝FailureInfo、unknown＝UnknownInfo | DrawValue は値だけ。要求は WorkId から対応する D 要求へ解決。Q4 |',
    2196: '| CandidateGeneration | candidates＝FCandidateDeclaration、no_candidates＝空オブジェクト | candidates は非空 input_order。NoCandidates に世界全体の不存在・再実行義務を足さない。Q5、B:1934〜1935 |',
    2197: '| ProofOutput | `{role:normalization/query,statement:ContractValue,checker:ProofRef}` | Q/R は ProofArgs と照合。/2 statement/checker は ◆G-01 |',
    2198: '| VerificationResponse | verified / rejected / insufficient の確定返答。各 payload は ◆G-01 | 実行 Failure/Unknown は外側。生きた認証物を裸の JSON で代替しない。B:374〜379、1137 |',
    2199: '| TerminalReturned | output＝ContractValue、point＝Point、draw_value＝JSON、または null | point 枝は実際に保存した対応生成物だけ。failure/unknown は null。返答内容と全照合する。S4 |',
    2200: '| TerminalBasis | `{generation:?GenerationPair,failure:?FailureInfo,unknown:?UnknownInfo}` | Compute では generation を持つ。Draw に開始終了の報告がない枝は null。failure/unknown は該当する一方だけ。既知出力では両方 null。B:1882 |',
    2201: '',
    2202: '新しい和型は A:29 の kind/value 形式。既存の kind/op を持つ値を別の同義タグで二重に包まない。外側の仕事の終わりと、内側の用途契約は別の層である。自由 JSON を形が似ているだけで和型にしない。',
    2203: '',
    2204: "**Draw の Rejected の注**：U6 に従い、生成器が当該要求を確定して断った返答は `DrawFailure(failure_kind='rejected',…)`。T.terminal_kind は failure、理由と内容は basis.failure に残す。第四の Draw 枝も、別の内側契約も足さない。DF・DU・Ee を作らず、同じ Draw を再実行しない。",
    2205: '',
    2206: 'これは Wv の確定返答 Rejected を WorkFailure へ置き換える規則ではない。また、窓口が原報告の出どころ・対応を認めなかったことを、生成器から実際に来た DrawFailure に捏造しない。B:788 の T(Failure/Rejected) は「Failure、その一種として Rejected」と注記する。B:1968〜1970 との反例は今回の読取りでは見つからなかった。',
    2207: '',
    2208: '> たとえ: PC の中で言うと、「処理が失敗した」と「処理は正常に返り、答えが拒否だった」を用途ごとに区別する。抽選器の確定した受付拒否は、抽選の失敗の種類として残す。',
    2209: '',
    2210: '#### 2-5-7. 区間の八枝と結びつきの入れ子',
    2211: '',
    2212: '`SegmentReport={segment:Point,item_slot:str,item:SegmentItem}`。segment は区間要求 k の名指し。Frame の MeasurementId と、名前のない報告族の item_slot は別の識別である（B:321、472）。',
    2213: '',
    2214: '| SegmentItem の枝 | 全欄・nullable | 時刻・参照・根拠 |',
    2215: '|---|---|---|',
    2216: '| started | `{work:str,reading:ReadingEvidence,reason:str,evidence:List[Ref]}` | 開始 e。segment/request は外側から解決。EW と照合。B:328、737、1126 |',
    2217: '| ended | 同じ四欄 | 終了 e。停止・解放の独立証拠と同一視しない。B:328、738 |',
    2218: '| route_applied | `{config:Point,reading:ReadingEvidence,reason:str,evidence:List[Ref]}` | 設定の実効 e。旧 RouteApplied DTO を変更しない。B:739、1057 |',
    2219: '| frame | `{route_epoch:str,sample_seq:int,measurement_id:MeasurementId,measurement_interval:MeasurementInterval,actual_time:ClockReading または Unavailable,value:JSON または Unavailable,quality:ContractValue,gap:?Gap,source_cursor:ContractValue}` | 区間 i・実測 e。既存 Frame 全欄。B:329、736、1127 |',
    2220: '| gap | `{route_epoch:str,sequence_range:[first:int,stop:int],interval:MeasurementInterval,reason:str,evidence:List[Ref]}` | 既存の F-a の Gap (A V-02・`f.py` の `tuple[int,int]`) そのまま。二整数 [first,stop] で意味は半開 first ≤ seq < stop。欠けをゼロ測定にしない。〔v0.22 FBW-CHK-01 で `{first,stop}` の包みから既存の二整数列に戻した〕B:344、740、1128 |',
    2221: '| measurement_unavailable | `{route_epoch:str,requested_interval:MeasurementInterval,reason:str,evidence:List[Ref]}` | Frame 内の Unavailable と別。B:741、1129 |',
    2222: '| claim | `{route_epoch:str,interval:MeasurementInterval,kind:str,contract:ContractRef,evidence:List[Ref]}` | kind は主張の種類。Support の認証と保存を分ける。B:742、1130 |',
    2223: '| coverage_unproved | `{route_epoch:str,interval:MeasurementInterval,missing_contracts:List[ContractRef],evidence:List[Ref]}` | 未来の窓も許すが、被覆成功ではない。B:743、1131 |',
    2224: '',
    2225: 'MeasurementInterval は既存の `{clock:Ref,start_ns:int,end_ns:int,closure:両閉/左閉/右閉/両開}`、MeasurementId は `{origin:Ref,route_epoch:str,sample_seq:int,component:str}`。Frame 内の ClockReading を ReadingEvidence に改造しない。時計の出どころは生成・結びつきの検査で解決する。',
    2226: '',
    2227: 'SegmentItem は八枝の一つ。旧 coverage 四枝は既存のタグ・本文を維持し、さらに coverage という同義の包みを足さない。',
    2228: '',
    2229: '`BindingGeneration={applied:?Point,started:?Point,ended:?Point}`。各 Point は対応する境界の原報告。null は当該枝の生成契約が不要とする項だけ。必要な証拠が未保存なら成功した B を作らず、不足を保持する。過去の Gap に、現在の Started が窓開始以前という条件を一律に課さない。',
    2230: '',
    2231: 'B.clock は用いた clock.source の Point 集合で、原報告内の source/reading と照合する。測る係が保存していない clock_reading の Point を作らない。Cq 等に既存 clock_reading の Point が要る場合は、窓口が照合した inline reading を既存契約で別に保存する。',
    2232: '',
    2233: '> たとえ: PC の中で言うと、計測ログの「測れた」「欠けた」「測れなかった」「そう主張した」を別の種類で残し、開始と終了の二行だけで途中の全ログが揃ったことにはしない。',
    2234: '',
    2235: '#### 2-5-8. U5：W に入るものと H/P に残すもの',
    2236: '',
    2237: '| 対象 | W に保存する範囲 | H/P に保持する範囲 |',
    2238: '|---|---|---|',
    2239: '| 元条件・義務鍵 | 保存済み Point・BootSlot・契約・宣言済みの名札だけで完全に表せる場合の識別 | 未保存計画、封筒、開始札等を含む完全な識別。W へ書けなくても義務を消さない |',
    2240: '| 元目的・対象部分 | 保存可能な元条件から完全に解決できる目的の役割と固定対象部分 | 未保存の対象を含む元目的・過程・読み手・対象・未達の全体 |',
    2241: '| 不足の対象 | 保存済み Point、足りない契約、具体的な理由 | 未保存対象そのものと、その計画・取得・生成との対応 |',
    2242: '| 証拠 | 保存済み witness と FixedView | 当該判断に対応する H/EH・EW・EA の独立証拠との結合 |',
    2243: '| 持ち主 | 保存済みの要求・宣言等へ結べる担当の説明 | 実際の担当場所、引継ぎ元と先、保持中の全内容、処理・保存を再開できる状態 |',
    2244: '| 未保存の値 | 保存できない理由 | PlanRef、原本へのメモリ参照、未保存 CID の計画、salt、開始札、生きた認証物 |',
    2245: '',
    2246: 'W の七欄は維持し、保存可能な投影と、H/P のみで保持する部分を型で区別する（U5、T3）。',
    2247: '',
    2248: '| 型 | 全欄・枝 |',
    2249: '|---|---|',
    2250: '| Projection<T> | evidence 枝＝T、held 枝＝`{reason:str}`。held は「完全な対応を H/P が保持する」枝であり、対象不存在や所有者不在を表さない |',
    2251: '| SavedKeyValue | point＝Point、boot_slot＝BootSlot、contract＝ContractRef、name＝str の和型 |',
    2252: '| SavedKeyField | `{role:str,value:SavedKeyValue}`。role と必要な並びは当該 O-ID の登録条件から決める |',
    2253: '| SavedCondition | `{o_id:str,key:List[SavedKeyField],condition:issue/save/run/handle/stop,target:SavedKeyValue}` |',
    2254: '| Part | whole＝空オブジェクト、cell＝`{interval:MeasurementInterval}`。cell は元要求で固定した区間・端点の部分。現在の残りから作り直さない |',
    2255: '| SavedPurpose | `{original:SavedCondition,role:str,part:Part}`。過程・読み手・対象は original の完全な鍵から解決できなければ evidence 枝にしない |',
    2256: '| SavedTarget | point＝Point、contract＝ContractRef、reason＝`{reason:str}` |',
    2257: '| MissingTarget | `{point:?Point,contract:?ContractRef,reason:str}`。存在しない対象を point に入れない。両方 null の場合も具体的な理由を保持する |',
    2258: '| SavedOwner | `{anchor:Point,slot:str}`。保存した要求または宣言の担当位置の説明。実所有の証明ではない |',
    2259: '| WaitingPayload | `{obligation:Projection<SavedCondition>,purpose:Projection<SavedPurpose>,target:SavedTarget,missing:List[MissingTarget],witness:Set[Point],view:FixedView,owner:Projection<SavedOwner>}` |',
    2260: '',
    2261: 'SavedCondition の key は B:623〜624、631〜647、1207〜1244、1942〜1948 の当該条件の完全な義務鍵と照合する。O-ID、role、name を自由な新条件の追加口にしない。封筒番号・receipt_seq・メモリアドレスを name や reason に符号化して台帳へ持ち出さない。完全な鍵を表せない場合は held 枝にする。',
    2262: '',
    2263: 'Projection.evidence は「保存可能な形で説明できる」という意味であり、独立証拠なしに真と認める枝ではない。部分的な鍵を完全な SavedCondition に見せない。held 枝の reason から未保存対象を復元しようとしない。',
    2264: '',
    2265: 'H/P は元条件・目的・対象・固定値・未達を完全なまま保持し、当該 W の計画・保存 Point との対応を保つ。W の保存で完全な保持を捨てたり、元目的を達成済みにしたりしない。W の義務の局所的な保存と、元目的の未達は別である。PurposePart の存在だけで新しい保存義務を足さない（B:1320〜1333）。',
    2266: '',
    2267: '> たとえ: PC の中で言うと、保存ファイルには「どの保存済み資料が足りないか」を残し、まだ保存中のバッファや実行中の担当はプロセス内の管理表が持ち続ける。',
    2268: '',
    2269: '#### 2-5-9. 新しい契約の宣言表',
    2270: '',
    2271: 'この表では `sui.fb.` を省略する。全欄の型は上の入れ子を含む。論理 O の r はすべて U2 に従う。原報告の名指しは保存時には E、使用時に対応と実在を改めて検査する。',
    2272: '',
    2273: '| 契約・版 | Body / Role / Category、本文の全欄 | 時刻・和型・参照用途 | 直接の親 | 根拠・決定 |',
    2274: '|---|---|---|---|---|',
    2275: '| received/1 | O、`{route_epoch:str,media_type:str,data:bytes,claims:JSON}` | r/s。claims 内の時刻・ID・契約名は送り手の主張 E | ∅ | B:168、172、463〜471、Q1 |',
    2276: '| boot_declaration/1 | O、BootDeclaration | r/s、宣言 d。保存 E、初期計画の使用 UE | ∅。boot との同封対応は H/P | B:177、326、469、Q2、U3/U4 |',
    2277: '| segment_report/1 | O、`{segment:Point,item_slot:str,item:SegmentItem}` | r/s、本文の e/i。保存 E、必要な境界・測定使用 UE | ∅ | B:173、321、472、1056〜1059、Q3 |',
    2278: '| work_report/1 | O、`{work:str,started:ReadingEvidence,finished:ReadingEvidence,outcome:WorkOutcome}` | r/s と生成 e を分離。保存 E | ∅ | B:174、473、1008、Q4 |',
    2279: '| draw_report/1 | O、`{work:str,outcome:DrawOutcome}` | r/s。要求は対応する D 要求から解決。保存 E | ∅ | B:474、1968〜1970、Q4/U6 |',
    2280: '| segment_requested/1〔k〕 | D、`{desc:Desc<SegmentArgs>}` | at=e、要求区間 i。route・宣言・許可 UE | Front({Boot 宣言,route}∪Ev(実使用 trigger・許可根拠)) | B:327、1026、1125、Q8/S1 |',
    2281: '| candidate_request/1〔Qgen〕 | D、`{desc:Desc<CandidateArgs>}` | at=e。生成 Xnum と入力・方法・許可 UE | Front({Boot 宣言,reader}∪Ev(model・basis・trigger・許可根拠)) | B:1931〜1937、Q8/S1 |',
    2282: '| work_requested/1〔Wr/Wp/Wv/Ee〕 | D、`{desc:Desc<用途別args>}` | at=e。四用途の対象・使用を区別 | Wr：Front({Q}∪Ev(trigger・許可))。Wp：Front({Q}∪Ev(R・trigger・許可))。Wv：Front({Q,Cq}∪Ev(R・全P・全G・trigger・許可))。Ee：Front({EQ,PR,DF}∪Ev(trigger・許可)) | B:358〜382、1007、1040、1049、Q8/S1 |',
    2283: '| evaluation_requested/1〔EQ/Ep〕 | D、`{desc:Desc<EvaluationPrepareArgs>}` | at=e。入力全文・操作・環境・評価 Xnum を固定。UE | Front({reader,context}∪Ev(CG・model・preferences・trigger・許可)) | B:1032、1139、1936 |',
    2284: '| draw_requested/1〔D〕 | D、`{desc:Desc<DrawArgs>}` | at=e。request.purpose=selection。UE | Front({PR}∪Ev(trigger・許可)) | B:333、1046、1140 |',
    2285: '| work_terminal/1〔T〕 | O、`{work:str,request:Point,stage:Stage,first_receipt:Point,terminal_kind:outputs/value/failure/unknown,returned:?TerminalReturned,basis:TerminalBasis,view:FixedView}` | 八欄。全体 E。request は当該 F-b 仕事要求。停止・認証成功を含意しない | **{request,first_receipt}** | B:776、1051、1882、S1/S4、U1/U2 |',
    2286: '| draw_unknown/1〔DU〕 | O、`{draw_request:Point,first_receipt:Point,unknown_basis:UnknownInfo,view:FixedView}` | UE。値を持たないが D の終わりの使用依存を持つ | {draw_request,first_receipt} | B:788、1048、U1/U2 |',
    2287: '| segment_binding/1〔B〕 | O、`{segment:Point,report:Point,route:Point,reading_contract:ContractRef,evidence:Set[Point],generation:BindingGeneration,clock:Set[Point],view:FixedView}` | report は E、成立に使う要求・設定・生成・時計は UE | Front({segment,report,route}∪Ev(evidence・generation の非null項・clock)) | B:1054〜1055、1145、Q3/S3 |',
    2288: '| verification/1〔V〕 | O、`{request:Point,report:Point}` | 保存 E、採用使用 UE。target/view/response は Wv 要求・原報告から解決 | {request,report} | B:641、791、1040〜1042、S3/U1 |',
    2289: '| prepared/1〔PR〕 | O、`{request:Point,report:Point,artifact:Point}` | request=EQ。FProblem/NoDecision は artifact 全内容。UE | Front({request,report}∪Ev(artifact)) | B:332、376、1045、1139、S3 |',
    2290: '| evaluated/1〔EV〕 | O、`{request:Point,report:Point,artifact:Point}` | request=Ee 要求。EQ/PR/DF/操作/Xnum を解決。UE | Front({request,report}∪Ev(artifact)) | B:334、377、1049、1141、S3 |',
    2291: '| selection/1〔S〕 | D、`{evaluated:Point}` | at=e。認証した Selected の artifact/root/draw を解決。UE | {evaluated}。必要依存が EV の実祖先にあることを検査 | B:335、1050、1142、S3 |',
    2292: '| acquisition_requested/1 | D、`{origin:Point,contents:Set[Point]}` | at=e。引受けであり実取得の証明ではない。UE | Front({origin}∪Ev(当該意図を生んだ完了・対象の必要生成根拠)) | B:340、640、1039、S1/S5 |',
    2293: '| adoption_requested/1 | D、`{origin:Point,completion:Point,planned_previous:?Point,verification:Point,acquisitions:Set[Point]}` | at=e。予定前状態・V/G の対象を固定。UE | Front({origin,completion,verification}∪Ev(planned_previous・acquisitions)) | B:342、1043〜1044、1138 |',
    2294: '| stale/1〔ST〕 | O、`{intent:Point,actual_previous:?Point,view:FixedView}` | E。計画と実前状態の不一致。Conflict ではない | Front({intent}∪Ev(actual_previous・系列の必要証拠)) | B:342、1044、1138、S3 |',
    2295: '| conflict/1〔Xc〕 | O、`{reports:Set[Point],rule:ConflictRule,view:FixedView}` | E。affected は規則から独立に計算 | Front(Ev(reports)∪Ev(規則が必要とする追加出来事)) | B:797、1052、1163〜1172、S3 |',
    2296: '| waiting/1〔W〕 | O、WaitingPayload の七欄 | E。保存可能な投影と H/P の保持を区別 | Front(Ev(witness)∪Ev(保存可能な元条件・引継ぎの成立根拠)) | B:642、646、1053、1146、U5/T3 |',
    2297: '| candidate_generation/1 | 内側の値契約、CandidateGeneration。独立 Body なし | WorkOutputs の内側。非空は既存 CG の P へ保存 | 適用外 | B:1934〜1935、1963、Q5 |',
    2298: '| proof_output/1 | 内側の値契約、ProofOutput。独立 Body なし | Wp の返答。statement/checker の /2 は ◆G-01 | 適用外 | B:363、373〜374 |',
    2299: '| verification_response/1 | 内側の値契約、VerificationResponse。独立 Body なし | 枝は確定。payload・発行物の全結合は ◆G-01 | 適用外 | B:374〜379、1137 |',
    2300: '',
    2301: "ConflictRule は `{id:CL-SAME/CL-SEQ/CL-MEASUREMENT/CL-EXECUTION/CL-DRAW/CL-APPLY,version:'1'}` とし、規則の本文は B:1163〜1172 に固定する。/2 に依存する CL-APPLY の適用同一性は G-01。Unknown＋後着値、正当な Stale、別 slot・別取得意図だけで Conflict を作らない。個数違反を Xc で代用しない。",
    2302: '',
    2303: '新しい D の inputs は、その確定が実使用する本文・宣言上の対象を認証して Ref 集合へ写す。各仕事要求では BootSlot の宣言 Point、reader、trigger、input_points、用途別 args の宣言された使用参照を照合する。selection では evaluated と、そこから解決して実使用する artifact・draw 等を照合する。取得意図は origin/contents、採用意図は origin/completion/planned_previous/verification/acquisitions を照合する。自由 JSON 全体を走査して作らない。方法別の未宣言経路は G-01 等の意味不足として残す（S5）。',
    2304: '',
    2305: '> たとえ: PC の中で言うと、通知、実行指示、計算結果、確認結果をそれぞれ決まった形式の記録にし、同じ仕事の名札だけで別の内容をつなげない。',
    2306: '',
    2307: '#### 2-5-10. 既存契約へ保存する箇所',
    2308: '',
    2309: 'ここでは既存契約の全欄・Body・版・意味を維持する。親の式は F-b がそれを生成する場面の接続を示し、旧 /1 の一般受理条件を書き換えない。',
    2310: '',
    2311: '| 契約 | Body・本文全欄 | F-b との対応・直接の親 | 根拠 |',
    2312: '|---|---|---|---|',
    2313: '| sui.s4.boot/1 | O、`{}` | Boot 二 slot の一方。親∅。宣言との同封対応は H/P | A:77、B:469 |',
    2314: '| sui.clock.source/1 | O、`{run,provider,implementation,python_version,resolution_s:R,monotonic:bool,adjustable:bool,measurement:?ContractRef}` | I-7 原報告。親∅。宣言 d、精度の証明ではない | A:78、B:1925 |',
    2315: '| sui.f.route_config/1 | O、`{config:RouteConfig,effective_from:ClockReading または Unavailable,execution:?Ref,evidence:List[Ref]}` | bootstrap の実適用。親 Front({Boot 宣言}∪Ev(実適用・時計の必要証拠)) | A:76、B:177、Q2 |',
    2316: '| sui.f.knowledge_origin/1 | O、`{model:Point}` | 初期宣言と model に対応。親 Front({Boot 宣言}∪Ev(model の必要来歴)) | A:59、B:326 |',
    2317: '| sui.f.computation_requested/1〔Q〕 | D、`{origin:Point,purpose:belief/query/certificate,method:ContractRef,args:JSON,inputs:List[Point],algorithm_draws:List[Point],output_contract:ContractRef}` | Wr 要求から指す旧 Q。親 Front(Ev(実使用 trigger・origin・入力・許可))。/2 args は G-01 | A:61、158、B:360、482 |',
    2318: '| sui.f.computation_result/1〔R〕 | P、`{request:Point,output:ContractValue}` | request=旧 Q。親 Front({Wr 要求,対応原報告}∪Ev(必要生成根拠)) | A:62、160〜161、B:361 |',
    2319: '| sui.f.computation_proof/1〔P〕 | P、`{request:Point,result:Point,role:normalization/query,statement:ContractValue,checker:ProofRef}` | 親 Front({Wp 要求,対応原報告}∪Ev(必要生成根拠))。R は親にしない | A:63、162〜166、B:363、382 |',
    2320: '| sui.f.clock_reading/1 | O、`{source:Point,reading:ClockReading}` | 照合した inline reading を既存形で保存。親 Front({対応報告,source,対応要求})。実取得の読み等ではその出来事の既存証拠を使う | A:66、B:1883、Q3 |',
    2321: '| sui.f.computation_completed/1〔Cq〕 | O、`{request:Point,result:Point,proofs:List[Point],started_clock:Point,finished_clock:Point}` | Wr 開始・Wp 終了の時計。親 Front({Q,started_clock,finished_clock}∪Ev(R・全P の必要生成根拠)) | A:64、B:338、364、1135 |',
    2322: '| sui.f.content_acquired/1〔G〕 | O、`{origin:Point,contents:List[Point],clock:Point}` | EA の実取得と意図に対応。親 Front({取得意図,origin,clock}∪Ev(対象の必要生成根拠)) | A:60、188〜189、B:340 |',
    2323: '| sui.f.knowledge_adopted/1〔A〕 | D、`{origin:Point,previous:?Point,completion:Point}` | 親 Front({採用意図,origin,completion,V}∪Ev(previous・実取得 G))。外側 inputs は旧 A:159 の式のまま | A:65、159、B:342 |',
    2324: '| sui.f.candidate_declaration/1〔CG〕 | P、FCandidateDeclaration | 非空返答の全内容。親 Front({Qgen,対応原報告}∪Ev(宣言された生成根拠)) | A:58、167、B:1934 |',
    2325: '| sui.f.draw_fact/1〔DF〕 | O、`{generator:ContractRef,stream_id:str,request:DrawRequest,value:JSON}` | 要求から三欄、first の原報告から値。親 {D 要求,first_receipt}。r は U2 | A:68、B:1047、1140 |',
    2326: '| sui.f.math_artifact/2 | P、既存 E-05 の正準包み | 親 Front({Ep/Ee 要求,対応原報告}∪Ev(必要入力))。全 bytes と発行物を照合 | A:86、B:376〜377、1060 |',
    2327: '',
    2328: '既存の入れ子は次の全欄を維持する。',
    2329: '',
    2330: '- `RouteConfig={route_epoch:str,origin:bootstrap/selected,version:str,sampling_contract:ContractRef,clock_contract:ContractRef,loss_contract:ContractRef,args:JSON,decision:?Ref,execution:?Ref}`。今回の適用は bootstrap、decision/execution=null。',
    2331: '- `DrawRequest={purpose:candidate_generation/selection/reservation/algorithm,context_key:str,ordinal:int,law:ContractRef,args:JSON}`。今回の D は selection。id 式外の law/args も比較する。',
    2332: '- `FCandidateDeclaration={model:Point,input_order:List[str],measure:?CandidateMeasureRef,generation:{generator:ContractRef,args:JSON,basis:List[Point],draws:List[Point]},continuation:{after:List[{candidate:str,policy:?PolicyRef}]}}`。input_order は非空・重複なし。CandidateMeasureRef・PolicyRef・ProofRef は既存の name/version/args。今回の生成方法は生成用 draw を要しないものに限り、必要な draw を空へ読み替えない。',
    2333: '- `FFactsRequest={fixed_parents:List[Point],model:Point,candidates:Point,preferences:List[Point],scope:EvaluationScope,context:Point,method:ContractRef}`。EvaluationScope は既存の name/version/H_ns/source を維持し、ResourceScope と交換しない。',
    2334: '- math_artifact/2 の contract/compiler/input/environment/calls/output/claim と FProblem・Selected・NoDecision の全型は A の E-05 を規範参照として維持する。内部 call 番号・output 番号は Point ではない。',
    2335: '',
    2336: 'R/P の request は旧 Q のままで、F-b の wrapper へ交換しない。about/basis/inputs の既存対応は A:157〜174 を維持する。新しい /2 の証明契約に旧 normalization の意味を自動転用しない。',
    2337: '',
    2338: '> たとえ: PC の中で言うと、新しい管理アプリから既存のファイル形式へ保存するが、昔のファイル形式に新しい欄をこっそり足さない。',
    2339: '',
    2340: '#### 2-5-11. 論理欄の解決規則',
    2341: '',
    2342: '| 論理欄 | 保存元・独立入力からの解決 |',
    2343: '|---|---|',
    2344: '| 一仕事の要求 | F-b 要求を一つ対応させる。WorkId だけでなく Desc 全欄・出どころ・因果を照合 |',
    2345: '| 論理 Q/Qgen/EQ/k/D | Wr/Wp は args.request の旧 Q。新用途は当該要求自身。Wv の Q は target.request、Ee の EQ は args.evaluation_request |',
    2346: '| process/trigger/reader/purpose/trigger_slots/numerical_view/permission | Desc と BootSlot の宣言内容。δ の期待値は独立の宣言・原報告・固定像から求める |',
    2347: '| link.report/generation/provenance | 要求、原報告、宣言された生成記録の親、H/EH・EW の実対応。窓口の link の写しを正解にしない |',
    2348: '| first_receipt | H/P.receipts の (r,receipt_seq)、受付済み前方範囲、EW の出どころ、保存済み原報告を照合 |',
    2349: '| PR の evaluation_request/input/numerical_view/operation | PR.request の EQ/Desc。problem/NoDecision は artifact 全内容 |',
    2350: '| EV の evaluation_request/prepared/draw/operation/numerical_view | EV.request の Ee/Desc と対応 EQ/PR/DF |',
    2351: '| S の artifact/root/draw | evaluated の EV と認証した Selected。root を Point と決めつけない |',
    2352: '| V の target/view/response/issued_certificate | Wv 要求、原報告、EA の実返答・発行と P の生きた認証物。V の保存から発行済み扱いを作らない |',
    2353: '| ST の target_completion/planned_previous/reason | 採用意図と、その像の実前状態の不一致から解決 |',
    2354: '| B の report_key/original_report/bound_cells | original_report=B.report。鍵は MeasurementId/item_slot と型から。bound_cells は要求・原報告・読み方・view から計算。ReportCells と Support を混同しない |',
    2355: '| Xc.affected | rule と全報告・必要依存から直接影響集合を求める。全下流は UseDeps で伝播 |',
    2356: '| W の元目的・未達・実所有 | W の投影と H/P の完全な識別・保持・独立の引継ぎを照合。held を達成や不存在にしない |',
    2357: '| G/A の intent/verification/acquisitions | 意図記録、実祖先、EA の実行から一意に対応。複数候補を CID 順で選ばない |',
    2358: '',
    2359: 'PR/EV/V/R/P/CG の対応を得るために、T の保存を新しい必須前提にしない。T と生成物の未保存責務は独立に保持する（B:637〜645、1882）。',
    2360: '',
    2361: '> たとえ: PC の中で言うと、同じ情報を何枚にもコピーせず、元の指示書・受信ログ・結果ファイルをたどって照合する。',
    2362: '',
    2363: '#### 2-5-12. E0 全8行の対応表',
    2364: '',
    2365: '| ID・根拠 | 対応先 | 制約 |',
    2366: '|---|---|---|',
    2367: '| E0-01、B:1004 | 契約名/版、欄経路、用途別 args、参照用途 | 未宣言経路は許可しない |',
    2368: '| E0-02、1005 | Boot、raw、要求、H/EH・EW・EA 等の独立証拠 | U1 の範囲で照合。窓口出力から期待値を作らない |',
    2369: '| E0-03、1006 | 第11節の link 解決規則 | DTO に仮想欄を読み足さない |',
    2370: '| E0-04、1007 | Desc 全13欄、BootSlot、用途別 args、FixedView | 集合と適用順、PlanRef と Point を分ける |',
    2371: '| E0-05、1008 | work_report/draw_report、要求、生成読み、EW | provenance は自己申告の保存欄にしない |',
    2372: '| E0-06、1009 | Xnum/check_view/Xuse/PreparedEntry | H/P を数値入力へ混ぜない |',
    2373: '| E0-07、1010 | 未宣言の契約・用途・◆G-01 | 意味の境界で不足。原報告保存は継続 |',
    2374: '| E0-08、1011 | k、Qgen/Wg/CG、Wr/Wp/Wv、EQ/Ep/D/Ee、G/A | R10・再起動等を縦へ混ぜない |',
    2375: '',
    2376: '> たとえ: PC の中で言うと、処理の正解を決める仕様と、実際に起きたログと、照合する環境を別々に指定する。',
    2377: '',
    2378: '#### 2-5-13. 参照用途表 全39行の対応',
    2379: '',
    2380: '| B の行 | 保存先・解決先 | 用途 |',
    2381: '|---|---|---|',
    2382: '| 1023 | raw 全文、Record.run、Observed.r。原本・番号/seq は Accept まで H、Accept の歩で P.receipts が原本・r/seq・slot 対応を引き受け、H は HostAck まで併持 (§2-5-2 C1) | E |',
    2383: '| 1024 | received.data/claims、原報告の未解決名指し | E |',
    2384: '| 1025 | Boot の版付き入れ子、BootSlot、既存 boot/origin/route_config | 対応 E、初期計画 U |',
    2385: '| 1026 | k.desc、SegmentArgs、route_config | UE |',
    2386: '| 1027 | 旧 Q.origin | UE |',
    2387: '| 1028 | 旧 Q.args の方法別宣言 | U。/2 は G-01 |',
    2388: '| 1029 | Q.inputs と独立した必須閉包 | E／必要部分 UE |',
    2389: '| 1030 | Q.algorithm_draws | U |',
    2390: '| 1031 | Wr Desc と Boot 内 received_update/1 | UE |',
    2391: '| 1032 | EQ.desc、FFactsRequest、FixedView | UE |',
    2392: '| 1033 | R.request、Wr 要求・raw・EW | UE |',
    2393: '| 1034 | R.output 全内容 | E |',
    2394: '| 1035 | P.request/result、statement の宣言経路 | UE |',
    2395: '| 1036 | ProofOutput、P.statement/checker、Wp raw | UE |',
    2396: '| 1037 | Cq.request/result/proofs | UE |',
    2397: '| 1038 | Cq の時計二件と対応する生成証拠 | UE |',
    2398: '| 1039 | G.origin/contents/clock、取得意図、EA | UE |',
    2399: '| 1040 | Wv Desc/args、実取得 G、固定検査像 | UE |',
    2400: '| 1041 | V.request/report、実返答・実発行との対応 | E |',
    2401: '| 1042 | V の対象・返答・実発行物を使用時に照合 | UE |',
    2402: '| 1043 | A の旧三欄、採用意図・V/G の実祖先 | UE |',
    2403: '| 1044 | ST.intent/actual_previous/view、意図の予定値 | E |',
    2404: '| 1045 | PR と EQ.desc、artifact 全内容 | UE |',
    2405: '| 1046 | D Desc、DrawArgs、PR/FProblem | UE |',
    2406: '| 1047 | 旧 DF 全文、D 要求・first の独立対応 | UE |',
    2407: '| 1048 | DU 四欄 | UE |',
    2408: '| 1049 | EV、Ee.args、EQ/PR/DF | UE |',
    2409: '| 1050 | S.evaluated、認証した Selected | UE |',
    2410: '| 1051 | T 八欄、H/EH・EW の再照合 | E |',
    2411: '| 1052 | Xc.reports/rule/view、affected の再計算 | E |',
    2412: '| 1053 | W 七欄の投影、H/P の完全な目的・不足・所有 | E |',
    2413: '| 1054 | B 八欄。view は CMP-23 と統合 | report E、成立根拠 UE |',
    2414: '| 1055 | B と読み方の意味別展開 | UE。/2 は G-01 |',
    2415: '| 1056 | Frame 全欄・宣言された内包参照 | 保存 E、必要使用 UE |',
    2416: '| 1057 | 境界三枝の reading/evidence と独立実行 | 保存 E、境界使用 UE |',
    2417: '| 1058 | Gap/MeasurementUnavailable/CoverageUnproved | E。ゼロ・成功へ変換しない |',
    2418: '| 1059 | Claim.kind/contract/evidence、固定像の Support | 保持 E、認証根拠 UE |',
    2419: '| 1060 | 既存 math_artifact/2 全欄 | 保存 E、宣言された入力・検査 UE |',
    2420: '| 1061 | 共通 Body、各行の親、旧 A-04、新 S5 | 親 E。ほかは個別用途 |',
    2421: '',
    2422: '> たとえ: PC の中で言うと、ファイルへのリンクが「調べる対象」なのか「処理を進める根拠」なのかを、リンクごとに区別する。',
    2423: '',
    2424: '#### 2-5-14. CMP 全24行の対応',
    2425: '',
    2426: '| ID・B の行 | 比較する保存先・独立入力 | 注意 |',
    2427: '|---|---|---|',
    2428: '| CMP-01、1123 | raw 全内容・run/r、H/P.receipts の封筒/seq、P の slot 計画 | 原本は同じプロセスの中だけ (C1)。Boot 二 slot を照合 |',
    2429: '| CMP-02、1124 | Boot の入れ子全内容、版・slot・量・方法・origin/model/environment 対応 | 宣言と適用を分ける |',
    2430: '| CMP-03、1125 | SegmentArgs、Desc、route_config 全文 | 名前だけ一致では不可 |',
    2431: '| CMP-04、1126 | segment と境界三枝の全欄、要求・EW | source/run/time と reason/evidence を比較 |',
    2432: '| CMP-05、1127 | Frame と gap/quality/cursor の全内容 | 同値 value だけで統合しない |',
    2433: '| CMP-06、1128 | segment/item_slot、gap 全欄 | 共通族の枝も比較 |',
    2434: '| CMP-07、1129 | segment/item_slot、measurement_unavailable 全欄 | Frame 内の Unavailable と別 |',
    2435: '| CMP-08、1130 | segment/item_slot、claim 全欄 | kind/contract を落とさない |',
    2436: '| CMP-09、1131 | segment/item_slot、coverage_unproved 全欄 | 未来窓と成功を分ける |',
    2437: '| CMP-10、1132 | Desc 13欄、用途別 args、δ、旧 Q 全欄 | WorkId だけで一致にしない |',
    2438: '| CMP-11、1133 | R 全文、Wr 要求、raw の読み・出力、EW | 出力契約の全内容を比較 |',
    2439: '| CMP-12、1134 | P 全文、ProofOutput、Wp 要求/raw/EW | statement の Q/R/model と外側を照合 |',
    2440: '| CMP-13、1135 | Cq 五欄、Wr 開始/Wp 終了 | 同内容でも二件目を作らない |',
    2441: '| CMP-14、1136 | 取得意図、G 三欄、時計、EA | 別意図・別読み手を統合しない |',
    2442: '| CMP-15、1137 | Wv Desc/args、V、EA の返答・実発行物 | payload・認証物は G-01 |',
    2443: '| CMP-16、1138 | 採用意図、A/ST、実前状態、V の認証物 | Stale と Conflict を分ける |',
    2444: '| CMP-17、1139 | PR、EQ 入力/操作/Xnum、artifact 全 bytes、Gen(Ep) | digest 自己申告で代用しない |',
    2445: '| CMP-18、1140 | D 要求、DrawValue、DF 全文 | law/args も比較 |',
    2446: '| CMP-19、1141 | EV、Ee 要求、PR/DF、artifact 全 bytes、Gen(Ee) | 別問題・別 Draw を混ぜない |',
    2447: '| CMP-20、1142 | S から EV/artifact/root/draw/Selected 全文 | NoDecision に S の枝なし |',
    2448: '| CMP-21、1143 | T 八欄、TerminalReturned/Basis、U2 の固定 r | 固定した終わりと報告集合の Conflict は別 |',
    2449: '| CMP-22、1144 | WorkOutcome/DrawOutcome、生成読み、FailureInfo、EW | Wv の内側 Rejected と、D の failure_kind=rejected を用途で区別 |',
    2450: '| CMP-23、1145 | B 八欄と report_key/original_report/bound_cells の解決 | 後から加える証拠で原報告を書き換えない |',
    2451: '| CMP-24、1146 | Xc の独立再計算、W の投影、H/P の完全な不足・所有 | held を消失・達成にしない。owner 名だけで所有成立にしない |',
    2452: '',
    2453: 'CMP-21 の意味比較に、配送の r を生成時刻として混ぜない。U2 の r は当該論理記録の固定・時刻検査の対象であり、原報告の論理同一性を決める生成読みの代用ではない。',
    2454: '',
    2455: '> たとえ: PC の中で言うと、同じジョブ番号の結果でも、入力・実行元・開始終了・返答の全内容が一致するかを比べる。',
    2456: '',
    2457: '#### 2-5-15. PATH 全20行の対応',
    2458: '',
    2459: '| PATH・B の行 | 対応・制限 |',
    2460: '|---|---|',
    2461: '| RECEIPT、1082 | 五つの raw 契約。未知名指しの解決を保存前提にしない |',
    2462: '| RESULT、1083 | 旧 R.request/output。/1 の意味を維持 |',
    2463: '| STATEMENT、1084 | 旧 P・ProofOutput。/2 へ自動転用しない |',
    2464: '| CHECKER、1085 | 旧 checker の版・args 制約を維持 |',
    2465: '| Q0、1086 | 旧 /1 の局所対照のまま |',
    2466: '| QPREV、1087 | 旧 /1 の前結果閉包のまま |',
    2467: '| QOBS、1088 | /2 の射影・閉包は G-01 |',
    2468: '| R-OUTER、1089 | 旧 A-04。request を wrapper へ交換しない |',
    2469: '| P-OUTER、1090 | 旧 A-04。取得済み R・未来 V を要求しない |',
    2470: '| COMPLETE、1091 | Cq と対応する時計二件・生成証拠 |',
    2471: '| ACQUIRE、1092 | G・取得意図・EA・実祖先 |',
    2472: '| ADOPT、1093 | 旧 A 三欄、意図・V/G・採用系列 |',
    2473: '| REPORT-EVIDENCE、1094 | 区間枝 evidence、B、固定像の Support |',
    2474: '| UNAVAILABLE、1095 | 宣言された Unavailable の reason/basis のみ |',
    2475: '| ARTIFACT-INPUT、1096 | EQ の FFactsRequest と既存 artifact input。完全な意味閉包とは別 |',
    2476: '| ARTIFACT-DRAW、1097 | Ee.args.draw と bind_draw の Point |',
    2477: '| ARTIFACT-NONPOINT、1098 | 契約版・環境キー・内部番号。Point と交換しない |',
    2478: '| LINK-GENERATION、1099 | 要求・raw・親と H/EH/EW。台帳だけとはしない |',
    2479: '| LINK-ACQUISITION、1100 | 意図・G/V・EA・生きた認証物。wire の未定義は G-01 |',
    2480: '| PARENTS、1101 | 各行の最小親式。P・固定像の全境界を親にしない |',
    2481: '',
    2482: 'E0 8行、参照用途39行、CMP 24行、PATH 20行、合計91行の対応を維持した。行の対応があることを、各経路の実装・意味検証が済んだこととは数えない。',
    2483: '',
    2484: '> たとえ: PC の中で言うと、どのファイルのどの欄から次の資料へ進むかを決め、似た名前の欄を勝手に辿らない。',
    2485: '',
    2486: '#### 2-5-16. 台帳契約と別の公開型・外付け',
    2487: '',
    2488: '| 対象 | 宣言上の位置 |',
    2489: '|---|---|',
    2490: '| 対象指定の発行済み認証物 | Q/R/全P/Cq・origin・固定像・registry・結果 digest に結合する F-a の新しい公開入口。生きた発行物と保存可能な説明値を分ける。◆G-01 |',
    2491: '| FWork | MeasureSegment / Compute / Draw。保存した要求と Desc に対応する実行用和型。新しい Body ではない。開始札・実行ハンドルを ledger の Point にしない |',
    2492: '| FStatus | 六つの意味を持つ読取り専用の公開像：受信保存、実行占有、生成取得認証採用、未判定不足Conflict、区間部分、未完目的引継ぎ。対象・像・保存済み Point または未保存保持との対応を付ける。判断入力や命令にはしない。B:1909〜1920 |',
    2493: '| 生きた H/P の識別 | PlanRef、封筒参照、開始札、実担当、未保存の完全な義務鍵。wire の Point と別型のまま保持する |',
    2494: '',
    2495: '| 外付け | 今回の扱い |',
    2496: '|---|---|',
    2497: '| sui.fb.generation_draw_requested/1 | R10。足す時に全欄・Body・時刻・参照・親を宣言する |',
    2498: '| sui.fb.generation_draw_unknown/1 | R10。同上。選択用 DU の名前だけの交換にしない |',
    2499: '| 再起動をまたぐ再確認・復元 | ★S5。H/P/Runners が失われる場合の証拠契約は今回足さない |',
    2500: '| 複数資源・別量型 | ★外付け。今回は一範囲・seats/1 一契約 |',
    2501: '',
    2502: 'もとの14名のうち二つは R10、candidate_generation/1 は内側の値契約である。「14個の新しい台帳 Record」とは数えない。',
    2503: '',
    2504: '> たとえ: PC の中で言うと、画面表示・実行中のハンドル・保存ファイルを別物として扱い、後で付ける機能は今回の接続済み一覧へ混ぜない。',
    2505: '',
    2506: '#### 2-5-17. 仮定と決定の出どころ',
    2507: '',
    2508: '仮定の数は、以下の名前付きの項目を単位に数える。個々のフィールド名の個数ではない。',
    2509: '',
    2510: '| 名前だけ | 内容 | 出どころ |',
    2511: '|---|---|---|',
    2512: '| N1 | 紙に名のない要求・処理記録・内側返答の sui.fb.* 名 | 第2便、今回採用 |',
    2513: '| N2 | Desc、FixedView、ReadingEvidence 等の補助型・和型タグ名 | 第2便、今回採用 |',
    2514: "| N3 | 今回の resource_scope/allocation/bootstrap_route/initial_process/environment/received_update の契約名、SlotValue/Projection 等の名、route='fb'、rejected の綴り | U3〜U6 を書くための識別名。seats/1 自体の仮称は今回の U3 指定 |",
    2515: '',
    2516: '| 意味を具体化 | 内容 | 出どころ |',
    2517: '|---|---|---|',
    2518: '| S1 | 一仕事一要求、旧 Q への参照、T.request の意味 | Q8 の具体化。第2便、今回採用 |',
    2519: '| S2 | BootSlot・FixedView・Desc の構造 | Q2/Q7/E0-04 の具体化。今回採用 |',
    2520: '| S3 | V/PR/EV/S/ST/Xc の論理欄と保存欄の分離 | E0-03・P1/P7。今回採用 |',
    2521: '| S4 | T 八欄の returned/basis の枝・null | B:776・1882。今回採用 |',
    2522: '| S5 | 新 D の inputs と用途別の最小親式 | Q7・A-03/A-04。今回採用 |',
    2523: '| T1 | Boot を SlotValue/SlottedMethod の入れ子として具体化 | U4、Q2。新しい適用記録は足さない |',
    2524: '| T2 | received_update/1 の全9欄と、差し替える方法の役割 | U4、B:623〜627。条件言語・周期・優先は固定しない |',
    2525: '| T3 | W 七欄を Projection と保存可能な識別に具体化 | U5、B:1320〜1333。完全な保持は H/P |',
    2526: '| T4 | seats/1、resource_scope、allocation と Need の契約位置 | U3、B:401・836〜840。負の差の扱いを明示し、量としての非負と混同しない |',
    2527: '| T5 | 起動環境の原文を environment/1.data に保持 | U4・P1、B:177・469。自由 JSON を認証済み環境へ自動解釈しない |',
    2528: '',
    2529: '| 既決の規則 | この稿への反映 |',
    2530: '|---|---|',
    2531: '| R-BODY | 四分類、W は規則4、九つ目の Body なし |',
    2532: '| Q1 | received 四欄、claims は原文、番号/seq は台帳に保存しない |',
    2533: '| Q2 | Boot 一記録の入れ子、BootSlot、適用は既存 route_config/origin |',
    2534: '| Q3 | 境界読みは inline、B は別記録、再計算できる鍵は非保存 |',
    2535: '| Q4 | 外側の終わりと内側の用途返答を分離。DrawValue は値のみ |',
    2536: '| Q5 | candidate_generation は内側、CG は既存 P |',
    2537: '| Q6 | R-BODY の四分類 |',
    2538: '| Q7 | O/D の最小親、P を親にしない、固定像は別型 |',
    2539: '| Q8 | Desc を持つ一仕事一要求、旧 /1 に欄を追加しない |',
    2540: '| U1 | 同一プロセス内の独立証拠を使う。台帳だけの限界を列挙。再起動は S5 |',
    2541: '| U2 | 論理成立時に M を一度読み r とする。r≤s。内部保存で架空の Accept なし |',
    2542: '| U3 | 量は版付き契約、今回の実例は非負整数の席数 |',
    2543: '| U4 | Boot の版付き宣言値と MethodCall の δ |',
    2544: '| U5 | W の保存可能部分と H/P の完全保持を分離 |',
    2545: '| U6 | Draw の Rejected は DrawFailure の failure_kind |',
    2546: '| C1 | 封筒の原本・番号・seq は同じプロセスの中だけ (Accept まで H、その後 P.receipts。紙の既存の引き継ぎのまま) |',
    2547: '',
    2548: '> たとえ: PC の中で言うと、仕様のどこが既存の規則で、どこが今回決めたデータ形式かを、変更履歴からたどれるようにする。',
    2549: '',
    2550: '#### 2-5-18. BLOCKER／直すべき／後で',
    2551: '',
    2552: '**BLOCKER**',
    2553: '',
    2554: '今回の最終稿の取りまとめを止める、新しい判断事項は見つからなかった。U1〜U6 は反映し、前便の U1/U2/U3/U4/U5/U6 を未決として残さない。',
    2555: '',
    2556: '一方、FBW-01 の「全型・全意味が閉じた」という合格判定には次が残る。',
    2557: '',
    2558: '- `verification_response/1` の verified/rejected/insufficient の全 payload と対象指定認証物の公開宣言は **◆G-01-9**。保存 DTO と生きた発行物の区別は閉じたが、対象 bytes/digest・結果・理由・不足・発行対応の全型は未定義。',
    2559: '- `/2` の args、数値射影、閉包、結果、statement/checker、CL-APPLY の意味は **◆G-01**。MethodCall/ContractValue の容器があることを意味の完成としない。',
    2560: '- δ や Need、生成器などの実際に選ぶ方法は、版付き宣言と実装の登録が必要。今回の型表は特定の未宣言メソッドを存在すると仮定していない。個別の方法が未宣言なら、その使用は missing_contract のまま。',
    2561: '',
    2562: '**直すべき**',
    2563: '',
    2564: '- R-BODY 4 の「再確認」を台帳限定と読めないよう、第2節の証拠範囲と S5 を併記する。',
    2565: '- 内部 O の r を U2 の意味で明記し、原報告 r の継承や null の未決表記を除く。',
    2566: '- B:1054 の B 七欄と CMP-23 を、view を含む八欄と解決規則へ統合する。',
    2567: '- B:1053・1146 の W は保存可能な投影と、H/P が持つ完全な識別を併記する。owner 欄だけで所有を証明しない。',
    2568: '- B:788・1970 の Failure/Rejected は U6 の注へ統一する。Wv の内側 Rejected へ一般化しない。',
    2569: '- Desc は13欄、T は8欄。T.request は当該仕事の F-b 要求と明記する。',
    2570: '',
    2571: 'これらはこの稿で置換文・表を用意した事項で、原本ファイルへはまだ反映していない。',
    2572: '',
    2573: '**後で**',
    2574: '',
    2575: '★S5、R10、複数資源・別量型、作用、At/When、割当変更は外付けのまま。FWork/FStatus の実装上のクラス分割は、宣言した意味と保持境界を変えずに実装段で接続する。今回の静的照合から模型や実装の合格を主張しない。',
    2576: '',
    2577: '> たとえ: PC の中で言うと、今回の設計図は渡せる状態になったが、未接続の認証部品まで動作済みの印を付けない。',
    2578: '',
    2579: '#### 2-5-19. G-01 に渡す10項目',
    2580: '',
    2581: '以下を次回の正の番号とする。前々便の番号との照合は要しない。今回、数値設計の問いを閉じたとは判定しない。',
    2582: '',
    2583: '| 番号 | 次回に決める問い | 今回で明確になった前提 |',
    2584: '|---|---|---|',
    2585: '| 1 数値射影 | B の Frame/Gap/Unavailable/Claim/Unproved のどの意味を、どの数値入力へ射影するか | 原報告・読み方・生成・時計・view の保存先 |',
    2586: '| 2 必須閉包 | method/origin/args から何を必須にし、inputs の余分・不足をどう照合するか | Desc.input_points、Xnum、実親を区別 |',
    2587: '| 3 前の結果 | previous_result の認証・過去 Q/R/P/Cq・採用系列をどう閉じるか | 旧 Q と F-b の仕事要求を分離 |',
    2588: '| 4 時計 | inline 読みと clock.source/clock_reading、区間 i、r/s、o/j の合法性をどう検査するか | 原報告の形と論理 O の r は決定。/2 の用途別時間条件は残る |',
    2589: '| 5 bootstrap の生成 | 旧 /1 の Attempt 条件を緩めず、k・適用・Started・B から /2 の生成をどう認証するか | 境界報告と B、独立実行証拠の位置 |',
    2590: '| 6 食い違い | Xnum と使用直前 Xuse をどう使い分け、どの依存先まで Conflict を伝播させるか | Xc の規則・報告・像、affected の独立計算 |',
    2591: '| 7 実取得 | 元測定・B・R/P の何を、どの origin が実取得し、どの祖先で証明するか | 取得意図/G、E/UE、EA の役割 |',
    2592: '| 8 再計算と結果 | /2 の正規化・joint/evidence_mass 等を、どの出力契約で全比較するか | WorkOutputs の内側の置場 |',
    2593: '| 9 証明と認証物 | /2 statement/checker、対象指定 verified/rejected/insufficient、発行物の全欄と結合をどう宣言するか | 実行終端と内側返答、V と生きた発行物を分離 |',
    2594: '| 10 採用と replay | 現在の前採用・実取得・認証物・Xuse をどう照合し、保存時の reader/registry でどう再読するか | 採用意図/ST、FixedView、同一プロセスの独立証拠と S5 の境界 |',
    2595: '',
    2596: '> たとえ: PC の中で言うと、データの置場と受け渡し方が決まったので、次は計算器と認証器がそのデータをどう正しく読むかを詰める。',
    2597: '',
}

PUBLIC_CLASS_DECLARATIONS = (
    {'name': 'Unavailable', 'line': 153, 'docstring': '未取得値。F-a で検査する: 理由と根拠。0・False・nullとは別。', 'fields': ({'name': 'reason', 'type': 'str', 'line': 155, 'references': ('str',), 'literal_values': ()}, {'name': 'basis', 'type': 'tuple[_Ref, ...]', 'line': 156, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'ExactReal', 'line': 160, 'docstring': 'F-a で検査する: op 別の厳密式、log の正の引数、非零分母。\n現状の全引数を採用。無関係な引数は None のみで JSON に出さない。\nrational は Fraction を既約Rへ符号化。0 log 0 は式を作らず寄与0。', 'fields': ({'name': 'op', 'type': "_Literal['rational', 'log', 'exp', 'add', 'mul', 'neg', 'div']", 'line': 164, 'references': ('_Literal', 'add', 'div', 'exp', 'log', 'mul', 'neg', 'rational'), 'literal_values': ('rational', 'log', 'exp', 'add', 'mul', 'neg', 'div')}, {'name': 'value', 'type': '_Fraction | None', 'line': 165, 'references': ('_Fraction',), 'literal_values': ()}, {'name': 'arg', 'type': 'ExactReal | None', 'line': 166, 'references': ('ExactReal',), 'literal_values': ()}, {'name': 'args', 'type': 'tuple[ExactReal, ...] | None', 'line': 167, 'references': ('ExactReal', 'tuple'), 'literal_values': ()}, {'name': 'numerator', 'type': 'ExactReal | None', 'line': 168, 'references': ('ExactReal',), 'literal_values': ()}, {'name': 'denominator', 'type': 'ExactReal | None', 'line': 169, 'references': ('ExactReal',), 'literal_values': ()})},
    {'name': 'ActionFamilyRef', 'line': 173, 'docstring': '操作族の版。F-a で検査する: 名前・版と認証範囲。動機enumにしない。', 'fields': ({'name': 'name', 'type': 'str', 'line': 175, 'references': ('str',), 'literal_values': ()}, {'name': 'version', 'type': 'str', 'line': 176, 'references': ('str',), 'literal_values': ()})},
    {'name': 'PredicateRef', 'line': 180, 'docstring': 'F-a で検査する: 状態型・依存・検査法・版・認証範囲と凍結したargs。', 'fields': ({'name': 'name', 'type': 'str', 'line': 182, 'references': ('str',), 'literal_values': ()}, {'name': 'version', 'type': 'str', 'line': 183, 'references': ('str',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 184, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'KernelRef', 'line': 188, 'docstring': 'F-a で検査する: 意味の版 finite_kernel/1 と args.id の宣言内 ID。\nname を kernel ID にせず、モデルは外側の FProblem から解決する。', 'fields': ({'name': 'name', 'type': 'str', 'line': 192, 'references': ('str',), 'literal_values': ()}, {'name': 'version', 'type': 'str', 'line': 193, 'references': ('str',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 194, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'PolicyRef', 'line': 198, 'docstring': 'F-a で検査する: 意味の版 finite_policy/1 と args.id、K 可測性。\nname を policy ID にせず、実行中は受信ごとに別方針へ替えない。', 'fields': ({'name': 'name', 'type': 'str', 'line': 202, 'references': ('str',), 'literal_values': ()}, {'name': 'version', 'type': 'str', 'line': 203, 'references': ('str',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 204, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'ProofRef', 'line': 208, 'docstring': 'F-a で検査する: 証明器の版・引数・根拠。自己申告だけでは認証しない。', 'fields': ({'name': 'name', 'type': 'str', 'line': 210, 'references': ('str',), 'literal_values': ()}, {'name': 'version', 'type': 'str', 'line': 211, 'references': ('str',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 212, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'QuantityRef', 'line': 216, 'docstring': 'F-a で検査する: 照会の宣言を識別する key と対象・根。数値を key に埋めない。', 'fields': ({'name': 'key', 'type': 'str', 'line': 218, 'references': ('str',), 'literal_values': ()},)},
    {'name': 'DependencyRef', 'line': 222, 'docstring': 'F-a で検査する: 依存先の key と出どころ basis の解決可能性。', 'fields': ({'name': 'key', 'type': 'str', 'line': 224, 'references': ('str',), 'literal_values': ()}, {'name': 'basis', 'type': 'tuple[_Ref, ...]', 'line': 225, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'ActionSpec', 'line': 229, 'docstring': '操作の宣言。F-a で検査する: 全参照、開始・方針・ψ・終わり方、\n予測と実行の適合、族の正準化か検査可能な別名証明によるsemantic_key。\n表示名や発見入口をsemantic_keyへ含めず、異なる機会は区別する。\nfinite_option/1.args は opportunity と path_action。path_action=null は\n内部処理と宣言した場合だけ。開始は実行前、終了は一回以上の実遷移後。\nfinite_option_proof/1.args は operation。simulated_execution/1 を実機に流用しない。', 'fields': ({'name': 'id', 'type': 'str', 'line': 237, 'references': ('str',), 'literal_values': ()}, {'name': 'family', 'type': 'ActionFamilyRef', 'line': 238, 'references': ('ActionFamilyRef',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 239, 'references': ('ImmutableJSON',), 'literal_values': ()}, {'name': 'start', 'type': 'PredicateRef', 'line': 240, 'references': ('PredicateRef',), 'literal_values': ()}, {'name': 'policy', 'type': 'PolicyRef', 'line': 241, 'references': ('PolicyRef',), 'literal_values': ()}, {'name': 'termination', 'type': 'PredicateRef', 'line': 242, 'references': ('PredicateRef',), 'literal_values': ()}, {'name': 'termination_kind', 'type': "_Literal['certain', 'may_never']", 'line': 243, 'references': ('_Literal', 'certain', 'may_never'), 'literal_values': ('certain', 'may_never')}, {'name': 'prediction', 'type': 'KernelRef', 'line': 244, 'references': ('KernelRef',), 'literal_values': ()}, {'name': 'execution', 'type': '_ContractRef', 'line': 245, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'proof', 'type': 'ProofRef', 'line': 246, 'references': ('ProofRef',), 'literal_values': ()}, {'name': 'semantic_key', 'type': 'str', 'line': 247, 'references': ('str',), 'literal_values': ()})},
    {'name': 'PredicateWork', 'line': 260, 'docstring': 'F-a で検査する: predicate/snapshot/missing の digest による安定した work_id。\n同じ Unknown の配送で重い仕事を増やさず、検査は窓口の外で行う。', 'fields': ({'name': 'work_id', 'type': 'str', 'line': 263, 'references': ('str',), 'literal_values': ()}, {'name': 'predicate', 'type': 'PredicateRef', 'line': 264, 'references': ('PredicateRef',), 'literal_values': ()}, {'name': 'snapshot', 'type': 'PredicateSnapshot', 'line': 265, 'references': ('PredicateSnapshot',), 'literal_values': ()}, {'name': 'missing', 'type': 'tuple[DependencyRef, ...]', 'line': 266, 'references': ('DependencyRef', 'tuple'), 'literal_values': ()})},
    {'name': 'CandidateMeasureRef', 'line': 343, 'docstring': 'F-a で検査する: 測度の版と引数。最初の成功範囲はcounting/1。', 'fields': ({'name': 'name', 'type': 'str', 'line': 345, 'references': ('str',), 'literal_values': ()}, {'name': 'version', 'type': 'str', 'line': 346, 'references': ('str',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 347, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'CandidateSet', 'line': 351, 'docstring': 'F-a で検査する: 順序・別名・測度・生成根拠・draw。未認証を消さない。', 'fields': ({'name': 'candidates', 'type': 'tuple[ActionSpec, ...]', 'line': 353, 'references': ('ActionSpec', 'tuple'), 'literal_values': ()}, {'name': 'aliases', 'type': '_Mapping[str, str]', 'line': 354, 'references': ('_Mapping', 'str'), 'literal_values': ()}, {'name': 'measure', 'type': 'CandidateMeasureRef | None', 'line': 355, 'references': ('CandidateMeasureRef',), 'literal_values': ()}, {'name': 'generator', 'type': '_ContractRef', 'line': 356, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'basis', 'type': 'tuple[_Ref, ...]', 'line': 357, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'draws', 'type': 'tuple[DrawRecord, ...]', 'line': 358, 'references': ('DrawRecord', 'tuple'), 'literal_values': ()})},
    {'name': 'EvaluationScope', 'line': 362, 'docstring': 'F-a で検査する: 範囲版1、finite_horizonの非負Hと本人の紙のsource。\nunbounded_total/one_stepはH_ns=None。source=Noneは白紙か明示互換だけ。', 'fields': ({'name': 'name', 'type': "_Literal['unbounded_total', 'one_step', 'finite_horizon']", 'line': 366, 'references': ('_Literal', 'finite_horizon', 'one_step', 'unbounded_total'), 'literal_values': ('unbounded_total', 'one_step', 'finite_horizon')}, {'name': 'version', 'type': "_Literal['1']", 'line': 367, 'references': ('_Literal',), 'literal_values': ('1',)}, {'name': 'H_ns', 'type': 'int | None', 'line': 368, 'references': ('int',), 'literal_values': ()}, {'name': 'source', 'type': '_Ref | None', 'line': 369, 'references': ('_Ref',), 'literal_values': ()})},
    {'name': 'CandidateExclusion', 'line': 373, 'docstring': 'F-a で検査する: 開始不能/許容不能の検査可能な証明。未認証候補を除かない。', 'fields': ({'name': 'candidate', 'type': 'str', 'line': 375, 'references': ('str',), 'literal_values': ()}, {'name': 'reason', 'type': 'str', 'line': 376, 'references': ('str',), 'literal_values': ()}, {'name': 'proof', 'type': 'ProofRef', 'line': 377, 'references': ('ProofRef',), 'literal_values': ()})},
    {'name': 'NormalizationCertificate', 'line': 381, 'docstring': 'F-a で検査する: 同じ問題の測度・許容候補・除外証明と0<Z<∞の保証。', 'fields': ({'name': 'problem_key', 'type': 'str', 'line': 383, 'references': ('str',), 'literal_values': ()}, {'name': 'measure', 'type': 'CandidateMeasureRef', 'line': 384, 'references': ('CandidateMeasureRef',), 'literal_values': ()}, {'name': 'admissible', 'type': 'tuple[str, ...]', 'line': 385, 'references': ('str', 'tuple'), 'literal_values': ()}, {'name': 'excluded', 'type': 'tuple[CandidateExclusion, ...]', 'line': 386, 'references': ('CandidateExclusion', 'tuple'), 'literal_values': ()}, {'name': 'Z', 'type': 'RationalInterval', 'line': 387, 'references': ('RationalInterval',), 'literal_values': ()}, {'name': 'proof', 'type': 'ProofRef', 'line': 388, 'references': ('ProofRef',), 'literal_values': ()})},
    {'name': 'MeasurementId', 'line': 392, 'docstring': 'F-a で検査する: origin・経路世代・連番・component。本文一致と別物。', 'fields': ({'name': 'origin', 'type': '_Ref', 'line': 394, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'route_epoch', 'type': 'str', 'line': 395, 'references': ('str',), 'literal_values': ()}, {'name': 'sample_seq', 'type': 'int', 'line': 396, 'references': ('int',), 'literal_values': ()}, {'name': 'component', 'type': 'str', 'line': 397, 'references': ('str',), 'literal_values': ()})},
    {'name': 'EvidenceLink', 'line': 401, 'docstring': 'F-a で検査する: 原記録・生成元・派生元・契約。同じ機会と独立機会を区別。', 'fields': ({'name': 'measurement', 'type': 'MeasurementId', 'line': 403, 'references': ('MeasurementId',), 'literal_values': ()}, {'name': 'records', 'type': 'tuple[_Ref, ...]', 'line': 404, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'generated_by', 'type': 'tuple[_Ref, ...]', 'line': 405, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'derived_from', 'type': 'tuple[MeasurementId, ...]', 'line': 406, 'references': ('MeasurementId', 'tuple'), 'literal_values': ()}, {'name': 'contract', 'type': '_ContractRef', 'line': 407, 'references': ('_ContractRef',), 'literal_values': ()})},
    {'name': 'EvidenceHistory', 'line': 411, 'docstring': 'build_histories が原記録から構築する E の DTO。\nF-a で検査する: 全配送の出どころ・生成関係。手組みの内容は未検査。', 'fields': ({'name': 'key', 'type': 'str', 'line': 414, 'references': ('str',), 'literal_values': ()}, {'name': 'links', 'type': 'tuple[EvidenceLink, ...]', 'line': 415, 'references': ('EvidenceLink', 'tuple'), 'literal_values': ()}, {'name': 'coverage', 'type': 'tuple[CoverageClaim, ...]', 'line': 416, 'references': ('CoverageClaim', 'tuple'), 'literal_values': ()}, {'name': 'gaps', 'type': 'tuple[Gap, ...]', 'line': 417, 'references': ('Gap', 'tuple'), 'literal_values': ()})},
    {'name': 'KnowledgeHistory', 'line': 421, 'docstring': 'build_histories が構築する K の DTO。F-a で検査する: E と証明の解決。\navailable と incorporated を分け、未計算を反映済みとせず手組みを信用しない。', 'fields': ({'name': 'key', 'type': 'str', 'line': 424, 'references': ('str',), 'literal_values': ()}, {'name': 'available', 'type': 'tuple[MeasurementId, ...]', 'line': 425, 'references': ('MeasurementId', 'tuple'), 'literal_values': ()}, {'name': 'incorporated', 'type': 'tuple[MeasurementId, ...]', 'line': 426, 'references': ('MeasurementId', 'tuple'), 'literal_values': ()}, {'name': 'belief', 'type': '_Ref | None', 'line': 427, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'kernel_basis', 'type': 'tuple[_Ref, ...]', 'line': 428, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'normalization_proofs', 'type': 'tuple[_Ref, ...]', 'line': 429, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'query_proofs', 'type': 'tuple[_Ref, ...]', 'line': 430, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'pending', 'type': 'tuple[DependencyRef, ...]', 'line': 431, 'references': ('DependencyRef', 'tuple'), 'literal_values': ()})},
    {'name': 'FContext', 'line': 435, 'docstring': 'F-a で検査する: 同 run の整数 ns・時計契約・検査時機。\nfact_ancestors は CID -> その時点で読める FactRecord の Ref 文字列集合。\nレコードIDを CID と取り違えず、別 run を自動整列しない。', 'fields': ({'name': 'run', 'type': '_Ref', 'line': 439, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'now_ns', 'type': 'int', 'line': 440, 'references': ('int',), 'literal_values': ()}, {'name': 'observed_ns', 'type': 'int', 'line': 441, 'references': ('int',), 'literal_values': ()}, {'name': 'clock_contract', 'type': '_ContractRef', 'line': 442, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'check_events', 'type': 'tuple[ImmutableJSON, ...]', 'line': 443, 'references': ('ImmutableJSON', 'tuple'), 'literal_values': ()}, {'name': 'fact_ancestors', 'type': '_Mapping[str, frozenset[str]]', 'line': 444, 'references': ('_Mapping', 'frozenset', 'str'), 'literal_values': ()})},
    {'name': 'FRoot', 'line': 448, 'docstring': 'bind_f_draw / restore_f_root (f_facts) が返す検査済みハンドル。\nF-a で検査する: 問題・資源・continuation・selection draw の全欄の結合。\n一度の発火は同根/uを再使用し、別発火は帳面が別 ordinal を受付する。\n手組み・構造復号だけを認証せず、後着事実を根に取り込まない。', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 453, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'problem_key', 'type': 'str', 'line': 454, 'references': ('str',), 'literal_values': ()}, {'name': 'root_key', 'type': 'str', 'line': 455, 'references': ('str',), 'literal_values': ()}, {'name': 'world_key', 'type': 'str', 'line': 456, 'references': ('str',), 'literal_values': ()}, {'name': 'world_manifest', 'type': "'FWorldManifest3'", 'line': 457, 'references': ('FWorldManifest3',), 'literal_values': ()}, {'name': 'model_ref', 'type': 'str', 'line': 458, 'references': ('str',), 'literal_values': ()}, {'name': 'parents', 'type': 'frozenset[str]', 'line': 459, 'references': ('frozenset', 'str'), 'literal_values': ()}, {'name': 'facts', 'type': 'tuple[_Ref, ...]', 'line': 460, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'E', 'type': 'EvidenceHistory', 'line': 461, 'references': ('EvidenceHistory',), 'literal_values': ()}, {'name': 'K', 'type': 'KnowledgeHistory', 'line': 462, 'references': ('KnowledgeHistory',), 'literal_values': ()}, {'name': 'context', 'type': 'FContext', 'line': 463, 'references': ('FContext',), 'literal_values': ()}, {'name': 'preferences', 'type': 'tuple[_Ref, ...]', 'line': 464, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'style', 'type': '_Ref | None', 'line': 465, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'scope', 'type': 'EvaluationScope', 'line': 466, 'references': ('EvaluationScope',), 'literal_values': ()}, {'name': 'gamma', 'type': '_Fraction', 'line': 467, 'references': ('_Fraction',), 'literal_values': ()}, {'name': 'candidates', 'type': 'CandidateSet', 'line': 468, 'references': ('CandidateSet',), 'literal_values': ()}, {'name': 'continuation', 'type': 'FContinuation', 'line': 469, 'references': ('FContinuation',), 'literal_values': ()}, {'name': 'measurement_contracts', 'type': 'tuple[_ContractRef, ...]', 'line': 470, 'references': ('_ContractRef', 'tuple'), 'literal_values': ()}, {'name': 'execution_contracts', 'type': 'tuple[_ContractRef, ...]', 'line': 471, 'references': ('_ContractRef', 'tuple'), 'literal_values': ()}, {'name': 'method', 'type': '_ContractRef', 'line': 472, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'selection_draw', 'type': 'DrawRecord', 'line': 473, 'references': ('DrawRecord',), 'literal_values': ()}, {'name': 'draw_point', 'type': 'str | None', 'line': 475, 'references': ('str',), 'literal_values': ()}, {'name': 'draw_record_digest', 'type': 'str | None', 'line': 476, 'references': ('str',), 'literal_values': ()})},
    {'name': 'DrawRecord', 'line': 484, 'docstring': 'F-a で検査する: request と purpose/context_key/ordinal の一致、生成器・stream・値域。\nrequest.law は分布、generator は供給実装で別契約。\nid は正準 JSON {domain:"sui.f.draw/1",generator,stream_id,purpose,context_key,ordinal}\nの SHA-256 に sha256: を付ける。value を ID に含めず同 ID の値衝突を検出する。', 'fields': ({'name': 'id', 'type': 'str', 'line': 489, 'references': ('str',), 'literal_values': ()}, {'name': 'purpose', 'type': "_Literal['candidate_generation', 'selection', 'reservation', 'algorithm']", 'line': 490, 'references': ('_Literal', 'algorithm', 'candidate_generation', 'reservation', 'selection'), 'literal_values': ('candidate_generation', 'selection', 'reservation', 'algorithm')}, {'name': 'generator', 'type': '_ContractRef', 'line': 491, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'stream_id', 'type': 'str', 'line': 492, 'references': ('str',), 'literal_values': ()}, {'name': 'request', 'type': 'DrawRequest', 'line': 493, 'references': ('DrawRequest',), 'literal_values': ()}, {'name': 'context_key', 'type': 'str', 'line': 494, 'references': ('str',), 'literal_values': ()}, {'name': 'ordinal', 'type': 'int', 'line': 495, 'references': ('int',), 'literal_values': ()}, {'name': 'value', 'type': 'ImmutableJSON', 'line': 496, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'FQuantity', 'line': 500, 'docstring': 'F-a で検査する: 構造的0・有限式と保証・証明済み∞・未認証の区別。', 'fields': ({'name': 'status', 'type': "_Literal['finite', 'positive_infinity', 'uncertified']", 'line': 502, 'references': ('_Literal', 'finite', 'positive_infinity', 'uncertified'), 'literal_values': ('finite', 'positive_infinity', 'uncertified')}, {'name': 'exact', 'type': 'ExactReal | None', 'line': 503, 'references': ('ExactReal',), 'literal_values': ()}, {'name': 'bounds', 'type': 'RationalInterval | None', 'line': 504, 'references': ('RationalInterval',), 'literal_values': ()}, {'name': 'proof', 'type': 'ProofRef | None', 'line': 505, 'references': ('ProofRef',), 'literal_values': ()}, {'name': 'reason', 'type': 'str | None', 'line': 506, 'references': ('str',), 'literal_values': ()})},
    {'name': 'TailCertificate', 'line': 522, 'docstring': 'F-a で検査する: prefix 表の digest、I_n、情報の残り、独立の費用保証。\nzero は情報と費用の残りが厳密0。residual_mass が正でも永久未着を区別できる。\nanalytic は厳密式を保持、bounded は非零を捨てず、未証明は unproved。', 'fields': ({'name': 'problem_key', 'type': 'str', 'line': 526, 'references': ('str',), 'literal_values': ()}, {'name': 'candidate', 'type': 'str', 'line': 527, 'references': ('str',), 'literal_values': ()}, {'name': 'prefix', 'type': 'TailPrefix', 'line': 528, 'references': ('TailPrefix',), 'literal_values': ()}, {'name': 'information_prefix', 'type': 'FQuantity', 'line': 529, 'references': ('FQuantity',), 'literal_values': ()}, {'name': 'information_remaining', 'type': 'FQuantity', 'line': 530, 'references': ('FQuantity',), 'literal_values': ()}, {'name': 'cost_total', 'type': 'FQuantity', 'line': 531, 'references': ('FQuantity',), 'literal_values': ()}, {'name': 'residual_mass', 'type': 'FQuantity', 'line': 532, 'references': ('FQuantity',), 'literal_values': ()}, {'name': 'closure', 'type': "_Literal['zero', 'analytic', 'bounded', 'unproved']", 'line': 533, 'references': ('_Literal', 'analytic', 'bounded', 'unproved', 'zero'), 'literal_values': ('zero', 'analytic', 'bounded', 'unproved')}, {'name': 'proof', 'type': 'ProofRef | None', 'line': 534, 'references': ('ProofRef',), 'literal_values': ()})},
    {'name': 'InformationParts', 'line': 538, 'docstring': 'F-a で検査する: total=already_received+additional。O0を一度数える。', 'fields': ({'name': 'already_received', 'type': 'FQuantity', 'line': 540, 'references': ('FQuantity',), 'literal_values': ()}, {'name': 'additional', 'type': 'FQuantity', 'line': 541, 'references': ('FQuantity',), 'literal_values': ()}, {'name': 'total_information', 'type': 'FQuantity', 'line': 542, 'references': ('FQuantity',), 'literal_values': ()})},
    {'name': 'FCertificate', 'line': 546, 'docstring': 'F-a で検査する: 根・方法・arithmetic・予算・trace・保証・残りの一致。\ntoleranceは診断幅であり情報の尾を捨てるεでも誤選択確率でもない。', 'fields': ({'name': 'problem_key', 'type': 'str', 'line': 550, 'references': ('str',), 'literal_values': ()}, {'name': 'root_key', 'type': 'str', 'line': 551, 'references': ('str',), 'literal_values': ()}, {'name': 'method', 'type': '_ContractRef', 'line': 552, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'arithmetic', 'type': '_ContractRef', 'line': 553, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 554, 'references': ('RateBudget',), 'literal_values': ()}, {'name': 'trace', 'type': 'tuple[ContractValue, ...]', 'line': 555, 'references': ('ContractValue', 'tuple'), 'literal_values': ()}, {'name': 'enclosures', 'type': 'ImmutableJSON', 'line': 556, 'references': ('ImmutableJSON',), 'literal_values': ()}, {'name': 'residuals', 'type': 'tuple[ImmutableJSON, ...]', 'line': 557, 'references': ('ImmutableJSON', 'tuple'), 'literal_values': ()})},
    {'name': 'FEvaluation', 'line': 561, 'docstring': 'F-a で検査する: 候補順と各値の軸、Z、尾と累積候補数+1。\n正規化を認証した時だけ末尾1。中点や表示値で選ばない。', 'fields': ({'name': 'root', 'type': 'FRoot', 'line': 565, 'references': ('FRoot',), 'literal_values': ()}, {'name': 'candidates', 'type': 'tuple[str, ...]', 'line': 566, 'references': ('str', 'tuple'), 'literal_values': ()}, {'name': 'expected_cost', 'type': 'tuple[FQuantity, ...]', 'line': 567, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'information', 'type': 'tuple[InformationParts, ...]', 'line': 568, 'references': ('InformationParts', 'tuple'), 'literal_values': ()}, {'name': 'G', 'type': 'tuple[FQuantity, ...]', 'line': 569, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'J', 'type': 'tuple[FQuantity, ...]', 'line': 570, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'q_star', 'type': 'tuple[FQuantity, ...]', 'line': 571, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'cumulative', 'type': 'tuple[RationalInterval, ...]', 'line': 572, 'references': ('RationalInterval', 'tuple'), 'literal_values': ()}, {'name': 'normalization', 'type': 'NormalizationCertificate | None', 'line': 573, 'references': ('NormalizationCertificate',), 'literal_values': ()}, {'name': 'tails', 'type': 'tuple[TailCertificate, ...]', 'line': 574, 'references': ('TailCertificate', 'tuple'), 'literal_values': ()}, {'name': 'certificate', 'type': 'FCertificate', 'line': 575, 'references': ('FCertificate',), 'literal_values': ()})},
    {'name': 'Selected', 'line': 579, 'docstring': 'F-a で検査する: 根・評価・index・操作・uと保証。静けさも本物の選択。\nprevious.upper<=u<current.lowerまたは認証した境界等値を要する。', 'fields': ({'name': 'root', 'type': 'FRoot', 'line': 583, 'references': ('FRoot',), 'literal_values': ()}, {'name': 'evaluation', 'type': 'FEvaluation', 'line': 584, 'references': ('FEvaluation',), 'literal_values': ()}, {'name': 'index', 'type': 'int', 'line': 585, 'references': ('int',), 'literal_values': ()}, {'name': 'choice', 'type': 'ActionSpec', 'line': 586, 'references': ('ActionSpec',), 'literal_values': ()}, {'name': 'u', 'type': '_Fraction', 'line': 587, 'references': ('_Fraction',), 'literal_values': ()}, {'name': 'previous', 'type': 'RationalInterval', 'line': 588, 'references': ('RationalInterval',), 'literal_values': ()}, {'name': 'current', 'type': 'RationalInterval', 'line': 589, 'references': ('RationalInterval',), 'literal_values': ()}, {'name': 'certificate', 'type': 'FCertificate', 'line': 590, 'references': ('FCertificate',), 'literal_values': ()})},
    {'name': 'NoDecision', 'line': 599, 'docstring': 'F-a で検査する: 未完了・拒否・故障の理由と証明・進捗・再開の対応。\nSuspend・静けさ・取消の選択ではない。不正入力や改ざんをここへ薄めない。', 'fields': ({'name': 'attempt_id', 'type': 'str | None', 'line': 603, 'references': ('str',), 'literal_values': ()}, {'name': 'root_key', 'type': 'str | None', 'line': 604, 'references': ('str',), 'literal_values': ()}, {'name': 'outcome', 'type': "_Literal['incomplete', 'rejected', 'failed']", 'line': 605, 'references': ('_Literal', 'failed', 'incomplete', 'rejected'), 'literal_values': ('incomplete', 'rejected', 'failed')}, {'name': 'reason', 'type': 'NoDecisionReason', 'line': 606, 'references': ('NoDecisionReason',), 'literal_values': ()}, {'name': 'detail', 'type': 'str', 'line': 607, 'references': ('str',), 'literal_values': ()}, {'name': 'field', 'type': 'str | None', 'line': 608, 'references': ('str',), 'literal_values': ()}, {'name': 'proof', 'type': 'ProofRef | None', 'line': 609, 'references': ('ProofRef',), 'literal_values': ()}, {'name': 'progress', 'type': 'FEvaluation | None', 'line': 610, 'references': ('FEvaluation',), 'literal_values': ()}, {'name': 'resume', 'type': 'ResumePoint | None', 'line': 611, 'references': ('ResumePoint',), 'literal_values': ()})},
    {'name': 'PredicateSnapshot', 'line': 626, 'docstring': 'F-a で検査する: モデル参照、取得済み E/K/数量/依存/位置と同じ資源束。\nmodel_ref=None はモデルを読まない述語だけ。policy_end はモデル内の節 kind を読む。\nquantities の JSON は正準 key bytes 順の key/value 配列。取得中に重い推論なし。', 'fields': ({'name': 'model_ref', 'type': 'str | None', 'line': 630, 'references': ('str',), 'literal_values': ()}, {'name': 'E', 'type': 'EvidenceHistory', 'line': 631, 'references': ('EvidenceHistory',), 'literal_values': ()}, {'name': 'K', 'type': 'KnowledgeHistory', 'line': 632, 'references': ('KnowledgeHistory',), 'literal_values': ()}, {'name': 'quantities', 'type': '_Mapping[QuantityRef, FQuantity]', 'line': 633, 'references': ('FQuantity', 'QuantityRef', '_Mapping'), 'literal_values': ()}, {'name': 'dependencies', 'type': 'tuple[DependencyRef, ...]', 'line': 634, 'references': ('DependencyRef', 'tuple'), 'literal_values': ()}, {'name': 'policy_position', 'type': 'PredicatePosition | None', 'line': 635, 'references': ('PredicatePosition',), 'literal_values': ()})},
    {'name': 'FScope', 'line': 649, 'docstring': 'F-a で検査する: 認証・未完了・意味不足・型の外・実行未認証の区別。\nconditions は ContractValue の列。登録名だけを証明にしない。', 'fields': ({'name': 'status', 'type': "_Literal['certified', 'incomplete', 'missing_spec', 'outside_evaluation', 'runtime_unverified']", 'line': 652, 'references': ('_Literal', 'certified', 'incomplete', 'missing_spec', 'outside_evaluation', 'runtime_unverified'), 'literal_values': ('certified', 'incomplete', 'missing_spec', 'outside_evaluation', 'runtime_unverified')}, {'name': 'method', 'type': '_ContractRef | None', 'line': 653, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'reason', 'type': 'str | None', 'line': 654, 'references': ('str',), 'literal_values': ()}, {'name': 'conditions', 'type': 'tuple[ContractValue, ...]', 'line': 655, 'references': ('ContractValue', 'tuple'), 'literal_values': ()})},
    {'name': 'FPathRow', 'line': 659, 'docstring': 'F-a で検査する: 候補軸、路と対象の共同質量、実際に見える E/K の履歴。\njoint_target の和は probability。隠れた outcome を別観測として分けない。', 'fields': ({'name': 'candidate', 'type': 'str', 'line': 662, 'references': ('str',), 'literal_values': ()}, {'name': 'probability', 'type': 'ExactReal', 'line': 663, 'references': ('ExactReal',), 'literal_values': ()}, {'name': 'joint_target', 'type': 'tuple[ExactReal, ...]', 'line': 664, 'references': ('ExactReal', 'tuple'), 'literal_values': ()}, {'name': 'E_trace', 'type': 'tuple[EvidenceHistory, ...]', 'line': 665, 'references': ('EvidenceHistory', 'tuple'), 'literal_values': ()}, {'name': 'K_trace', 'type': 'tuple[KnowledgeHistory, ...]', 'line': 666, 'references': ('KnowledgeHistory', 'tuple'), 'literal_values': ()}, {'name': 'actions', 'type': 'tuple[ActionSpec, ...]', 'line': 667, 'references': ('ActionSpec', 'tuple'), 'literal_values': ()}, {'name': 'terminal', 'type': 'FPathTerminal', 'line': 668, 'references': ('FPathTerminal',), 'literal_values': ()})},
    {'name': 'FPathTable', 'line': 671, 'docstring': 'F-a で検査する: 根、候補別の終端・未展開質量の和1と共同状態の保持。\ncomplete は frontier が空、residual が候補ごとに厳密0。prefix を全路と呼ばない。\nsteps は展開の深さであり評価範囲 H ではない。', 'fields': ({'name': 'problem_key', 'type': 'str', 'line': 675, 'references': ('str',), 'literal_values': ()}, {'name': 'root_key', 'type': 'str', 'line': 676, 'references': ('str',), 'literal_values': ()}, {'name': 'kind', 'type': "_Literal['complete', 'prefix']", 'line': 677, 'references': ('_Literal', 'complete', 'prefix'), 'literal_values': ('complete', 'prefix')}, {'name': 'steps', 'type': 'int | None', 'line': 678, 'references': ('int',), 'literal_values': ()}, {'name': 'candidates', 'type': 'tuple[str, ...]', 'line': 679, 'references': ('str', 'tuple'), 'literal_values': ()}, {'name': 'rows', 'type': 'tuple[FPathRow, ...]', 'line': 680, 'references': ('FPathRow', 'tuple'), 'literal_values': ()}, {'name': 'frontier', 'type': 'tuple[FFrontierRow, ...]', 'line': 681, 'references': ('FFrontierRow', 'tuple'), 'literal_values': ()}, {'name': 'residual', 'type': 'tuple[FPathResidual, ...]', 'line': 682, 'references': ('FPathResidual', 'tuple'), 'literal_values': ()}, {'name': 'nodes', 'type': 'tuple[FNodeValue, ...]', 'line': 683, 'references': ('FNodeValue', 'tuple'), 'literal_values': ()})},
    {'name': 'LegacyComparison', 'line': 686, 'docstring': 'F-a で検査する: 対象・候補対応・所要・測定時刻・範囲・好み・O0 の橋。\nassumptions は ContractValue の列。旧 float を新しい保証値へ格上げしない。', 'fields': ({'name': 'legacy_contract', 'type': '_ContractRef', 'line': 689, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'assumptions', 'type': 'tuple[ContractValue, ...]', 'line': 690, 'references': ('ContractValue', 'tuple'), 'literal_values': ()}, {'name': 'old_information', 'type': 'tuple[float, ...]', 'line': 691, 'references': ('float', 'tuple'), 'literal_values': ()}, {'name': 'reconstructed_information', 'type': 'tuple[FQuantity, ...]', 'line': 692, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'old_J', 'type': 'tuple[float, ...]', 'line': 693, 'references': ('float', 'tuple'), 'literal_values': ()}, {'name': 'new_J', 'type': 'tuple[FQuantity, ...]', 'line': 694, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'old_probabilities', 'type': 'tuple[float, ...]', 'line': 695, 'references': ('float', 'tuple'), 'literal_values': ()}, {'name': 'new_probabilities', 'type': 'tuple[FQuantity, ...]', 'line': 696, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'old_choice', 'type': 'str', 'line': 697, 'references': ('str',), 'literal_values': ()}, {'name': 'new_choice', 'type': 'str', 'line': 698, 'references': ('str',), 'literal_values': ()})},
    {'name': 'ResumePoint', 'line': 702, 'docstring': 'F-a で検査する: 同根・方法・arithmetic・trace・状態 digest と前証明。\n外形は採用済み。stage の版・payload の内部 schema は F-c 前に決める。', 'fields': ({'name': 'root_key', 'type': 'str', 'line': 705, 'references': ('str',), 'literal_values': ()}, {'name': 'method', 'type': '_ContractRef', 'line': 706, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'arithmetic', 'type': '_ContractRef', 'line': 707, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'stage', 'type': 'str', 'line': 708, 'references': ('str',), 'literal_values': ()}, {'name': 'trace_prefix', 'type': 'tuple[ImmutableJSON, ...]', 'line': 709, 'references': ('ImmutableJSON', 'tuple'), 'literal_values': ()}, {'name': 'state_digest', 'type': 'str', 'line': 710, 'references': ('str',), 'literal_values': ()}, {'name': 'state_payload', 'type': 'ImmutableJSON', 'line': 711, 'references': ('ImmutableJSON',), 'literal_values': ()}, {'name': 'previous_certificate', 'type': 'FCertificate | None', 'line': 712, 'references': ('FCertificate',), 'literal_values': ()})},
    {'name': 'ClockReading', 'line': 750, 'docstring': 'F-a で検査する: RUN Ref の時計領域と整数 ns。既存 Instant へ暗黙変換しない。', 'fields': ({'name': 'run', 'type': '_Ref', 'line': 752, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'time_ns', 'type': 'int', 'line': 753, 'references': ('int',), 'literal_values': ()})},
    {'name': 'MeasurementInterval', 'line': 757, 'docstring': 'F-a で検査する: RUN Ref の時計と整数 ns・宣言通りの端点開閉。\n時計契約は RouteConfig.clock_contract から解決。C1 は (start,end]。', 'fields': ({'name': 'clock', 'type': '_Ref', 'line': 760, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'start_ns', 'type': 'int', 'line': 761, 'references': ('int',), 'literal_values': ()}, {'name': 'end_ns', 'type': 'int', 'line': 762, 'references': ('int',), 'literal_values': ()}, {'name': 'closure', 'type': "_Literal['[start,end)', '(start,end]', '[start,end]', '(start,end)']", 'line': 763, 'references': ('_Literal', 'end', 'start'), 'literal_values': ('[start,end)', '(start,end]', '[start,end]', '(start,end)')})},
    {'name': 'ContractValue', 'line': 767, 'docstring': 'F-a で検査する: 契約の版と不変 JSON 値の対応。自己申告を認証としない。', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 769, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'value', 'type': 'ImmutableJSON', 'line': 770, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'Gap', 'line': 785, 'docstring': 'F-a で検査する: 経路、区間、根拠。sequence_range は二整数 [first,stop] だが\n意味は first <= seq < stop。閉区間を無到着の観測にしない。', 'fields': ({'name': 'route_epoch', 'type': 'str', 'line': 788, 'references': ('str',), 'literal_values': ()}, {'name': 'sequence_range', 'type': 'tuple[int, int]', 'line': 789, 'references': ('int', 'tuple'), 'literal_values': ()}, {'name': 'interval', 'type': 'MeasurementInterval', 'line': 790, 'references': ('MeasurementInterval',), 'literal_values': ()}, {'name': 'reason', 'type': 'str', 'line': 791, 'references': ('str',), 'literal_values': ()}, {'name': 'evidence', 'type': 'tuple[_Ref, ...]', 'line': 792, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'MeasurementUnavailable', 'line': 796, 'docstring': 'F-a で検査する: 実際に測れなかった区間と根拠。測って0とは区別。', 'fields': ({'name': 'route_epoch', 'type': 'str', 'line': 798, 'references': ('str',), 'literal_values': ()}, {'name': 'requested_interval', 'type': 'MeasurementInterval', 'line': 799, 'references': ('MeasurementInterval',), 'literal_values': ()}, {'name': 'reason', 'type': 'str', 'line': 800, 'references': ('str',), 'literal_values': ()}, {'name': 'evidence', 'type': 'tuple[_Ref, ...]', 'line': 801, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'CoverageUnproved', 'line': 805, 'docstring': 'F-a で検査する: 完全性未証明と欠測を区別し不足契約と根拠を保持。', 'fields': ({'name': 'route_epoch', 'type': 'str', 'line': 807, 'references': ('str',), 'literal_values': ()}, {'name': 'interval', 'type': 'MeasurementInterval', 'line': 808, 'references': ('MeasurementInterval',), 'literal_values': ()}, {'name': 'missing_contracts', 'type': 'tuple[_ContractRef, ...]', 'line': 809, 'references': ('_ContractRef', 'tuple'), 'literal_values': ()}, {'name': 'evidence', 'type': 'tuple[_Ref, ...]', 'line': 810, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'CoverageClaim', 'line': 814, 'docstring': 'F-a で検査する: kind・区間・契約・根拠。見張り生存を実測の完全性にしない。', 'fields': ({'name': 'route_epoch', 'type': 'str', 'line': 816, 'references': ('str',), 'literal_values': ()}, {'name': 'interval', 'type': 'MeasurementInterval', 'line': 817, 'references': ('MeasurementInterval',), 'literal_values': ()}, {'name': 'kind', 'type': 'str', 'line': 818, 'references': ('str',), 'literal_values': ()}, {'name': 'contract', 'type': '_ContractRef', 'line': 819, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'evidence', 'type': 'tuple[_Ref, ...]', 'line': 820, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'MeasurementFrame', 'line': 824, 'docstring': 'F-a で検査する: 実測 ID/区間/時計/実値と quality/cursor/欠け。\nmeasured_quality/1 の値は文字列 measured、sequence_cursor/1 は sample_seq と同じ非負整数。\nbool を整数とせず、Unavailable を実値へ射影しない。実測時刻を受信時刻で置換しない。\nsimulated_clock/1 は同 RUN の ns・開閉・所属を検査するが実機適合の認証ではない。', 'fields': ({'name': 'route_epoch', 'type': 'str', 'line': 829, 'references': ('str',), 'literal_values': ()}, {'name': 'sample_seq', 'type': 'int', 'line': 830, 'references': ('int',), 'literal_values': ()}, {'name': 'measurement_id', 'type': 'MeasurementId', 'line': 831, 'references': ('MeasurementId',), 'literal_values': ()}, {'name': 'measurement_interval', 'type': 'MeasurementInterval', 'line': 832, 'references': ('MeasurementInterval',), 'literal_values': ()}, {'name': 'actual_time', 'type': 'ClockReading | Unavailable', 'line': 833, 'references': ('ClockReading', 'Unavailable'), 'literal_values': ()}, {'name': 'value', 'type': 'ImmutableJSON | Unavailable', 'line': 834, 'references': ('ImmutableJSON', 'Unavailable'), 'literal_values': ()}, {'name': 'quality', 'type': 'ContractValue', 'line': 835, 'references': ('ContractValue',), 'literal_values': ()}, {'name': 'gap', 'type': 'Gap | None', 'line': 836, 'references': ('Gap',), 'literal_values': ()}, {'name': 'source_cursor', 'type': 'ContractValue', 'line': 837, 'references': ('ContractValue',), 'literal_values': ()})},
    {'name': 'RouteConfig', 'line': 841, 'docstring': 'F-a で検査する: bootstrapのnullとselectedの意思/実行参照。\nF-bで実際の有効化時刻を別に保持し、測る・運ぶ・検査する契約を分ける。', 'fields': ({'name': 'route_epoch', 'type': 'str', 'line': 845, 'references': ('str',), 'literal_values': ()}, {'name': 'origin', 'type': "_Literal['bootstrap', 'selected']", 'line': 846, 'references': ('_Literal',), 'literal_values': ('bootstrap', 'selected')}, {'name': 'version', 'type': 'str', 'line': 847, 'references': ('str',), 'literal_values': ()}, {'name': 'sampling_contract', 'type': '_ContractRef', 'line': 848, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'clock_contract', 'type': '_ContractRef', 'line': 849, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'loss_contract', 'type': '_ContractRef', 'line': 850, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 851, 'references': ('ImmutableJSON',), 'literal_values': ()}, {'name': 'decision', 'type': '_Ref | None', 'line': 852, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'execution', 'type': '_Ref | None', 'line': 853, 'references': ('_Ref',), 'literal_values': ()})},
    {'name': 'Run', 'line': 857, 'docstring': 'F-b の未確定 DTO。RunException の名は採用済みだが columns の全数列/定数列の札、\n空列・count・欠番は F-b 着手前に確定する。F-a で未知 columns を検査済み Run として\nserializer の受理対象にしない。差分/等差は別版、時計の RUN Ref と別型。', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 861, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'route_epoch', 'type': 'str', 'line': 862, 'references': ('str',), 'literal_values': ()}, {'name': 'first_seq', 'type': 'int', 'line': 863, 'references': ('int',), 'literal_values': ()}, {'name': 'count', 'type': 'int', 'line': 864, 'references': ('int',), 'literal_values': ()}, {'name': 'encoding', 'type': 'str', 'line': 865, 'references': ('str',), 'literal_values': ()}, {'name': 'columns', 'type': '_Mapping[str, ImmutableJSON]', 'line': 866, 'references': ('ImmutableJSON', '_Mapping', 'str'), 'literal_values': ()}, {'name': 'exceptions', 'type': 'tuple[RunException, ...]', 'line': 867, 'references': ('RunException', 'tuple'), 'literal_values': ()})},
    {'name': 'CapabilityDeclaration', 'line': 919, 'docstring': 'F-a で検査する: 能力の意味・入出力・引数・依存・条件。登録だけで認証しない。', 'fields': ({'name': 'kind', 'type': 'CapabilityKind', 'line': 921, 'references': ('CapabilityKind',), 'literal_values': ()}, {'name': 'ref', 'type': '_ContractRef', 'line': 922, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'args_contract', 'type': '_ContractRef', 'line': 923, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'input_contract', 'type': '_ContractRef', 'line': 924, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'output_contract', 'type': '_ContractRef', 'line': 925, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'dependencies', 'type': 'tuple[_ContractRef, ...]', 'line': 926, 'references': ('_ContractRef', 'tuple'), 'literal_values': ()}, {'name': 'conditions', 'type': 'tuple[ContractValue, ...]', 'line': 927, 'references': ('ContractValue', 'tuple'), 'literal_values': ()})},
    {'name': 'CapabilityImplementation', 'line': 931, 'docstring': 'Python 側だけの対応。F-a で検査する: 同 kind/ref の重複と対応宣言。\nimplementation は CapabilityCallable。args/input/output の直の JSON を構造検査し、\nproof の真偽の検査と分ける。JSON に関数を保存しない。\nidentity は明示した不変の版・内容識別子 (今の約束 V-11・E-05)。組込みは\n"sui.f.native/1"。中身の違う実装に同じ identity を使い回さない。', 'fields': ({'name': 'kind', 'type': 'CapabilityKind', 'line': 937, 'references': ('CapabilityKind',), 'literal_values': ()}, {'name': 'ref', 'type': '_ContractRef', 'line': 938, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'implementation', 'type': 'CapabilityCallable', 'line': 939, 'references': ('CapabilityCallable',), 'literal_values': ()}, {'name': 'identity', 'type': 'str', 'line': 940, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FRegistry', 'line': 944, 'docstring': 'make_f_registry が返す不変ハンドル。保持欄と factory 専用扱いは採用済み。\nF-a で検査する: 宣言と実装の対応。宣言だけの能力は登録可能。\n手組み・構造復号・登録だけを能力や proof の認証にしない。JSON にしない。', 'fields': ({'name': 'declarations', 'type': 'tuple[CapabilityDeclaration, ...]', 'line': 948, 'references': ('CapabilityDeclaration', 'tuple'), 'literal_values': ()}, {'name': 'implementations', 'type': 'tuple[CapabilityImplementation, ...]', 'line': 949, 'references': ('CapabilityImplementation', 'tuple'), 'literal_values': ()})},
    {'name': 'StyleScope', 'line': 1037, 'docstring': 'FStyle.scope の匿名値。F-a で検査する: 範囲と H。source は持たない。', 'fields': ({'name': 'name', 'type': "_Literal['unbounded_total', 'one_step', 'finite_horizon']", 'line': 1039, 'references': ('_Literal', 'finite_horizon', 'one_step', 'unbounded_total'), 'literal_values': ('unbounded_total', 'one_step', 'finite_horizon')}, {'name': 'version', 'type': "_Literal['1']", 'line': 1040, 'references': ('_Literal',), 'literal_values': ('1',)}, {'name': 'H_ns', 'type': 'int | None', 'line': 1041, 'references': ('int',), 'literal_values': ()})},
    {'name': 'FStyle', 'line': 1045, 'docstring': 'F-a で検査する: F の style 宣言と gamma。source は保存レコードから得る。', 'fields': ({'name': 'kind', 'type': "_Literal['style']", 'line': 1047, 'references': ('_Literal', 'style'), 'literal_values': ('style',)}, {'name': 'scope', 'type': 'StyleScope', 'line': 1048, 'references': ('StyleScope',), 'literal_values': ()}, {'name': 'gamma', 'type': '_Fraction', 'line': 1049, 'references': ('_Fraction',), 'literal_values': ()})},
    {'name': 'FProblem', 'line': 1066, 'docstring': 'prepare_f_from_facts が返す検査済みハンドル。F-a で検査する: draw を除く凍結問題。\ncontinuation.after は正準候補と同じ順/件数で一候補一項。問題 digest に含める。\nscope は resolved に一本化。予算・再開・表示を含めず手組みを認証しない。', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 1070, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'problem_key', 'type': 'str', 'line': 1071, 'references': ('str',), 'literal_values': ()}, {'name': 'world_key', 'type': 'str', 'line': 1072, 'references': ('str',), 'literal_values': ()}, {'name': 'world_manifest', 'type': "'FWorldManifest3'", 'line': 1073, 'references': ('FWorldManifest3',), 'literal_values': ()}, {'name': 'model_ref', 'type': 'str', 'line': 1074, 'references': ('str',), 'literal_values': ()}, {'name': 'parents', 'type': 'frozenset[str]', 'line': 1075, 'references': ('frozenset', 'str'), 'literal_values': ()}, {'name': 'facts', 'type': 'tuple[_Ref, ...]', 'line': 1076, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'E', 'type': 'EvidenceHistory', 'line': 1077, 'references': ('EvidenceHistory',), 'literal_values': ()}, {'name': 'K', 'type': 'KnowledgeHistory', 'line': 1078, 'references': ('KnowledgeHistory',), 'literal_values': ()}, {'name': 'context', 'type': 'FContext', 'line': 1079, 'references': ('FContext',), 'literal_values': ()}, {'name': 'preferences', 'type': 'tuple[_Ref, ...]', 'line': 1080, 'references': ('_Ref', 'tuple'), 'literal_values': ()}, {'name': 'style', 'type': '_Ref | None', 'line': 1081, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'scope', 'type': 'EvaluationScope', 'line': 1082, 'references': ('EvaluationScope',), 'literal_values': ()}, {'name': 'gamma', 'type': '_Fraction', 'line': 1083, 'references': ('_Fraction',), 'literal_values': ()}, {'name': 'candidates', 'type': 'CandidateSet', 'line': 1084, 'references': ('CandidateSet',), 'literal_values': ()}, {'name': 'continuation', 'type': 'FContinuation', 'line': 1085, 'references': ('FContinuation',), 'literal_values': ()}, {'name': 'measurement_contracts', 'type': 'tuple[_ContractRef, ...]', 'line': 1086, 'references': ('_ContractRef', 'tuple'), 'literal_values': ()}, {'name': 'execution_contracts', 'type': 'tuple[_ContractRef, ...]', 'line': 1087, 'references': ('_ContractRef', 'tuple'), 'literal_values': ()}, {'name': 'method', 'type': '_ContractRef', 'line': 1088, 'references': ('_ContractRef',), 'literal_values': ()})},
    {'name': 'PredicatePosition', 'line': 1097, 'docstring': 'PredicateSnapshot.policy_position の二欄の匿名値。\nF-a で検査する: policy_end/1 の対象。全路の PolicyPosition とは欄が異なる。', 'fields': ({'name': 'policy', 'type': 'str', 'line': 1100, 'references': ('str',), 'literal_values': ()}, {'name': 'node', 'type': 'str', 'line': 1101, 'references': ('str',), 'literal_values': ()})},
    {'name': 'PolicyReturn', 'line': 1105, 'docstring': 'F-a で検査する: 呼出元の policy/return_node と終了を追跡する operation。', 'fields': ({'name': 'policy', 'type': 'str', 'line': 1107, 'references': ('str',), 'literal_values': ()}, {'name': 'return_node', 'type': 'str', 'line': 1108, 'references': ('str',), 'literal_values': ()}, {'name': 'operation', 'type': 'str | None', 'line': 1109, 'references': ('str',), 'literal_values': ()})},
    {'name': 'PolicyPosition', 'line': 1113, 'docstring': 'F-a で検査する: 方針節・現在 operation・初手の完了・スタック・整数経過 ns。\noperation=None は初手終了後の外側方針。子 W の終了だけで複合 C を完了にしない。\nchoose.next は子の ψ 成立後の戻り先。包装の制御を測定や Thought にしない。', 'fields': ({'name': 'policy', 'type': 'str', 'line': 1117, 'references': ('str',), 'literal_values': ()}, {'name': 'node', 'type': 'str', 'line': 1118, 'references': ('str',), 'literal_values': ()}, {'name': 'operation', 'type': 'str | None', 'line': 1119, 'references': ('str',), 'literal_values': ()}, {'name': 'first_completed', 'type': 'bool', 'line': 1120, 'references': ('bool',), 'literal_values': ()}, {'name': 'stack', 'type': 'tuple[PolicyReturn, ...]', 'line': 1121, 'references': ('PolicyReturn', 'tuple'), 'literal_values': ()}, {'name': 'elapsed_ns', 'type': 'int', 'line': 1122, 'references': ('int',), 'literal_values': ()})},
    {'name': 'FPathTerminal', 'line': 1126, 'docstring': 'FPathRow.terminal の匿名値。F-a で検査する: 終了と範囲打切りを区別。', 'fields': ({'name': 'kind', 'type': "_Literal['ended', 'horizon']", 'line': 1128, 'references': ('_Literal', 'ended', 'horizon'), 'literal_values': ('ended', 'horizon')}, {'name': 'position', 'type': 'PolicyPosition', 'line': 1129, 'references': ('PolicyPosition',), 'literal_values': ()})},
    {'name': 'FPathResidual', 'line': 1133, 'docstring': 'FPathTable.residual の匿名要素。F-a で検査する: 候補別未展開質量。', 'fields': ({'name': 'candidate', 'type': 'str', 'line': 1135, 'references': ('str',), 'literal_values': ()}, {'name': 'mass', 'type': 'FQuantity', 'line': 1136, 'references': ('FQuantity',), 'literal_values': ()})},
    {'name': 'FFrontierRow', 'line': 1140, 'docstring': 'F-a で検査する: 未展開の共同状態・位置・E/K・路全体費用の履歴。\n残余質量だけに潰さず、joint_state の和は probability。', 'fields': ({'name': 'candidate', 'type': 'str', 'line': 1143, 'references': ('str',), 'literal_values': ()}, {'name': 'probability', 'type': 'ExactReal', 'line': 1144, 'references': ('ExactReal',), 'literal_values': ()}, {'name': 'joint_state', 'type': 'tuple[ExactReal, ...]', 'line': 1145, 'references': ('ExactReal', 'tuple'), 'literal_values': ()}, {'name': 'E', 'type': 'EvidenceHistory', 'line': 1146, 'references': ('EvidenceHistory',), 'literal_values': ()}, {'name': 'K', 'type': 'KnowledgeHistory', 'line': 1147, 'references': ('KnowledgeHistory',), 'literal_values': ()}, {'name': 'actions', 'type': 'tuple[ActionSpec, ...]', 'line': 1148, 'references': ('ActionSpec', 'tuple'), 'literal_values': ()}, {'name': 'position', 'type': 'PolicyPosition', 'line': 1149, 'references': ('PolicyPosition',), 'literal_values': ()})},
    {'name': 'FNodeValue', 'line': 1153, 'docstring': 'F-a で検査する: 選択節の候補軸と J/q/V。V は後続 J の softmax 平均。', 'fields': ({'name': 'key', 'type': 'str', 'line': 1155, 'references': ('str',), 'literal_values': ()}, {'name': 'candidate', 'type': 'str', 'line': 1156, 'references': ('str',), 'literal_values': ()}, {'name': 'position', 'type': 'PolicyPosition', 'line': 1157, 'references': ('PolicyPosition',), 'literal_values': ()}, {'name': 'knowledge_key', 'type': 'str', 'line': 1158, 'references': ('str',), 'literal_values': ()}, {'name': 'alternatives', 'type': 'tuple[str, ...]', 'line': 1159, 'references': ('str', 'tuple'), 'literal_values': ()}, {'name': 'J', 'type': 'tuple[FQuantity, ...]', 'line': 1160, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'q_star', 'type': 'tuple[FQuantity, ...]', 'line': 1161, 'references': ('FQuantity', 'tuple'), 'literal_values': ()}, {'name': 'V', 'type': 'FQuantity', 'line': 1162, 'references': ('FQuantity',), 'literal_values': ()})},
    {'name': 'TailPrefix', 'line': 1166, 'docstring': 'TailCertificate.prefix の匿名値。F-a で検査する: 表 digest と対象候補。', 'fields': ({'name': 'table_digest', 'type': 'str', 'line': 1168, 'references': ('str',), 'literal_values': ()}, {'name': 'kind', 'type': "_Literal['complete', 'prefix']", 'line': 1169, 'references': ('_Literal', 'complete', 'prefix'), 'literal_values': ('complete', 'prefix')}, {'name': 'steps', 'type': 'int | None', 'line': 1170, 'references': ('int',), 'literal_values': ()}, {'name': 'candidate', 'type': 'str', 'line': 1171, 'references': ('str',), 'literal_values': ()})},
    {'name': 'LimitProcess', 'line': 1207, 'docstring': 'FLimitProblem.process と費用 law の匿名宣言。F-a で検査する: 独立公平ビット。', 'fields': ({'name': 'name', 'type': "_Literal['iid_fair_bits']", 'line': 1209, 'references': ('_Literal', 'iid_fair_bits'), 'literal_values': ('iid_fair_bits',)}, {'name': 'version', 'type': "_Literal['1']", 'line': 1210, 'references': ('_Literal',), 'literal_values': ('1',)}, {'name': 'args', 'type': 'LimitProcessArgs', 'line': 1211, 'references': ('LimitProcessArgs',), 'literal_values': ()})},
    {'name': 'LimitProcessArgs', 'line': 1215, 'docstring': 'LimitProcess.args の匿名値。F-a で検査する: bool を整数0としない。', 'fields': ({'name': 'index_origin', 'type': '_Literal[0]', 'line': 1217, 'references': ('_Literal',), 'literal_values': (0,)},)},
    {'name': 'LimitObservations', 'line': 1221, 'docstring': 'FLimitProblem.observations の匿名値。F-a で検査する: args は空 object のみ。', 'fields': ({'name': 'name', 'type': "_Literal['reveal_next_bit']", 'line': 1223, 'references': ('_Literal', 'reveal_next_bit'), 'literal_values': ('reveal_next_bit',)}, {'name': 'version', 'type': "_Literal['1']", 'line': 1224, 'references': ('_Literal',), 'literal_values': ('1',)}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 1225, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'BlankLimitCost', 'line': 1229, 'docstring': '空白費用の和型。F-a で検査する: 追加キーなし、費用0。', 'fields': ({'name': 'kind', 'type': "_Literal['blank']", 'line': 1231, 'references': ('_Literal', 'blank'), 'literal_values': ('blank',)},)},
    {'name': 'PrefixLogLoss', 'line': 1235, 'docstring': '有限 prefix の log-loss 宣言。F-a で検査する: 宣言法則との一致。', 'fields': ({'name': 'kind', 'type': "_Literal['prefix_log_loss']", 'line': 1237, 'references': ('_Literal', 'prefix_log_loss'), 'literal_values': ('prefix_log_loss',)}, {'name': 'law', 'type': 'LimitProcess', 'line': 1238, 'references': ('LimitProcess',), 'literal_values': ()})},
    {'name': 'LimitScope', 'line': 1242, 'docstring': '負の極限診断の範囲。F-a で検査する: H_ns=null のみ。', 'fields': ({'name': 'name', 'type': "_Literal['unbounded_total']", 'line': 1244, 'references': ('_Literal', 'unbounded_total'), 'literal_values': ('unbounded_total',)}, {'name': 'version', 'type': "_Literal['1']", 'line': 1245, 'references': ('_Literal',), 'literal_values': ('1',)}, {'name': 'H_ns', 'type': 'None', 'line': 1246, 'references': (), 'literal_values': ()})},
    {'name': 'FLimitProblem', 'line': 1250, 'docstring': 'F-a で検査する: 負の診断だけの数学宣言。model.10 や選択・作用の入口にしない。', 'fields': ({'name': 'process', 'type': 'LimitProcess', 'line': 1252, 'references': ('LimitProcess',), 'literal_values': ()}, {'name': 'observations', 'type': 'LimitObservations', 'line': 1253, 'references': ('LimitObservations',), 'literal_values': ()}, {'name': 'information_target', 'type': "_Literal['entire_sequence']", 'line': 1254, 'references': ('_Literal', 'entire_sequence'), 'literal_values': ('entire_sequence',)}, {'name': 'cost', 'type': 'BlankLimitCost | PrefixLogLoss', 'line': 1255, 'references': ('BlankLimitCost', 'PrefixLogLoss'), 'literal_values': ()}, {'name': 'scope', 'type': 'LimitScope', 'line': 1256, 'references': ('LimitScope',), 'literal_values': ()}, {'name': 'proof', 'type': 'ProofRef | None', 'line': 1257, 'references': ('ProofRef',), 'literal_values': ()})},
    {'name': 'LinearSequenceArgs', 'line': 1261, 'docstring': 'ExactSequence.args の匿名値。F-a で検査する: 厳密な線形列の係数。', 'fields': ({'name': 'slope', 'type': 'ExactReal', 'line': 1263, 'references': ('ExactReal',), 'literal_values': ()}, {'name': 'intercept', 'type': 'ExactReal', 'line': 1264, 'references': ('ExactReal',), 'literal_values': ()})},
    {'name': 'ExactSequence', 'line': 1268, 'docstring': 'F-a で検査する: prefix の厳密な線形列。有限 prefix だけから発散を断定しない。', 'fields': ({'name': 'name', 'type': "_Literal['linear']", 'line': 1270, 'references': ('_Literal', 'linear'), 'literal_values': ('linear',)}, {'name': 'version', 'type': "_Literal['1']", 'line': 1271, 'references': ('_Literal',), 'literal_values': ('1',)}, {'name': 'args', 'type': 'LinearSequenceArgs', 'line': 1272, 'references': ('LinearSequenceArgs',), 'literal_values': ()})},
    {'name': 'LimitInformation', 'line': 1276, 'docstring': 'LimitCertificate.information の匿名値。F-a で検査する: 発散の証明。', 'fields': ({'name': 'prefix', 'type': 'ExactSequence', 'line': 1278, 'references': ('ExactSequence',), 'literal_values': ()}, {'name': 'bound', 'type': "_Literal['diverges']", 'line': 1279, 'references': ('_Literal', 'diverges'), 'literal_values': ('diverges',)})},
    {'name': 'LimitCost', 'line': 1283, 'docstring': 'LimitCertificate.cost の匿名値。F-a で検査する: 費用の極限を別に証明。', 'fields': ({'name': 'prefix', 'type': 'ExactSequence', 'line': 1285, 'references': ('ExactSequence',), 'literal_values': ()}, {'name': 'bound', 'type': "_Literal['zero', 'diverges']", 'line': 1286, 'references': ('_Literal', 'diverges', 'zero'), 'literal_values': ('zero', 'diverges')})},
    {'name': 'LimitCertificate', 'line': 1290, 'docstring': 'F-a で検査する: iid_bits_limit/1 の問題 digest と列の傾き。\n発散と証明不足を区別し、無限の差を相殺して Selected を作らない。', 'fields': ({'name': 'problem_key', 'type': 'str', 'line': 1293, 'references': ('str',), 'literal_values': ()}, {'name': 'checker', 'type': '_ContractRef', 'line': 1294, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'information', 'type': 'LimitInformation', 'line': 1295, 'references': ('LimitInformation',), 'literal_values': ()}, {'name': 'cost', 'type': 'LimitCost', 'line': 1296, 'references': ('LimitCost',), 'literal_values': ()}, {'name': 'conclusion', 'type': "_Literal['information_divergent', 'undefined_infinite_difference']", 'line': 1297, 'references': ('_Literal', 'information_divergent', 'undefined_infinite_difference'), 'literal_values': ('information_divergent', 'undefined_infinite_difference')})},
    {'name': 'RunException', 'line': 1330, 'docstring': 'Run.exceptions の匿名要素。F-b で検査する: index と Frame 全欄との対応。', 'fields': ({'name': 'index', 'type': 'int', 'line': 1332, 'references': ('int',), 'literal_values': ()}, {'name': 'fields', 'type': '_Mapping[str, ImmutableJSON]', 'line': 1333, 'references': ('ImmutableJSON', '_Mapping', 'str'), 'literal_values': ()})},
    {'name': 'CapabilityCallable', 'line': 1336, 'docstring': '全能力共通の呼出規約。実装名から任意コードを import しない。', 'fields': ()},
    {'name': 'CapabilityContext', 'line': 1350, 'docstring': '非 JSON の読み取り専用依存。F-a で検査する: 解決元と対象・予算。\n時計・乱数源・台帳書き手・可変主体を渡さない。', 'fields': ({'name': 'registry', 'type': 'FRegistry | None', 'line': 1353, 'references': ('FRegistry',), 'literal_values': ()}, {'name': 'resources', 'type': 'object | None', 'line': 1354, 'references': ('object',), 'literal_values': ()}, {'name': 'model_ref', 'type': 'str | None', 'line': 1355, 'references': ('str',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget | None', 'line': 1356, 'references': ('RateBudget',), 'literal_values': ()}, {'name': 'numeric_work', 'type': 'object | None', 'line': 1357, 'references': ('object',), 'literal_values': ()}, {'name': 'cached_quantities', 'type': 'object | None', 'line': 1358, 'references': ('object',), 'literal_values': ()}, {'name': 'numeric_input', 'type': 'object | None', 'line': 1359, 'references': ('object',), 'literal_values': ()}, {'name': 'certified_input', 'type': 'object | None', 'line': 1360, 'references': ('object',), 'literal_values': ()})},
    {'name': 'DrawRequest', 'line': 1474, 'docstring': 'F-a で検査する: 用途・問題キー・ordinal と値の法則。selection は uniform_unit/1、args={}。\n§3-10-13-補で採用した配置: f.py で定義する。', 'fields': ({'name': 'purpose', 'type': "_Literal['candidate_generation', 'selection', 'reservation', 'algorithm']", 'line': 1477, 'references': ('_Literal', 'algorithm', 'candidate_generation', 'reservation', 'selection'), 'literal_values': ('candidate_generation', 'selection', 'reservation', 'algorithm')}, {'name': 'context_key', 'type': 'str', 'line': 1478, 'references': ('str',), 'literal_values': ()}, {'name': 'ordinal', 'type': 'int', 'line': 1479, 'references': ('int',), 'literal_values': ()}, {'name': 'law', 'type': '_ContractRef', 'line': 1480, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 1481, 'references': ('ImmutableJSON',), 'literal_values': ()})},
    {'name': 'RequiredCapability', 'line': 1485, 'docstring': 'FPreflight.required_capabilities の要素。名前は §3-10-13-補で採用済み。\nF-a で検査する: 意味と必要な実装を分け、bool を数値としない。', 'fields': ({'name': 'kind', 'type': 'CapabilityKind', 'line': 1488, 'references': ('CapabilityKind',), 'literal_values': ()}, {'name': 'ref', 'type': '_ContractRef', 'line': 1489, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'implementation_required', 'type': 'bool', 'line': 1490, 'references': ('bool',), 'literal_values': ()})},
    {'name': 'PreflightReady', 'line': 1504, 'docstring': 'F-a で検査する: 検査器が固定 resources から求めた前提 input_key。\n成功しても根・Selected・外部作用を作らない。', 'fields': ({'name': 'input_key', 'type': 'str', 'line': 1507, 'references': ('str',), 'literal_values': ()},)},
    {'name': 'ContinuationAfter', 'line': 1511, 'docstring': 'FContinuation.after の要素。名前は §3-10-13-補で採用済み。\nF-a で検査する: 正準候補ごとに一項。policy=None は宣言した追加操作がない意味。', 'fields': ({'name': 'candidate', 'type': 'str', 'line': 1514, 'references': ('str',), 'literal_values': ()}, {'name': 'policy', 'type': 'PolicyRef | None', 'line': 1515, 'references': ('PolicyRef',), 'literal_values': ()})},
    {'name': 'FContinuation', 'line': 1519, 'docstring': 'F-a で検査する: 候補と同順・同件数の初手終了後の明示方針。\none_step は起動せず、unbounded_total/finite_horizon は初手終了後に一度入る。\n終わらない枝は移らない。null でも既存経路/残りの測定を切らず未認証尾を保持する。', 'fields': ({'name': 'after', 'type': 'tuple[ContinuationAfter, ...]', 'line': 1523, 'references': ('ContinuationAfter', 'tuple'), 'literal_values': ()},)},
    {'name': 'FPreferencePoint', 'line': 1554, 'docstring': 'A visible ledger point; CID and record ID are distinct identities.', 'fields': ({'name': 'cid', 'type': 'str', 'line': 1556, 'references': ('str',), 'literal_values': ()}, {'name': 'record', 'type': '_Ref', 'line': 1557, 'references': ('_Ref',), 'literal_values': ()})},
    {'name': 'FPreferenceCausality', 'line': 1561, 'docstring': 'Canonical receipt of the relation derived by preference.from_ledger.', 'fields': ({'name': 'points', 'type': 'tuple[FPreferencePoint, ...]', 'line': 1563, 'references': ('FPreferencePoint', 'tuple'), 'literal_values': ()}, {'name': 'before', 'type': 'tuple[tuple[_Ref, _Ref], ...]', 'line': 1564, 'references': ('_Ref', 'tuple'), 'literal_values': ()})},
    {'name': 'FFactsPointDependency', 'line': 1569, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'point', 'type': 'str', 'line': 1570, 'references': ('str',), 'literal_values': ()}, {'name': 'entry_present', 'type': 'bool', 'line': 1571, 'references': ('bool',), 'literal_values': ()}, {'name': 'body_present', 'type': 'bool', 'line': 1572, 'references': ('bool',), 'literal_values': ()}, {'name': 'record', 'type': '_Ref | None', 'line': 1573, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'record_digest', 'type': 'str | None', 'line': 1574, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FFactsModelDependency', 'line': 1578, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'point', 'type': 'str', 'line': 1579, 'references': ('str',), 'literal_values': ()}, {'name': 'model_ref', 'type': 'str | None', 'line': 1580, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FFactsCapabilityDependency', 'line': 1584, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'kind', 'type': 'CapabilityKind', 'line': 1585, 'references': ('CapabilityKind',), 'literal_values': ()}, {'name': 'ref', 'type': '_ContractRef', 'line': 1586, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'declaration', 'type': 'CapabilityDeclaration | None', 'line': 1587, 'references': ('CapabilityDeclaration',), 'literal_values': ()}, {'name': 'implemented', 'type': 'bool', 'line': 1588, 'references': ('bool',), 'literal_values': ()}, {'name': 'implementation_id', 'type': 'str | None', 'line': 1589, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FFactsRefLookup', 'line': 1593, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'ref', 'type': '_Ref', 'line': 1594, 'references': ('_Ref',), 'literal_values': ()}, {'name': 'points', 'type': 'tuple[str, ...]', 'line': 1595, 'references': ('str', 'tuple'), 'literal_values': ()})},
    {'name': 'FFactsAbsenceEnvironment', 'line': 1599, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'reader_view_key', 'type': 'str', 'line': 1600, 'references': ('str',), 'literal_values': ()}, {'name': 'registry_key', 'type': 'str', 'line': 1601, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FFactsDependencies', 'line': 1605, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'points', 'type': 'tuple[FFactsPointDependency, ...]', 'line': 1606, 'references': ('FFactsPointDependency', 'tuple'), 'literal_values': ()}, {'name': 'models', 'type': 'tuple[FFactsModelDependency, ...]', 'line': 1607, 'references': ('FFactsModelDependency', 'tuple'), 'literal_values': ()}, {'name': 'capabilities', 'type': 'tuple[FFactsCapabilityDependency, ...]', 'line': 1608, 'references': ('FFactsCapabilityDependency', 'tuple'), 'literal_values': ()}, {'name': 'ref_lookups', 'type': 'tuple[FFactsRefLookup, ...]', 'line': 1609, 'references': ('FFactsRefLookup', 'tuple'), 'literal_values': ()}, {'name': 'absence_environment', 'type': 'FFactsAbsenceEnvironment | None', 'line': 1610, 'references': ('FFactsAbsenceEnvironment',), 'literal_values': ()})},
    {'name': 'FWorldManifest3', 'line': 1614, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 1615, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'compiler', 'type': '_ContractRef', 'line': 1616, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'request', 'type': "'FMathFactsInput | FMathLegacyBridgeInput'", 'line': 1617, 'references': ('FMathFactsInput', 'FMathLegacyBridgeInput'), 'literal_values': ()}, {'name': 'dependencies', 'type': 'FFactsDependencies', 'line': 1618, 'references': ('FFactsDependencies',), 'literal_values': ()}, {'name': 'preference_causality', 'type': 'FPreferenceCausality', 'line': 1619, 'references': ('FPreferenceCausality',), 'literal_values': ()})},
    {'name': 'FReader', 'line': 3637, 'docstring': 'Readonly facts interface; factories must capture an immutable view.\n\nNo append, ID source, clock or current-head fallback belongs to this API.\nA Point is an Entry CID, not a Record Ref or model content hash.', 'fields': ()},
    {'name': 'FCandidateGeneration', 'line': 3817, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'generator', 'type': '_ContractRef', 'line': 3818, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'args', 'type': 'ImmutableJSON', 'line': 3819, 'references': ('ImmutableJSON',), 'literal_values': ()}, {'name': 'basis', 'type': 'tuple[Point, ...]', 'line': 3820, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'draws', 'type': 'tuple[Point, ...]', 'line': 3821, 'references': ('Point', 'tuple'), 'literal_values': ()})},
    {'name': 'FCandidateDeclaration', 'line': 3825, 'docstring': 'Prediction/MODEL/PREDICTION: before canonicalization and aliasing.', 'fields': ({'name': 'model', 'type': 'Point', 'line': 3827, 'references': ('Point',), 'literal_values': ()}, {'name': 'input_order', 'type': 'tuple[str, ...]', 'line': 3828, 'references': ('str', 'tuple'), 'literal_values': ()}, {'name': 'measure', 'type': 'CandidateMeasureRef | None', 'line': 3829, 'references': ('CandidateMeasureRef',), 'literal_values': ()}, {'name': 'generation', 'type': 'FCandidateGeneration', 'line': 3830, 'references': ('FCandidateGeneration',), 'literal_values': ()}, {'name': 'continuation', 'type': 'FContinuation', 'line': 3831, 'references': ('FContinuation',), 'literal_values': ()})},
    {'name': 'FFactsRequest', 'line': 3897, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'fixed_parents', 'type': 'tuple[Point, ...]', 'line': 3898, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'model', 'type': 'Point', 'line': 3899, 'references': ('Point',), 'literal_values': ()}, {'name': 'candidates', 'type': 'Point', 'line': 3900, 'references': ('Point',), 'literal_values': ()}, {'name': 'preferences', 'type': 'tuple[Point, ...]', 'line': 3901, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'scope', 'type': 'EvaluationScope', 'line': 3902, 'references': ('EvaluationScope',), 'literal_values': ()}, {'name': 'context', 'type': 'Point', 'line': 3903, 'references': ('Point',), 'literal_values': ()}, {'name': 'method', 'type': '_ContractRef', 'line': 3904, 'references': ('_ContractRef',), 'literal_values': ()})},
    {'name': 'FPreflightFacts', 'line': 3908, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'fixed_parents', 'type': 'tuple[Point, ...]', 'line': 3909, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'model', 'type': 'Point | None', 'line': 3910, 'references': ('Point',), 'literal_values': ()}, {'name': 'required_records', 'type': 'tuple[Point, ...]', 'line': 3911, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'required_capabilities', 'type': 'tuple[RequiredCapability, ...]', 'line': 3912, 'references': ('RequiredCapability', 'tuple'), 'literal_values': ()})},
    {'name': 'FMathFactsInput', 'line': 3916, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'kind', 'type': "_Literal['facts']", 'line': 3917, 'references': ('_Literal', 'facts'), 'literal_values': ('facts',)}, {'name': 'value', 'type': 'FFactsRequest', 'line': 3918, 'references': ('FFactsRequest',), 'literal_values': ()})},
    {'name': 'FMathPreflightInput', 'line': 3922, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'kind', 'type': "_Literal['preflight']", 'line': 3923, 'references': ('_Literal', 'preflight'), 'literal_values': ('preflight',)}, {'name': 'value', 'type': 'FPreflightFacts', 'line': 3924, 'references': ('FPreflightFacts',), 'literal_values': ()})},
    {'name': 'FLimitFactsRequest', 'line': 3928, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'declaration', 'type': 'Point', 'line': 3929, 'references': ('Point',), 'literal_values': ()},)},
    {'name': 'FMathLimitInput', 'line': 3933, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'kind', 'type': "_Literal['limit']", 'line': 3934, 'references': ('_Literal', 'limit'), 'literal_values': ('limit',)}, {'name': 'value', 'type': 'FLimitFactsRequest', 'line': 3935, 'references': ('FLimitFactsRequest',), 'literal_values': ()})},
    {'name': 'FMathEnvironment', 'line': 3943, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'reader_view_key', 'type': 'str', 'line': 3944, 'references': ('str',), 'literal_values': ()}, {'name': 'registry_key', 'type': 'str', 'line': 3945, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FPrepareCallArgs', 'line': 3949, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'budget', 'type': 'RateBudget', 'line': 3950, 'references': ('RateBudget',), 'literal_values': ()},)},
    {'name': 'FBindDrawCallArgs', 'line': 3954, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'problem_step', 'type': 'int', 'line': 3955, 'references': ('int',), 'literal_values': ()}, {'name': 'draw', 'type': 'Point', 'line': 3956, 'references': ('Point',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 3957, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FRootCallArgs', 'line': 3961, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'root_step', 'type': 'int', 'line': 3962, 'references': ('int',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 3963, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FEnumeratedCallArgs', 'line': 3967, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'root_step', 'type': 'int', 'line': 3968, 'references': ('int',), 'literal_values': ()}, {'name': 'paths_step', 'type': 'int', 'line': 3969, 'references': ('int',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 3970, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FPrefixCallArgs', 'line': 3974, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'root_step', 'type': 'int', 'line': 3975, 'references': ('int',), 'literal_values': ()}, {'name': 'steps', 'type': 'int', 'line': 3976, 'references': ('int',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 3977, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FPrefixEvaluationCallArgs', 'line': 3981, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'root_step', 'type': 'int', 'line': 3982, 'references': ('int',), 'literal_values': ()}, {'name': 'prefix_step', 'type': 'int', 'line': 3983, 'references': ('int',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 3984, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FTailCallArgs', 'line': 3988, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'root_step', 'type': 'int', 'line': 3989, 'references': ('int',), 'literal_values': ()}, {'name': 'prefix_step', 'type': 'int', 'line': 3990, 'references': ('int',), 'literal_values': ()}, {'name': 'candidate', 'type': 'str', 'line': 3991, 'references': ('str',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 3992, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FChoiceCallArgs', 'line': 3996, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'evaluation_step', 'type': 'int', 'line': 3997, 'references': ('int',), 'literal_values': ()},)},
    {'name': 'FEvaluateCallArgs', 'line': 4001, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'root_step', 'type': 'int', 'line': 4002, 'references': ('int',), 'literal_values': ()}, {'name': 'resume_step', 'type': 'int | None', 'line': 4003, 'references': ('int',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 4004, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FPreflightCallArgs', 'line': 4008, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ()},
    {'name': 'FMathCall', 'line': 4027, 'docstring': 'Whole args of the named op; prior-step/type/use checks are factory work.\n\nprepare/limit_certificate/limit use FPrepareCallArgs;\nscope/enumerate/recursive use FRootCallArgs. choice has no caller-supplied u.', 'fields': ({'name': 'op', 'type': 'FMathOpV1', 'line': 4033, 'references': ('FMathOpV1',), 'literal_values': ()}, {'name': 'args', 'type': 'FMathCallArgsV1', 'line': 4034, 'references': ('FMathCallArgsV1',), 'literal_values': ()})},
    {'name': 'FProblemMathClaim', 'line': 4041, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['FProblem']", 'line': 4042, 'references': ('FProblem', '_Literal'), 'literal_values': ('FProblem',)}, {'name': 'value', 'type': 'FProblem', 'line': 4043, 'references': ('FProblem',), 'literal_values': ()})},
    {'name': 'FRootMathClaim', 'line': 4047, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['FRoot']", 'line': 4048, 'references': ('FRoot', '_Literal'), 'literal_values': ('FRoot',)}, {'name': 'value', 'type': 'FRoot', 'line': 4049, 'references': ('FRoot',), 'literal_values': ()})},
    {'name': 'FEvaluationMathClaim', 'line': 4053, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['FEvaluation']", 'line': 4054, 'references': ('FEvaluation', '_Literal'), 'literal_values': ('FEvaluation',)}, {'name': 'value', 'type': 'FEvaluation', 'line': 4055, 'references': ('FEvaluation',), 'literal_values': ()})},
    {'name': 'SelectedMathClaim', 'line': 4059, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['Selected']", 'line': 4060, 'references': ('Selected', '_Literal'), 'literal_values': ('Selected',)}, {'name': 'value', 'type': 'Selected', 'line': 4061, 'references': ('Selected',), 'literal_values': ()})},
    {'name': 'NoDecisionMathClaim', 'line': 4065, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['NoDecision']", 'line': 4066, 'references': ('NoDecision', '_Literal'), 'literal_values': ('NoDecision',)}, {'name': 'value', 'type': 'NoDecision', 'line': 4067, 'references': ('NoDecision',), 'literal_values': ()})},
    {'name': 'PreflightReadyMathClaim', 'line': 4071, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['PreflightReady']", 'line': 4072, 'references': ('PreflightReady', '_Literal'), 'literal_values': ('PreflightReady',)}, {'name': 'value', 'type': 'PreflightReady', 'line': 4073, 'references': ('PreflightReady',), 'literal_values': ()})},
    {'name': 'LimitCertificateMathClaim', 'line': 4077, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['LimitCertificate']", 'line': 4078, 'references': ('LimitCertificate', '_Literal'), 'literal_values': ('LimitCertificate',)}, {'name': 'value', 'type': 'LimitCertificate', 'line': 4079, 'references': ('LimitCertificate',), 'literal_values': ()})},
    {'name': 'FScopeMathClaim', 'line': 4083, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['FScope']", 'line': 4084, 'references': ('FScope', '_Literal'), 'literal_values': ('FScope',)}, {'name': 'value', 'type': 'FScope', 'line': 4085, 'references': ('FScope',), 'literal_values': ()})},
    {'name': 'FPathTableMathClaim', 'line': 4089, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['FPathTable']", 'line': 4090, 'references': ('FPathTable', '_Literal'), 'literal_values': ('FPathTable',)}, {'name': 'value', 'type': 'FPathTable', 'line': 4091, 'references': ('FPathTable',), 'literal_values': ()})},
    {'name': 'TailCertificateMathClaim', 'line': 4095, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['TailCertificate']", 'line': 4096, 'references': ('TailCertificate', '_Literal'), 'literal_values': ('TailCertificate',)}, {'name': 'value', 'type': 'TailCertificate', 'line': 4097, 'references': ('TailCertificate',), 'literal_values': ()})},
    {'name': 'FMathArtifactJSON', 'line': 4112, 'docstring': 'Unverified structural envelope. Decoding it cannot issue a handle.', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 4114, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'compiler', 'type': '_ContractRef', 'line': 4115, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'input', 'type': 'FMathInputV1', 'line': 4116, 'references': ('FMathInputV1',), 'literal_values': ()}, {'name': 'environment', 'type': 'FMathEnvironment', 'line': 4117, 'references': ('FMathEnvironment',), 'literal_values': ()}, {'name': 'calls', 'type': 'tuple[FMathCallV1, ...]', 'line': 4118, 'references': ('FMathCallV1', 'tuple'), 'literal_values': ()}, {'name': 'output', 'type': 'int', 'line': 4119, 'references': ('int',), 'literal_values': ()}, {'name': 'claim', 'type': 'FMathClaimV1', 'line': 4120, 'references': ('FMathClaimV1',), 'literal_values': ()})},
    {'name': 'FCheckedMathCall', 'line': 4127, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'index', 'type': 'int', 'line': 4128, 'references': ('int',), 'literal_values': ()}, {'name': 'op', 'type': 'FMathOp', 'line': 4129, 'references': ('FMathOp',), 'literal_values': ()}, {'name': 'input_digest', 'type': 'str', 'line': 4130, 'references': ('str',), 'literal_values': ()}, {'name': 'output_digest', 'type': 'str', 'line': 4131, 'references': ('str',), 'literal_values': ()})},
    {'name': 'FMathVerificationContent', 'line': 4135, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'artifact_digest', 'type': 'str', 'line': 4136, 'references': ('str',), 'literal_values': ()}, {'name': 'input_digest', 'type': 'str', 'line': 4137, 'references': ('str',), 'literal_values': ()}, {'name': 'result_digest', 'type': 'str', 'line': 4138, 'references': ('str',), 'literal_values': ()}, {'name': 'checked_calls', 'type': 'tuple[FCheckedMathCall, ...]', 'line': 4139, 'references': ('FCheckedMathCall', 'tuple'), 'literal_values': ()})},
    {'name': 'FMathVerificationCertificate', 'line': 4143, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 4144, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'value', 'type': 'FMathVerificationContent', 'line': 4145, 'references': ('FMathVerificationContent',), 'literal_values': ()})},
    {'name': 'FMathArtifact', 'line': 4165, 'docstring': 'Factory-only readonly value/bytes/reader; no writes or consumption.', 'fields': ({'name': 'value', 'type': '_MathT', 'line': 4167, 'references': ('_MathT',), 'literal_values': ()}, {'name': 'canonical_bytes', 'type': 'bytes', 'line': 4168, 'references': ('bytes',), 'literal_values': ()}, {'name': 'reader', 'type': 'FReader', 'line': 4169, 'references': ('FReader',), 'literal_values': ()})},
    {'name': 'FLegacyBridgeRequest', 'line': 4296, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'fixed_parents', 'type': 'tuple[Point, ...]', 'line': 4297, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'model', 'type': 'Point', 'line': 4298, 'references': ('Point',), 'literal_values': ()}, {'name': 'context', 'type': 'Point', 'line': 4299, 'references': ('Point',), 'literal_values': ()}, {'name': 'preferences', 'type': 'tuple[Point, ...]', 'line': 4300, 'references': ('Point', 'tuple'), 'literal_values': ()}, {'name': 'candidates', 'type': 'tuple[str, ...]', 'line': 4301, 'references': ('str', 'tuple'), 'literal_values': ()}, {'name': 'adapter', 'type': '_ContractRef', 'line': 4302, 'references': ('_ContractRef',), 'literal_values': ()})},
    {'name': 'FLegacyBridgeProblem', 'line': 4306, 'docstring': 'Factory-only old-bridge problem; no budget/draw in problem_key.\n\nReading state and corresponding finite world are internal certified values;\npublic descriptor/JSON or an equal ID cannot issue the problem.', 'fields': ({'name': 'problem_key', 'type': 'str', 'line': 4312, 'references': ('str',), 'literal_values': ()}, {'name': 'request', 'type': 'FLegacyBridgeRequest', 'line': 4313, 'references': ('FLegacyBridgeRequest',), 'literal_values': ()}, {'name': 'legacy_model_ref', 'type': 'str', 'line': 4314, 'references': ('str',), 'literal_values': ()}, {'name': 'adapter', 'type': '_ContractRef', 'line': 4315, 'references': ('_ContractRef',), 'literal_values': ()})},
    {'name': 'FMathLegacyBridgeInput', 'line': 4353, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'kind', 'type': "_Literal['legacy_bridge']", 'line': 4354, 'references': ('_Literal', 'legacy_bridge'), 'literal_values': ('legacy_bridge',)}, {'name': 'value', 'type': 'FLegacyBridgeRequest', 'line': 4355, 'references': ('FLegacyBridgeRequest',), 'literal_values': ()})},
    {'name': 'FPreflightFactsCallArgs', 'line': 4359, 'docstring': "math_artifact/2 preflight args; v1's empty args type stays available.", 'fields': ({'name': 'budget', 'type': 'RateBudget', 'line': 4361, 'references': ('RateBudget',), 'literal_values': ()},)},
    {'name': 'FLegacyBridgeCallArgs', 'line': 4365, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'problem_step', 'type': 'int', 'line': 4366, 'references': ('int',), 'literal_values': ()}, {'name': 'draw', 'type': 'Point', 'line': 4367, 'references': ('Point',), 'literal_values': ()}, {'name': 'budget', 'type': 'RateBudget', 'line': 4368, 'references': ('RateBudget',), 'literal_values': ()})},
    {'name': 'FMathCallV2', 'line': 4385, 'docstring': 'v2 op/whole args; legacy_bridge_prepare uses FPrepareCallArgs.\n\nThe facts factory checks op/args, prior steps and return types, then replays\nthe existing mathematical functions before issuing a result.', 'fields': ({'name': 'op', 'type': 'FMathOpV2', 'line': 4391, 'references': ('FMathOpV2',), 'literal_values': ()}, {'name': 'args', 'type': 'FMathCallArgsV2', 'line': 4392, 'references': ('FMathCallArgsV2',), 'literal_values': ()})},
    {'name': 'FLegacyBridgeProblemMathClaim', 'line': 4396, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['FLegacyBridgeProblem']", 'line': 4397, 'references': ('FLegacyBridgeProblem', '_Literal'), 'literal_values': ('FLegacyBridgeProblem',)}, {'name': 'value', 'type': 'FLegacyBridgeProblem', 'line': 4398, 'references': ('FLegacyBridgeProblem',), 'literal_values': ()})},
    {'name': 'LegacyComparisonMathClaim', 'line': 4402, 'docstring': '適用外: 公開クラスのdocstringなし', 'fields': ({'name': 'type', 'type': "_Literal['LegacyComparison']", 'line': 4403, 'references': ('LegacyComparison', '_Literal'), 'literal_values': ('LegacyComparison',)}, {'name': 'value', 'type': 'LegacyComparison', 'line': 4404, 'references': ('LegacyComparison',), 'literal_values': ()})},
    {'name': 'FMathArtifactJSONV2', 'line': 4411, 'docstring': 'Unverified math_artifact/2 envelope; v1 remains a distinct wire type.', 'fields': ({'name': 'contract', 'type': '_ContractRef', 'line': 4413, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'compiler', 'type': '_ContractRef', 'line': 4414, 'references': ('_ContractRef',), 'literal_values': ()}, {'name': 'input', 'type': 'FMathInputV2', 'line': 4415, 'references': ('FMathInputV2',), 'literal_values': ()}, {'name': 'environment', 'type': 'FMathEnvironment', 'line': 4416, 'references': ('FMathEnvironment',), 'literal_values': ()}, {'name': 'calls', 'type': 'tuple[FMathCallV2, ...]', 'line': 4417, 'references': ('FMathCallV2', 'tuple'), 'literal_values': ()}, {'name': 'output', 'type': 'int', 'line': 4418, 'references': ('int',), 'literal_values': ()}, {'name': 'claim', 'type': 'FMathClaimV2', 'line': 4419, 'references': ('FMathClaimV2',), 'literal_values': ()})},
)

REVISION2_SPEC = {'version': 'v0.22', 'lines': 2723, 'sha256_lf': '72bfe382a80675166772eb91c4c816503bce5472c0c47639cd4c233e3151b5a9', 'read_scope': '§2-5:2005–2597全文、D7:22、既存指定節の差分/該当部分', 'public_scope': 'src/sui/f.py: 公開クラスの名前・注釈つきの公開欄・docstringのみ。メソッド/関数/私有定義・型別名の定義は未読。', 'public_classes': 134, 'public_fields': 548}


# 型名の補助部分 ('.payload' 等) は一覧の欄経路であり、新契約ではない。
WIRE_TYPES = {}
def _wire_type(name, line, fields='', branches=(), *, note='', issues=(), end=None):
    WIRE_TYPES[name] = dict(name=name, sources=(source(FB, line, end or line),),
                            fields=tuple(tuple(item.split(':', 1)) for item in fields.split(';') if item),
                            branches=tuple(branches), note=note or WIRE_SECTION_LINES[line], issues=tuple(issues))

_wire_type('ContractRef',2103,'name:str;version:str')
_wire_type('ContractValue',2104,'contract:ContractRef;value:JSON')
_wire_type('MethodCall',2105,'contract:ContractRef;args:JSON',note='名前・版・全args、入力/返値/参照経路の意味はその方法の宣言で閉じる。未宣言方法はmissing_contract (2149)。')
_wire_type('SlotValue<T>',2106,'slot:str;declaration:SlotValue.declaration<T>')
_wire_type('SlotValue.declaration<T>',2106,'contract:ContractRef;value:T')
_wire_type('SlottedMethod',2107,'slot:str;method:MethodCall')
_wire_type('BootSlot',2108,'declaration:Point;slot:str',note='保存したboot_declaration内の一意な位置。process/reader/allocation/permissionを順番で選ばない (2112)。')
_wire_type('QuantityValue',2109,'contract:ContractRef;value:非負整数(bool不可)')
_wire_type('FixedView',2110,'boundary:Set[Point];environment:FixedView.environment')
_wire_type('FixedView.environment',2110,'reader_view_key:str;registry_key:?str',note='registry_key=nullはregistryを使わないと宣言した操作だけ (2055)。')
_wire_type('Seats',2116,'value:非負整数(bool不可)',note='スカラー値そのもの。valueキーを持つオブジェクトを新設しない。負のFree/割当を0へ丸めない。')
_wire_type('ResourceScope',2117,'quantity_contract:ContractRef;need:MethodCall')
_wire_type('Allocation',2118,'scope_slot:str;amount:QuantityValue')
_wire_type('BootstrapRoute',2119,'config:RouteConfig;process_slot:str;allocation:SlotValue<Allocation>')
_wire_type('InitialProcess',2120,'process_slot:str;reader_slot:str;model:Point;generator:MethodCall;method:MethodCall;allocation:SlotValue<Allocation>;derivation:SlottedMethod')
_wire_type('Environment',2121,'data:JSON',note='明示された自由JSON。文字列をPointや認証済みregistry識別へ変換しない。')
_wire_type('BootDeclaration',2125,'capacity:QuantityValue;scope:SlotValue<ResourceScope>;routes:List[SlotValue<BootstrapRoute>];initial:?SlotValue<InitialProcess>;environment:SlotValue<Environment>')
_wire_type('ReceivedUpdateArgs',2135,'process_slot:str;reader_slot:str;purpose:belief_result;condition:MethodCall;trigger_slots:MethodCall;inputs:MethodCall;stage_slots:MethodCall;grouping:MethodCall;request:MethodCall',end=2153,
           note='δの宣言の全9欄。具体的方法はBootの設定。一定間隔・全Receivedで即更新という規則を足さない。/2射影はG-01を別に保持。')
_wire_type('Trigger',2159,'point:Point;slot:str')
_wire_type('Stage',2161,branches=tuple((x,'適用外: 列挙値だけ') for x in ('measure_segment','candidate_generation','belief_result','belief_proof','verification','evaluation_prepare','selection_draw','evaluation')))
_wire_type('Desc<Args>',2163,'work_id:str;process:BootSlot;trigger:Set[Trigger];purpose:Stage;stage_slot:str;reader:?Point;method:ContractRef;output_contract:ContractRef;args:Args;input_points:Set[Point];numerical_view:?FixedView;allocation:BootSlot;permissions:Set[BootSlot]',note='13欄。reader/numerical_viewのnullは用途宣言が不使用とする場合だけ (2165)。input_pointsを必要閉包の正解にせず、集合とargs内の入力順を区別 (2180)。')
_wire_type('SegmentArgs',2169,'route:Point;requested_interval:MeasurementInterval;start_reason:str')
_wire_type('CandidateArgs',2170,'model:Point;generator_args:JSON;basis:List[Point]')
_wire_type('ResultArgs',2171,'request:Point',note='requestは旧Q。新wrapperではない。')
_wire_type('ProofArgs',2172,'request:Point;result:Point;checker:ProofRef')
_wire_type('VerificationArgs',2173,'target:VerificationArgs.target;check_view:FixedView;checker:ProofRef;acquisitions:Set[Point]')
_wire_type('VerificationArgs.target',2173,'request:Point;result:Point;proofs:Set[Point];completion:Point')
_wire_type('EvaluationPrepareArgs',2174,'input:FFactsRequest;compiler:ContractRef')
_wire_type('DrawArgs',2175,'prepared:Point;stream_id:str;request:DrawRequest')
_wire_type('EvaluationArgs',2176,'evaluation_request:Point;prepared:Point;draw:Point')
_wire_type('ClockReading',2188,'run:Ref;time_ns:int')
_wire_type('Unavailable',2189,'reason:str;basis:List[Ref]')
_wire_type('ReadingEvidence',2190,branches=(('clock','ReadingEvidence.clock'),('unavailable','Unavailable')))
_wire_type('ReadingEvidence.clock',2190,'source:Point;reading:ClockReading')
_wire_type('GenerationPair',2191,'started:ReadingEvidence;finished:ReadingEvidence')
_wire_type('FailureInfo',2192,'failure_kind:str;content:JSON;readings:List[ReadingEvidence];basis:List[Ref]')
_wire_type('UnknownInfo',2193,'reason:str;basis:List[Ref]')
_wire_type('WorkOutcome',2194,branches=(('outputs','ContractValue'),('failure','FailureInfo'),('unknown','UnknownInfo')))
_wire_type('DrawOutcome',2195,branches=(('value','JSON'),('failure','FailureInfo'),('unknown','UnknownInfo')))
_wire_type('CandidateGeneration',2196,branches=(('candidates','FCandidateDeclaration'),('no_candidates','{}')))
_wire_type('ProofOutput',2197,'role:normalization/query;statement:ContractValue;checker:ProofRef',note='形は確定。/2のstatement/checker意味は別のG-01行で未決。')
_wire_type('VerificationResponse',2198,branches=(('verified','◆G-01'),('rejected','◆G-01'),('insufficient','◆G-01')),issues=('G-01',))
_wire_type('TerminalReturned',2199,branches=(('output','ContractValue'),('point','Point'),('draw_value','JSON'),('null','null')),
           note='nullはタグ付きの第四枝ではなく値全体がnull。pointは保存済みの対応生成物だけ。')
_wire_type('TerminalBasis',2200,'generation:?GenerationPair;failure:?FailureInfo;unknown:?UnknownInfo',note='Computeのgeneration必須、開始終了報告のないDrawはnull。failure/unknownは該当一方、既知出力では両方null。')
_wire_type('SegmentReport',2212,'segment:Point;item_slot:str;item:SegmentItem')
_wire_type('SegmentItem',2214,branches=(('started','SegmentItem.started'),('ended','SegmentItem.ended'),('route_applied','SegmentItem.route_applied'),('frame','MeasurementFrame'),('gap','Gap'),('measurement_unavailable','MeasurementUnavailable'),('claim','CoverageClaim'),('coverage_unproved','CoverageUnproved')),
           note='2216–2223の8枝。kind/value。既存DTOに同義タグを二重に足さない (2202)。',end=2227)
_wire_type('SegmentItem.started',2216,'work:str;reading:ReadingEvidence;reason:str;evidence:List[Ref]')
_wire_type('SegmentItem.ended',2217,'work:str;reading:ReadingEvidence;reason:str;evidence:List[Ref]')
_wire_type('SegmentItem.route_applied',2218,'config:Point;reading:ReadingEvidence;reason:str;evidence:List[Ref]')
_wire_type('MeasurementFrame',2219,'route_epoch:str;sample_seq:int;measurement_id:MeasurementId;measurement_interval:MeasurementInterval;actual_time:ClockReading/Unavailable;value:JSON/Unavailable;quality:ContractValue;gap:?Gap;source_cursor:ContractValue')
_wire_type('Gap',2220,'route_epoch:str;sequence_range:[first:int,stop:int];interval:MeasurementInterval;reason:str;evidence:List[Ref]',note='sequence_rangeは二整数列。{first,stop}オブジェクトへ変えない (v0.22修正)。')
_wire_type('MeasurementUnavailable',2221,'route_epoch:str;requested_interval:MeasurementInterval;reason:str;evidence:List[Ref]')
_wire_type('CoverageClaim',2222,'route_epoch:str;interval:MeasurementInterval;kind:str;contract:ContractRef;evidence:List[Ref]')
_wire_type('CoverageUnproved',2223,'route_epoch:str;interval:MeasurementInterval;missing_contracts:List[ContractRef];evidence:List[Ref]')
_wire_type('MeasurementInterval',2225,'clock:Ref;start_ns:int;end_ns:int;closure:[start,end)/(start,end]/[start,end]/(start,end)')
_wire_type('MeasurementId',2225,'origin:Ref;route_epoch:str;sample_seq:int;component:str')
_wire_type('BindingGeneration',2229,'applied:?Point;started:?Point;ended:?Point',note='原報告のPoint。契約が不使用とする時だけnull。古いgapへ一律のstarted先行を課さない。')
_wire_type('Projection<T>',2250,branches=(('evidence','T'),('held','Projection.held')))
_wire_type('Projection.held',2250,'reason:str',note='H/Pが完全な対応を保持。対象不存在/所有者なしを意味しない。')
_wire_type('SavedKeyValue',2251,branches=(('point','Point'),('boot_slot','BootSlot'),('contract','ContractRef'),('name','str')))
_wire_type('SavedKeyField',2252,'role:str;value:SavedKeyValue')
_wire_type('SavedCondition',2253,'o_id:str;key:List[SavedKeyField];condition:issue/save/run/handle/stop;target:SavedKeyValue')
_wire_type('Part',2254,branches=(('whole','{}'),('cell','Part.cell')))
_wire_type('Part.cell',2254,'interval:MeasurementInterval')
_wire_type('SavedPurpose',2255,'original:SavedCondition;role:str;part:Part')
_wire_type('SavedTarget',2256,branches=(('point','Point'),('contract','ContractRef'),('reason','SavedTarget.reason')))
_wire_type('SavedTarget.reason',2256,'reason:str')
_wire_type('MissingTarget',2257,'point:?Point;contract:?ContractRef;reason:str')
_wire_type('SavedOwner',2258,'anchor:Point;slot:str')
_wire_type('WaitingPayload',2259,'obligation:Projection<SavedCondition>;purpose:Projection<SavedPurpose>;target:SavedTarget;missing:List[MissingTarget];witness:Set[Point];view:FixedView;owner:Projection<SavedOwner>')
_wire_type('ConflictRule',2301,'id:CL-SAME/CL-SEQ/CL-MEASUREMENT/CL-EXECUTION/CL-DRAW/CL-APPLY;version:1',
           note='六規則。CL-APPLYの/2適用同一性は別G-01行。Unknown+後着値/正当なStaleだけではConflictではない。')

# 新しい台帳契約22。本文の外側/親/使い方は該当表の原文も保持する。
WIRE_LEDGER_SPECS = (
    ('received','Received','route_epoch:str;media_type:str;data:bytes;claims:JSON',2275),
    ('boot_declaration','BootDeclaration','',2276),
    ('segment_report','SegmentReport','',2277),
    ('work_report','WorkReport','work:str;started:ReadingEvidence;finished:ReadingEvidence;outcome:WorkOutcome',2278),
    ('draw_report','DrawReport','work:str;outcome:DrawOutcome',2279),
    ('segment_requested','SegmentRequested','desc:Desc<SegmentArgs>',2280),
    ('candidate_request','CandidateRequest','desc:Desc<CandidateArgs>',2281),
    ('work_requested','WorkRequested','desc:Desc<用途別args>',2282),
    ('evaluation_requested','EvaluationRequested','desc:Desc<EvaluationPrepareArgs>',2283),
    ('draw_requested','DrawRequested','desc:Desc<DrawArgs>',2284),
    ('work_terminal','WorkTerminal','work:str;request:Point;stage:Stage;first_receipt:Point;terminal_kind:outputs/value/failure/unknown;returned:?TerminalReturned;basis:TerminalBasis;view:FixedView',2285),
    ('draw_unknown','DrawUnknown','draw_request:Point;first_receipt:Point;unknown_basis:UnknownInfo;view:FixedView',2286),
    ('segment_binding','SegmentBinding','segment:Point;report:Point;route:Point;reading_contract:ContractRef;evidence:Set[Point];generation:BindingGeneration;clock:Set[Point];view:FixedView',2287),
    ('verification','Verification','request:Point;report:Point',2288),
    ('prepared','Prepared','request:Point;report:Point;artifact:Point',2289),
    ('evaluated','Evaluated','request:Point;report:Point;artifact:Point',2290),
    ('selection','Selection','evaluated:Point',2291),
    ('acquisition_requested','AcquisitionRequested','origin:Point;contents:Set[Point]',2292),
    ('adoption_requested','AdoptionRequested','origin:Point;completion:Point;planned_previous:?Point;verification:Point;acquisitions:Set[Point]',2293),
    ('stale','Stale','intent:Point;actual_previous:?Point;view:FixedView',2294),
    ('conflict','Conflict','reports:Set[Point];rule:ConflictRule;view:FixedView',2295),
    ('waiting','WaitingPayload','',2296),
)
WIRE_VALUE_SPECS = (
    ('seats','Seats',2116),('resource_scope','ResourceScope',2117),
    ('allocation','Allocation',2118),('bootstrap_route','BootstrapRoute',2119),
    ('initial_process','InitialProcess',2120),('environment','Environment',2121),
    ('received_update','ReceivedUpdateArgs',2135),
    ('candidate_generation','CandidateGeneration',2297),
    ('proof_output','ProofOutput',2298),('verification_response','VerificationResponse',2299),
)
WIRE_EXTERNAL_SPECS = (('generation_draw_requested',2497),('generation_draw_unknown',2498))

for _contract, _type, _fields, _line in WIRE_LEDGER_SPECS:
    if _fields:
        _wire_type(_type, _line, _fields)

# 既存契約のコピー。新契約の件数に加算しない。
EXISTING_COPY_SPECS = (
    ('sui.s4.boot/1','ExistingBoot','',2313),
    ('sui.clock.source/1','ExistingClockSource','run:Ref;provider:str;implementation:str;python_version:str;resolution_s:R;monotonic:bool;adjustable:bool;measurement:?ContractRef',2314),
    ('sui.f.route_config/1','ExistingRouteApplied','config:RouteConfig;effective_from:ClockReading/Unavailable;execution:?Ref;evidence:List[Ref]',2315),
    ('sui.f.knowledge_origin/1','ExistingOrigin','model:Point',2316),
    ('sui.f.computation_requested/1','ExistingQ','origin:Point;purpose:belief/query/certificate;method:ContractRef;args:JSON;inputs:List[Point];algorithm_draws:List[Point];output_contract:ContractRef',2317),
    ('sui.f.computation_result/1','ExistingResult','request:Point;output:ContractValue',2318),
    ('sui.f.computation_proof/1','ExistingProof','request:Point;result:Point;role:normalization/query;statement:ContractValue;checker:ProofRef',2319),
    ('sui.f.clock_reading/1','ExistingClockReading','source:Point;reading:ClockReading',2320),
    ('sui.f.computation_completed/1','ExistingCompletion','request:Point;result:Point;proofs:List[Point];started_clock:Point;finished_clock:Point',2321),
    ('sui.f.content_acquired/1','ExistingAcquisition','origin:Point;contents:List[Point];clock:Point',2322),
    ('sui.f.knowledge_adopted/1','ExistingAdoption','origin:Point;previous:?Point;completion:Point',2323),
    ('sui.f.candidate_declaration/1','FCandidateDeclaration','',2324),
    ('sui.f.draw_fact/1','ExistingDrawFact','generator:ContractRef;stream_id:str;request:DrawRequest;value:JSON',2325),
    ('sui.f.math_artifact/2','ExistingMathArtifact2','contract:ContractRef;compiler:ContractRef;input:FMathInputV2;environment:FMathEnvironment;calls:List[FMathCallV2];output:int;claim:FMathClaimV2',2326),
)
for _contract, _type, _fields, _line in EXISTING_COPY_SPECS:
    if _type != 'FCandidateDeclaration':
        _wire_type(_type, _line, _fields)
_wire_type('RouteConfig',2330,'route_epoch:str;origin:bootstrap/selected;version:str;sampling_contract:ContractRef;clock_contract:ContractRef;loss_contract:ContractRef;args:JSON;decision:?Ref;execution:?Ref')
_wire_type('DrawRequest',2331,'purpose:candidate_generation/selection/reservation/algorithm;context_key:str;ordinal:int;law:ContractRef;args:JSON')
_wire_type('FCandidateDeclaration',2332,'model:Point;input_order:List[str];measure:?CandidateMeasureRef;generation:FCandidateGeneration;continuation:FContinuation')
_wire_type('FCandidateGeneration',2332,'generator:ContractRef;args:JSON;basis:List[Point];draws:List[Point]')
_wire_type('FContinuation',2332,'after:List[ContinuationAfter]')
_wire_type('ContinuationAfter',2332,'candidate:str;policy:?PolicyRef')
for _name in ('CandidateMeasureRef','PolicyRef','ProofRef'):
    _wire_type(_name,2332,'name:str;version:str;args:JSON')
_wire_type('FFactsRequest',2333,'fixed_parents:List[Point];model:Point;candidates:Point;preferences:List[Point];scope:EvaluationScope;context:Point;method:ContractRef')
_wire_type('EvaluationScope',2333,'name:unbounded_total/one_step/finite_horizon;version:1;H_ns:?int;source:?Ref',note='§2-5:2333とF-a公開EvaluationScope (f.py:362–369)。ResourceScopeではない。')

# 共通保存層。八Bodyは既存T.body.*で列挙済み、ここで第九Bodyを作らない。
_wire_type('RecordEnvelope',2025,'id:Ref;at:Instant;writer:Role;producer:Producer;body:Body;schema:3')
_wire_type('Instant',2025,'run:Ref;run_index:int;seq:int;mono_ns:int;wall_ns:int')
_wire_type('Producer',2025,'component:str;code_version:str;state:?ProducerState')
_wire_type('ProducerState',2025,'lineage:str;revision:int')
_wire_type('ObservedEnvelope',2042,'route:fb;content:Payload;contract:ContractRef;caused_by:null;source_id:null;source_time_ns:null;received_ns:int',note='rawと論理Oでrの根拠が別。rawはPostのr、論理Oは形成時にMを一回読み再試行で固定 (2063–2065)。')
_wire_type('DecidedEnvelope',2044,'inputs:List[Ref];content:Payload;contract:ContractRef')
_wire_type('PredictionEnvelope',2045,'target:str;about:List[Ref];basis:List[Ref];content:Payload;contract:ContractRef')


# 旧版の出典位置を現行の行へ移す。IDは安定させ、元位置と版も失わない。
# PAPER_FRAGMENTSの完全一致で166行を照合: +5が127行、+598が39行。
# 旧486は追記案内が変わった行。旧17の合格条件は現行20、D7は22。
def _current_fb_line(n):
    return n + (3 if n <= 18 else 5 if n < 2000 else 598)

def _relocate_sources(obj):
    if isinstance(obj, dict):
        if obj.get('path') == FB and 'first' in obj and 'last' in obj:
            obj['original_version'] = 'v0.19'
            obj['original_first'], obj['original_last'] = obj['first'], obj['last']
            obj['first'], obj['last'] = _current_fb_line(obj['first']), _current_fb_line(obj['last'])
            obj['version'] = 'v0.22'
        else:
            for v in obj.values():
                _relocate_sources(v)
    elif isinstance(obj, (tuple, list)):
        for v in obj:
            _relocate_sources(v)

# 各構造を独立コピーしてから更新し、同一source辞書の二重移動を避ける。
for _key in DENOMINATOR_KEYS + ('BRIDGES','BRIDGE_SOURCE_ITEMS','BRIDGE_RECIPES','SECTION_DISPOSITIONS'):
    globals()[_key] = _copy_tree(globals()[_key])
    _relocate_sources(globals()[_key])
PROVENANCE = dict(PROVENANCE, version='2', spec_version='v0.22',
                  spec_lines=REVISION2_SPEC['lines'], spec_sha256_lf=REVISION2_SPEC['sha256_lf'],
                  read_limits=REVISION2_SPEC['public_scope'])
_rows = list(TARGETS)

GAPS['G-01']['sources'] += (source(FB,2558,2560), source(FB,2585,2594))
GAPS['G-02'] = dict(classification='後で',status='解消',
                    message='v0.22 §2-5で保存の形が宣言された。/2の未決はG-01として別に保持。',sources=(source(FB,2005,2597),))
GAPS['G-03'] = dict(classification='後で',status='解消',
                    message='D7で量化と観察の範囲が決まった。★実走は実装後の観察で、自己点検/自動試験の成功ではない。',sources=(source(FB,22),))
GAPS['G-05'] = dict(classification='直すべき',status='未対応',
                    message='残り: RateBudgetの宣言・旧sui.s4d.preference/1の全保存形・公開クラスの注釈から参照される未列挙型別名。許可された公開クラス宣言だけで全枝を作らない。',
                    sources=(source(FA,82),source(FA,433),source('src/sui/f.py',546,559),source('src/sui/f.py',599,609)))
GAPS['G-RUN-CODEC'] = dict(classification='後で',status='未決',
                    message='Runの公開欄は列挙できたが、measurement_run/1のcolumns/encoding/例外・空列の符号化は公開docstring自身がF-b未確定とする。',
                    sources=(source(FA,74),source('src/sui/f.py',857,867)))
RESOLVED_MISMATCHES = tuple(dict(x, resolution='紙V-02訂正と§2-5:2025、公開Instant.wall_ns:intが一致。隔離解除。',
                                   resolution_sources=(source(FA,28),source(FB,2025),source('src/sui/clock.py',18))) for x in MISMATCHES)
MISMATCHES = ()

# 紙で定義済みの規則IDを使う。管理用IDは規則を新設しない。
def _wire_context(name):
    if name in ('ResourceScope','QuantityValue','Seats','Allocation'):
        return ('INV-8','INV-13'),('I-6',)
    if name in ('BootDeclaration','BootstrapRoute','InitialProcess','Environment','BootSlot','SlotValue<T>','SlotValue.declaration<T>','SlottedMethod'):
        return ('INV-13','INV-10'),('I-6',)
    if name == 'ReceivedUpdateArgs':
        return ('L-DERIVE','INV-2','INV-3'),('I-1','I-6')
    if name == 'Received':
        return ('INV-1','I-1','背骨②'),('I-1',)
    if name.startswith(('Segment','Measurement','Coverage','Gap','Binding')):
        return ('INV-12','INV-3'),('I-2',)
    if name in ('DrawOutcome','DrawReport','DrawArgs','DrawRequested','DrawUnknown','DrawRequest','ExistingDrawFact'):
        return ('INV-14','INV-15'),('I-8',)
    if name.startswith(('Saved','Waiting','Missing','Projection','Part')):
        return ('INV-2.c','INV-7'),('I-3',)
    if name.startswith(('Work','Terminal','Generation','Reading','Failure','Unknown')):
        return ('INV-15','INV-9','INV-3'),('I-3','I-8')
    if name in ('CandidateGeneration','CandidateRequest','CandidateArgs','FCandidateDeclaration','FCandidateGeneration'):
        return ('INV-2.g','INV-9'),('I-3','I-6')
    if name in ('Verification','VerificationArgs','VerificationArgs.target','VerificationResponse','ProofOutput','ProofArgs'):
        return ('INV-6','INV-11','INV-3'),('I-3',)
    if name in ('Prepared','Evaluated','Selection','EvaluationRequested','EvaluationArgs','EvaluationPrepareArgs','ExistingMathArtifact2','FFactsRequest'):
        return ('INV-5','INV-11','INV-16'),('I-3','I-8')
    return ('INV-3','INV-10','背骨⑤'),('I-1','I-2','I-3','I-6','I-7','I-8')

WIRE_FIELD_ENUMS = {
    ('ReceivedUpdateArgs','purpose'):('belief_result',),
    ('ProofOutput','role'):('normalization','query'),
    ('ExistingProof','role'):('normalization','query'),
    ('WorkTerminal','terminal_kind'):('outputs','value','failure','unknown'),
    ('SavedCondition','condition'):('issue','save','run','handle','stop'),
    ('ConflictRule','id'):('CL-SAME','CL-SEQ','CL-MEASUREMENT','CL-EXECUTION','CL-DRAW','CL-APPLY'),
    ('ConflictRule','version'):('1',),
    ('ExistingQ','purpose'):('belief','query','certificate'),
    ('RouteConfig','origin'):('bootstrap','selected'),
    ('DrawRequest','purpose'):('candidate_generation','selection','reservation','algorithm'),
    ('EvaluationScope','name'):('unbounded_total','one_step','finite_horizon'),
    ('EvaluationScope','version'):('1',),
    ('MeasurementInterval','closure'):('[start,end)','(start,end]','[start,end]','(start,end)'),
    ('MeasurementFrame','actual_time'):('clock','unavailable'),
    ('MeasurementFrame','value'):('value','unavailable'),
    ('ExistingRouteApplied','effective_from'):('clock','unavailable'),
}
WORK_PURPOSE_ARGS = (
    ('measure_segment','SegmentArgs'),('candidate_generation','CandidateArgs'),
    ('belief_result','ResultArgs'),('belief_proof','ProofArgs'),
    ('verification','VerificationArgs'),('evaluation_prepare','EvaluationPrepareArgs'),
    ('selection_draw','DrawArgs'),('evaluation','EvaluationArgs'),
)

# 紙に型名だけでなく意味の未決がある部分は形の確定と区別する。
WIRE_SEMANTIC_GAPS = (
    ('verification_payload',2198,('VerificationResponse',),'三枝のpayload・実発行物の全結合は◆G-01'),
    ('proof_statement',2197,('ProofOutput',),'finite_update/2のstatement/checkerの意味'),
    ('binding_support',2414,('SegmentBinding',),'読み方の契約別Support・数値射影の意味はG-01'),
    ('cl_apply',2301,('ConflictRule',),'CL-APPLYの/2適用同一性'),
    ('method_paths',2303,('Desc<Args>','ReceivedUpdateArgs'),'方法別の未宣言経路・/2の入力閉包はG-01'),
    ('target_certificate',2490,('VerificationArgs','Verification'),'対象指定の生きた発行物と保存説明値の契約はG-01'),
)

# FBT-04の行を作る。wire形だけの行は、意味・実装の合格を主張しない。
def _wire_add(id, kind, subject, *, refs, fields=NA, branch=NA, body=NA, contract=NA,
              use, rules, entries, role=NA, edges=NA, presence='必須', status='整理済み', issues=(),
              related=(), representation='保存宣言', value_type=None):
    row = _target(id,kind,subject,sources=refs,rules=rules,entries=entries,use=use,
                  evidence='紙の宣言・固定した独立入力・公開型の宣言。窓口の出力から期待値を作らない。',
                  negative='宣言した欄/枝/型/版/対応の一つだけを変え、保存と意味使用の境界ごとに差を確かめる。',
                  legal='他の入力を同一に保ち、当該宣言と用途の条件を満たす値。未決の数値正解を作らない。',
                  body=body,contract=contract,field=fields,branch=branch,role=role,edges=edges,
                  owner='保存の担当と意味の使用者を区別。独立原本は§2-5-2のH/EH/EW/EA/P。',
                  consumer='/'.join(entries),presence=presence,status=status,issues=issues)
    row['representation'] = representation
    row['related_targets'] = tuple(related)
    if value_type is not None:
        row['declared_type'] = value_type
    _rows.append(row)
    return row

for _name, _decl in WIRE_TYPES.items():
    _tid = 'T.wire.type.' + _name
    _rules,_entries = _wire_context(_name)
    _issues = _decl['issues']
    _status = '未決' if _issues else '整理済み'
    _wire_add(_tid,'relation',_name,refs=_decl['sources'],use=_decl['note'],rules=_rules,entries=_entries,
              issues=_issues,status=_status,representation='入れ子の値型。単独Body・親なし')
    for _field,_annotation in _decl['fields']:
        _fid = _tid+'.field.'+_field
        _row = _wire_add(_fid,'field',_name,refs=_decl['sources'],fields=_field,
                        use=_decl['note'],rules=_rules,entries=_entries,related=(_tid,),
                        presence='キー必須・null可 (用途別の条件も必要)' if _annotation.startswith('?') else 'キー必須・非null',
                        issues=_issues,status=_status,value_type=_annotation)
        if _name=='Seats':
            _row['field']='値そのもの (保存キーなし)'
            _row['presence']='非負整数のスカラー。bool不可'
            _row['negative']='-1・true・0へ丸めた負のFree・{value:0}を席の合法値とする'
            _row['nearest_legal']='整数0または1。負の算術差は保存可能な資源量と区別する'
        if _field in ('time_ns','mono_ns','received_ns','start_ns','end_ns','wall_ns'):
            _row['role']={'time_ns':'e/r等は使用箇所で固定','mono_ns':'s','received_ns':'r','start_ns':'i','end_ns':'i','wall_ns':'s (壁時計)'}[_field]
            _row['domain']='U' if _field=='wall_ns' else 'M (宣言されたrunと時計契約を照合)'
            _row['run']='Record.at.run / ClockReading.run / MeasurementInterval.clock の宣言された対応'
        _choices = WIRE_FIELD_ENUMS.get((_name,_field),())
        if _annotation.startswith('?'):
            _choices = ('value','null')
        for _choice in _choices:
            _wire_add(_fid+'.branch.'+_choice,'branch',_name+'.'+_field,refs=_decl['sources'],
                      branch=_choice,fields=_field,use=_decl['note'],rules=_rules,entries=_entries,
                      related=(_fid,),issues=_issues,status=_status)
    for _branch,_payload in _decl['branches']:
        _bid=_tid+'.branch.'+_branch
        _wire_add(_bid,'branch',_name,refs=_decl['sources'],branch=_branch,use=_decl['note'],rules=_rules,entries=_entries,
                  related=(_tid,),issues=_issues,status=_status,value_type=_payload)
        if _name not in ('Stage',) and _branch!='null':
            for _field,_type in (('kind',_branch),('value',_payload)):
                _wire_add(_bid+'.field.'+_field,'field',_name,refs=_decl['sources']+(source(FB,2202),),fields=_field,branch=_branch,
                          use='kind/valueの新しい和型。既存kind/opへ同義タグを足さない。'+_decl['note'],rules=_rules,entries=_entries,
                          related=(_bid,),issues=_issues,status=_status,value_type=_type)

WIRE_DECLARATIONS = []
for _name,_type,_fields,_line in WIRE_LEDGER_SPECS:
    _cols = tuple(c.strip() for c in WIRE_SECTION_LINES[_line].split('|')[1:-1])
    _body = 'Decided' if _cols[1].startswith('D、') else 'Observed'
    _role = 'MODEL / FACT' if _body=='Decided' else 'MEMBRANE / FACT'
    _rules,_entries = _wire_context(_type)
    _id = 'T.wire.contract.'+_name
    _wire_add(_id,'contract','sui.fb.'+_name+'/1',refs=(source(FB,_line),source(FB,2031,2045)),
              body=_body,contract='sui.fb.'+_name+'/1',role=_role,edges='親: '+_cols[3]+'; 使用: '+_cols[2],
              use=_cols[2]+'。'+WIRE_TYPES[_type]['note'],rules=_rules,entries=_entries,
              related=('T.wire.type.'+_type,))
    WIRE_DECLARATIONS.append(dict(name='sui.fb.'+_name,version='1',category='ledger',payload=_type,target=_id,
                                   source=source(FB,_line),body=_body,role_category=_role,parents=_cols[3]))
for _name,_type,_line in WIRE_VALUE_SPECS:
    _rules,_entries = _wire_context(_type)
    _id = 'T.wire.contract.'+_name
    _wire_add(_id,'contract','sui.fb.'+_name+'/1',refs=(source(FB,_line),source(FB,2123)),contract='sui.fb.'+_name+'/1',
              use='内側の値契約。単独Body/Role/Category/親なし。'+WIRE_TYPES[_type]['note'],rules=_rules,entries=_entries,
              related=('T.wire.type.'+_type,),status='未決' if _type=='VerificationResponse' else '整理済み',issues=('G-01',) if _type=='VerificationResponse' else ())
    WIRE_DECLARATIONS.append(dict(name='sui.fb.'+_name,version='1',category='value',payload=_type,target=_id,
                                   source=source(FB,_line),body=NA,role_category=NA,parents=NA))
for _name,_line in WIRE_EXTERNAL_SPECS:
    _id='T.wire.contract.'+_name
    _wire_add(_id,'contract','sui.fb.'+_name+'/1',refs=(source(FB,_line),),contract='sui.fb.'+_name+'/1',
              use='未採用R10。全欄・Body・時刻・参照・親は追加時に宣言。選択用D/DUの名前交換ではない。',rules=('INV-14.c',),entries=('I-8',),
              related=('T.external.R10',),status='未採用',issues=('G-04',))
    WIRE_DECLARATIONS.append(dict(name='sui.fb.'+_name,version='1',category='external',payload='未採用: R10追加時',target=_id,
                                   source=source(FB,_line),body='未採用: 追加時に宣言',role_category='未採用: 追加時に宣言',parents='未採用: 追加時に宣言'))
WIRE_DECLARATIONS=tuple(WIRE_DECLARATIONS)

EXISTING_COPIES=[]
for _contract,_type,_fields,_line in EXISTING_COPY_SPECS:
    _cols=tuple(c.strip() for c in WIRE_SECTION_LINES[_line].split('|')[1:-1])
    _body={'O':'Observed','D':'Decided','P':'Prediction'}[_cols[1][0]]
    _id='T.wire.existing.'+_contract
    _rules,_entries=_wire_context(_type)
    _wire_add(_id,'relation',_contract,refs=(source(FB,_line),source(FB,2309)),body=_body,contract=_contract,
              role='MODEL / PREDICTION' if _body=='Prediction' else 'MODEL / FACT' if _body=='Decided' else 'MEMBRANE / FACT',
              use=_cols[2]+'。既存の全欄と旧一般受理条件を変更しない。',edges=_cols[2],rules=_rules,entries=_entries,
              related=('T.wire.type.'+_type,))
    EXISTING_COPIES.append(dict(contract=_contract,payload=_type,target=_id,source=source(FB,_line)))
EXISTING_COPIES=tuple(EXISTING_COPIES)

for _purpose,_type in WORK_PURPOSE_ARGS:
    _wire_add('T.wire.purpose.'+_purpose,'relation',_purpose,refs=(source(FB,2161,2176),source(FB,2280,2284)),
              use='Desc.purposeから用途別argsへ。タグを足さず対象・入力・出力契約・親を用途ごとに照合。',
              rules=('INV-3','INV-9'),entries=('I-2','I-3','I-8'),
              related=('T.wire.type.Stage.branch.'+_purpose,'T.wire.type.Desc<Args>','T.wire.type.'+_type))
for _key,_line,_types,_reason in WIRE_SEMANTIC_GAPS:
    _wire_add('T.wire.unresolved.'+_key,'relation',_key,refs=(source(FB,_line),source(FB,2585,2594)),
              use='未決 (G-01): '+_reason,rules=('INV-3','INV-6','INV-11'),entries=('I-3',),
              related=tuple('T.wire.type.'+n for n in _types),status='未決',issues=('G-01',))

PUBLIC_ANNOTATION_UNIONS = (
    ('ExactReal', 'value', (('annotation', '_Fraction'), ('annotation', 'None'))),
    ('ExactReal', 'arg', (('annotation', 'ExactReal'), ('annotation', 'None'))),
    ('ExactReal', 'args', (('annotation', 'tuple[ExactReal, ...]'), ('annotation', 'None'))),
    ('ExactReal', 'numerator', (('annotation', 'ExactReal'), ('annotation', 'None'))),
    ('ExactReal', 'denominator', (('annotation', 'ExactReal'), ('annotation', 'None'))),
    ('CandidateSet', 'measure', (('annotation', 'CandidateMeasureRef'), ('annotation', 'None'))),
    ('EvaluationScope', 'H_ns', (('annotation', 'int'), ('annotation', 'None'))),
    ('EvaluationScope', 'source', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('KnowledgeHistory', 'belief', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('FRoot', 'style', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('FRoot', 'draw_point', (('annotation', 'str'), ('annotation', 'None'))),
    ('FRoot', 'draw_record_digest', (('annotation', 'str'), ('annotation', 'None'))),
    ('FQuantity', 'exact', (('annotation', 'ExactReal'), ('annotation', 'None'))),
    ('FQuantity', 'bounds', (('annotation', 'RationalInterval'), ('annotation', 'None'))),
    ('FQuantity', 'proof', (('annotation', 'ProofRef'), ('annotation', 'None'))),
    ('FQuantity', 'reason', (('annotation', 'str'), ('annotation', 'None'))),
    ('TailCertificate', 'proof', (('annotation', 'ProofRef'), ('annotation', 'None'))),
    ('FEvaluation', 'normalization', (('annotation', 'NormalizationCertificate'), ('annotation', 'None'))),
    ('NoDecision', 'attempt_id', (('annotation', 'str'), ('annotation', 'None'))),
    ('NoDecision', 'root_key', (('annotation', 'str'), ('annotation', 'None'))),
    ('NoDecision', 'field', (('annotation', 'str'), ('annotation', 'None'))),
    ('NoDecision', 'proof', (('annotation', 'ProofRef'), ('annotation', 'None'))),
    ('NoDecision', 'progress', (('annotation', 'FEvaluation'), ('annotation', 'None'))),
    ('NoDecision', 'resume', (('annotation', 'ResumePoint'), ('annotation', 'None'))),
    ('PredicateSnapshot', 'model_ref', (('annotation', 'str'), ('annotation', 'None'))),
    ('PredicateSnapshot', 'policy_position', (('annotation', 'PredicatePosition'), ('annotation', 'None'))),
    ('FScope', 'method', (('annotation', '_ContractRef'), ('annotation', 'None'))),
    ('FScope', 'reason', (('annotation', 'str'), ('annotation', 'None'))),
    ('FPathTable', 'steps', (('annotation', 'int'), ('annotation', 'None'))),
    ('ResumePoint', 'previous_certificate', (('annotation', 'FCertificate'), ('annotation', 'None'))),
    ('MeasurementFrame', 'actual_time', (('annotation', 'ClockReading'), ('annotation', 'Unavailable'))),
    ('MeasurementFrame', 'value', (('annotation', 'ImmutableJSON'), ('annotation', 'Unavailable'))),
    ('MeasurementFrame', 'gap', (('annotation', 'Gap'), ('annotation', 'None'))),
    ('RouteConfig', 'decision', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('RouteConfig', 'execution', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('StyleScope', 'H_ns', (('annotation', 'int'), ('annotation', 'None'))),
    ('FProblem', 'style', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('PolicyReturn', 'operation', (('annotation', 'str'), ('annotation', 'None'))),
    ('PolicyPosition', 'operation', (('annotation', 'str'), ('annotation', 'None'))),
    ('TailPrefix', 'steps', (('annotation', 'int'), ('annotation', 'None'))),
    ('FLimitProblem', 'cost', (('annotation', 'BlankLimitCost'), ('annotation', 'PrefixLogLoss'))),
    ('FLimitProblem', 'proof', (('annotation', 'ProofRef'), ('annotation', 'None'))),
    ('CapabilityContext', 'registry', (('annotation', 'FRegistry'), ('annotation', 'None'))),
    ('CapabilityContext', 'resources', (('annotation', 'object'), ('annotation', 'None'))),
    ('CapabilityContext', 'model_ref', (('annotation', 'str'), ('annotation', 'None'))),
    ('CapabilityContext', 'budget', (('annotation', 'RateBudget'), ('annotation', 'None'))),
    ('CapabilityContext', 'numeric_work', (('annotation', 'object'), ('annotation', 'None'))),
    ('CapabilityContext', 'cached_quantities', (('annotation', 'object'), ('annotation', 'None'))),
    ('CapabilityContext', 'numeric_input', (('annotation', 'object'), ('annotation', 'None'))),
    ('CapabilityContext', 'certified_input', (('annotation', 'object'), ('annotation', 'None'))),
    ('ContinuationAfter', 'policy', (('annotation', 'PolicyRef'), ('annotation', 'None'))),
    ('FFactsPointDependency', 'record', (('annotation', '_Ref'), ('annotation', 'None'))),
    ('FFactsPointDependency', 'record_digest', (('annotation', 'str'), ('annotation', 'None'))),
    ('FFactsModelDependency', 'model_ref', (('annotation', 'str'), ('annotation', 'None'))),
    ('FFactsCapabilityDependency', 'declaration', (('annotation', 'CapabilityDeclaration'), ('annotation', 'None'))),
    ('FFactsCapabilityDependency', 'implementation_id', (('annotation', 'str'), ('annotation', 'None'))),
    ('FFactsDependencies', 'absence_environment', (('annotation', 'FFactsAbsenceEnvironment'), ('annotation', 'None'))),
    ('FWorldManifest3', 'request', (('annotation', 'FMathFactsInput'), ('annotation', 'FMathLegacyBridgeInput'))),
    ('FCandidateDeclaration', 'measure', (('annotation', 'CandidateMeasureRef'), ('annotation', 'None'))),
    ('FPreflightFacts', 'model', (('annotation', 'Point'), ('annotation', 'None'))),
    ('FEvaluateCallArgs', 'resume_step', (('annotation', 'int'), ('annotation', 'None'))),
)


# f.pyのpublic carrierの宣言。保存DTOと同一とは仮定しない (F-a:405)。
PUBLIC_UNRESOLVED_NAMES = (
    'RateBudget','RationalInterval','NoDecisionReason','CapabilityKind',
    'FMathCallArgsV1','FMathCallArgsV2','FMathCallV1','FMathClaimV1','FMathClaimV2',
    'FMathInputV1','FMathInputV2','FMathOp','FMathOpV1','FMathOpV2',
)
PUBLIC_CLASS_BY_NAME = {x['name']:x for x in PUBLIC_CLASS_DECLARATIONS}
for _decl in PUBLIC_CLASS_DECLARATIONS:
    _name=_decl['name'];_tid='T.public.'+_name
    _refs=(source('src/sui/f.py',_decl['line'],max([_decl['line']]+[f['line'] for f in _decl['fields']])),source(FB,2334))
    _wire_add(_tid,'relation',_name,refs=_refs,use='公開クラスの宣言だけ。'+_decl['docstring'],
              rules=('INV-3','INV-10','背骨⑤'),entries=('I-3',),representation='公開Python型。保存DTOへの同一視なし')
    for _field in _decl['fields']:
        _fid=_tid+'.field.'+_field['name']
        _unknown=set(_field['references'])&set(PUBLIC_UNRESOLVED_NAMES)
        _related=tuple('T.public.'+n for n in _field['references'] if n in PUBLIC_CLASS_BY_NAME)
        _row=_wire_add(_fid,'field',_name,refs=(source('src/sui/f.py',_field['line']),source(FB,2334)),
                       fields=_field['name'],value_type=_field['type'],
                       use='注釈をそのまま保持。正準保存のpresence/枝はF-aの紙と区別して照合。'+('未対応: '+','.join(sorted(_unknown))+'の全宣言/別名の全枝。' if _unknown else ''),
                       rules=('INV-3','INV-10','背骨⑤'),entries=('I-3',),related=(_tid,)+_related,
                       presence='公開型注釈のnullableに従う。保存キーの省略規則ではない',
                       status='未対応' if _unknown else '整理済み',issues=('G-05',) if _unknown else (),
                       representation='公開Python型の注釈')
        _row['unresolved_type_references']=tuple(sorted(_unknown))
        _row['negative']='この公開欄を欠落/別型へ変える。nullableのcarrierから保存DTOのnull許可を推論しない。'
        _row['nearest_legal']='注釈で宣言された型の値。発行物の検証や正準保存には別途紙の条件を満たす。'
        for _idx,_value in enumerate(_field['literal_values']):
            _wire_add(_fid+'.literal.'+str(_idx),'branch',_name+'.'+_field['name'],refs=_row['sources'],
                      branch=repr(_value),fields=_field['name'],use='Literal注釈の枝。新たな和型タグは追加しない。',
                      rules=_row['rules'],entries=_row['entries'],related=(_fid,),representation='公開型のLiteral枝')
for _name,_field,_unions in PUBLIC_ANNOTATION_UNIONS:
    _decl=PUBLIC_CLASS_BY_NAME[_name]
    _line=next(x['line'] for x in _decl['fields'] if x['name']==_field)
    for _idx,(_path,_member) in enumerate(_unions):
        _wire_add('T.public.'+_name+'.field.'+_field+'.union.'+str(_idx),'branch',_name+'.'+_field,
                  refs=(source('src/sui/f.py',_line),source(FB,2334)),branch=_member,fields=_field,
                  use='注釈中の和型 '+_path+'。NoneとUnavailable、公開carrierと保存DTOを混同しない。',
                  rules=('INV-3','INV-10'),entries=('I-3',),related=('T.public.'+_name+'.field.'+_field,),
                  representation='公開型の和型枝')
for _name in PUBLIC_UNRESOLVED_NAMES:
    _uses=[(c,f) for c in PUBLIC_CLASS_DECLARATIONS for f in c['fields'] if _name in f['references']]
    _wire_add('T.public.unresolved.'+_name,'relation',_name,
              refs=tuple(source('src/sui/f.py',f['line']) for c,f in _uses)+(source(FB,2334),),
              use='未対応 (G-05): 許可された公開クラス宣言内で参照される名前。定義元/型別名の全枝は未読。名前から内容を作らない。',
              rules=('INV-3','INV-10'),entries=('I-3',),status='未対応',issues=('G-05',),
              related=tuple('T.public.'+c['name']+'.field.'+f['name'] for c,f in _uses))

# 保存DTOとして紙で閉じているartifact入力は、型別名を未読でも別に列挙できる。
ARTIFACT_INPUT_BRANCHES=(('facts','FMathFactsInput'),('preflight','FMathPreflightInput'),('limit','FMathLimitInput'),('legacy_bridge','FMathLegacyBridgeInput'))
for _tag,_class in ARTIFACT_INPUT_BRANCHES:
    _wire_add('T.wire.artifact_input.'+_tag,'branch','math_artifact/2.input',
              refs=(source(FA,408,412),source(FB,2334)),branch=_tag,use='保存されたinputのkind/value枝。公開型別名の定義の確認とは別。',
              rules=('INV-3','INV-10'),entries=('I-3',),related=('T.public.'+_class,'T.wire.type.ExistingMathArtifact2'))

# 91行を実装表からでなく紙のE0/参照用途/CMP/PATHから写し、対応先を明示。
_E0_TYPES=(
    ('ContractRef','Desc<Args>'),('BootDeclaration','Received','WorkReport'),
    ('Verification','Prepared','Evaluated'),('Desc<Args>','BootSlot','FixedView'),
    ('WorkReport','DrawReport','GenerationPair'),('FixedView','Desc<Args>'),
    ('ContractRef','VerificationResponse'),('SegmentRequested','CandidateRequest','ExistingAcquisition','ExistingAdoption'),
)
_REF_TYPES=(
    ('RecordEnvelope','ObservedEnvelope'),('Received',),('BootDeclaration','BootSlot','ExistingBoot','ExistingOrigin','ExistingRouteApplied'),
    ('SegmentRequested','SegmentArgs','RouteConfig'),('ExistingQ',),('ExistingQ',),('ExistingQ',),('ExistingQ',),
    ('Desc<Args>','ReceivedUpdateArgs'),('EvaluationRequested','FFactsRequest','FixedView'),('ExistingResult','WorkReport'),
    ('ExistingResult',),('ExistingProof',),('ProofOutput','ExistingProof','WorkReport'),('ExistingCompletion',),
    ('ExistingCompletion','GenerationPair'),('ExistingAcquisition','AcquisitionRequested'),('VerificationArgs','FixedView'),
    ('Verification','WorkReport'),('Verification','VerificationResponse'),('ExistingAdoption','AdoptionRequested'),
    ('Stale','AdoptionRequested'),('Prepared','EvaluationRequested','ExistingMathArtifact2'),('DrawRequested','DrawArgs'),
    ('ExistingDrawFact','DrawReport'),('DrawUnknown',),('Evaluated','EvaluationArgs'),('Selection',),('WorkTerminal',),
    ('Conflict',),('WaitingPayload',),('SegmentBinding',),('SegmentBinding',),('MeasurementFrame',),
    ('SegmentItem.started','SegmentItem.ended','SegmentItem.route_applied'),('Gap','MeasurementUnavailable','CoverageUnproved'),
    ('CoverageClaim','FixedView'),('ExistingMathArtifact2',),('RecordEnvelope','ObservedEnvelope','DecidedEnvelope','PredictionEnvelope'),
)
_CMP_TYPES=(
    ('Received','RecordEnvelope','ObservedEnvelope'),('BootDeclaration','BootSlot'),('SegmentArgs','Desc<Args>','RouteConfig'),
    ('SegmentItem.started','SegmentItem.ended','SegmentItem.route_applied'),('MeasurementFrame',),('SegmentReport','Gap'),
    ('SegmentReport','MeasurementUnavailable'),('SegmentReport','CoverageClaim'),('SegmentReport','CoverageUnproved'),
    ('Desc<Args>','ReceivedUpdateArgs','ExistingQ'),('ExistingResult','WorkReport'),('ExistingProof','ProofOutput','WorkReport'),
    ('ExistingCompletion','GenerationPair'),('AcquisitionRequested','ExistingAcquisition'),('VerificationArgs','Verification'),
    ('AdoptionRequested','ExistingAdoption','Stale'),('Prepared','EvaluationPrepareArgs','ExistingMathArtifact2'),
    ('DrawRequested','DrawOutcome','ExistingDrawFact'),('Evaluated','EvaluationArgs','ExistingMathArtifact2'),('Selection',),
    ('WorkTerminal','TerminalReturned','TerminalBasis'),('WorkOutcome','DrawOutcome','FailureInfo','GenerationPair'),
    ('SegmentBinding',),('Conflict','WaitingPayload','SavedOwner'),
)
_PATH_TYPES=(
    ('Received','BootDeclaration','SegmentReport','WorkReport','DrawReport'),('ExistingResult',),('ExistingProof','ProofOutput'),
    ('ProofRef',),('ExistingQ',),('ExistingQ',),('ExistingQ','SegmentBinding'),('ExistingResult',),('ExistingProof',),
    ('ExistingCompletion','ExistingClockReading'),('ExistingAcquisition','AcquisitionRequested'),('ExistingAdoption','AdoptionRequested'),
    ('SegmentItem','SegmentBinding'),('Unavailable',),('FFactsRequest','ExistingMathArtifact2'),('EvaluationArgs',),
    ('ContractRef','FixedView','ExistingMathArtifact2'),('WorkReport','Desc<Args>'),('AcquisitionRequested','Verification'),
    ('RecordEnvelope','PredictionEnvelope'),
)
LOGICAL_MAPPING=[]
for _group,_first,_types in (('E0',2367,_E0_TYPES),('REFERENCE',2382,_REF_TYPES),('CMP',2428,_CMP_TYPES),('PATH',2461,_PATH_TYPES)):
    for _offset,_names in enumerate(_types):
        _line=_first+_offset;_raw=WIRE_SECTION_LINES[_line]
        _label=_raw.split('|')[1].strip().split('、')[0]
        _key=('REF-'+_label) if _group=='REFERENCE' else ('PATH-'+_label if _group=='PATH' else _label)
        _id='T.wire.logical.'+_key
        _rules=tuple(sorted({r for n in _names for r in _wire_context(n)[0]}))
        _entries=tuple(sorted({e for n in _names for e in _wire_context(n)[1]}))
        _gap='G-01' in _raw
        _wire_add(_id,'relation',_key,refs=(source(FB,_line),),use=_raw,rules=_rules,entries=_entries,
                  related=tuple('T.wire.type.'+n for n in _names),status='未決' if _gap else '整理済み',issues=('G-01',) if _gap else ())
        LOGICAL_MAPPING.append(dict(id=_key,group=_group,source=source(FB,_line),target=_id,
                                    targets=tuple('T.wire.type.'+n for n in _names),disposition='形の対応あり。意味はG-01' if _gap else '対応先あり'))
LOGICAL_MAPPING=tuple(LOGICAL_MAPPING)

# 規範本文の非表部分も1行ずつ保持し、明示宣言の未接続を隠さない。
# 見出し/空行/罫線/たとえは新しい入力を宣言しないため理由を付ける。
WIRE_SOURCE_COVERAGE=[]
_section='0'
for _line,_text in WIRE_SECTION_LINES.items():
    if _text.startswith('#### 2-5-'):
        _section=_text.split('2-5-')[1].split('.')[0]
    _targets=tuple(dict.fromkeys(r['id'] for r in _rows if r['id'].startswith('T.wire.') and any(s['path']==FB and s['first']<=_line<=s['last'] for s in r['sources'])))
    if not _text.strip() or _text.startswith(('#','>','|---')):
        _reason='適用外: 空行・見出し・表罫線・たとえであり新しい欄/契約の宣言ではない'
    elif _targets:
        _reason='対応先あり'
    elif _text.startswith('|') and any(x in _text for x in ('| 型 |','| 入れ子の契約','| args の欄','| 論理欄 |','| ID・根拠 |','| B の行 |','| PATH・','| 契約 |','| 契約・版 |','| 外付け |')):
        _reason='適用外: 表の列見出し。内容行を個別に対応'
    else:
        _id='T.wire.text.'+str(_line)
        _gap=_section=='19' and _text.startswith('|')
        _external=_line in (2499,2500,2575)
        _wire_add(_id,'relation','§2-5-'+_section+' 行'+str(_line),refs=(source(FB,_line),),use=_text,
                  rules=('INV-3','INV-10','背骨⑤'),entries=('I-1','I-2','I-3','I-6','I-7','I-8'),
                  status='未採用' if _external else '未決' if _gap else '整理済み',
                  issues=('G-04',) if _external else ('G-01',) if _gap else ())
        _targets=(_id,);_reason='関係・制約として本文を保持。新しいBody/契約/欄を推測しない'
    WIRE_SOURCE_COVERAGE.append(dict(line=_line,source=source(FB,_line),targets=_targets,reason=_reason))
WIRE_SOURCE_COVERAGE=tuple(WIRE_SOURCE_COVERAGE)


# 第一稿IDは消さず、同じ欄/論理欄の保存先を明記する。
def _public_unresolved_closure(name, seen=None):
    seen=set() if seen is None else seen
    if name in seen:
        return set()
    seen.add(name)
    unresolved=set()
    for field in PUBLIC_CLASS_BY_NAME[name]['fields']:
        for ref in field['references']:
            if ref in PUBLIC_UNRESOLVED_NAMES:
                unresolved.add(ref)
            elif ref in PUBLIC_CLASS_BY_NAME:
                unresolved.update(_public_unresolved_closure(ref,seen))
    return unresolved

PUBLIC_CLOSURE_GAPS={name:tuple(sorted(_public_unresolved_closure(name))) for name in PUBLIC_CLASS_BY_NAME}
for _row in _rows:
    if _row['id'] in {'T.public.'+name for name in PUBLIC_CLASS_BY_NAME}:
        _missing=PUBLIC_CLOSURE_GAPS[_row['subject']]
        _row['unresolved_type_closure']=_missing
        if _missing:
            _row['status']='未対応';_row['issues']=('G-05',)
            _row['use']+=' 未対応 (G-05): 入れ子を含む全枝の閉包: '+','.join(_missing)+'。注釈欄の列挙済みと全型の解決を区別。'

_G02_ROOT_TYPES={
    'T.boot_decl':'BootDeclaration','T.initial':'InitialProcess','T.resource_scope':'ResourceScope',
    'T.received':'Received','T.work_finished':'WorkReport','T.segment.Started':'SegmentItem.started','T.segment.Ended':'SegmentItem.ended',
    'T.segment_binding':'SegmentBinding','T.qgen':'CandidateRequest','T.candidate_generation':'CandidateGeneration',
    'T.eq':'EvaluationRequested','T.prepared':'Prepared','T.evaluated':'Evaluated','T.selection':'Selection',
    'T.terminal':'WorkTerminal','T.verification':'Verification','T.stale':'Stale','T.draw_unknown':'DrawUnknown',
    'T.conflict':'Conflict','T.waiting':'WaitingPayload',
}
_G02_PAYLOADS={
    'T.payload.WorkOutputs':('WorkOutcome','outputs'),'T.payload.WorkFailure':('WorkOutcome','failure'),
    'T.payload.WorkUnknown':('WorkOutcome','unknown'),'T.payload.DrawValue':('DrawOutcome','value'),
    'T.payload.DrawFailure':('DrawOutcome','failure'),'T.payload.DrawUnknown':('DrawOutcome','unknown'),
}
_LOGICAL_RESOLUTION={
    'T.qgen':(2345,('CandidateRequest','CandidateArgs','Desc<Args>')),
    'T.eq':(2346,('EvaluationRequested','EvaluationPrepareArgs','Desc<Args>','FixedView')),
    'T.prepared':(2349,('Prepared','EvaluationRequested','Desc<Args>','ExistingMathArtifact2')),
    'T.evaluated':(2350,('Evaluated','EvaluationArgs','Desc<Args>','ExistingMathArtifact2')),
    'T.selection':(2351,('Selection','Evaluated','ExistingMathArtifact2')),
    'T.verification':(2352,('Verification','VerificationArgs','WorkReport','VerificationResponse')),
    'T.stale':(2353,('Stale','AdoptionRequested')),
    'T.segment_binding':(2354,('SegmentBinding','SegmentReport')),
    'T.conflict':(2355,('Conflict','ConflictRule')),
    'T.waiting':(2356,('WaitingPayload','SavedCondition','SavedPurpose','SavedOwner')),
}
_NEW_BY_ID={r['id']:r for r in _rows}
FBT01B_RESOLUTIONS=[]
for _row in _rows[:DRAFT1_SUMMARY['targets']]:
    if _row['id'] not in DRAFT1_AFFECTED:
        continue
    _old=next(r for r in DRAFT1_DENOMINATOR['TARGETS'] if r['id']==_row['id'])
    _related=[];_resolution='';_new_issues=set(_old['issues'])-{'G-02','G-05','D-01'}
    if 'G-02' in _old['issues']:
        if _row['id'].startswith('T.target_certificate'):
            _related=['T.wire.unresolved.target_certificate']
            _row['sources']+=(source(FB,2490),source(FB,2558),source(FB,2593))
            _new_issues.add('G-01')
            _resolution='未決 (G-01): 発行物の契約・全結合は§2-5でも未定義。論理欄を保存宣言としない。'
            _row['representation']='未決: 発行物の論理的な結合要件。保存型ではない'
        elif _row['id'].startswith('T.paper.'):
            _related=list(_row.get('related_targets',()))
            _resolution='関連対象の保存先を§2-5で具体化。元の論理関係/生成/所有の条件は保持。'
            _row['sources']+=(source(FB,2344,2359),source(FB,2275,2299))
        elif _row['id'] in _G02_PAYLOADS:
            _type,_branch=_G02_PAYLOADS[_row['id']]
            _related=['T.wire.type.'+_type+'.branch.'+_branch]
            _row['sources']+=WIRE_TYPES[_type]['sources']+(source(FB,2202,2206),)
            _resolution='外側の返答のkind/value枝。内側の用途契約を別層として保持。'
        else:
            _root=next(k for k in sorted(_G02_ROOT_TYPES,key=len,reverse=True) if _row['id']==k or _row['id'].startswith(k+'.'))
            _type=_G02_ROOT_TYPES[_root];_tid='T.wire.type.'+_type
            _related=[_tid];_row['sources']+=WIRE_TYPES[_type]['sources']
            _declaration=next((d for d in WIRE_DECLARATIONS if d['payload']==_type),None)
            if _declaration is not None:
                _row['body']=_declaration['body']
                _row['role']=_declaration['role_category']
                _row['contract']=_declaration['name']+'/'+_declaration['version']
                _row['edges']='親: '+_declaration['parents']+'。用途ごとのE/U/UEは関連する論理対応行。'
                _row['sources']+=(_declaration['source'],)
            _field=_row['field'].removesuffix('[]').removesuffix('?')
            _direct=_tid+'.field.'+_field
            if _row['kind']=='field' and _direct in _NEW_BY_ID:
                _canonical=_NEW_BY_ID[_direct]
                _related=[_direct]
                for _key in ('presence','declared_type','negative','nearest_legal'):
                    _row[_key]=_canonical[_key]
                _resolution='§2-5の実在する保存欄へ直接対応。'
                _row['representation']='保存宣言 (第一稿IDを保持)'
            elif _row['kind']=='field':
                _line,_types=_LOGICAL_RESOLUTION[_root]
                _related=['T.wire.type.'+n for n in _types]
                _row['sources']+=(source(FB,_line),)
                _row['original_logical_field']=_row['field']
                _row['kind']='relation';_row['field']=NA
                _row['representation']='論理欄の解決関係。保存欄を追加しない'
                _resolution=WIRE_SECTION_LINES[_line]
                if _root=='T.qgen' and _old['field']=='input_order[]':
                    _resolution+='。Qgenにinput_order保存欄はない。CandidateArgs.basisの順と宣言されたgenerator_argsを照合し、結果CG.input_orderとは区別 (2170,2332)。'
                    _row['sources']+=(source(FB,2170),source(FB,2332))
                if _root=='T.verification' and _old['field'] in ('response','issued_certificate'):
                    _new_issues.add('G-01');_resolution+='。返答payload/実発行物の全結合はG-01。'
                    _row['sources']+=(source(FB,2558),)
            else:
                _resolution='§2-5の型・枝・保存形へ対応。意味の保証/実装の合格とは別。'
                _row['representation']='保存型への索引/論理返答の枝'
                if _root=='T.boot_decl' and _row['kind']=='branch':
                    _related=['T.wire.type.BootDeclaration.field.initial.branch.'+('null' if 'None' in _row['branch'] else 'value')]
                if _root=='T.candidate_generation' and _row['kind']=='branch':
                    _case={'非空の候補':('CandidateGeneration','candidates'),'NoCandidates':('CandidateGeneration','no_candidates'),
                           'Failure':('WorkOutcome','failure'),'Unknown':('WorkOutcome','unknown')}[_row['branch']]
                    _related=['T.wire.type.'+_case[0]+'.branch.'+_case[1]]
                    _row['representation']='返答の枝。Failure/Unknownはcandidate_generation値契約の外側'
                    _row['sources']+=(source(FB,2194,2196),)
                    if _row['branch'] in ('Failure','Unknown'):
                        _row['contract']='sui.fb.work_report/1'
                        _row['body']='Observed';_row['role']='MEMBRANE / FACT'
                        _row['edges']='原報告work_reportの親は空。内側のcandidate_generation契約の枝ではない。'
                if _root in ('T.prepared','T.evaluated') and _row['kind']=='branch':
                    _related+=['T.public.'+_row['branch']]
        _row['issues']=tuple(sorted(_new_issues))
        _row['status']='未決' if _new_issues else '整理済み'
        if _row['presence'].startswith('未決:') or '内側の構造は未決' in _row['presence']:
            _row['presence']='未決: G-01の発行物/意味宣言待ち' if _row['id'].startswith('T.target_certificate') else '保存形は参照先。論理欄に新しい保存キーを足さない'
    else:
        if _row['id'].startswith('T.missing.RateBudget') or _row['id']=='T.old_style':
            _row['issues']=('G-05',);_row['status']='未対応'
            _related=['T.public.unresolved.RateBudget'] if _row['id'].startswith('T.missing.RateBudget') else []
            _resolution='未対応 (G-05): 許可された公開クラスに全宣言なし。別の理由へ付け替えて閉じない。'
        else:
            _name='CapabilityImplementation' if _row['id'].startswith('T.capability_implementation') else 'Run' if _row['id']=='T.measurement_run' else 'FLimitProblem' if _row['id']=='T.limit' else _row['id'].split('.')[2]
            _related=['T.public.'+_name]
            _decl=PUBLIC_CLASS_BY_NAME[_name]
            _row['sources']+=(source('src/sui/f.py',_decl['line'],max([_decl['line']]+[f['line'] for f in _decl['fields']])),)
            _row['issues']=('G-RUN-CODEC',) if _name=='Run' else ()
            _row['status']='未決' if _name=='Run' else '整理済み'
            _resolution='公開クラスの全注釈欄・Literal/和型枝をT.public.*へ展開。未解決の内側型は専用の未対応行へ接続。'
            if _old['field']=='未列挙の欄と枝':
                _row['kind']='relation';_row['field']=NA
                _row['presence']='適用外: 公開クラスの全注釈欄への索引。保存キーの宣言ではない'
                _row['representation']='公開クラス宣言の全欄へ展開した索引'
                _related+=['T.public.'+_name+'.field.'+f['name'] for f in _decl['fields']]
            if _old['id']=='T.capability_implementation.identity':
                _row['declared_type']='str';_row['presence']='公開クラスでstrと宣言'
                _related=['T.public.CapabilityImplementation.field.identity']
            if _name=='Run':
                _resolution+='。ただしdocstringが明示する未定codecはG-RUN-CODECとして未決。'
            _closure=PUBLIC_CLOSURE_GAPS[_name]
            if _closure and _old['id']!='T.capability_implementation.identity':
                _row['status']='未対応';_row['issues']=('G-05',)
                _resolution+=' 未対応 (G-05): '+','.join(_closure)+'の全宣言/枝が未読のため、この全体行を閉じない。'
                _related+=['T.public.unresolved.'+n for n in _closure]
    _row['related_targets']=tuple(dict.fromkeys(_related))
    _row['previous_issues']=tuple(_old['issues'])
    _row['previous_use']=_old['use']
    _row['resolution']=_resolution
    _row['use']=_resolution+' 元の用途: '+_old['use'] if _row['id'].startswith('T.paper.') else _resolution
    # 外形が宣言済みでも、数値意味/認証物の未決を消さない。
    _row['evidence']='§2-5・許可された公開型の宣言と独立した原入力。実装出力を根にしない。'
    FBT01B_RESOLUTIONS.append(dict(target=_row['id'],before_status=_old['status'],before_issues=tuple(_old['issues']),
                                   after_status=_row['status'],remaining_issues=_row['issues'],targets=_row['related_targets'],
                                   reason=_resolution,sources=_row['sources']))
FBT01B_RESOLUTIONS=tuple(FBT01B_RESOLUTIONS)

# D-01: 壁時計値を隔離解除。負の値とnullableは別問題 (F-a V-04)。
_wall=_NEW_BY_ID['T.wire.type.Instant.field.wall_ns']
_wall['sources']+=(source(FA,28,30),source('src/sui/clock.py',18))
_wall['negative']='wall_nsキーの省略/null/bool。符号付き整数を負という理由だけで拒否する。'
_wall['nearest_legal']='wall_nsをintで保持し、単調時計mono_nsやrunの因果順序の代用にしない。'
_wall['resolution']='D-01解消: 紙と公開宣言がintで一致。'

_no_ninth=_wire_add('T.wire.no_ninth_body','relation','九つ目のBodyを足さない',refs=(source(FB,2038),),
                   use='既存の八Bodyのまま。F-bでInterpretation/Preference/JobOpened/AttemptClosed/Intentionを新規に使わない。値契約・FWorkをBodyにしない。',
                   rules=('INV-3','背骨⑤'),entries=('I-1','I-2','I-3','I-6','I-7','I-8'),
                   related=tuple(r['id'] for r in _rows if r['kind']=='body'))
for _coverage in WIRE_SOURCE_COVERAGE:
    if _coverage['line']==2038:
        _coverage['targets']+=(_no_ninth['id'],)

# D7は既存の背骨/INV/Lの適用条件を固定した決定。新しい試験規則IDは作らない。
_D7_ROWS=(
    ('perception','測定記録は背骨①、更新は安定して条件が揃えばL-DERIVE。周期を合格基準にしない。',
     ('背骨①','L-DERIVE','L-DERIVE.N','L-DERIVE.P'),('I-1','I-2','I-6'),('T.rel.measurement','T.rel.declared_derive')),
    ('two_starts','席2で二つの条件が揃えば両方の開始操作を提供。片方が固まっても他方の開始と受信を止めない。走り終わる保証ではない。',
     ('INV-2.e','背骨②','INV-8'),('I-1','I-3','I-6'),('T.rel.resource','T.rel.owner','T.rel.independence')),
    ('display','試験の対象外 (理由: D7の実走で見る)。F-b実装後、おもちゃの世界を数分、最初の考えるあり/なしの2体、FStatusの小さな表示で観察。F-d全部はF-c後。',
     ('背骨⑤','INV-13'),('I-6',),('T.status','T.rel.initial_none')),
)
for _key,_meaning,_rules,_entries,_related in _D7_ROWS:
    _row=_wire_add('T.d7.'+_key,'relation','D7 '+_key,refs=(source(FB,22),),use=_meaning,rules=_rules,entries=_entries,related=_related)
    _row['verification_kind']='実装後の観察' if _key=='display' else '実装の段の新しい試験'
    _row['automated_disposition']='試験の対象外 (D7の実走で見る)' if _key=='display' else '未実行: 実装の段'
    _row['count_as_pass']=False

TARGETS=tuple(_rows)
TARGET_BY_ID={r['id']:r for r in TARGETS}
for _criterion in ACCEPTANCE:
    _id=_criterion['id']
    _key='perception' if _id in ('AC-FB-01','AC-FA-01','AC-SPINE-1') else 'two_starts' if _id in ('AC-FB-03','AC-FA-03','AC-SPINE-2','AC-SPINE-3') else 'display' if _id=='AC-STAR-01' else None
    if _key:
        _criterion['targets']+=('T.d7.'+_key,)
        _criterion['meaning']=TARGET_BY_ID['T.d7.'+_key]['use'] if _id in ('AC-FB-01','AC-FA-01','AC-FB-03','AC-FA-03','AC-STAR-01') else _criterion['meaning']+'。D7の条件を併記。'
        _criterion['sources']+=(source(FB,22),)
        _criterion['unconnected']='';_criterion['issue']=None
    _criterion['verification_kind']='実装後の観察' if _id=='AC-STAR-01' else '実装の段の試験'
    _criterion['automated_disposition']='試験の対象外 (理由: D7の実走で見る)' if _id=='AC-STAR-01' else '未実行: 実装の段'
    _criterion['count_as_pass']=False
ACCEPTANCE_LINKS=tuple(
    dict(acceptance=c['id'],target=t,rule=r,use=TARGET_BY_ID[t]['use'],entry=e,
         sources=c['sources']+TARGET_BY_ID[t]['sources'],execution='not_run',
         verification_kind=c['verification_kind'],automated_disposition=c['automated_disposition'],count_as_pass=False)
    for c in ACCEPTANCE for t in c['targets'] for r in TARGET_BY_ID[t]['rules'] for e in TARGET_BY_ID[t]['entries'])

# 橋の元の197件・残りの数値条件・未採用R10は変更しない。設計待ち札だけ現在化。
for _bridge in BRIDGES:
    _bridge['previous_prerequisite_issues']=tuple(_bridge['prerequisite_issues'])
    _bridge['prerequisite_issues']=tuple(sorted((set(_bridge['prerequisite_issues'])-{'G-02','G-03'}) |
                                               {i for t in _bridge['targets'] for i in TARGET_BY_ID[t]['issues']}))
    _bridge['execution']='not_run'


# 生成器が型→欄→枝・参照型を辿れる索引。循環型はグラフのまま保持する。
_GENERIC_TYPES={'SlotValue':'SlotValue<T>','Projection':'Projection<T>','Desc':'Desc<Args>'}
def _type_tokens(annotation):
    tokens=[]; current=''
    for char in annotation:
        if char.isalnum() or char in '_.':
            current+=char
        elif current:
            tokens.append(current);current=''
    if current:
        tokens.append(current)
    return tuple(tokens)

for _name,_decl in WIRE_TYPES.items():
    _prefix='T.wire.type.'+_name
    _decl['target']=_prefix
    _decl['field_targets']=tuple(_prefix+'.field.'+f for f,t in _decl['fields'])
    _decl['branch_targets']=tuple(_prefix+'.branch.'+b for b,t in _decl['branches'])
    _type_refs=set()
    for _field,_annotation in _decl['fields']:
        _fid=_prefix+'.field.'+_field
        _deps=[]
        for _token in _type_tokens(_annotation):
            _type=_GENERIC_TYPES.get(_token,_token)
            if _type in WIRE_TYPES:
                _deps.append('T.wire.type.'+_type)
            elif _token in PUBLIC_CLASS_BY_NAME:
                _deps.append('T.public.'+_token)
            elif _token in PUBLIC_UNRESOLVED_NAMES:
                _deps.append('T.public.unresolved.'+_token)
        TARGET_BY_ID[_fid]['related_targets']=tuple(dict.fromkeys(TARGET_BY_ID[_fid]['related_targets']+tuple(_deps)))
        _type_refs.update(_deps)
    for _branch,_payload in _decl['branches']:
        _deps=[]
        for _token in _type_tokens(_payload):
            _type=_GENERIC_TYPES.get(_token,_token)
            if _type in WIRE_TYPES:
                _deps.append('T.wire.type.'+_type)
            elif _token in PUBLIC_CLASS_BY_NAME:
                _deps.append('T.public.'+_token)
        _bid=_prefix+'.branch.'+_branch
        TARGET_BY_ID[_bid]['related_targets']=tuple(dict.fromkeys(TARGET_BY_ID[_bid]['related_targets']+tuple(_deps)))
        _type_refs.update(_deps)
    _decl['type_references']=tuple(sorted(_type_refs))
    TARGET_BY_ID[_prefix]['related_targets']=_decl['field_targets']+_decl['branch_targets']+_decl['type_references']
for _decl in PUBLIC_CLASS_DECLARATIONS:
    TARGET_BY_ID['T.public.'+_decl['name']]['related_targets']=tuple('T.public.'+_decl['name']+'.field.'+f['name'] for f in _decl['fields'])

# 既に整理済みだった第一稿の入力にも保存層への入口を付ける。
# 古い論理索引をそのまま新しいwireの欄生成に使うことを防ぐ。
WIRE_LEGACY_LINKS={
    'T.descriptor':'Desc<Args>','T.received':'Received','T.segment_report':'SegmentReport',
    'T.work_finished':'WorkReport','T.draw_returned':'DrawReport','T.frame':'MeasurementFrame',
    'T.claim':'CoverageClaim','T.gap':'Gap','T.measurement_unavailable':'MeasurementUnavailable',
    'T.unproved':'CoverageUnproved','T.request':'ExistingQ','T.result':'ExistingResult',
    'T.proof':'ExistingProof','T.completed':'ExistingCompletion','T.adopted':'ExistingAdoption',
    'T.acquired':'ExistingAcquisition','T.origin':'ExistingOrigin','T.candidate':'FCandidateDeclaration',
    'T.draw_fact':'ExistingDrawFact','T.clock_reading':'ExistingClockReading',
    'T.route_applied':'ExistingRouteApplied','T.boot_fact':'ExistingBoot','T.clock_source':'ExistingClockSource',
}
for _row in TARGETS[:DRAFT1_SUMMARY['targets']]:
    _row.setdefault('representation','第一稿の論理/公開宣言の対象。v0.22の保存形はWIRE_DECLARATIONS/EXISTING_COPIESを優先')
    _root=next((k for k in WIRE_LEGACY_LINKS if _row['id']==k or _row['id'].startswith(k+'.')),None)
    if _root:
        _canonical='T.wire.type.'+WIRE_LEGACY_LINKS[_root]
        _field=_row['field'].removesuffix('[]').removesuffix('?')
        if _canonical+'.field.'+_field in TARGET_BY_ID:
            _canonical+='.field.'+_field
        _row['wire_targets']=(_canonical,)
        _row['related_targets']=tuple(dict.fromkeys(_row.get('related_targets',())+(_canonical,)))

CATALOG_LAYERS=dict(
    primary='TARGETSは論理・保存宣言・公開carrierを含む。kindとrepresentationを確認する。',
    wire='新契約はWIRE_DECLARATIONS、既存コピーはEXISTING_COPIESからpayloadのWIRE_TYPESを辿る。',
    public='PUBLIC_CLASS_DECLARATIONSは公開carrier。保存DTOのnullable/正準形を推論しない。',
    historical='DRAFT1_DENOMINATORはv0.19の凍結済み履歴。現在の期待値生成には使わない。',
    unresolved='未決/未対応/未採用、および関連先の未解決型を生成済みの合格ケースに数えない。',
)

# 宣言の件数を紙の表からもう一度数える。編集した一覧の件数だけを分母にしない。
WIRE_DECLARED_SOURCE=[]
for _line,_raw in WIRE_SECTION_LINES.items():
    if 2273<_line<2300 and _raw.startswith('| ') and not _raw.startswith('|---'):
        _cols=[c.strip() for c in _raw.split('|')[1:-1]]
        _name=_cols[0].split('〔')[0]
        _category='value' if '内側の値契約' in _cols[1] else 'ledger'
        WIRE_DECLARED_SOURCE.append(dict(contract='sui.fb.'+_name,category=_category,source=source(FB,_line)))
    elif 2114<_line<2122 and _raw.startswith('| sui.fb.'):
        WIRE_DECLARED_SOURCE.append(dict(contract=_raw.split('|')[1].strip(),category='value',source=source(FB,_line)))
    elif _line==2135:
        WIRE_DECLARED_SOURCE.append(dict(contract=_raw.split('**')[1],category='value',source=source(FB,_line)))
    elif 2495<_line<2499 and _raw.startswith('| sui.fb.'):
        WIRE_DECLARED_SOURCE.append(dict(contract=_raw.split('|')[1].strip(),category='external',source=source(FB,_line)))
WIRE_DECLARED_SOURCE=tuple(WIRE_DECLARED_SOURCE)

# 共有する既存の入れ子はpublicの欄名と照合。表現の差は保存とcarrierを分離。
WIRE_PUBLIC_FIELD_COMPARISONS=tuple(
    dict(name=n,paper_fields=tuple(f for f,t in WIRE_TYPES[n]['fields']),
         public_fields=tuple(f['name'] for f in PUBLIC_CLASS_BY_NAME[n]['fields']),
         sources=WIRE_TYPES[n]['sources']+(source('src/sui/f.py',PUBLIC_CLASS_BY_NAME[n]['line']),),
         representation_note='List/Setの保存表現とtuple/frozenset等のcarrierは別。欄名の一致だけで意味や値の一致を証明しない。')
    for n in ('ClockReading','Unavailable','MeasurementFrame','Gap','MeasurementUnavailable','CoverageClaim','CoverageUnproved',
              'MeasurementInterval','MeasurementId','RouteConfig','DrawRequest','FCandidateDeclaration','FCandidateGeneration',
              'FContinuation','ContinuationAfter','CandidateMeasureRef','PolicyRef','ProofRef','FFactsRequest','EvaluationScope'))

FBT04_DISPOSITIONS=dict(
    declared_counts=dict(Counter(x['category'] for x in WIRE_DECLARED_SOURCE)),
    target_counts=dict(Counter(x['category'] for x in WIRE_DECLARATIONS)),
    reported_other_reviewer={'ledger':22,'value':10,'external':2},
    existing_copies=len(EXISTING_COPIES),nested_types=len(WIRE_TYPES),
    logical_counts=dict(Counter(x['group'] for x in LOGICAL_MAPPING)),
    no_ninth_body_target='T.wire.no_ninth_body',
    unresolved_meaning='G-01は宣言された未決として行に保持。未採用R10の全欄を選択用契約から補わない。',
    unlisted_declarations=(),
)
FBT01B_REMAINING=tuple(x for x in FBT01B_RESOLUTIONS if x['after_status'] in ('未決','未対応'))
FBT01B_UNCLOSED=tuple(x['target'] for x in FBT01B_REMAINING if set(x['remaining_issues'])<= {'G-02','G-05','D-01'})
ACCEPTANCE_CHANGES=tuple(dict(id=c['id'],before=DRAFT1_SUMMARY['acceptance'][c['id']],after=summary_counts()['acceptance'][c['id']],
                              verification_kind=c['verification_kind'],automated_disposition=c['automated_disposition']) for c in ACCEPTANCE)

REVISION2_FINDINGS=(
    dict(id='G-05',classification='直すべき',status='未対応',targets=FBT01B_UNCLOSED,
         message='FBT-01bの閉じる条件は未達。旧style/RateBudgetの3行と、CapabilityImplementation/Selected/NoDecision/FEvaluation/PredicateWorkの全枝を含む9行が資料不足。型別名/入れ子の未読定義を理由の付替えで解消にしない。',
         sources=(source(FA,82),source(FA,433),source('src/sui/f.py',554),source('src/sui/f.py',606))),
    dict(id='G-01',classification='BLOCKER',status='未決',
         message='未決対象の実装試験/合格判定を保留するBLOCKER。未決を明記した準備への引継ぎはユーザー指定どおり可能。/2の10設計項目を勝手に埋めない。',
         sources=(source(FB,2558,2560),source(FB,2585,2594))),
    dict(id='G-RUN-CODEC',classification='後で',status='未決',targets=('T.measurement_run',),
         message='公開欄の欠落ではなく、Runの符号化そのものが公開docstringでF-b未確定。解決対象を意味の設計残件へ分けた。',
         sources=(source(FA,74),source('src/sui/f.py',857,867))),
)
SESSION_NOTE=dict(
    date='2026-10-18',project='sui',tool='codex',session_id=DRAFT1_SESSION_NOTE['session_id'],
    artifact_version='FBT draft 2 / paper v0.22',
    artifacts=('tests/fb_targets.py','tests/test_fb_targets.py'),
    decision='v0.22 §2-5の優先に従い保存宣言を具体化。公開クラスの注釈だけを使用。D7は既存規則に接続し★実走は自動試験外。',
    unresolved='G-01は未決で引継ぎ、G-05の残り12行は隠さずFBT-01b未達。Run codecは紙/公開docstringが未定。',
    verification='tests/test_fb_targets.pyだけ19件通過。Python 3.12.10 / pytest 9.1.1。初稿12件の不変条件を維持し、改訂の7件を追加。実装/模型試験はnot_run。',
    failed_attempts='UTF-8のPowerShellパイプ設定漏れを修正。公開型の初回索引で落ちた測定系6型を追加。初回自己点検が旧Body/契約/presenceの未決表示を検出し、宣言元に従って修正。全枝の未解決を追跡してG-05残件を3行から12行へ訂正。',
    reuse='有効: 第一稿の独立分母をハッシュで保存し、実装を読まず紙と公開宣言で更新。後段の橋197件はそのまま。',
    read_scope='§2-5 2005–2597全文とD7 22、F-a紙該当部分、f.py公開クラスの名前/注釈/docstring。内部/私有定義/方法本体/既存試験期待値は未読。Webなし。',
    other_agent='他AIへの連絡なし。別の係の数えは比較値だけ。今回の場面/誤実装ファイルの再読なし。',
    not_done='commit、src/specs/既存tests編集、模型/実装試験は未実行。書込み許可2ファイルのためObsidian Sessions/Projects/Heat未更新。',
    next='G-05の宣言だけの資料/参照範囲を得る。G-01設計後に未決対象を接続し、実装の段でこの一覧から試験を書く。',
    assumptions={'name_only':0,'meaning_change':0},
    administrative_names='T.wire.* / Existing* / .payload等は索引名。新しいsui契約名や保存キーを採用する仮定ではない。',
)
DENOMINATOR_KEYS=DENOMINATOR_KEYS+(
    'WIRE_TYPES','WIRE_DECLARATIONS','EXISTING_COPIES','LOGICAL_MAPPING','WIRE_SOURCE_COVERAGE',
    'PUBLIC_CLASS_DECLARATIONS','PUBLIC_ANNOTATION_UNIONS','PUBLIC_UNRESOLVED_NAMES','PUBLIC_CLOSURE_GAPS',
    'FBT01B_RESOLUTIONS','FBT01B_UNCLOSED','WIRE_DECLARED_SOURCE','FBT04_DISPOSITIONS',
    'WIRE_LEGACY_LINKS','CATALOG_LAYERS',
)
# この値は紙/公開宣言の改訂後に固定。第一稿の別ハッシュも自己点検する。
DENOMINATOR_SHA256='619d6f73934f39ca71a66fce5187dbc3c133a55b8657c3ffd3ee3b6ab47b85a2'

def revision_summary():
    return dict(current=summary_counts(),previous=DRAFT1_SUMMARY,
                unresolved_by_issue={status:dict(Counter(issue for t in TARGETS if t['status']==status for issue in t['issues']))
                                     for status in ('未決','未対応')},
                fbt01b=dict(affected=len(DRAFT1_AFFECTED),resolved=sum(x['after_status']=='整理済み' for x in FBT01B_RESOLUTIONS),
                            remaining=len(FBT01B_REMAINING),unclosed=FBT01B_UNCLOSED,
                            remaining_by_issue=dict(Counter(i for x in FBT01B_REMAINING for i in x['remaining_issues']))),
                fbt04=FBT04_DISPOSITIONS,acceptance_changes=ACCEPTANCE_CHANGES,
                bridges=dict(Counter(x['group'] for x in BRIDGES)),
                assumptions={'name_only':0,'meaning_change':0})


# FBT draft 3 — ユーザーが指定した宣言だけの資料でG-05を照合。
# 原文f.py/rate.py、関数/メソッド本体、模型は読まない・実行しない。
DRAFT2_DENOMINATOR={key:_copy_tree(globals()[key]) for key in DENOMINATOR_KEYS}
DRAFT2_DENOMINATOR_KEYS=tuple(DENOMINATOR_KEYS)
DRAFT2_DENOMINATOR_SHA256=DENOMINATOR_SHA256
DRAFT2_SUMMARY=_copy_tree(revision_summary())
DRAFT2_G05_IDS=tuple(r['id'] for r in TARGETS if 'G-05' in r['issues'])
DRAFT2_FBT01B_UNCLOSED=tuple(FBT01B_UNCLOSED)
DRAFT2_PUBLIC_UNRESOLVED_NAMES=tuple(PUBLIC_UNRESOLVED_NAMES)
DRAFT2_BRIDGES=_copy_tree(BRIDGES)
DRAFT2_SESSION_NOTE=_copy_tree(SESSION_NOTE)
DECLARATIONS_PATH='scratchpad/fb_public_decls.md'
DECLARATIONS_PROVENANCE={'lines': 1936, 'sha256_lf': '9ed95b41fe5b282aea8028416eb7498f908b078a47dbe02eb42829d097cbebf0', 'read_scope': '該当部分: import、対象の型別名と参照先のクラス宣言、RateBudget/RationalInterval/FStyle/StyleScope。抽出スクリプト全文。原文との再抽出照合は未実行。', 'extractor': 'scratchpad/extract_public_decls.py', 'extractor_sha256_lf': 'b8b2978f44a66490e646f6fe60bd8de0624f34018403388992a95cb231c75d4a'}
DRAFT2_TEST_CHECKS={'test_target_ids_and_required_columns': '9b4a228a57ea409df8a06fd4d1bf6ade27a79693bfe6a6d35964acb3b77e231c', 'test_not_applicable_and_unresolved_cells_are_explicit': '4f206621d18353375ba35dd53465e06592a93794ce92018652b085bae93ee21b', 'test_rule_entry_and_target_references_exist': '3bc95e4ca061392126344666514c4c39c5ae9e3db3f9347198bfe01df3c0dc5a', 'test_paper_source_units_have_dispositions': 'f805d7c5b645d1324eae399c305d085a763122a2c02b191ea04e3ba93d63aa9f', 'test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap': '64209ae2b2113b49c97dc2c1bc2875c2552ed5810a6d27e51ad7d28c5c9eb976', 'test_denominator_was_not_changed_by_the_model_bridge': '2083ff8d8ef77d9c84c91ad531d4477d32943cb3530a830d257afdf7c6fbcd84', 'test_bridge_source_universe_independent_counts_and_selectors': '6cd010c6a863183fd0bcaa60862dbfc5d6b73584e343cdbc232b1476c7e13c27', 'test_every_bridge_item_has_exactly_one_disposition': 'b2c9e1cb516572475e9dbc7fcabd07bb208a0faadd1eb9e4906a7513971f19b2', 'test_numeric_remainders_and_unadopted_branches_not_promoted': 'ce33cee576d69273a7a66c57dbbd75b70b11c70ec404db428391a8d0dd7b7b98', 'test_supplemental_scope_holes_remain_separate_from_107_7_79': '7bddb16f3dee4eea45f48753fadb79882868386b0710d2ffd77fbbc65110f190', 'test_disagreement_is_reported_without_choosing_an_expected_type': 'ad6441b71c897ff01015ff52dd349d569ba454fbef12c2fb6c770b51cc370e01', 'test_data_module_has_no_model_or_implementation_import': 'e9edd0c72d82ad8c8052100d67d55b11f0f509e3af6305001c85a27b202be486', 'test_revision_accounts_for_every_original_affected_row_and_reports_unclosed': '56d0d7af43a1c088382d04c26c2bf498cd9237f1f4ef04b6f94c0e157f80b11d', 'test_wire_contract_universe_is_counted_from_paper_and_every_declaration_has_target': '6d4c1857943277f973c55180194e1599392075b84e0cf6230941eb4385196a49', 'test_wire_nested_fields_nullable_and_union_branches_are_all_addressable': 'a1f0c9b40f085c6fdfa4d1e07e8de682d946fa8d3c02de83f3950cdbc07cb481', 'test_all_91_logical_rows_and_entire_wire_section_have_dispositions': 'b4c69f22efe9485b5fb4ad53714fbbdef11bb788296ddf2b7bcea9217fca230f', 'test_public_class_declarations_expand_fields_literals_unions_and_keep_unknown_types': '095d4646fb16314488e66d33059fa232696fcddcf7c83cd84cd282044e7f0fb5', 'test_d7_connections_are_conditions_and_observation_not_automatic_success': 'f080272e75eb2b069dd586b75a7c24709976643e70b45dd0779241a08c51eb9c', 'test_revision_preserves_all_bridge_sources_targets_checks_and_remainders': '092a9f6732bd42fd1531eab674d58a9fe3f4234691611825613d7da22eb0749c'}
DECLARATION_EXCERPTS={
    6: 'L26: from __future__ import annotations',
    7: 'L28: from collections.abc import Mapping as _Mapping',
    8: 'L29: from dataclasses import dataclass as _dataclass',
    9: 'L30: from fractions import Fraction as _Fraction',
    10: 'L31: from typing import Literal as _Literal, TypeAlias as _TypeAlias, Protocol as _Protocol',
    11: 'L33: from .agent import ModelFalsified as _ModelFalsified, RebuildMismatch as _RebuildMismatch',
    12: 'L34: from .contracts import ContractRef as _ContractRef',
    13: 'L35: from .f_model import FModel',
    14: 'L36: from .ids import Ref as _Ref',
    15: 'L37: from .records import Record as _Record',
    16: 'L38: from .inference import NumericalRange as _NumericalRange',
    17: 'L39: from .lookahead import OutsideEvaluationType as _OutsideEvaluationType',
    18: 'L40: from .quantity import IntegrationIncomplete as _IntegrationIncomplete',
    19: 'L41: from .rate import RateBudget, RationalInterval',
    20: 'L42: from .rate_model import RateModel',
    21: "L46: ImmutableJSON: _TypeAlias = str | int | float | bool | None | tuple['ImmutableJSON', ...] | _Mapping[str, 'ImmutableJSON']",
    22: "L50: NoDecisionReason: _TypeAlias = _Literal['NoAdmissibleCandidate', 'NumericalRange', 'budget_exhausted', 'selection_boundary', 'algorithm_unavailable', 'proof_incomplete', 'runtime_unverified', 'candidate_measure_missing', 'normalization_unproved', 'OutsideEvaluationType', 'certificate_incomplete', 'information_divergent', 'undefined_infinite_difference', 'clock_unaligned', 'prerequisite_unavailable', 'cost_certificate', 'missing_contract', 'model_falsified', 'c1_closure_unproved']",
    661: "L911: CapabilityKind: _TypeAlias = _Literal['action', 'predicate', 'kernel', 'policy', 'execution', 'proof', 'method', 'arithmetic', 'choice', 'measurement', 'projection', 'generation', 'clock', 'quality', 'cursor', 'generator']",
    759: 'L1037: @_dataclass(frozen=True, slots=True, kw_only=True) class StyleScope():',
    760: '    """FStyle.scope の匿名値。F-a で検査する: 範囲と H。source は持たない。"""',
    761: "    name: _Literal['unbounded_total', 'one_step', 'finite_horizon']",
    762: "    version: _Literal['1']",
    763: '    H_ns: int | None',
    764: '',
    765: 'L1045: @_dataclass(frozen=True, slots=True, kw_only=True) class FStyle():',
    766: '    """F-a で検査する: F の style 宣言と gamma。source は保存レコードから得る。"""',
    767: "    kind: _Literal['style']",
    768: '    scope: StyleScope',
    769: '    gamma: _Fraction',
    1421: 'L3916: @_dataclass(frozen=True, slots=True, kw_only=True) class FMathFactsInput(_FactsDTO):',
    1422: "    kind: _Literal['facts']",
    1423: '    value: FFactsRequest',
    1424: '',
    1425: 'L3922: @_dataclass(frozen=True, slots=True, kw_only=True) class FMathPreflightInput(_FactsDTO):',
    1426: "    kind: _Literal['preflight']",
    1427: '    value: FPreflightFacts',
    1428: '',
    1432: 'L3933: @_dataclass(frozen=True, slots=True, kw_only=True) class FMathLimitInput(_FactsDTO):',
    1433: "    kind: _Literal['limit']",
    1434: '    value: FLimitFactsRequest',
    1435: 'L3938: FMathInput: _TypeAlias = FMathFactsInput | FMathPreflightInput | FMathLimitInput',
    1436: 'L3939: FMathInputV1: _TypeAlias = FMathInput',
    1442: 'L3949: @_dataclass(frozen=True, slots=True, kw_only=True) class FPrepareCallArgs(_FactsDTO):',
    1443: '    budget: RateBudget',
    1444: '',
    1445: 'L3954: @_dataclass(frozen=True, slots=True, kw_only=True) class FBindDrawCallArgs(_FactsDTO):',
    1446: '    problem_step: int',
    1447: '    draw: Point',
    1448: '    budget: RateBudget',
    1449: '',
    1450: 'L3961: @_dataclass(frozen=True, slots=True, kw_only=True) class FRootCallArgs(_FactsDTO):',
    1451: '    root_step: int',
    1452: '    budget: RateBudget',
    1453: '',
    1454: 'L3967: @_dataclass(frozen=True, slots=True, kw_only=True) class FEnumeratedCallArgs(_FactsDTO):',
    1455: '    root_step: int',
    1456: '    paths_step: int',
    1457: '    budget: RateBudget',
    1458: '',
    1459: 'L3974: @_dataclass(frozen=True, slots=True, kw_only=True) class FPrefixCallArgs(_FactsDTO):',
    1460: '    root_step: int',
    1461: '    steps: int',
    1462: '    budget: RateBudget',
    1463: '',
    1464: 'L3981: @_dataclass(frozen=True, slots=True, kw_only=True) class FPrefixEvaluationCallArgs(_FactsDTO):',
    1465: '    root_step: int',
    1466: '    prefix_step: int',
    1467: '    budget: RateBudget',
    1468: '',
    1469: 'L3988: @_dataclass(frozen=True, slots=True, kw_only=True) class FTailCallArgs(_FactsDTO):',
    1470: '    root_step: int',
    1471: '    prefix_step: int',
    1472: '    candidate: str',
    1473: '    budget: RateBudget',
    1474: '',
    1475: 'L3996: @_dataclass(frozen=True, slots=True, kw_only=True) class FChoiceCallArgs(_FactsDTO):',
    1476: '    evaluation_step: int',
    1477: '',
    1478: 'L4001: @_dataclass(frozen=True, slots=True, kw_only=True) class FEvaluateCallArgs(_FactsDTO):',
    1479: '    root_step: int',
    1480: '    resume_step: int | None',
    1481: '    budget: RateBudget',
    1482: '',
    1483: 'L4008: @_dataclass(frozen=True, slots=True, kw_only=True) class FPreflightCallArgs(_FactsDTO):',
    1484: 'L4012: FMathCallArgs: _TypeAlias = FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs | FEnumeratedCallArgs | FPrefixCallArgs | FPrefixEvaluationCallArgs | FTailCallArgs | FChoiceCallArgs | FEvaluateCallArgs | FPreflightCallArgs',
    1485: "L4017: FMathOp: _TypeAlias = _Literal['prepare', 'bind_draw', 'scope', 'enumerate', 'recursive', 'enumerated', 'prefix', 'prefix_evaluation', 'tail', 'choice', 'evaluate', 'preflight', 'limit_certificate', 'limit']",
    1486: 'L4022: FMathCallArgsV1: _TypeAlias = FMathCallArgs',
    1487: 'L4023: FMathOpV1: _TypeAlias = FMathOp',
    1489: 'L4027: @_dataclass(frozen=True, slots=True, kw_only=True) class FMathCall(_FactsDTO):',
    1490: '    """Whole args of the named op; prior-step/type/use checks are factory work.',
    1491: '    ',
    1492: '    prepare/limit_certificate/limit use FPrepareCallArgs;',
    1493: '    scope/enumerate/recursive use FRootCallArgs. choice has no caller-supplied u."""',
    1494: '    op: FMathOpV1',
    1495: '    args: FMathCallArgsV1',
    1496: 'L4037: FMathCallV1 = FMathCall',
    1498: 'L4041: @_dataclass(frozen=True, slots=True, kw_only=True) class FProblemMathClaim(_FactsDTO):',
    1499: "    type: _Literal['FProblem']",
    1500: '    value: FProblem',
    1501: '',
    1502: 'L4047: @_dataclass(frozen=True, slots=True, kw_only=True) class FRootMathClaim(_FactsDTO):',
    1503: "    type: _Literal['FRoot']",
    1504: '    value: FRoot',
    1505: '',
    1506: 'L4053: @_dataclass(frozen=True, slots=True, kw_only=True) class FEvaluationMathClaim(_FactsDTO):',
    1507: "    type: _Literal['FEvaluation']",
    1508: '    value: FEvaluation',
    1509: '',
    1510: 'L4059: @_dataclass(frozen=True, slots=True, kw_only=True) class SelectedMathClaim(_FactsDTO):',
    1511: "    type: _Literal['Selected']",
    1512: '    value: Selected',
    1513: '',
    1514: 'L4065: @_dataclass(frozen=True, slots=True, kw_only=True) class NoDecisionMathClaim(_FactsDTO):',
    1515: "    type: _Literal['NoDecision']",
    1516: '    value: NoDecision',
    1517: '',
    1518: 'L4071: @_dataclass(frozen=True, slots=True, kw_only=True) class PreflightReadyMathClaim(_FactsDTO):',
    1519: "    type: _Literal['PreflightReady']",
    1520: '    value: PreflightReady',
    1521: '',
    1522: 'L4077: @_dataclass(frozen=True, slots=True, kw_only=True) class LimitCertificateMathClaim(_FactsDTO):',
    1523: "    type: _Literal['LimitCertificate']",
    1524: '    value: LimitCertificate',
    1525: '',
    1526: 'L4083: @_dataclass(frozen=True, slots=True, kw_only=True) class FScopeMathClaim(_FactsDTO):',
    1527: "    type: _Literal['FScope']",
    1528: '    value: FScope',
    1529: '',
    1530: 'L4089: @_dataclass(frozen=True, slots=True, kw_only=True) class FPathTableMathClaim(_FactsDTO):',
    1531: "    type: _Literal['FPathTable']",
    1532: '    value: FPathTable',
    1533: '',
    1534: 'L4095: @_dataclass(frozen=True, slots=True, kw_only=True) class TailCertificateMathClaim(_FactsDTO):',
    1535: "    type: _Literal['TailCertificate']",
    1536: '    value: TailCertificate',
    1537: 'L4100: FMathClaim: _TypeAlias = FProblemMathClaim | FRootMathClaim | FEvaluationMathClaim | SelectedMathClaim | NoDecisionMathClaim | PreflightReadyMathClaim | LimitCertificateMathClaim | FScopeMathClaim | FPathTableMathClaim | TailCertificateMathClaim',
    1538: 'L4103: FMathClaimV1: _TypeAlias = FMathClaim',
    1707: 'L4353: @_dataclass(frozen=True, slots=True, kw_only=True) class FMathLegacyBridgeInput(_FactsDTO):',
    1708: "    kind: _Literal['legacy_bridge']",
    1709: '    value: FLegacyBridgeRequest',
    1710: '',
    1711: 'L4359: @_dataclass(frozen=True, slots=True, kw_only=True) class FPreflightFactsCallArgs(_FactsDTO):',
    1712: '    """math_artifact/2 preflight args; v1\'s empty args type stays available."""',
    1713: '    budget: RateBudget',
    1714: '',
    1715: 'L4365: @_dataclass(frozen=True, slots=True, kw_only=True) class FLegacyBridgeCallArgs(_FactsDTO):',
    1716: '    problem_step: int',
    1717: '    draw: Point',
    1718: '    budget: RateBudget',
    1719: 'L4371: FMathInputV2: _TypeAlias = FMathInputV1 | FMathLegacyBridgeInput',
    1720: "L4372: FMathOpV2: _TypeAlias = _Literal['prepare', 'bind_draw', 'scope', 'enumerate', 'recursive', 'enumerated', 'prefix', 'prefix_evaluation', 'tail', 'choice', 'evaluate', 'preflight', 'limit_certificate', 'limit', 'legacy_bridge_prepare', 'legacy_bridge']",
    1721: 'L4377: FMathCallArgsV2: _TypeAlias = FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs | FEnumeratedCallArgs | FPrefixCallArgs | FPrefixEvaluationCallArgs | FTailCallArgs | FChoiceCallArgs | FEvaluateCallArgs | FPreflightFactsCallArgs | FLegacyBridgeCallArgs',
    1731: 'L4396: @_dataclass(frozen=True, slots=True, kw_only=True) class FLegacyBridgeProblemMathClaim(_FactsDTO):',
    1732: "    type: _Literal['FLegacyBridgeProblem']",
    1733: '    value: FLegacyBridgeProblem',
    1734: '',
    1735: 'L4402: @_dataclass(frozen=True, slots=True, kw_only=True) class LegacyComparisonMathClaim(_FactsDTO):',
    1736: "    type: _Literal['LegacyComparison']",
    1737: '    value: LegacyComparison',
    1738: 'L4407: FMathClaimV2: _TypeAlias = FMathClaimV1 | FLegacyBridgeProblemMathClaim | LegacyComparisonMathClaim',
    1749: 'L4423: FMathInput = FMathInputV2',
    1750: 'L4424: FMathOp = FMathOpV2',
    1751: 'L4425: FMathCallArgs = FMathCallArgsV2',
    1752: 'L4426: FMathCall = FMathCallV2',
    1753: 'L4427: FMathClaim = FMathClaimV2',
    1754: 'L4428: FMathArtifactJSON = FMathArtifactJSONV2',
    1761: 'L3: from collections.abc import Mapping as _Mapping',
    1762: 'L4: from dataclasses import dataclass as _dataclass',
    1763: 'L5: from fractions import Fraction as _Fraction',
    1764: 'L6: from types import MappingProxyType as _MappingProxyType',
    1765: 'L7: import hashlib as _hashlib',
    1766: 'L8: import json as _json',
    1767: 'L15: from .contracts import ContractRef as _ContractRef',
    1768: 'L16: from .agent import ModelFalsified as _ModelFalsified, RebuildMismatch as _RebuildMismatch',
    1769: 'L17: from .ids import Ref as _Ref',
    1770: 'L18: from .inference import NumericalRange as _NumericalRange',
    1771: 'L19: from .lookahead import NoAdmissibleCandidate as _NoAdmissibleCandidate, OutsideEvaluationType as _OutsideEvaluationType',
    1772: 'L21: from .quantity import IntegrationIncomplete as _IntegrationIncomplete',
    1797: 'L53: @_dataclass(frozen=True, slots=True) class RationalInterval():',
    1798: '    lower: _Fraction',
    1799: '    upper: _Fraction',
    1800: '',
    1801: 'L63: @_dataclass(frozen=True, slots=True) class RateBudget():',
    1802: '    """実行側が渡す計算の予算 (§3-10-10 G2)。モデル・好み・行動の規則ではない。"""',
    1803: '    tolerance: _Fraction',
    1804: '    max_cells: int',
    1805: '    max_terms: int',
    1806: '    max_refinements: int',
}
SUPPLEMENTAL_IMPORT_DECLARATIONS=(
    {'module': 'src/sui/f.py', 'line': 6, 'upstream_line': 26, 'declaration': 'from __future__ import annotations'},
    {'module': 'src/sui/f.py', 'line': 7, 'upstream_line': 28, 'declaration': 'from collections.abc import Mapping as _Mapping'},
    {'module': 'src/sui/f.py', 'line': 8, 'upstream_line': 29, 'declaration': 'from dataclasses import dataclass as _dataclass'},
    {'module': 'src/sui/f.py', 'line': 9, 'upstream_line': 30, 'declaration': 'from fractions import Fraction as _Fraction'},
    {'module': 'src/sui/f.py', 'line': 10, 'upstream_line': 31, 'declaration': 'from typing import Literal as _Literal, TypeAlias as _TypeAlias, Protocol as _Protocol'},
    {'module': 'src/sui/f.py', 'line': 11, 'upstream_line': 33, 'declaration': 'from .agent import ModelFalsified as _ModelFalsified, RebuildMismatch as _RebuildMismatch'},
    {'module': 'src/sui/f.py', 'line': 12, 'upstream_line': 34, 'declaration': 'from .contracts import ContractRef as _ContractRef'},
    {'module': 'src/sui/f.py', 'line': 13, 'upstream_line': 35, 'declaration': 'from .f_model import FModel'},
    {'module': 'src/sui/f.py', 'line': 14, 'upstream_line': 36, 'declaration': 'from .ids import Ref as _Ref'},
    {'module': 'src/sui/f.py', 'line': 15, 'upstream_line': 37, 'declaration': 'from .records import Record as _Record'},
    {'module': 'src/sui/f.py', 'line': 16, 'upstream_line': 38, 'declaration': 'from .inference import NumericalRange as _NumericalRange'},
    {'module': 'src/sui/f.py', 'line': 17, 'upstream_line': 39, 'declaration': 'from .lookahead import OutsideEvaluationType as _OutsideEvaluationType'},
    {'module': 'src/sui/f.py', 'line': 18, 'upstream_line': 40, 'declaration': 'from .quantity import IntegrationIncomplete as _IntegrationIncomplete'},
    {'module': 'src/sui/f.py', 'line': 19, 'upstream_line': 41, 'declaration': 'from .rate import RateBudget, RationalInterval'},
    {'module': 'src/sui/f.py', 'line': 20, 'upstream_line': 42, 'declaration': 'from .rate_model import RateModel'},
    {'module': 'src/sui/rate.py', 'line': 1761, 'upstream_line': 3, 'declaration': 'from collections.abc import Mapping as _Mapping'},
    {'module': 'src/sui/rate.py', 'line': 1762, 'upstream_line': 4, 'declaration': 'from dataclasses import dataclass as _dataclass'},
    {'module': 'src/sui/rate.py', 'line': 1763, 'upstream_line': 5, 'declaration': 'from fractions import Fraction as _Fraction'},
    {'module': 'src/sui/rate.py', 'line': 1764, 'upstream_line': 6, 'declaration': 'from types import MappingProxyType as _MappingProxyType'},
    {'module': 'src/sui/rate.py', 'line': 1765, 'upstream_line': 7, 'declaration': 'import hashlib as _hashlib'},
    {'module': 'src/sui/rate.py', 'line': 1766, 'upstream_line': 8, 'declaration': 'import json as _json'},
    {'module': 'src/sui/rate.py', 'line': 1767, 'upstream_line': 15, 'declaration': 'from .contracts import ContractRef as _ContractRef'},
    {'module': 'src/sui/rate.py', 'line': 1768, 'upstream_line': 16, 'declaration': 'from .agent import ModelFalsified as _ModelFalsified, RebuildMismatch as _RebuildMismatch'},
    {'module': 'src/sui/rate.py', 'line': 1769, 'upstream_line': 17, 'declaration': 'from .ids import Ref as _Ref'},
    {'module': 'src/sui/rate.py', 'line': 1770, 'upstream_line': 18, 'declaration': 'from .inference import NumericalRange as _NumericalRange'},
    {'module': 'src/sui/rate.py', 'line': 1771, 'upstream_line': 19, 'declaration': 'from .lookahead import NoAdmissibleCandidate as _NoAdmissibleCandidate, OutsideEvaluationType as _OutsideEvaluationType'},
    {'module': 'src/sui/rate.py', 'line': 1772, 'upstream_line': 21, 'declaration': 'from .quantity import IntegrationIncomplete as _IntegrationIncomplete'},
)
SUPPLEMENTAL_DECLARATION_NODES=(
    {'key': 'src/sui/f.py:NoDecisionReason@22', 'kind': 'literal', 'name': 'NoDecisionReason', 'line': 22, 'upstream_line': 50, 'module': 'src/sui/f.py', 'rhs': "_Literal['NoAdmissibleCandidate', 'NumericalRange', 'budget_exhausted', 'selection_boundary', 'algorithm_unavailable', 'proof_incomplete', 'runtime_unverified', 'candidate_measure_missing', 'normalization_unproved', 'OutsideEvaluationType', 'certificate_incomplete', 'information_divergent', 'undefined_infinite_difference', 'clock_unaligned', 'prerequisite_unavailable', 'cost_certificate', 'missing_contract', 'model_falsified', 'c1_closure_unproved']", 'references': (), 'values': ('NoAdmissibleCandidate', 'NumericalRange', 'budget_exhausted', 'selection_boundary', 'algorithm_unavailable', 'proof_incomplete', 'runtime_unverified', 'candidate_measure_missing', 'normalization_unproved', 'OutsideEvaluationType', 'certificate_incomplete', 'information_divergent', 'undefined_infinite_difference', 'clock_unaligned', 'prerequisite_unavailable', 'cost_certificate', 'missing_contract', 'model_falsified', 'c1_closure_unproved')},
    {'key': 'src/sui/f.py:CapabilityKind@661', 'kind': 'literal', 'name': 'CapabilityKind', 'line': 661, 'upstream_line': 911, 'module': 'src/sui/f.py', 'rhs': "_Literal['action', 'predicate', 'kernel', 'policy', 'execution', 'proof', 'method', 'arithmetic', 'choice', 'measurement', 'projection', 'generation', 'clock', 'quality', 'cursor', 'generator']", 'references': (), 'values': ('action', 'predicate', 'kernel', 'policy', 'execution', 'proof', 'method', 'arithmetic', 'choice', 'measurement', 'projection', 'generation', 'clock', 'quality', 'cursor', 'generator')},
    {'key': 'src/sui/f.py:FMathFactsInput@1421', 'kind': 'class', 'name': 'FMathFactsInput', 'line': 1421, 'upstream_line': 3916, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FMathFactsInput(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathPreflightInput@1425', 'kind': 'class', 'name': 'FMathPreflightInput', 'line': 1425, 'upstream_line': 3922, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FMathPreflightInput(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathLimitInput@1432', 'kind': 'class', 'name': 'FMathLimitInput', 'line': 1432, 'upstream_line': 3933, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FMathLimitInput(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathInput@1435', 'kind': 'alias', 'name': 'FMathInput', 'line': 1435, 'upstream_line': 3938, 'module': 'src/sui/f.py', 'rhs': 'FMathFactsInput | FMathPreflightInput | FMathLimitInput', 'references': ('src/sui/f.py:FMathFactsInput@1421', 'src/sui/f.py:FMathPreflightInput@1425', 'src/sui/f.py:FMathLimitInput@1432'), 'values': ()},
    {'key': 'src/sui/f.py:FMathInputV1@1436', 'kind': 'alias', 'name': 'FMathInputV1', 'line': 1436, 'upstream_line': 3939, 'module': 'src/sui/f.py', 'rhs': 'FMathInput', 'references': ('src/sui/f.py:FMathInput@1435',), 'values': ()},
    {'key': 'src/sui/f.py:FPrepareCallArgs@1442', 'kind': 'class', 'name': 'FPrepareCallArgs', 'line': 1442, 'upstream_line': 3949, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FPrepareCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FBindDrawCallArgs@1445', 'kind': 'class', 'name': 'FBindDrawCallArgs', 'line': 1445, 'upstream_line': 3954, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FBindDrawCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FRootCallArgs@1450', 'kind': 'class', 'name': 'FRootCallArgs', 'line': 1450, 'upstream_line': 3961, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FRootCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FEnumeratedCallArgs@1454', 'kind': 'class', 'name': 'FEnumeratedCallArgs', 'line': 1454, 'upstream_line': 3967, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FEnumeratedCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FPrefixCallArgs@1459', 'kind': 'class', 'name': 'FPrefixCallArgs', 'line': 1459, 'upstream_line': 3974, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FPrefixCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FPrefixEvaluationCallArgs@1464', 'kind': 'class', 'name': 'FPrefixEvaluationCallArgs', 'line': 1464, 'upstream_line': 3981, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FPrefixEvaluationCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FTailCallArgs@1469', 'kind': 'class', 'name': 'FTailCallArgs', 'line': 1469, 'upstream_line': 3988, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FTailCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FChoiceCallArgs@1475', 'kind': 'class', 'name': 'FChoiceCallArgs', 'line': 1475, 'upstream_line': 3996, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FChoiceCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FEvaluateCallArgs@1478', 'kind': 'class', 'name': 'FEvaluateCallArgs', 'line': 1478, 'upstream_line': 4001, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FEvaluateCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FPreflightCallArgs@1483', 'kind': 'class', 'name': 'FPreflightCallArgs', 'line': 1483, 'upstream_line': 4008, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FPreflightCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathCallArgs@1484', 'kind': 'alias', 'name': 'FMathCallArgs', 'line': 1484, 'upstream_line': 4012, 'module': 'src/sui/f.py', 'rhs': 'FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs | FEnumeratedCallArgs | FPrefixCallArgs | FPrefixEvaluationCallArgs | FTailCallArgs | FChoiceCallArgs | FEvaluateCallArgs | FPreflightCallArgs', 'references': ('src/sui/f.py:FPrepareCallArgs@1442', 'src/sui/f.py:FBindDrawCallArgs@1445', 'src/sui/f.py:FRootCallArgs@1450', 'src/sui/f.py:FEnumeratedCallArgs@1454', 'src/sui/f.py:FPrefixCallArgs@1459', 'src/sui/f.py:FPrefixEvaluationCallArgs@1464', 'src/sui/f.py:FTailCallArgs@1469', 'src/sui/f.py:FChoiceCallArgs@1475', 'src/sui/f.py:FEvaluateCallArgs@1478', 'src/sui/f.py:FPreflightCallArgs@1483'), 'values': ()},
    {'key': 'src/sui/f.py:FMathOp@1485', 'kind': 'literal', 'name': 'FMathOp', 'line': 1485, 'upstream_line': 4017, 'module': 'src/sui/f.py', 'rhs': "_Literal['prepare', 'bind_draw', 'scope', 'enumerate', 'recursive', 'enumerated', 'prefix', 'prefix_evaluation', 'tail', 'choice', 'evaluate', 'preflight', 'limit_certificate', 'limit']", 'references': (), 'values': ('prepare', 'bind_draw', 'scope', 'enumerate', 'recursive', 'enumerated', 'prefix', 'prefix_evaluation', 'tail', 'choice', 'evaluate', 'preflight', 'limit_certificate', 'limit')},
    {'key': 'src/sui/f.py:FMathCallArgsV1@1486', 'kind': 'alias', 'name': 'FMathCallArgsV1', 'line': 1486, 'upstream_line': 4022, 'module': 'src/sui/f.py', 'rhs': 'FMathCallArgs', 'references': ('src/sui/f.py:FMathCallArgs@1484',), 'values': ()},
    {'key': 'src/sui/f.py:FMathOpV1@1487', 'kind': 'alias', 'name': 'FMathOpV1', 'line': 1487, 'upstream_line': 4023, 'module': 'src/sui/f.py', 'rhs': 'FMathOp', 'references': ('src/sui/f.py:FMathOp@1485',), 'values': ()},
    {'key': 'src/sui/f.py:FMathCall@1489', 'kind': 'class', 'name': 'FMathCall', 'line': 1489, 'upstream_line': 4027, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FMathCall(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathCallV1@1496', 'kind': 'alias', 'name': 'FMathCallV1', 'line': 1496, 'upstream_line': 4037, 'module': 'src/sui/f.py', 'rhs': 'FMathCall', 'references': ('src/sui/f.py:FMathCall@1489',), 'values': ()},
    {'key': 'src/sui/f.py:FProblemMathClaim@1498', 'kind': 'class', 'name': 'FProblemMathClaim', 'line': 1498, 'upstream_line': 4041, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FProblemMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FRootMathClaim@1502', 'kind': 'class', 'name': 'FRootMathClaim', 'line': 1502, 'upstream_line': 4047, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FRootMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FEvaluationMathClaim@1506', 'kind': 'class', 'name': 'FEvaluationMathClaim', 'line': 1506, 'upstream_line': 4053, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FEvaluationMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:SelectedMathClaim@1510', 'kind': 'class', 'name': 'SelectedMathClaim', 'line': 1510, 'upstream_line': 4059, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class SelectedMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:NoDecisionMathClaim@1514', 'kind': 'class', 'name': 'NoDecisionMathClaim', 'line': 1514, 'upstream_line': 4065, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class NoDecisionMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:PreflightReadyMathClaim@1518', 'kind': 'class', 'name': 'PreflightReadyMathClaim', 'line': 1518, 'upstream_line': 4071, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class PreflightReadyMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:LimitCertificateMathClaim@1522', 'kind': 'class', 'name': 'LimitCertificateMathClaim', 'line': 1522, 'upstream_line': 4077, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class LimitCertificateMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FScopeMathClaim@1526', 'kind': 'class', 'name': 'FScopeMathClaim', 'line': 1526, 'upstream_line': 4083, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FScopeMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FPathTableMathClaim@1530', 'kind': 'class', 'name': 'FPathTableMathClaim', 'line': 1530, 'upstream_line': 4089, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FPathTableMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:TailCertificateMathClaim@1534', 'kind': 'class', 'name': 'TailCertificateMathClaim', 'line': 1534, 'upstream_line': 4095, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class TailCertificateMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathClaim@1537', 'kind': 'alias', 'name': 'FMathClaim', 'line': 1537, 'upstream_line': 4100, 'module': 'src/sui/f.py', 'rhs': 'FProblemMathClaim | FRootMathClaim | FEvaluationMathClaim | SelectedMathClaim | NoDecisionMathClaim | PreflightReadyMathClaim | LimitCertificateMathClaim | FScopeMathClaim | FPathTableMathClaim | TailCertificateMathClaim', 'references': ('src/sui/f.py:FProblemMathClaim@1498', 'src/sui/f.py:FRootMathClaim@1502', 'src/sui/f.py:FEvaluationMathClaim@1506', 'src/sui/f.py:SelectedMathClaim@1510', 'src/sui/f.py:NoDecisionMathClaim@1514', 'src/sui/f.py:PreflightReadyMathClaim@1518', 'src/sui/f.py:LimitCertificateMathClaim@1522', 'src/sui/f.py:FScopeMathClaim@1526', 'src/sui/f.py:FPathTableMathClaim@1530', 'src/sui/f.py:TailCertificateMathClaim@1534'), 'values': ()},
    {'key': 'src/sui/f.py:FMathClaimV1@1538', 'kind': 'alias', 'name': 'FMathClaimV1', 'line': 1538, 'upstream_line': 4103, 'module': 'src/sui/f.py', 'rhs': 'FMathClaim', 'references': ('src/sui/f.py:FMathClaim@1537',), 'values': ()},
    {'key': 'src/sui/f.py:FMathLegacyBridgeInput@1707', 'kind': 'class', 'name': 'FMathLegacyBridgeInput', 'line': 1707, 'upstream_line': 4353, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FMathLegacyBridgeInput(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FPreflightFactsCallArgs@1711', 'kind': 'class', 'name': 'FPreflightFactsCallArgs', 'line': 1711, 'upstream_line': 4359, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FPreflightFactsCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FLegacyBridgeCallArgs@1715', 'kind': 'class', 'name': 'FLegacyBridgeCallArgs', 'line': 1715, 'upstream_line': 4365, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FLegacyBridgeCallArgs(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathInputV2@1719', 'kind': 'alias', 'name': 'FMathInputV2', 'line': 1719, 'upstream_line': 4371, 'module': 'src/sui/f.py', 'rhs': 'FMathInputV1 | FMathLegacyBridgeInput', 'references': ('src/sui/f.py:FMathInputV1@1436', 'src/sui/f.py:FMathLegacyBridgeInput@1707'), 'values': ()},
    {'key': 'src/sui/f.py:FMathOpV2@1720', 'kind': 'literal', 'name': 'FMathOpV2', 'line': 1720, 'upstream_line': 4372, 'module': 'src/sui/f.py', 'rhs': "_Literal['prepare', 'bind_draw', 'scope', 'enumerate', 'recursive', 'enumerated', 'prefix', 'prefix_evaluation', 'tail', 'choice', 'evaluate', 'preflight', 'limit_certificate', 'limit', 'legacy_bridge_prepare', 'legacy_bridge']", 'references': (), 'values': ('prepare', 'bind_draw', 'scope', 'enumerate', 'recursive', 'enumerated', 'prefix', 'prefix_evaluation', 'tail', 'choice', 'evaluate', 'preflight', 'limit_certificate', 'limit', 'legacy_bridge_prepare', 'legacy_bridge')},
    {'key': 'src/sui/f.py:FMathCallArgsV2@1721', 'kind': 'alias', 'name': 'FMathCallArgsV2', 'line': 1721, 'upstream_line': 4377, 'module': 'src/sui/f.py', 'rhs': 'FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs | FEnumeratedCallArgs | FPrefixCallArgs | FPrefixEvaluationCallArgs | FTailCallArgs | FChoiceCallArgs | FEvaluateCallArgs | FPreflightFactsCallArgs | FLegacyBridgeCallArgs', 'references': ('src/sui/f.py:FPrepareCallArgs@1442', 'src/sui/f.py:FBindDrawCallArgs@1445', 'src/sui/f.py:FRootCallArgs@1450', 'src/sui/f.py:FEnumeratedCallArgs@1454', 'src/sui/f.py:FPrefixCallArgs@1459', 'src/sui/f.py:FPrefixEvaluationCallArgs@1464', 'src/sui/f.py:FTailCallArgs@1469', 'src/sui/f.py:FChoiceCallArgs@1475', 'src/sui/f.py:FEvaluateCallArgs@1478', 'src/sui/f.py:FPreflightFactsCallArgs@1711', 'src/sui/f.py:FLegacyBridgeCallArgs@1715'), 'values': ()},
    {'key': 'src/sui/f.py:FLegacyBridgeProblemMathClaim@1731', 'kind': 'class', 'name': 'FLegacyBridgeProblemMathClaim', 'line': 1731, 'upstream_line': 4396, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class FLegacyBridgeProblemMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:LegacyComparisonMathClaim@1735', 'kind': 'class', 'name': 'LegacyComparisonMathClaim', 'line': 1735, 'upstream_line': 4402, 'module': 'src/sui/f.py', 'header': '@_dataclass(frozen=True, slots=True, kw_only=True) class LegacyComparisonMathClaim(_FactsDTO):', 'references': ()},
    {'key': 'src/sui/f.py:FMathClaimV2@1738', 'kind': 'alias', 'name': 'FMathClaimV2', 'line': 1738, 'upstream_line': 4407, 'module': 'src/sui/f.py', 'rhs': 'FMathClaimV1 | FLegacyBridgeProblemMathClaim | LegacyComparisonMathClaim', 'references': ('src/sui/f.py:FMathClaimV1@1538', 'src/sui/f.py:FLegacyBridgeProblemMathClaim@1731', 'src/sui/f.py:LegacyComparisonMathClaim@1735'), 'values': ()},
    {'key': 'src/sui/f.py:FMathOp@1750', 'kind': 'alias', 'name': 'FMathOp', 'line': 1750, 'upstream_line': 4424, 'module': 'src/sui/f.py', 'rhs': 'FMathOpV2', 'references': ('src/sui/f.py:FMathOpV2@1720',), 'values': ()},
)
SUPPLEMENTAL_ALIAS_EXPORTS={'NoDecisionReason': 'src/sui/f.py:NoDecisionReason@22', 'CapabilityKind': 'src/sui/f.py:CapabilityKind@661', 'FMathCallArgsV1': 'src/sui/f.py:FMathCallArgsV1@1486', 'FMathCallArgsV2': 'src/sui/f.py:FMathCallArgsV2@1721', 'FMathCallV1': 'src/sui/f.py:FMathCallV1@1496', 'FMathClaimV1': 'src/sui/f.py:FMathClaimV1@1538', 'FMathClaimV2': 'src/sui/f.py:FMathClaimV2@1738', 'FMathInputV1': 'src/sui/f.py:FMathInputV1@1436', 'FMathInputV2': 'src/sui/f.py:FMathInputV2@1719', 'FMathOp': 'src/sui/f.py:FMathOp@1750', 'FMathOpV1': 'src/sui/f.py:FMathOpV1@1487', 'FMathOpV2': 'src/sui/f.py:FMathOpV2@1720'}
SUPPLEMENTAL_CLASSES=(
    {'name': 'RationalInterval', 'module': 'src/sui/rate.py', 'upstream_line': 53, 'first': 1797, 'last': 1800, 'header': '@_dataclass(frozen=True, slots=True) class RationalInterval():', 'fields': ({'name': 'lower', 'type': '_Fraction', 'line': 1798}, {'name': 'upper', 'type': '_Fraction', 'line': 1799}), 'docstring': '適用外: 資料にdocstringなし'},
    {'name': 'RateBudget', 'module': 'src/sui/rate.py', 'upstream_line': 63, 'first': 1801, 'last': 1807, 'header': '@_dataclass(frozen=True, slots=True) class RateBudget():', 'fields': ({'name': 'tolerance', 'type': '_Fraction', 'line': 1803}, {'name': 'max_cells', 'type': 'int', 'line': 1804}, {'name': 'max_terms', 'type': 'int', 'line': 1805}, {'name': 'max_refinements', 'type': 'int', 'line': 1806}), 'docstring': '実行側が渡す計算の予算 (§3-10-10 G2)。モデル・好み・行動の規則ではない。'},
)


# 宣言の追補を独立した索引へ展開。元のクラス宣言と後の同名exportを混ぜない。
SUPPLEMENTAL_NODE_BY_KEY={n['key']:n for n in SUPPLEMENTAL_DECLARATION_NODES}
SUPPLEMENTAL_NODE_TARGETS={n['key']:('T.public.'+n['name'] if n['kind']=='class'
                                   else 'T.decl.alias.'+n['name']+'@'+str(n['line']))
                           for n in SUPPLEMENTAL_DECLARATION_NODES}

def _declaration_leaves(key, trail=()):
    if key in trail:
        raise ValueError('型別名の循環: '+key)
    node=SUPPLEMENTAL_NODE_BY_KEY[key]
    if node['kind']=='class':
        return (dict(kind='class',value=node['name'],target=SUPPLEMENTAL_NODE_TARGETS[key],
                     declaration=key,path=trail+(key,)),)
    if node['kind']=='literal':
        return tuple(dict(kind='literal',value=v,target=NA,declaration=key,path=trail+(key,))
                     for v in node['values'])
    return tuple(leaf for ref in node['references'] for leaf in _declaration_leaves(ref,trail+(key,)))

SUPPLEMENTAL_ALIAS_BRANCHES={n['key']:_declaration_leaves(n['key'])
                             for n in SUPPLEMENTAL_DECLARATION_NODES if n['kind']!='class'}
SUPPLEMENTAL_TYPE_RESOLUTIONS={}
for _decl in SUPPLEMENTAL_CLASSES:
    _name=_decl['name'];_tid='T.public.'+_name
    _refs=(source(DECLARATIONS_PATH,_decl['first'],_decl['last']),source(DECLARATIONS_PATH,1763),
           source(FA,27),source(FA,333,334),source(FB,2334))
    _field_ids=tuple(_tid+'.field.'+f['name'] for f in _decl['fields'])
    _row=_wire_add(_tid,'relation',_name,refs=_refs,
                  use='公開Python型の全注釈欄。'+_decl['docstring']+' 初期値・値域・constructorの動作はこの宣言から補わない。',
                  rules=('INV-3','INV-10','背骨⑤'),entries=('I-3',),related=_field_ids,
                  representation='追補資料の公開Python型。保存DTOへの同一視なし')
    _row['owner']=NA
    for _field in _decl['fields']:
        _row=_wire_add(_tid+'.field.'+_field['name'],'field',_name,
                      refs=(source(DECLARATIONS_PATH,_field['line']),)+_refs[1:],
                      fields=_field['name'],value_type=_field['type'],
                      use='注釈は'+_field['type']+'。_Fractionはfractions.Fractionの別名。型宣言を数値正解や追加の値域にしない。',
                      rules=('INV-3','INV-10','背骨⑤'),entries=('I-3',),related=(_tid,),
                      presence='注釈欄は非nullable。既定値や保存キーの省略可否はこの資料から推論しない',
                      representation='追補資料の公開Python型の欄')
        _row['owner']=NA
        _row['negative']='当該欄を別型へ一つだけ変える。数値の境界条件は紙に宣言された条件だけを別に試す。'
        _row['nearest_legal']='注釈された型の値。型が合うだけで数値の認証成功と数えない。'
    SUPPLEMENTAL_TYPE_RESOLUTIONS[_name]=dict(target=_tid,fields=_field_ids,branches=(),
                                             sources=_refs,kind='class',declaration=NA)

for _node in SUPPLEMENTAL_DECLARATION_NODES:
    if _node['kind']=='class':
        continue
    _key=_node['key'];_tid=SUPPLEMENTAL_NODE_TARGETS[_key]
    _branches=SUPPLEMENTAL_ALIAS_BRANCHES[_key]
    _branch_ids=tuple(_tid+'.branch.'+str(i) for i in range(len(_branches)))
    _refs=(source(DECLARATIONS_PATH,_node['line']),source(FB,2334))
    _row=_wire_add(_tid,'relation',_node['name'],refs=_refs,
                  use='型別名の宣言時点の結合: '+_node['rhs']+'。保存の契約名・版を新設しない。後の同名代入は既存のV1を変えない。',
                  rules=('INV-3','INV-10'),entries=('I-3',),
                  related=_branch_ids+tuple(SUPPLEMENTAL_NODE_TARGETS[r] for r in _node['references']),
                  representation='型別名（宣言の位置で識別）',value_type=_node['rhs'])
    _row['owner']=NA;_row['declaration_key']=_key
    for _idx,_leaf in enumerate(_branches):
        _refs=tuple(source(DECLARATIONS_PATH,SUPPLEMENTAL_NODE_BY_KEY[k]['line']) for k in _leaf['path'])+(source(FB,2334),)
        _related=(_tid,)+((_leaf['target'],) if _leaf['kind']=='class' else ())
        _row=_wire_add(_branch_ids[_idx],'branch',_node['name'],refs=_refs,
                      branch=repr(_leaf['value']) if _leaf['kind']=='literal' else _leaf['value'],
                      use='宣言された'+_leaf['kind']+'の枝。class枝の全欄はrelated_targetsの公開型へ。',
                      rules=('INV-3','INV-10'),entries=('I-3',),related=_related,
                      representation='型別名のLiteral/クラス枝',value_type=_leaf['value'])
        _row['owner']=NA;_row['declaration_path']=_leaf['path'];_row['leaf_kind']=_leaf['kind']
        _row['negative']='この和型にないLiteral/クラスを与える。版固有の枝を別版へ混入しない。'
        _row['nearest_legal']='この宣言時点に存在する枝。クラス枝はその全欄と紙の用途条件を保つ。'
    if SUPPLEMENTAL_ALIAS_EXPORTS.get(_node['name'])==_key:
        SUPPLEMENTAL_TYPE_RESOLUTIONS[_node['name']]=dict(target=_tid,fields=(),branches=_branch_ids,
                                                         sources=_refs,kind='alias',declaration=_key)

# FStyleは新style/1の形。旧契約の保存キーを新型から推測して埋めない。
LEGACY_STYLE_DISPOSITION=dict(
    target='T.old_style',issue='G-LEGACY-STYLE',status='未対応',classification='直すべき',
    confirmed='新FStyleはkind/scope/gamma、scopeはname/version/H_ns。旧floatは正確な有理数へ、旧H=nullはone_stepへ。',
    missing='資料で未確認: sui.s4d.preference/1の全保存キー、旧H/gammaの保存位置・全型・presence。新FStyleを旧契約の保存形に同一視できない。',
    reason='F-a紙82はFStyle / 旧styleを区別。宣言資料759–769は新FStyle/StyleScopeのみを宣言し、旧保存形との一対一対応を宣言していない。',
    sources=(source(FA,16),source(FA,27),source(FA,82),source(FA,389),source(DECLARATIONS_PATH,759,769)),
    related_targets=('T.public.FStyle','T.public.StyleScope'),execution='not_run',count_as_pass=False,
)
GAPS['G-LEGACY-STYLE']=dict(classification='直すべき',status='未対応',
                            message=LEGACY_STYLE_DISPOSITION['missing']+' '+LEGACY_STYLE_DISPOSITION['reason'],
                            sources=LEGACY_STYLE_DISPOSITION['sources'])
GAPS['G-05']=dict(classification='後で',status='解消',
                  message='宣言だけの追補で14型名を解決。旧styleだけは具体的な旧保存形の不足G-LEGACY-STYLEとして未対応を保つ。',
                  sources=(source(DECLARATIONS_PATH,22),source(DECLARATIONS_PATH,661),
                           source(DECLARATIONS_PATH,1435,1750),source(DECLARATIONS_PATH,1797,1806)))

TARGETS=tuple(_rows)
TARGET_BY_ID={r['id']:r for r in TARGETS}
_DRAFT2_BY_ID={r['id']:r for r in DRAFT2_DENOMINATOR['TARGETS']}
G05_RESOLUTIONS=[]
for _id in DRAFT2_G05_IDS:
    _row=TARGET_BY_ID[_id];_old=_DRAFT2_BY_ID[_id]
    if _id=='T.old_style':
        _row['issues']=('G-LEGACY-STYLE',)
        _row['use']=LEGACY_STYLE_DISPOSITION['missing']+' '+LEGACY_STYLE_DISPOSITION['reason']
        _row['related_targets']=LEGACY_STYLE_DISPOSITION['related_targets']
        _row['sources']+=LEGACY_STYLE_DISPOSITION['sources']
        _row['negative']='未対応: 旧保存形の宣言を得てから未知・欠落キー/旧float/旧nullの取込みの負例を固定する。'
        _row['nearest_legal']='未対応: 旧保存形の全欄が資料で未確認。新FStyleを旧版の合法例として代用しない。'
        _resolved_names=()
        _reason=LEGACY_STYLE_DISPOSITION['reason']
    else:
        _names=set(_old.get('unresolved_type_closure',()))|set(_old.get('unresolved_type_references',()))
        _names.update(t.removeprefix('T.public.unresolved.') for t in _old.get('related_targets',())
                      if t.startswith('T.public.unresolved.'))
        if _id.startswith('T.public.unresolved.'):
            _names.add(_id.removeprefix('T.public.unresolved.'))
        _resolved_names=tuple(sorted(_names))
        if not _resolved_names or not _names<=SUPPLEMENTAL_TYPE_RESOLUTIONS.keys():
            raise ValueError('未確認の名前を解消にできない: '+_id)
        _concrete=tuple(SUPPLEMENTAL_TYPE_RESOLUTIONS[n]['target'] for n in _resolved_names)
        _row['related_targets']=tuple(dict.fromkeys(_old.get('related_targets',())+_concrete))
        _row['sources']+=tuple(s for n in _resolved_names for s in SUPPLEMENTAL_TYPE_RESOLUTIONS[n]['sources'])
        _row['issues']=tuple(i for i in _old['issues'] if i!='G-05')
        _row['status']='整理済み'
        _row['use']='公開宣言の欄・枝の索引。追補資料で '+','.join(_resolved_names)+' を解決。型別名は宣言時点の結合を保持。保存DTO・数値正解・実装の成功はこの型列挙から推論しない。'
        _row['resolved_type_names']=_resolved_names
        _row['supplemental_targets']=_concrete
        if 'unresolved_type_closure' in _row:
            _row['unresolved_type_closure']=()
        if 'unresolved_type_references' in _row:
            _row['unresolved_type_references']=()
        if _id.startswith('T.missing.RateBudget'):
            _row['kind']='relation';_row['field']=NA
            _row['related_targets']=tuple(dict.fromkeys(_row['related_targets']+SUPPLEMENTAL_TYPE_RESOLUTIONS['RateBudget']['fields']))
            _row['presence']='適用外: 旧placeholderを全4欄への索引に置換。欄のpresenceは各公開注釈行に記載'
            _row['negative']='RateBudgetの四つの欄の型を一つずつ変える。値域・既定値を宣言から創作しない。'
            _row['nearest_legal']='RateBudgetの四つの注釈に合う入力。数値認証の成否とは別の対象。'
        _reason='追補の宣言と全枝/全欄への具体的な参照先を付与。旧IDは照合用に維持。'
    G05_RESOLUTIONS.append(dict(target=_id,before_status=_old['status'],before_issues=tuple(_old['issues']),
                                after_status=_row['status'],remaining_issues=tuple(_row['issues']),
                                resolved_names=_resolved_names,targets=_row['related_targets'],
                                reason=_reason,sources=_row['sources'],execution='not_run',count_as_pass=False))
G05_RESOLUTIONS=tuple(G05_RESOLUTIONS)

# 欄から辿る索引で解消を検査できるよう、旧unknownの名前と解決先を併存させる。
PUBLIC_UNRESOLVED_NAMES=tuple(n for n in DRAFT2_PUBLIC_UNRESOLVED_NAMES if n not in SUPPLEMENTAL_TYPE_RESOLUTIONS)
PUBLIC_CLOSURE_GAPS={name:tuple(n for n in missing if n in PUBLIC_UNRESOLVED_NAMES)
                     for name,missing in DRAFT2_DENOMINATOR['PUBLIC_CLOSURE_GAPS'].items()}
for _resolution in FBT01B_RESOLUTIONS:
    if _resolution['target'] not in DRAFT2_G05_IDS:
        continue
    _current=next(x for x in G05_RESOLUTIONS if x['target']==_resolution['target'])
    for _key in ('after_status','remaining_issues','targets','reason','sources'):
        _resolution[_key]=_copy_tree(_current[_key])
FBT01B_REMAINING=tuple(x for x in FBT01B_RESOLUTIONS if x['after_status'] in ('未決','未対応'))
FBT01B_UNCLOSED=tuple(x['target'] for x in FBT01B_REMAINING if set(x['remaining_issues'])<={'G-02','G-05','D-01'})

for _bridge in BRIDGES:
    _bridge['prerequisite_issues']=tuple(sorted((set(_bridge['prerequisite_issues'])-{'G-05'}) |
                                               {i for t in _bridge['targets'] for i in TARGET_BY_ID[t]['issues']}))
# 過去の指摘はREVISION2_FINDINGSに保持。現在の未解決理由はここだけを使う。
REVISION3_FINDINGS=(
    dict(id='G-LEGACY-STYLE',classification='直すべき',status='未対応',targets=('T.old_style',),
         message=GAPS['G-LEGACY-STYLE']['message'],sources=LEGACY_STYLE_DISPOSITION['sources']),
    _copy_tree(REVISION2_FINDINGS[1]),
    dict(id='G-RUN-CODEC',classification='後で',status='未決',targets=('T.measurement_run',),
         message=GAPS['G-RUN-CODEC']['message'],sources=(source(FA,74),source(DECLARATIONS_PATH,619,629))),
)
CATALOG_LAYERS['supplement']='SUPPLEMENTAL_TYPE_RESOLUTIONSから14型名の宣言/全欄/全枝へ。元クラス134と追補クラス2を区別。'
CATALOG_LAYERS['historical']='DRAFT1_DENOMINATOR/DRAFT2_DENOMINATORは凍結した履歴。現在の期待値生成には使わない。'
CATALOG_LAYERS['alias_binding']='SUPPLEMENTAL_DECLARATION_NODESは宣言位置で結合を保存。FMathOpの最終exportをV1へ遡及適用しない。'
SESSION_NOTE=dict(
    date='2026-10-18',project='sui',tool='codex',session_id=DRAFT2_SESSION_NOTE['session_id'],
    artifact_version='FBT draft 3 / paper v0.22 / fb_public_decls.md 1936 lines',
    artifacts=('tests/fb_targets.py','tests/test_fb_targets.py'),
    decision='宣言だけの資料で109行を具体化。旧style1行は全保存形が資料で未確認としてG-LEGACY-STYLEに分離し、未対応を維持。',
    unresolved='G-01の意味設計、Run codec、旧style保存形を保留。未対応行の改名は成功ではない。',
    verification='tests/test_fb_targets.pyだけ23件通過 (0.60秒)。Python 3.12.10 / pytest 9.1.1。旧19件: 17件のASTは同一、2件は旧断言を履歴へ保持して現在の断言を追加。追補4件追加。模型/実装試験はnot_run。',
    failed_attempts='読取りコマンドのPowerShell UTF-8パイプ設定漏れを訂正。初回自己点検22通過/1失敗: Python 3.14/3.12間のast.dump空optional欄の表示差。元の17本のハッシュ一致を3.14で確認し、表記だけ正規化後23通過。禁止ファイルの読取り・書込みはなし。',
    reuse='有効: 第一/第二稿の分母を別ハッシュで保存。版付き別名の宣言時の結合を維持。橋197件と合格条件17件は元の対象/条件を保持。',
    read_scope='追補mdは型別名・imports・対象クラスの該当部分、extract_public_decls.pyは全文。F-a紙16/27/82/333–334/389/391–412/433/474–489など該当部分。原文f.py/rate.pyはこの第三稿では未読、抽出は未実行。Webなし。',
    other_agent='他AIへの連絡なし。資料はユーザー指定の情報として読み、他担当の判断を承認とは扱わない。',
    not_done='commit、src/specs/他tests編集、模型/実装試験は未実行。書込み許可2ファイルのためObsidian Sessions/Projects/Heat未更新。',
    next='旧style保存形の宣言を得た時にT.old_styleの未対応を具体化。G-01/Run codec設計後に該当試験を接続。',
    assumptions={'name_only':0,'meaning_change':0},
    administrative_names='T.decl.alias.*とG-LEGACY-STYLEは一覧の索引/資料不足名。suiの契約や意味の仮定ではない。',
)
DENOMINATOR_KEYS=DENOMINATOR_KEYS+(
    'DECLARATIONS_PROVENANCE','DECLARATION_EXCERPTS','SUPPLEMENTAL_IMPORT_DECLARATIONS',
    'SUPPLEMENTAL_DECLARATION_NODES','SUPPLEMENTAL_ALIAS_EXPORTS','SUPPLEMENTAL_CLASSES',
    'SUPPLEMENTAL_NODE_TARGETS','SUPPLEMENTAL_ALIAS_BRANCHES','SUPPLEMENTAL_TYPE_RESOLUTIONS',
    'LEGACY_STYLE_DISPOSITION','G05_RESOLUTIONS',
)
DENOMINATOR_SHA256='b5dd539a66d405caf89342a68e647a65e979ca5b7a9aa91cb4437e1bcc48cf46'

def third_revision_summary():
    return dict(previous=DRAFT2_SUMMARY['current'],current=summary_counts(),
                g05=dict(previous_unclosed=len(DRAFT2_FBT01B_UNCLOSED),current_unclosed=len(FBT01B_UNCLOSED),
                         previous_rows=len(DRAFT2_G05_IDS),current_rows=sum('G-05' in t['issues'] for t in TARGETS),
                         resolved=sum(r['after_status']=='整理済み' for r in G05_RESOLUTIONS),
                         remaining_by_issue=dict(Counter(i for r in G05_RESOLUTIONS for i in r['remaining_issues']))),
                unresolved_by_issue=revision_summary()['unresolved_by_issue'],
                fbt01b=revision_summary()['fbt01b'],
                supplemental=dict(classes=len(SUPPLEMENTAL_CLASSES),fields=sum(len(c['fields']) for c in SUPPLEMENTAL_CLASSES),
                                  alias_declarations=len(SUPPLEMENTAL_ALIAS_BRANCHES),
                                  alias_branches=sum(len(b) for b in SUPPLEMENTAL_ALIAS_BRANCHES.values()),
                                  resolved_type_names=len(SUPPLEMENTAL_TYPE_RESOLUTIONS)),
                assumptions={'name_only':0,'meaning_change':0})


# FBT draft 4: 旧styleだけを正本の契約宣言で具体化する。
DRAFT3_DENOMINATOR={key:_copy_tree(globals()[key]) for key in DENOMINATOR_KEYS}
DRAFT3_DENOMINATOR_SHA256=DENOMINATOR_SHA256
DRAFT3_TARGET_BY_ID={r['id']:r for r in DRAFT3_DENOMINATOR['TARGETS']}
DRAFT3_SUMMARY=_copy_tree(summary_counts())
DRAFT3_BRIDGES=_copy_tree(BRIDGES)
DRAFT3_SESSION_NOTE=_copy_tree(SESSION_NOTE)
DRAFT3_TEST_CHECKS={'test_target_ids_and_required_columns': '9b4a228a57ea409df8a06fd4d1bf6ade27a79693bfe6a6d35964acb3b77e231c', 'test_not_applicable_and_unresolved_cells_are_explicit': '4f206621d18353375ba35dd53465e06592a93794ce92018652b085bae93ee21b', 'test_rule_entry_and_target_references_exist': '3bc95e4ca061392126344666514c4c39c5ae9e3db3f9347198bfe01df3c0dc5a', 'test_paper_source_units_have_dispositions': 'f805d7c5b645d1324eae399c305d085a763122a2c02b191ea04e3ba93d63aa9f', 'test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap': '64209ae2b2113b49c97dc2c1bc2875c2552ed5810a6d27e51ad7d28c5c9eb976', 'test_denominator_was_not_changed_by_the_model_bridge': '2733c62df8c75cb8a33e650a739148a03aa893c6130e227ef13f46c06ba63d20', 'test_bridge_source_universe_independent_counts_and_selectors': '6cd010c6a863183fd0bcaa60862dbfc5d6b73584e343cdbc232b1476c7e13c27', 'test_every_bridge_item_has_exactly_one_disposition': 'b2c9e1cb516572475e9dbc7fcabd07bb208a0faadd1eb9e4906a7513971f19b2', 'test_numeric_remainders_and_unadopted_branches_not_promoted': 'ce33cee576d69273a7a66c57dbbd75b70b11c70ec404db428391a8d0dd7b7b98', 'test_supplemental_scope_holes_remain_separate_from_107_7_79': '7bddb16f3dee4eea45f48753fadb79882868386b0710d2ffd77fbbc65110f190', 'test_disagreement_is_reported_without_choosing_an_expected_type': 'ad6441b71c897ff01015ff52dd349d569ba454fbef12c2fb6c770b51cc370e01', 'test_data_module_has_no_model_or_implementation_import': 'e9edd0c72d82ad8c8052100d67d55b11f0f509e3af6305001c85a27b202be486', 'test_revision_accounts_for_every_original_affected_row_and_reports_unclosed': '47fa52ebacc2df7b76ae25706e56fcd2e239a11f8a321257787867aa3f0708c5', 'test_wire_contract_universe_is_counted_from_paper_and_every_declaration_has_target': '6d4c1857943277f973c55180194e1599392075b84e0cf6230941eb4385196a49', 'test_wire_nested_fields_nullable_and_union_branches_are_all_addressable': 'a1f0c9b40f085c6fdfa4d1e07e8de682d946fa8d3c02de83f3950cdbc07cb481', 'test_all_91_logical_rows_and_entire_wire_section_have_dispositions': 'b4c69f22efe9485b5fb4ad53714fbbdef11bb788296ddf2b7bcea9217fca230f', 'test_public_class_declarations_expand_fields_literals_unions_and_keep_unknown_types': '095d4646fb16314488e66d33059fa232696fcddcf7c83cd84cd282044e7f0fb5', 'test_d7_connections_are_conditions_and_observation_not_automatic_success': 'f080272e75eb2b069dd586b75a7c24709976643e70b45dd0779241a08c51eb9c', 'test_revision_preserves_all_bridge_sources_targets_checks_and_remainders': '092a9f6732bd42fd1531eab674d58a9fe3f4234691611825613d7da22eb0749c', 'test_revision3_retains_all_19_previous_checks_and_their_fixed_baselines': '3edbf4dad1930ed79746dd321d31ad3f90ecc9152cfdda1c7543b032a617f9c0', 'test_supplemental_alias_graph_matches_saved_declarations_and_declaration_time_binding': '43f5a496f334938ef1eb9f13e5eb4c16a4c33498a425e38f706039cada39391d', 'test_rate_declarations_and_all_14_previously_missing_names_have_concrete_targets': '08df505051b98ad46725cbc4d47a1ddbebd04b69afd4b799b150f5efbce1c39f', 'test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved': '42a578c8b5497a2fcbc194382c68d5ad943371831d9ec1232a5b4b3d93ab0839'}
LEGACY_CONTRACT_EXCERPTS={7: 'PREFERENCE = _ContractRef("sui.s4d.preference", "1")', 17: '    _Contract(ref=PREFERENCE,', 18: "        meaning='MODELが定めた好みの原記録。item={kind,rule:{name,version},args}、withdraw={kind,items:[PreferenceのRecord.id]}、style={kind,H_ns,gamma}。付箋は費用を足す。はがせるのは祖先の付箋だけ。紙はRecord.idの祖先グラフの末尾の強連結成分に残す',", 19: "        unit='H_nsは非負整数nsかnull、gammaは有限の非負数。P*は対数の確率',", 20: "        state_owner='sui.agent', persistence='因果の出来事。古い紙とはがした付箋も残す',", 21: "        failure='読めない本文・未知の約束・不正なwithdrawはPreferenceUnreadable。紙が複数残ればAmbiguousPreference。採用では印を保持し評価で例外にする',", 22: "        cancel='withdrawで祖先の付箋を名指す。本文の破棄をwithdrawとみなさない',", 23: "        redelivery='Record.idで一度。採用した範囲の実際の祖先関係から読み直す'),"}
LEGACY_CONTRACT_PROVENANCE={'path': 'src/sui/s4d_contracts.py', 'lines': 30, 'read_scope': '全文', 'sha256_lf': 'd5bfb44470aef5ac037333faa3f70ac932003707b8e738924fe7a768a341320f'}

LEGACY_STYLE_SCHEMA=dict(
    target='T.old_style',contract_name='sui.s4d.preference',version='1',body='Preference',branch='style',
    fields=(
        dict(name='kind',type="Literal['style']",presence='必須・非null',source=source('src/sui/s4d_contracts.py',18)),
        dict(name='H_ns',type='非負整数ns | null',presence='必須・null可（省略不可）',source=source('src/sui/s4d_contracts.py',19)),
        dict(name='gamma',type='有限の非負JSON数',presence='必須・非null',source=source('src/sui/s4d_contracts.py',19)),
    ),
    field_targets=tuple('T.old_style.field.'+n for n in ('kind','H_ns','gamma')),
    branch_targets=('T.old_style.branch.style','T.old_style.branch.H_ns.integer','T.old_style.branch.H_ns.null'),
    relation_targets=('T.old_style.import.null','T.old_style.import.float'),
    sources=(source('src/sui/s4d_contracts.py',7),source('src/sui/s4d_contracts.py',17,23),
             source(FA,82),source(FA,27),source(FA,16),source(FA,389)),
    presence='三つのキーが必須。未知・欠落・重複キーはV-01に従う。nullはH_nsだけ。',
    independent_of_new_style='旧styleにscopeキーを追加しない。旧gammaを新FStyle.gammaのR配列と同一視しない。',
    sibling_disposition='適用外: 同じ契約のitem/withdrawは正本18行にあるが、今回のT.old_styleはstyle枝だけ。兄弟枝の既存対象は変更しない。',
    state_owner='sui.agent',persistence='因果の出来事。古い紙も残す',
    failure='読めない本文等はPreferenceUnreadable、紙が複数残ればAmbiguousPreference。F-aの入口への変換はE-03。',
    execution='not_run',count_as_pass=False,
)
_row=TARGET_BY_ID['T.old_style']
_row.update(status='整理済み',issues=(),branch='style',role='MODEL',owner='sui.agent',
            presence=LEGACY_STYLE_SCHEMA['presence'],
            use='旧sui.s4d.preference/1のstyle枝はkind/H_ns/gamma。保存形は正本の宣言、取込みはF-a V-01/P-06に従う。新FStyleと別の保存形として保持。',
            evidence='src/sui/s4d_contracts.pyのPREFERENCE契約宣言とF-aの紙。実装から期待値を作らない。',
            negative='旧styleへscopeを加える、H_nsを省略する、H_nsを負数/boolへ、gammaを負数/非有限値へ変える。',
            nearest_legal='旧形 {kind:style,H_ns:null,gamma:1.0}。省略値・新scope・新R配列で代用しない。',
            related_targets=LEGACY_STYLE_SCHEMA['field_targets']+LEGACY_STYLE_SCHEMA['branch_targets']+LEGACY_STYLE_SCHEMA['relation_targets'],
            sources=_row['sources']+LEGACY_STYLE_SCHEMA['sources'],
            representation='旧sui.s4d.preference/1の保存宣言（style枝）。新FStyleの公開carrierとは別',
            resolution='G-LEGACY-STYLE解消: 正本18–19行で全キー・型・presenceを具体化。',
            execution='not_run',count_as_pass=False)
_root_rules=_row['rules'];_root_entries=_row['entries']
for _field in LEGACY_STYLE_SCHEMA['fields']:
    _row=_wire_add('T.old_style.field.'+_field['name'],'field','旧style',
                  refs=(_field['source'],)+LEGACY_STYLE_SCHEMA['sources'],fields=_field['name'],
                  branch='style',body='Preference',contract='sui.s4d.preference/1',role='MODEL',
                  presence=_field['presence'],value_type=_field['type'],
                  use='旧保存形の欄。'+_field['type']+'。V-01の未知・欠落キー拒否に従う。',
                  rules=_root_rules,entries=_root_entries,related=('T.old_style',),representation='旧styleの保存欄')
    _row['owner']='sui.agent'
    _row['negative']={'kind':'kindを未知の文字列にする。',
                      'H_ns':'H_nsを欠落/負整数/boolにする。nullと欠落を同一視しない。',
                      'gamma':'gammaを負数/非有限値/null/R配列にする。旧JSON数と新Rを混同しない。'}[_field['name']]
    _row['nearest_legal']={'kind':'kind=style。残りの二欄を同一に保つ。',
                           'H_ns':'H_ns=0またはnull。値域/枝に応じた最近傍を使う。',
                           'gamma':'gamma=0または有限の非負数。旧形の数を保持。'}[_field['name']]
for _suffix,_field,_value in (('style','kind',"Literal['style']"),('H_ns.integer','H_ns','非負整数ns'),('H_ns.null','H_ns','null')):
    _row=_wire_add('T.old_style.branch.'+_suffix,'branch','旧style.'+_field,
                  refs=LEGACY_STYLE_SCHEMA['sources'],fields=_field,branch=_value,body='Preference',
                  contract='sui.s4d.preference/1',role='MODEL',value_type=_value,
                  use='旧styleの宣言された枝。H_nsのnullは値であってキー省略ではない。',
                  rules=_root_rules,entries=_root_entries,related=('T.old_style.field.'+_field,),representation='旧保存形の枝')
    _row['owner']='sui.agent'
LEGACY_STYLE_IMPORTS=(
    dict(id='T.old_style.import.null',field='H_ns',input='旧H_ns=null',
         expected='one_step',source=source(FA,16),
         negative='旧nullを新しい白紙のunbounded_totalと混同する。',
         nearest_legal='同じ旧styleでH_ns=nullをone_stepとして取り込む。'),
    dict(id='T.old_style.import.float',field='gamma',input='旧gammaのbinary float',
         expected='そのbinary floatの正確な有理数（文字列経由で別の数にしない）',source=source(FA,27),
         negative='旧floatを文字列経由で有理数化し、別の数へ変える。',
         nearest_legal='同じ旧floatの正確な有理数を使う。尾切り/選択の閾値を加えない。'),
)
for _conversion in LEGACY_STYLE_IMPORTS:
    _row=_wire_add(_conversion['id'],'relation','旧styleの取込み',
                  refs=(_conversion['source'],)+LEGACY_STYLE_SCHEMA['sources'],
                  use=_conversion['input']+' → '+_conversion['expected'],rules=_root_rules,entries=_root_entries,
                  related=('T.old_style','T.old_style.field.'+_conversion['field']),representation='旧保存形から意味を読む関係')
    _row['owner']='sui.agent';_row['negative']=_conversion['negative'];_row['nearest_legal']=_conversion['nearest_legal']
    _row['count_as_pass']=False
TARGETS=tuple(_rows)
TARGET_BY_ID={r['id']:r for r in TARGETS}
LEGACY_STYLE_DISPOSITION=dict(
    target='T.old_style',issue=None,status='整理済み',classification='解消',
    confirmed='旧style={kind,H_ns,gamma}。H_nsは非負整数nsかnull、gammaは有限非負数。V-01/P-06の取込みと分けて列挙。',
    missing=NA,reason='正本のPREFERENCE宣言18–19行とF-a V-01/P-06/82行で具体化。',
    sources=LEGACY_STYLE_SCHEMA['sources'],related_targets=TARGET_BY_ID['T.old_style']['related_targets'],
    execution='not_run',count_as_pass=False,
)
GAPS['G-LEGACY-STYLE']=dict(classification='後で',status='解消',message=LEGACY_STYLE_DISPOSITION['confirmed'],sources=LEGACY_STYLE_SCHEMA['sources'])
GAPS['G-05']['message']='宣言追補で14型名を解決。旧styleの保存形も正本s4d_contracts.pyから具体化済み。'
for _registry in (G05_RESOLUTIONS,FBT01B_RESOLUTIONS):
    for _resolution in _registry:
        if _resolution['target']=='T.old_style':
            _resolution.update(after_status='整理済み',remaining_issues=(),
                               targets=TARGET_BY_ID['T.old_style']['related_targets'],
                               reason=LEGACY_STYLE_DISPOSITION['reason'],sources=TARGET_BY_ID['T.old_style']['sources'])
FBT01B_REMAINING=tuple(x for x in FBT01B_RESOLUTIONS if x['after_status'] in ('未決','未対応'))
FBT01B_UNCLOSED=tuple(x['target'] for x in FBT01B_REMAINING if set(x['remaining_issues'])<={'G-02','G-05','D-01'})
for _bridge in BRIDGES:
    _bridge['prerequisite_issues']=tuple(i for i in _bridge['prerequisite_issues'] if i!='G-LEGACY-STYLE')
REVISION4_FINDINGS=tuple(_copy_tree(f) for f in REVISION3_FINDINGS if f['id']!='G-LEGACY-STYLE')
CATALOG_LAYERS['legacy_style']='LEGACY_STYLE_SCHEMAは旧style枝の保存宣言。新FStyleへの同一視なし。'
SESSION_NOTE=dict(DRAFT3_SESSION_NOTE,
    artifact_version='FBT draft 4 / legacy style contract declaration',
    decision='T.old_styleを正本s4d_contracts.pyの7/17–23行とF-a V-01/P-06/82行から具体化。3欄・3枝・2取込み関係を追加。',
    unresolved='今回の旧style対象に未確認/未対応は残らない。既存G-01/Run codec/未採用対象は維持。',
    verification='tests/test_fb_targets.pyだけ25件通過 (0.68秒)。旧23件を保持: 20件はAST同一、3件は旧断言を第三稿へ保持して現在の断言を追加。2件追加。Python 3.12.10 / pytest 9.1.1。模型/実装試験はnot_run。',
    failed_attempts='なし。',
    reuse='有効: 第三稿の分母と自己点検23件を保存し、旧styleだけを正本に接続。',
    read_scope='src/sui/s4d_contracts.pyは全文30行、F-a紙16/27/82/389は該当部分。f.py/rate.py原文・内部・模型・既存試験期待値は未読。Webなし。',
    next='G-01/Run codecの既存保留を維持し、実装の段で一覧から試験を作る。')
DENOMINATOR_KEYS=DENOMINATOR_KEYS+('LEGACY_CONTRACT_PROVENANCE','LEGACY_CONTRACT_EXCERPTS','LEGACY_STYLE_SCHEMA','LEGACY_STYLE_IMPORTS')
DENOMINATOR_SHA256='dddb95fbb0a676110b23202fb407c22792a962a4cfd10cba0f3ffce8f8fc30fd'

def fourth_revision_summary():
    return dict(previous=DRAFT3_SUMMARY,current=summary_counts(),
                legacy_style=dict(before='未対応',after=TARGET_BY_ID['T.old_style']['status'],
                                  remaining_issues=TARGET_BY_ID['T.old_style']['issues'],
                                  added_fields=3,added_branches=3,added_relations=2,execution='not_run'),
                assumptions={'name_only':0,'meaning_change':0})


# FBT draft 5: v0.23。旧引用は提供されたv0.22写しへ固定し、新宣言と混ぜない。
DRAFT4_DENOMINATOR={key:_copy_tree(globals()[key]) for key in DENOMINATOR_KEYS}
DRAFT4_DENOMINATOR_SHA256=DENOMINATOR_SHA256
DRAFT4_TARGET_BY_ID={r['id']:r for r in DRAFT4_DENOMINATOR['TARGETS']}
DRAFT4_SUMMARY=_copy_tree(summary_counts())
DRAFT4_BRIDGES=_copy_tree(BRIDGES)
DRAFT4_SESSION_NOTE=_copy_tree(SESSION_NOTE)
DRAFT4_G01_IDS=tuple(r['id'] for r in TARGETS if any(i.startswith('G-01') for i in r['issues']))
FB22='scratchpad/関所F_Fb_今の約束_v0.22.md'

def _pin_v22(value):
    if isinstance(value,dict):
        if value.get('path')==FB:
            value['path']=FB22
        for item in value.values():
            _pin_v22(item)
    elif isinstance(value,(tuple,list)):
        for item in value:
            _pin_v22(item)

for _key in DENOMINATOR_KEYS:
    _pin_v22(globals()[_key])
for _value in (BRIDGES,BRIDGE_SOURCE_ITEMS,BRIDGE_RECIPES,RESOLVED_MISMATCHES,WIRE_PUBLIC_FIELD_COMPARISONS):
    _pin_v22(_value)
DRAFT4_TEST_SOURCE={'test_target_ids_and_required_columns': 'def test_target_ids_and_required_columns():\n    assert len(data.TARGETS) == len(data.TARGET_BY_ID)\n    for row in data.TARGETS:\n        assert REQUIRED_COLUMNS <= row.keys(), row["id"]\n        assert row["kind"] in KINDS\n        assert row["status"] in STATUSES\n        for key in REQUIRED_COLUMNS - {"issues"}:\n            assert row[key] is not None and row[key] != "", (row["id"], key)\n            if isinstance(row[key], str):\n                assert row[key].strip(), (row["id"], key)\n        assert row["rules"] and row["entries"] and row["sources"], row["id"]\n        if row["kind"] == "field":\n            assert row["field"] != data.NA\n        if row["kind"] == "branch":\n            assert row["branch"] != data.NA', 'test_not_applicable_and_unresolved_cells_are_explicit': 'def test_not_applicable_and_unresolved_cells_are_explicit():\n    for row in data.TARGETS:\n        for key in ("body", "contract", "branch", "field", "role", "domain",\n                    "run", "owner", "presence", "edges", "consumer"):\n            value = row[key]\n            assert value not in ("?", "TODO", "TBD", "N/A", "-"), (row["id"], key)\n            if value == data.NA:\n                assert value.startswith("適用外:"), (row["id"], key)\n            if value.startswith(("未決:", "未対応:")):\n                assert row["status"] in {"未決", "未対応", "未採用"}, row["id"]\n        if row["status"] in {"未決", "未対応"}:\n            assert row["issues"], row["id"]\n        assert set(row["issues"]) <= data.GAPS.keys()\n    # 未決/未対応は削除されず、整理済みとは別に数える。\n    counts = Counter(row["status"] for row in data.TARGETS)\n    assert counts["未決"] > 0 and counts["未対応"] > 0\n    assert sum(counts.values()) == len(data.TARGETS)', 'test_rule_entry_and_target_references_exist': 'def test_rule_entry_and_target_references_exist():\n    for row in data.TARGETS:\n        assert set(row["rules"]) <= data.RULES.keys(), row["id"]\n        assert set(row["entries"]) <= data.ENTRY_POINTS.keys(), row["id"]\n        assert set(row.get("related_targets", ())) <= data.TARGET_BY_ID.keys(), row["id"]\n        for ref in row["sources"]:\n            _assert_source(ref)\n    for registry in (data.RULES, data.ENTRY_POINTS):\n        for key, row in registry.items():\n            assert row["id"] == key\n            assert row["sources"]\n            for ref in row["sources"]:\n                _assert_source(ref)\n    assert len(data.COMPLETION_CONDITIONS) == 51\n    assert set(data.COMPLETION_CONDITIONS) <= data.RULES.keys()', 'test_paper_source_units_have_dispositions': 'def test_paper_source_units_have_dispositions():\n    units = data.SOURCE_ENUMERATION\n    assert len(units) == 168\n    assert len({unit["id"] for unit in units}) == len(units)\n    for unit in units:\n        _assert_source(unit["source"])\n        assert unit["disposition"] and unit["reason"]\n        assert unit["targets"]\n        assert set(unit["targets"]) <= data.TARGET_BY_ID.keys(), unit["id"]\n    assert {s["section"] for s in data.SECTION_DISPOSITIONS} == {\n        "§1", "§2-1", "§2-4-7", "§2-4-8", "§2-4-11", "§3", "§4",\n    }\n    assert len(data.VOCABULARY) == 36\n    assert {r["id"] for r in data.EXTERNAL_ROWS} == {f"R{i}" for i in range(1, 11)}\n    assert {r["id"] for r in data.USAGE_ROWS} == {f"B{i}" for i in range(1, 8)}', 'test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap': 'def test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap():\n    criteria = {c["id"]: c for c in data.ACCEPTANCE}\n    expected = {f"AC-{prefix}-{i:02}" for prefix in ("FB", "FA") for i in range(1, 6)}\n    expected |= {f"AC-SPINE-{i}" for i in range(1, 6)} | {"AC-STAR-01", "AC-STAR-02"}\n    assert criteria.keys() == expected\n    links = data.ACCEPTANCE_LINKS\n    for link in links:\n        assert link["acceptance"] in criteria\n        assert link["target"] in criteria[link["acceptance"]]["targets"]\n        target = data.TARGET_BY_ID[link["target"]]\n        assert link["rule"] in target["rules"] and link["rule"] in data.RULES\n        assert link["entry"] in target["entries"] and link["entry"] in data.ENTRY_POINTS\n        assert link["use"] and link["sources"]\n        assert link["execution"] == "not_run"\n    for id, criterion in criteria.items():\n        associated = [link for link in links if link["acceptance"] == id]\n        assert associated or criterion["unconnected"], id\n        assert {link["target"] for link in associated} == set(criterion["targets"]), id\n        if criterion["unconnected"]:\n            assert "紙に規則が無い" in criterion["unconnected"]\n            assert criterion["issue"] in data.GAPS\n    # 第一稿の未接続5件を記録から消さず、D7の根拠でのみ現在化する。\n    assert {c["id"] for c in data.DRAFT1_DENOMINATOR["ACCEPTANCE"] if c["unconnected"]} == {\n        "AC-FB-01", "AC-FB-03", "AC-FA-01", "AC-FA-03", "AC-STAR-01",\n    }\n    assert not any(c["unconnected"] or c["issue"] == "G-03" for c in data.ACCEPTANCE)\n    for criterion in data.ACCEPTANCE:\n        assert criterion["count_as_pass"] is False\n        assert criterion["automated_disposition"]\n    star = criteria["AC-STAR-01"]\n    assert star["verification_kind"] == "実装後の観察"\n    assert "試験の対象外" in star["automated_disposition"]\n    assert any(s["path"] == data.FB and s["first"] == 22 for s in star["sources"])\n    assert all(x["count_as_pass"] is False for x in links)', 'test_denominator_was_not_changed_by_the_model_bridge': 'def test_denominator_was_not_changed_by_the_model_bridge():\n    # 元のハッシュも検査する。紙の改訂を模型から分母を作り直す口実にしない。\n    old = json.dumps(data.DRAFT1_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()\n    assert hashlib.sha256(old).hexdigest() == data.DRAFT1_DENOMINATOR_SHA256\n    assert data.DRAFT1_DENOMINATOR_SHA256 == "4cbabdea70d8f841f889af9f3e36de3c1d714d415531378994355e1162a71b9e"\n    second = json.dumps(data.DRAFT2_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()\n    assert hashlib.sha256(second).hexdigest() == data.DRAFT2_DENOMINATOR_SHA256\n    assert data.DRAFT2_DENOMINATOR_SHA256 == "619d6f73934f39ca71a66fce5187dbc3c133a55b8657c3ffd3ee3b6ab47b85a2"\n    third = json.dumps(data.DRAFT3_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()\n    assert hashlib.sha256(third).hexdigest() == data.DRAFT3_DENOMINATOR_SHA256\n    assert data.DRAFT3_DENOMINATOR_SHA256 == "b5dd539a66d405caf89342a68e647a65e979ca5b7a9aa91cb4437e1bcc48cf46"\n    payload = {key: getattr(data, key) for key in data.DENOMINATOR_KEYS}\n    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()\n    assert hashlib.sha256(encoded).hexdigest() == data.DENOMINATOR_SHA256', 'test_bridge_source_universe_independent_counts_and_selectors': 'def test_bridge_source_universe_independent_counts_and_selectors():\n    items = data.BRIDGE_SOURCE_ITEMS\n    assert len({(x["group"], x["id"]) for x in items}) == len(items)\n    counts = Counter(x["group"] for x in items)\n    for group, expected in EXPECTED_COUNTS.items():\n        assert counts[group] == expected\n        assert data.BRIDGE_EXTRACTION["differences"][group] == 0\n    assert {x["id"] for x in items if x["group"] == "mutant_outside"} == EXPECTED_OUTSIDE_MUTANTS\n    for x in items:\n        _assert_source(x["source"])\n        if x["group"] in {"scene_b", "nested_scene_b"}:\n            assert x["scope_class"] == "b"\n        if x["group"] == "structural_a":\n            assert x["scope_class"] == "a"\n            assert x["implementation_scope"] == (data.STRUCTURAL_NUMERIC_REMAINDER,)', 'test_every_bridge_item_has_exactly_one_disposition': 'def test_every_bridge_item_has_exactly_one_disposition():\n    expected = {(x["group"], x["id"]) for x in data.BRIDGE_SOURCE_ITEMS}\n    actual = Counter((b["group"], b["source_id"]) for b in data.BRIDGES)\n    assert set(actual) == expected\n    assert set(actual.values()) == {1}\n    assert len({b["id"] for b in data.BRIDGES}) == len(data.BRIDGES)\n    for bridge in data.BRIDGES:\n        assert bridge["disposition"] in {"対応先あり", "消えた"}\n        if bridge["disposition"] == "対応先あり":\n            assert bridge["targets"] and bridge["verification_kinds"]\n            assert set(bridge["targets"]) <= data.TARGET_BY_ID.keys()\n            assert set(bridge["verification_kinds"]) <= CHECK_KINDS\n            assert bridge["recipes"] and set(bridge["recipes"]) <= data.BRIDGE_RECIPES.keys()\n        else:\n            assert bridge["disappearance_reason"]\n            assert not bridge["disappearance_reason"].startswith("適用外")\n        assert bridge["scope_to_preserve"] and bridge["branch_constraint"]\n        assert bridge["execution"] == "not_run"\n        assert bridge["readiness"] in {"未接続", "未採用"}\n        assert set(bridge["prerequisite_issues"]) <= data.GAPS.keys()', 'test_numeric_remainders_and_unadopted_branches_not_promoted': 'def test_numeric_remainders_and_unadopted_branches_not_promoted():\n    for bridge in data.BRIDGES:\n        if bridge["group"] == "structural_a":\n            assert bridge["scope_to_preserve"] == (data.STRUCTURAL_NUMERIC_REMAINDER,)\n        if "generation_draw" in bridge["recipes"]:\n            assert bridge["readiness"] == "未採用"\n            assert "T.external.R10" in bridge["targets"]\n        if bridge["group"] == "mutant_outside":\n            assert "変異" in bridge["verification_kinds"]\n    for recipe in data.BRIDGE_RECIPES.values():\n        assert set(recipe["targets"]) <= data.TARGET_BY_ID.keys()\n        assert set(recipe["checks"]) <= CHECK_KINDS and recipe["method"]', 'test_supplemental_scope_holes_remain_separate_from_107_7_79': 'def test_supplemental_scope_holes_remain_separate_from_107_7_79():\n    extra = {x["id"] for x in data.BRIDGE_SOURCE_ITEMS if x["group"] not in EXPECTED_COUNTS}\n    assert extra == {"SC-04-publish-PR-D", "SC-04-publish-DF-Ee",\n                     "SC-14-M3-Hung-D-cap1", "SC-14-M3-Hung-D-cap2"}', 'test_disagreement_is_reported_without_choosing_an_expected_type': 'def test_disagreement_is_reported_without_choosing_an_expected_type():\n    assert any(d["id"] == "D-01" and d["subject"] == "Instant.wall_ns" for d in data.DRAFT1_DENOMINATOR["MISMATCHES"])\n    assert not any(t["field"] == "wall_ns" for t in data.DRAFT1_DENOMINATOR["TARGETS"])\n    assert not data.MISMATCHES\n    assert {x["id"] for x in data.RESOLVED_MISMATCHES} == {"D-01"}\n    wall = data.TARGET_BY_ID["T.wire.type.Instant.field.wall_ns"]\n    assert wall["declared_type"] == "int" and wall["status"] == "整理済み"\n    assert "非null" in wall["presence"] and wall["domain"] == "U"\n    assert any(s["path"] == data.FA and s["first"] == 28 for s in wall["sources"])\n    assert any(s["path"] == "src/sui/clock.py" and s["first"] == 18 for s in wall["sources"])\n    assert len(data.TRANSFERRED_TEST_NAMES) == 36\n    assert sum(not t["targets"] for t in data.TRANSFERRED_TEST_NAMES) == 3\n    for item in data.TRANSFERRED_TEST_NAMES:\n        assert set(item["targets"]) <= data.TARGET_BY_ID.keys()\n        assert item["reason"] and item["status"]', 'test_data_module_has_no_model_or_implementation_import': 'def test_data_module_has_no_model_or_implementation_import():\n    tree = ast.parse(_path.read_text(encoding="utf-8"))\n    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]\n    assert len(imports) == 1\n    assert isinstance(imports[0], ast.ImportFrom) and imports[0].module == "collections"\n    assert all(t["execution"] == "not_run" for t in data.TARGETS)', 'test_revision_accounts_for_every_original_affected_row_and_reports_unclosed': 'def test_revision_accounts_for_every_original_affected_row_and_reports_unclosed():\n    old = {x["id"]: x for x in data.DRAFT1_DENOMINATOR["TARGETS"]}\n    expected = {id for id, row in old.items() if set(row["issues"]) & {"G-02", "G-05", "D-01"}}\n    assert len(expected) == 179\n    assert set(old) <= data.TARGET_BY_ID.keys()\n    actual = {x["target"]: x for x in data.FBT01B_RESOLUTIONS}\n    assert set(actual) == expected and len(actual) == len(data.FBT01B_RESOLUTIONS)\n    reported = {t for finding in data.REVISION4_FINDINGS for t in finding.get("targets", ())}\n    for id, resolution in actual.items():\n        current = data.TARGET_BY_ID[id]\n        assert resolution["before_status"] == old[id]["status"]\n        assert resolution["before_issues"] == tuple(old[id]["issues"])\n        assert resolution["after_status"] == current["status"]\n        assert set(resolution["remaining_issues"]) == set(current["issues"])\n        assert resolution["reason"] and resolution["sources"]\n        assert set(resolution["targets"]) <= data.TARGET_BY_ID.keys()\n        if current["status"] in {"未決", "未対応"}:\n            assert current["issues"]\n            assert all(issue in data.GAPS and data.GAPS[issue]["sources"] for issue in current["issues"])\n            if set(current["issues"]) <= {"G-02", "G-05", "D-01"}:\n                assert id in data.FBT01B_UNCLOSED and id in reported\n        else:\n            assert resolution["targets"]\n            assert not set(current["issues"]) & {"G-02", "G-05", "D-01"}\n    # 自己点検通過をFBT-01b完了と取り違えない。残件は消さず報告に出す。\n    assert set(data.DRAFT2_FBT01B_UNCLOSED) == {\n        "T.old_style", "T.missing.RateBudget", "T.missing.RateBudget.未列挙の欄と枝",\n        "T.capability_implementation",\n    } | {"T.missing." + name + suffix\n         for name in ("Selected", "NoDecision", "FEvaluation", "PredicateWork")\n         for suffix in ("", ".未列挙の欄と枝")}\n    assert not any("G-02" in r["issues"] for r in data.TARGETS)\n    assert not data.FBT01B_UNCLOSED\n    assert {id for id in data.DRAFT2_FBT01B_UNCLOSED\n            if data.DRAFT3_TARGET_BY_ID[id]["status"] != "整理済み"} == {"T.old_style"}\n    assert "T.old_style" in {t for f in data.REVISION3_FINDINGS for t in f.get("targets", ())}\n    assert all(data.TARGET_BY_ID[id]["status"] == "整理済み" for id in data.DRAFT2_FBT01B_UNCLOSED)\n    assert "T.old_style" not in reported', 'test_wire_contract_universe_is_counted_from_paper_and_every_declaration_has_target': 'def test_wire_contract_universe_is_counted_from_paper_and_every_declaration_has_target():\n    declared = {(x["category"], x["contract"]) for x in data.WIRE_DECLARED_SOURCE}\n    actual = {(x["category"], x["name"] + "/" + x["version"]) for x in data.WIRE_DECLARATIONS}\n    assert len(declared) == len(data.WIRE_DECLARED_SOURCE) == 34\n    assert actual == declared and len(actual) == len(data.WIRE_DECLARATIONS)\n    assert Counter(x["category"] for x in data.WIRE_DECLARED_SOURCE) == {"ledger": 22, "value": 10, "external": 2}\n    for declaration in data.WIRE_DECLARATIONS:\n        target = data.TARGET_BY_ID[declaration["target"]]\n        assert target["contract"] == declaration["name"] + "/" + declaration["version"]\n        _assert_source(declaration["source"])\n        if declaration["category"] == "ledger":\n            assert declaration["body"] in {"Observed", "Decided"}\n            assert declaration["role_category"] in {"MEMBRANE / FACT", "MODEL / FACT"}\n            assert declaration["parents"] != data.NA\n        elif declaration["category"] == "value":\n            assert declaration["body"] == declaration["parents"] == data.NA\n        else:\n            assert target["status"] == "未採用" and target["issues"] == ("G-04",)\n    assert len(data.EXISTING_COPIES) == 14\n    assert len({x["contract"] for x in data.EXISTING_COPIES}) == 14\n    for copy in data.EXISTING_COPIES:\n        assert copy["target"] in data.TARGET_BY_ID\n        assert copy["payload"] in data.WIRE_TYPES\n    bodies = {t["id"] for t in data.TARGETS if t["kind"] == "body"}\n    assert len(bodies) == 8\n    assert set(data.TARGET_BY_ID[data.FBT04_DISPOSITIONS["no_ninth_body_target"]]["related_targets"]) == bodies', 'test_wire_nested_fields_nullable_and_union_branches_are_all_addressable': 'def test_wire_nested_fields_nullable_and_union_branches_are_all_addressable():\n    for name, declaration in data.WIRE_TYPES.items():\n        prefix = "T.wire.type." + name\n        assert declaration["target"] == prefix\n        assert len(declaration["field_targets"]) == len(declaration["fields"])\n        assert len(declaration["branch_targets"]) == len(declaration["branches"])\n        for field, annotation in declaration["fields"]:\n            row = data.TARGET_BY_ID[prefix + ".field." + field]\n            assert row["declared_type"] == annotation and row["sources"]\n            if annotation.startswith("?"):\n                assert prefix + ".field." + field + ".branch.null" in data.TARGET_BY_ID\n                assert prefix + ".field." + field + ".branch.value" in data.TARGET_BY_ID\n        for branch, payload in declaration["branches"]:\n            row = data.TARGET_BY_ID[prefix + ".branch." + branch]\n            assert row["declared_type"] == payload\n            if payload == "◆G-01":\n                assert row["status"] == "未決" and row["issues"] == ("G-01",)\n        assert set(declaration["type_references"]) <= data.TARGET_BY_ID.keys()\n    assert len(data.WIRE_TYPES["Desc<Args>"]["fields"]) == 13\n    assert len(data.WIRE_TYPES["SegmentItem"]["branches"]) == 8\n    assert len(data.WIRE_TYPES["WaitingPayload"]["fields"]) == 7\n    assert len(data.WIRE_TYPES["SegmentBinding"]["fields"]) == 8\n    assert {b for b, _ in data.WIRE_TYPES["DrawOutcome"]["branches"]} == {"value", "failure", "unknown"}\n    assert dict(data.WIRE_TYPES["Gap"]["fields"])["sequence_range"] == "[first:int,stop:int]"\n    assert tuple(f for f, _ in data.WIRE_TYPES["Verification"]["fields"]) == ("request", "report")\n    assert tuple(f for f, _ in data.WIRE_TYPES["Selection"]["fields"]) == ("evaluated",)\n    assert len(data.WORK_PURPOSE_ARGS) == 8', 'test_all_91_logical_rows_and_entire_wire_section_have_dispositions': 'def test_all_91_logical_rows_and_entire_wire_section_have_dispositions():\n    assert len(data.LOGICAL_MAPPING) == 91\n    assert Counter(x["group"] for x in data.LOGICAL_MAPPING) == {"E0": 8, "REFERENCE": 39, "CMP": 24, "PATH": 20}\n    expected_lines = set(range(2367, 2375)) | set(range(2382, 2421)) | set(range(2428, 2452)) | set(range(2461, 2481))\n    assert {x["source"]["first"] for x in data.LOGICAL_MAPPING} == expected_lines\n    assert len({x["id"] for x in data.LOGICAL_MAPPING}) == 91\n    for mapping in data.LOGICAL_MAPPING:\n        assert mapping["target"] in data.TARGET_BY_ID\n        assert mapping["targets"] and set(mapping["targets"]) <= data.TARGET_BY_ID.keys()\n        assert mapping["disposition"]\n    assert {x["line"] for x in data.WIRE_SOURCE_COVERAGE} == set(data.WIRE_SECTION_LINES) == set(range(2005, 2598))\n    for unit in data.WIRE_SOURCE_COVERAGE:\n        assert unit["reason"]\n        assert unit["targets"] or unit["reason"].startswith("適用外:")\n        assert set(unit["targets"]) <= data.TARGET_BY_ID.keys()', 'test_public_class_declarations_expand_fields_literals_unions_and_keep_unknown_types': 'def test_public_class_declarations_expand_fields_literals_unions_and_keep_unknown_types():\n    assert len(data.PUBLIC_CLASS_DECLARATIONS) == data.REVISION2_SPEC["public_classes"] == 134\n    assert sum(len(x["fields"]) for x in data.PUBLIC_CLASS_DECLARATIONS) == data.REVISION2_SPEC["public_fields"] == 548\n    for declaration in data.PUBLIC_CLASS_DECLARATIONS:\n        prefix = "T.public." + declaration["name"]\n        assert prefix in data.TARGET_BY_ID\n        assert not declaration["name"].startswith("_")\n        assert declaration["docstring"]\n        root = data.TARGET_BY_ID[prefix]\n        assert tuple(root["unresolved_type_closure"]) == data.PUBLIC_CLOSURE_GAPS[declaration["name"]]\n        if root["unresolved_type_closure"]:\n            assert root["status"] == "未対応" and root["issues"] == ("G-05",)\n        for field in declaration["fields"]:\n            id = prefix + ".field." + field["name"]\n            row = data.TARGET_BY_ID[id]\n            assert row["declared_type"] == field["type"]\n            assert row["sources"][0]["first"] == field["line"]\n            unknown = set(field["references"]) & set(data.PUBLIC_UNRESOLVED_NAMES)\n            assert set(row["unresolved_type_references"]) == unknown\n            if unknown:\n                assert row["status"] == "未対応" and row["issues"] == ("G-05",)\n            for index, value in enumerate(field["literal_values"]):\n                assert data.TARGET_BY_ID[id + ".literal." + str(index)]["branch"] == repr(value)\n    for name, field, unions in data.PUBLIC_ANNOTATION_UNIONS:\n        for index, (path, member) in enumerate(unions):\n            row = data.TARGET_BY_ID["T.public." + name + ".field." + field + ".union." + str(index)]\n            assert row["branch"] == member and path in row["use"]\n    for comparison in data.WIRE_PUBLIC_FIELD_COMPARISONS:\n        assert comparison["paper_fields"] == comparison["public_fields"], comparison["name"]', 'test_d7_connections_are_conditions_and_observation_not_automatic_success': 'def test_d7_connections_are_conditions_and_observation_not_automatic_success():\n    criteria = {c["id"]: c for c in data.ACCEPTANCE}\n    for id in ("AC-FB-01", "AC-FA-01", "AC-SPINE-1"):\n        assert "T.d7.perception" in criteria[id]["targets"]\n    for id in ("AC-FB-03", "AC-FA-03", "AC-SPINE-2", "AC-SPINE-3"):\n        assert "T.d7.two_starts" in criteria[id]["targets"]\n    assert "T.d7.display" in criteria["AC-STAR-01"]["targets"]\n    assert {"L-DERIVE", "背骨①"} <= set(data.TARGET_BY_ID["T.d7.perception"]["rules"])\n    assert {"INV-2.e", "背骨②"} <= set(data.TARGET_BY_ID["T.d7.two_starts"]["rules"])\n    assert data.TARGET_BY_ID["T.d7.display"]["count_as_pass"] is False', 'test_revision_preserves_all_bridge_sources_targets_checks_and_remainders': 'def test_revision_preserves_all_bridge_sources_targets_checks_and_remainders():\n    assert _restore_original_source_positions(data.BRIDGE_SOURCE_ITEMS) == _restore_original_source_positions(data.DRAFT1_SOURCE_ITEMS)\n    assert len(data.BRIDGES) == len(data.DRAFT1_BRIDGES) == 197\n    for before, after in zip(data.DRAFT1_BRIDGES, data.BRIDGES):\n        assert tuple(before["prerequisite_issues"]) == after["previous_prerequisite_issues"]\n        for key in before.keys() - {"prerequisite_issues"}:\n            assert _restore_original_source_positions(before[key]) == _restore_original_source_positions(after[key]), (before["id"], key)\n        assert after["execution"] == "not_run"', 'test_revision3_retains_all_19_previous_checks_and_their_fixed_baselines': 'def test_revision3_retains_all_19_previous_checks_and_their_fixed_baselines():\n    functions = {node.name: node for node in ast.parse(Path(__file__).read_text(encoding="utf-8")).body\n                 if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}\n    amended = {"test_denominator_was_not_changed_by_the_model_bridge",\n               "test_revision_accounts_for_every_original_affected_row_and_reports_unclosed"}\n    assert len(data.DRAFT2_TEST_CHECKS) == 19\n    assert data.DRAFT2_TEST_CHECKS.keys() <= functions.keys()\n    for name, digest in data.DRAFT2_TEST_CHECKS.items():\n        if name not in amended:\n            current = _compact_ast_dump(functions[name]).encode()\n            assert hashlib.sha256(current).hexdigest() == digest, name\n    # 上の2件は旧断言を削らず第二稿へ適用し、現在の閉じる条件の断言を追加。\n    assert len(data.DRAFT2_DENOMINATOR["TARGETS"]) == 3047\n    assert set(data.DRAFT2_DENOMINATOR) == set(data.DRAFT2_DENOMINATOR_KEYS)\n    assert Counter(r["status"] for r in data.DRAFT2_DENOMINATOR["TARGETS"]) == {\n        "整理済み": 2728, "未決": 56, "未対応": 147, "未採用": 116,\n    }\n    assert data.ACCEPTANCE == data.DRAFT2_DENOMINATOR["ACCEPTANCE"]\n    assert data.ACCEPTANCE_LINKS == data.DRAFT2_DENOMINATOR["ACCEPTANCE_LINKS"]\n    assert len(data.BRIDGES) == len(data.DRAFT2_BRIDGES) == 197\n    for before, after in zip(data.DRAFT2_BRIDGES, data.BRIDGES):\n        for key in before.keys() - {"prerequisite_issues"}:\n            assert before[key] == after[key], (before["id"], key)\n        assert "G-05" not in after["prerequisite_issues"]', 'test_supplemental_alias_graph_matches_saved_declarations_and_declaration_time_binding': 'def test_supplemental_alias_graph_matches_saved_declarations_and_declaration_time_binding():\n    nodes = data.SUPPLEMENTAL_NODE_BY_KEY\n    assert len(nodes) == len(data.SUPPLEMENTAL_DECLARATION_NODES) == 45\n    assert Counter(n["kind"] for n in nodes.values()) == {"class": 29, "alias": 12, "literal": 4}\n    for key, node in nodes.items():\n        assert key == node["key"]\n        raw = data.DECLARATION_EXCERPTS[node["line"]].split(": ", 1)[1]\n        assert data.SUPPLEMENTAL_NODE_TARGETS[key] in data.TARGET_BY_ID\n        if node["kind"] == "class":\n            assert raw == node["header"]\n            assert node["name"] in data.PUBLIC_CLASS_BY_NAME\n            assert data.PUBLIC_CLASS_BY_NAME[node["name"]]["line"] == node["upstream_line"]\n            continue\n        declaration = ast.parse(raw).body[0]\n        rhs = declaration.value\n        assert ast.dump(rhs) == ast.dump(ast.parse(node["rhs"], mode="eval").body)\n        root = data.TARGET_BY_ID[data.SUPPLEMENTAL_NODE_TARGETS[key]]\n        assert root["declared_type"] == node["rhs"]\n        if node["kind"] == "literal":\n            assert isinstance(rhs, ast.Subscript) and rhs.value.id == "_Literal"\n            values = rhs.slice.elts if isinstance(rhs.slice, ast.Tuple) else [rhs.slice]\n            assert tuple(ast.literal_eval(value) for value in values) == node["values"]\n            assert not node["references"]\n        else:\n            names = [n.id for n in ast.walk(rhs) if isinstance(n, ast.Name)]\n            # AST walkの順番でなく、各参照名の直前の宣言で固定する。\n            expected = set()\n            for name in names:\n                prior = [n for n in nodes.values() if n["name"] == name and n["line"] < node["line"]]\n                assert prior, (key, name)\n                expected.add(max(prior, key=lambda n: n["line"])["key"])\n            assert set(node["references"]) == expected, key\n        leaves = data.SUPPLEMENTAL_ALIAS_BRANCHES[key]\n        assert leaves\n        actual_leaves = Counter((leaf["kind"], leaf["value"]) for leaf in leaves)\n        if node["kind"] == "literal":\n            expected_leaves = Counter(("literal", value) for value in node["values"])\n        else:\n            expected_leaves = Counter()\n            for ref in node["references"]:\n                child = nodes[ref]\n                if child["kind"] == "class":\n                    expected_leaves[("class", child["name"])] += 1\n                else:\n                    expected_leaves.update((leaf["kind"], leaf["value"])\n                                           for leaf in data.SUPPLEMENTAL_ALIAS_BRANCHES[ref])\n        assert actual_leaves == expected_leaves, key\n        for index, leaf in enumerate(leaves):\n            bid = data.SUPPLEMENTAL_NODE_TARGETS[key] + ".branch." + str(index)\n            branch = data.TARGET_BY_ID[bid]\n            assert bid in root["related_targets"]\n            assert leaf["path"][0] == key and leaf["path"][-1] == leaf["declaration"]\n            for parent, child in zip(leaf["path"], leaf["path"][1:]):\n                assert child in nodes[parent]["references"]\n            terminal = nodes[leaf["declaration"]]\n            if leaf["kind"] == "class":\n                assert terminal["kind"] == "class" and leaf["value"] == terminal["name"]\n                assert leaf["target"] in branch["related_targets"]\n            else:\n                assert leaf["value"] in terminal["values"]\n            assert branch["declared_type"] == leaf["value"]\n            assert {s["first"] for s in branch["sources"] if s["path"] == data.DECLARATIONS_PATH} == {\n                nodes[p]["line"] for p in leaf["path"]}\n    counts = {name: len(data.SUPPLEMENTAL_ALIAS_BRANCHES[key]) for name, key in data.SUPPLEMENTAL_ALIAS_EXPORTS.items()}\n    assert counts == {"NoDecisionReason": 19, "CapabilityKind": 16, "FMathInputV1": 3, "FMathInputV2": 4,\n                      "FMathCallArgsV1": 10, "FMathCallArgsV2": 11, "FMathCallV1": 1,\n                      "FMathClaimV1": 10, "FMathClaimV2": 12, "FMathOpV1": 14, "FMathOpV2": 16, "FMathOp": 16}\n    assert sum(len(v) for v in data.SUPPLEMENTAL_ALIAS_BRANCHES.values()) == 169\n    exports = {name: {leaf["value"] for leaf in data.SUPPLEMENTAL_ALIAS_BRANCHES[key]}\n               for name, key in data.SUPPLEMENTAL_ALIAS_EXPORTS.items()}\n    assert exports["FMathOpV2"] - exports["FMathOpV1"] == {"legacy_bridge_prepare", "legacy_bridge"}\n    assert exports["FMathCallArgsV1"] - exports["FMathCallArgsV2"] == {"FPreflightCallArgs"}\n    assert exports["FMathCallArgsV2"] - exports["FMathCallArgsV1"] == {"FPreflightFactsCallArgs", "FLegacyBridgeCallArgs"}\n    assert exports["FMathCallV1"] == {"FMathCall"}', 'test_rate_declarations_and_all_14_previously_missing_names_have_concrete_targets': 'def test_rate_declarations_and_all_14_previously_missing_names_have_concrete_targets():\n    expected = {"RationalInterval": {"lower": "_Fraction", "upper": "_Fraction"},\n                "RateBudget": {"tolerance": "_Fraction", "max_cells": "int", "max_terms": "int", "max_refinements": "int"}}\n    assert len(data.SUPPLEMENTAL_CLASSES) == 2\n    assert set(data.SUPPLEMENTAL_TYPE_RESOLUTIONS) == set(data.DRAFT2_PUBLIC_UNRESOLVED_NAMES)\n    assert len(data.SUPPLEMENTAL_TYPE_RESOLUTIONS) == 14 and not data.PUBLIC_UNRESOLVED_NAMES\n    assert any(i["line"] == 1763 and i["declaration"] == "from fractions import Fraction as _Fraction"\n               for i in data.SUPPLEMENTAL_IMPORT_DECLARATIONS)\n    for declaration in data.SUPPLEMENTAL_CLASSES:\n        name = declaration["name"]\n        assert {f["name"]: f["type"] for f in declaration["fields"]} == expected[name]\n        resolution = data.SUPPLEMENTAL_TYPE_RESOLUTIONS[name]\n        root = data.TARGET_BY_ID[resolution["target"]]\n        assert tuple(root["related_targets"]) == resolution["fields"]\n        assert len(resolution["fields"]) == len(expected[name])\n        for field in declaration["fields"]:\n            text = data.DECLARATION_EXCERPTS[field["line"]].strip()\n            assert text == field["name"] + ": " + field["type"]\n            target = data.TARGET_BY_ID[resolution["target"] + ".field." + field["name"]]\n            assert target["declared_type"] == field["type"]\n            assert target["sources"][0] == data.source(data.DECLARATIONS_PATH, field["line"])\n    for name, resolution in data.SUPPLEMENTAL_TYPE_RESOLUTIONS.items():\n        assert resolution["target"] in data.TARGET_BY_ID\n        assert resolution["fields"] or resolution["branches"]\n        assert set(resolution["fields"] + resolution["branches"]) <= data.TARGET_BY_ID.keys()\n        assert data.TARGET_BY_ID[resolution["target"]]["status"] == "整理済み"\n    for name, formerly_missing in data.DRAFT2_DENOMINATOR["PUBLIC_CLOSURE_GAPS"].items():\n        root = data.TARGET_BY_ID["T.public." + name]\n        assert not root["unresolved_type_closure"]\n        for missing in formerly_missing:\n            assert data.SUPPLEMENTAL_TYPE_RESOLUTIONS[missing]["target"] in root["related_targets"]\n    for old in data.DRAFT2_DENOMINATOR["TARGETS"]:\n        for missing in old.get("unresolved_type_references", ()):\n            assert data.SUPPLEMENTAL_TYPE_RESOLUTIONS[missing]["target"] in data.TARGET_BY_ID[old["id"]]["related_targets"]', 'test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved': 'def test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved():\n    old = {row["id"]: row for row in data.DRAFT2_DENOMINATOR["TARGETS"]}\n    expected = {id for id, row in old.items() if "G-05" in row["issues"]}\n    assert len(expected) == 110 and expected == set(data.DRAFT2_G05_IDS)\n    resolutions = {r["target"]: r for r in data.G05_RESOLUTIONS}\n    assert len(resolutions) == len(data.G05_RESOLUTIONS) == 110 and set(resolutions) == expected\n    assert not any("G-05" in row["issues"] for row in data.TARGETS)\n    assert sum(data.DRAFT3_TARGET_BY_ID[id]["status"] == "整理済み" for id in expected) == 109\n    assert {id for id in expected if data.DRAFT3_TARGET_BY_ID[id]["status"] != "整理済み"} == {"T.old_style"}\n    assert sum(data.TARGET_BY_ID[id]["status"] == "整理済み" for id in expected) == 110\n    for id, resolution in resolutions.items():\n        row = data.TARGET_BY_ID[id]\n        assert resolution["before_status"] == old[id]["status"] == "未対応"\n        assert resolution["before_issues"] == old[id]["issues"]\n        assert resolution["after_status"] == row["status"]\n        assert resolution["remaining_issues"] == row["issues"]\n        assert resolution["sources"] and resolution["reason"] and resolution["targets"]\n        assert resolution["execution"] == "not_run" and resolution["count_as_pass"] is False\n        assert any(s["path"] == data.DECLARATIONS_PATH for s in resolution["sources"])\n        if id != "T.old_style":\n            assert resolution["resolved_names"]\n            for name in resolution["resolved_names"]:\n                assert data.SUPPLEMENTAL_TYPE_RESOLUTIONS[name]["target"] in resolution["targets"]\n    remaining = data.DRAFT3_TARGET_BY_ID["T.old_style"]\n    assert remaining["status"] == "未対応" and remaining["issues"] == ("G-LEGACY-STYLE",)\n    assert "資料で未確認" in remaining["use"]\n    assert data.LEGACY_STYLE_DISPOSITION["count_as_pass"] is False\n    assert any(s["path"] == data.FA and s["first"] == 82 for s in remaining["sources"])\n    assert any(s["path"] == data.DECLARATIONS_PATH and s["first"] == 759 and s["last"] == 769\n               for s in remaining["sources"])\n    assert any(f["id"] == "G-LEGACY-STYLE" and f["targets"] == ("T.old_style",) for f in data.REVISION3_FINDINGS)\n    assert not any(t["id"].startswith("T.old_style.") for t in data.DRAFT3_DENOMINATOR["TARGETS"])\n    assert data.TARGET_BY_ID["T.old_style"]["status"] == "整理済み"\n    assert not data.TARGET_BY_ID["T.old_style"]["issues"]\n    assert {id for id in old if id not in expected} <= data.TARGET_BY_ID.keys()\n    for id in old.keys() - expected:\n        assert old[id] == data.TARGET_BY_ID[id], id', 'test_legacy_style_matches_contract_shape_and_keeps_import_semantics_separate': 'def test_legacy_style_matches_contract_shape_and_keeps_import_semantics_separate():\n    schema = data.LEGACY_STYLE_SCHEMA\n    assert schema["contract_name"] == "sui.s4d.preference" and schema["version"] == "1"\n    assert schema["body"] == "Preference" and schema["branch"] == "style"\n    assert \'PREFERENCE = _ContractRef("sui.s4d.preference", "1")\' in data.LEGACY_CONTRACT_EXCERPTS[7]\n    assert "style={kind,H_ns,gamma}" in data.LEGACY_CONTRACT_EXCERPTS[18]\n    assert "H_nsは非負整数nsかnull、gammaは有限の非負数" in data.LEGACY_CONTRACT_EXCERPTS[19]\n    assert {f["name"]: f["type"] for f in schema["fields"]} == {\n        "kind": "Literal[\'style\']", "H_ns": "非負整数ns | null", "gamma": "有限の非負JSON数"}\n    assert len(schema["field_targets"]) == len(schema["branch_targets"]) == 3\n    assert len(schema["relation_targets"]) == 2\n    root = data.TARGET_BY_ID["T.old_style"]\n    assert root["status"] == "整理済み" and not root["issues"]\n    assert root["body"] == "Preference" and root["contract"] == "sui.s4d.preference/1"\n    assert root["owner"] == "sui.agent" and root["branch"] == "style"\n    assert root["execution"] == "not_run" and root["count_as_pass"] is False\n    assert set(root["related_targets"]) == set(schema["field_targets"] + schema["branch_targets"] + schema["relation_targets"])\n    for field in schema["fields"]:\n        row = data.TARGET_BY_ID["T.old_style.field." + field["name"]]\n        assert row["declared_type"] == field["type"]\n        assert row["presence"] == field["presence"] and "必須" in row["presence"]\n        assert field["source"] in row["sources"]\n        assert row["rules"] == root["rules"] and row["entries"] == root["entries"]\n    assert "null可" in data.TARGET_BY_ID["T.old_style.field.H_ns"]["presence"]\n    assert "非null" in data.TARGET_BY_ID["T.old_style.field.gamma"]["presence"]\n    imports = {item["field"]: item for item in data.LEGACY_STYLE_IMPORTS}\n    assert imports["H_ns"]["expected"] == "one_step" and imports["H_ns"]["source"] == data.source(data.FA, 16)\n    assert "binary floatの正確な有理数" in imports["gamma"]["expected"]\n    assert imports["gamma"]["source"] == data.source(data.FA, 27)\n    for item in imports.values():\n        row = data.TARGET_BY_ID[item["id"]]\n        assert item["source"] in row["sources"] and item["expected"] in row["use"]\n        assert row["negative"] == item["negative"] and row["nearest_legal"] == item["nearest_legal"]\n    assert "scope" not in {f["name"] for f in schema["fields"]}\n    assert "旧gammaを新FStyle.gammaのR配列と同一視しない" in schema["independent_of_new_style"]\n    assert data.GAPS["G-LEGACY-STYLE"]["status"] == "解消"\n    assert not any("G-LEGACY-STYLE" in row["issues"] for row in data.TARGETS)\n    assert not any(f["id"] == "G-LEGACY-STYLE" for f in data.REVISION4_FINDINGS)', 'test_revision4_preserves_23_checks_and_changes_only_old_style_and_its_children': 'def test_revision4_preserves_23_checks_and_changes_only_old_style_and_its_children():\n    functions = {node.name: node for node in ast.parse(Path(__file__).read_text(encoding="utf-8")).body\n                 if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}\n    amended = {"test_denominator_was_not_changed_by_the_model_bridge",\n               "test_revision_accounts_for_every_original_affected_row_and_reports_unclosed",\n               "test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved"}\n    assert len(data.DRAFT3_TEST_CHECKS) == 23 and data.DRAFT3_TEST_CHECKS.keys() <= functions.keys()\n    for name, digest in data.DRAFT3_TEST_CHECKS.items():\n        if name not in amended:\n            assert hashlib.sha256(_compact_ast_dump(functions[name]).encode()).hexdigest() == digest, name\n    assert len(data.DRAFT3_DENOMINATOR["TARGETS"]) == 3240\n    for id, old in data.DRAFT3_TARGET_BY_ID.items():\n        if id != "T.old_style":\n            assert data.TARGET_BY_ID[id] == old, id\n    added = set(data.TARGET_BY_ID) - data.DRAFT3_TARGET_BY_ID.keys()\n    assert added == set(data.LEGACY_STYLE_SCHEMA["field_targets"] + data.LEGACY_STYLE_SCHEMA["branch_targets"]\n                        + data.LEGACY_STYLE_SCHEMA["relation_targets"])\n    assert len(added) == 8\n    assert Counter(data.TARGET_BY_ID[id]["kind"] for id in added) == {"field": 3, "branch": 3, "relation": 2}\n    for key in ("ACCEPTANCE", "ACCEPTANCE_LINKS", "RULES", "ENTRY_POINTS", "MISMATCHES"):\n        assert getattr(data, key) == data.DRAFT3_DENOMINATOR[key]\n    assert data.BRIDGES == data.DRAFT3_BRIDGES\n    before = Counter(r["status"] for r in data.DRAFT3_DENOMINATOR["TARGETS"])\n    after = Counter(r["status"] for r in data.TARGETS)\n    assert after["整理済み"] == before["整理済み"] + 9\n    assert after["未対応"] == before["未対応"] - 1\n    assert after["未決"] == before["未決"] and after["未採用"] == before["未採用"]'}
V23_PROVENANCE={'version': 'v0.23', 'lines': 3205, 'sha256_lf': 'a5c21962402bae36caaf23a2d4b48b26f19bf8b97d5f6255e39d18118b62efb3', 'archive_path': 'scratchpad/関所F_Fb_今の約束_v0.22.md', 'archive_sha256_lf': '72bfe382a80675166772eb91c4c816503bce5472c0c47639cd4c233e3151b5a9', 'read_scope': '§2-5-19 2582–3078全文、関連差分・引用先の該当部分。v0.22写しは差分照合用。'}
V23_SECTION_LINES={2582: '#### 2-5-19. finite_update/2 の意味と認証', 2583: '', 2584: '本節は、保存の形に残した G-01 の意味を定める (v0.23。Codex `sui-fb-update2` 1〜3 通目の下書きに Claude の決定と修正を入れた。**独立の点検は未**。本節の `B:n` は v0.22 の行番号、`A:n` は F-a の紙、`P:n` は ROADMAP)。宣言・計算・証明・認証・採用は別の段である。ここに契約を書いたことを実装の存在・認証成功・実取得の証拠にしない。', 2585: '', 2586: '`finite_update/2` は新しい不変の registry へ追加する。旧 factory、旧 `/1` の宣言・実装 identity・dispatch・Binding の Attempt 条件を変えない。数学の和・積・正規化の共通部分を共有し、読み方・証明・参照の展開・registry の構成を版で分ける。', 2587: '', 2588: '以下の `R` は A:27 の正準な厳密有理数、`Digest` は契約が指定する正準内容の digest、`ProofRef` は既存の `{name,version,args}`。`Point` と `Ref` は交換しない。記載した全欄以外を暗黙に受け取らず、nullable は `?` を付した欄だけとする。入れ子の `ContractValue`・`MethodCall` の意味も、指定契約で閉じる。', 2589: '', 2590: '##### 19-1. 数値射影と適用済みの出来事', 2591: '', 2592: '**決定。** モデルの読み方・生成の宣言から数値射影を解く。更新のベイズの数学と、原報告を読む宣言を独立にする。同じ生成過程に属する証拠は、既適用の出来事と新しい出来事の連言で条件づける。', 2593: '', 2594: '〔v0.23 M07 の決定 (Claude、技術): 適用済みの状態は**主張の述語の連言そのもの**で持つ。時間の原子の集合で覚える形は到着なしだけに効く圧縮で、一般の件数の主張では十分統計量にならない (P1)。反例: 二つの原子にまたがる `N(I1)+N(I2)=1` と `=0` は同じ原子集合 `{I1,I2}` になり、事後が `(1,0)` と `(0,1)` に分かれる。細分と、連言を満たす行の集合は (法則, 述語) から作り直せる導出物で、状態に持たない。〕', 2595: '', 2596: '**要求と読み方の宣言。**', 2597: '', 2598: '```', 2599: 'sui.f.finite_update/2', 2600: 'args = {', 2601: '  model: Point,', 2602: '  previous_result: ?Point,', 2603: '  observations: List[ObservationUse]', 2604: '}', 2605: 'ObservationUse = {binding: Point, reading: Point}', 2606: 'output_contract = sui.f.finite_update_result/1', 2607: 'algorithm_draws = []', 2608: '', 2609: 'sui.f.observation_plan/2', 2610: 'value = {', 2611: '  model: Point,', 2612: '  projection: MethodCall,', 2613: '  generation: MethodCall', 2614: '}', 2615: '```', 2616: '', 2617: '`reading` は `observation_plan/2` の Point。独立の Prediction / MODEL / PREDICTION として保存する。`about` は対象 model、`basis` は model と、projection/generation の型つき宣言が直接必要とする参照。親は必要な出来事の `Front(Ev(...))` とし、Prediction を因果の親へ昇格させない。', 2618: '', 2619: '`binding` は既存の `segment_binding/1`。plan.model と Q.args.model が一致し、B.reading_contract と plan.projection.contract の名前・版が一致することを要求する。B は原報告と区間の対応・認証であり、特定の読み方の args には結ばない (同じ B を別の読み方で読める。読み方はモデルの生成の宣言の側)。projection・generation の全 args は Q が指す reading の Point の内容として、実呼出し・再計算・認証 (§19-9 の call_digest・closure_digest) に固定する。名前・版の一致を args の一致の代わりにしない〔v0.23 FB23-R03〕。宣言が一つだけでも、その意味・版・参照用途を数学から独立に固定する。', 2620: '', 2621: '縦の一本の具体射影を次とする。', 2622: '', 2623: '```', 2624: 'sui.fb.finite_segment_projection/1', 2625: 'args = {', 2626: '  frame: ?FrameProjection,', 2627: '  claims: List[ClaimProjection],', 2628: '  time_projection: MethodCall', 2629: '}', 2630: 'FrameProjection = {', 2631: '  measurement_contract: ContractRef,', 2632: '  kernel: KernelRef,', 2633: '  cells: List[ProjectionCell]', 2634: '}', 2635: 'ProjectionCell = {', 2636: '  id: str,', 2637: '  observation: ContractValue,', 2638: '  outcomes: Set[str]', 2639: '}', 2640: 'ClaimProjection = {', 2641: '  meaning: ContractRef,', 2642: '  law: Point,', 2643: '  channel: str', 2644: '}', 2645: '```', 2646: '', 2647: '各 ProjectionCell の observation は、measurement_contract と projection 契約が定める閉じた値。自由 JSON の一致を数値の意味にしない。outcomes は存在する outcome の非空集合で、原報告から cell が一意に定まること、生成し得る観測の必要な範囲を覆うことを確かめる。加えて、**異なる cell の outcomes は互いに素で、cell の outcomes の和は核が生成し得る outcome の全体と一致する** (各 cell はその観測の逆像。観測の確率が各状態で和 1 になる条件)。重なる outcomes を別々の報告として許すには、どちらの報告を生成するかの法則が要る。その法則が未宣言なら missing_contract〔v0.23 FB23-R01。反例: 二状態・事前 (1/2,1/2)、Tᵤ=diag(3/4,1/4)・Tᵥ=diag(1/4,3/4)、a→{u}・b→{u,v} と置くと P(a)=1/2・P(b)=1 で和 3/2〕。複数 outcome に見分けられない観測は核を合算してから一度正規化する。', 2648: '', 2649: 'Frame の適用単位は、同じ model・読み手の系列内の認証した原測定 MID。縦の一本では一つの Frame が一つの MID を供給する。別 k に結んだ同じ Frame、再配送、別の B の保存を新しい適用単位にしない。同じ MID の意味の不一致は食い違いである。Frame の射影が求める kernel・outcomes・MID と input_digest の比較、同じ入力の no-op は維持する。未宣言の要約を独立観測にしない。', 2650: '', 2651: 'ClaimProjection は原 Claim の contract と kind の意味を解決する。初回に具体的に定義する意味は次の二つとする。', 2652: '', 2653: '| 契約 | 合法な kind | 射影する述語 | 生成・Support |', 2654: '|---|---|---|---|', 2655: '| `sui.fb.no_arrival/1` | `no_arrival` | 対象 channel の区間件数 `N(I)=0` | 窓全体を支える観測・設定・時計・生成の証拠 |', 2656: '| `sui.fb.count_exactly_one/1` | `count_exactly_one` | `N(I)=1` | 同上 |', 2657: '', 2658: 'これは固定した行動候補の一覧ではなく、初回の具体的な読み方の宣言である。別 kind・範囲を読む契約は、意味と参照経路を宣言して追加できる。未知の kind を上記のどちらかへ寄せない。縦の一本 (§2-4-0) の I-2 が使うのは no_arrival/1。count_exactly_one/1 は、和の述語を原子の集合へ潰す誤りを試験で識別するための具体の宣言として置く。', 2659: '', 2660: '現行 Claim の全欄は `route_epoch, interval, kind, contract, evidence` のまま。下限・上限を勝手に保存欄へ追加しない。この二契約では `(lower,upper)` はそれぞれ `(0,0)`、`(1,1)` と契約から導く。任意の範囲を報告ごとに指定する場合には、その値の保存場所と解決規則を別途宣言する必要があり、現在の Claim に自由な引数があるとは扱わない。', 2661: '', 2662: '**具体の有限同時法則。** `sui.fb.finite_joint_count_law/1` を Prediction / MODEL / PREDICTION として宣言する。', 2663: '', 2664: '```', 2665: 'value = {', 2666: '  model: Point,', 2667: '  extends: ?Point,', 2668: '  carrier_by_state: List[str],', 2669: '  channels: List[CountChannel],', 2670: '  rows: List[CountLawRow],', 2671: '  frame_relation: independent_given_carrier', 2672: '}', 2673: 'CountChannel = {', 2674: '  id: str,', 2675: '  process: BootSlot,', 2676: '  route_configs: Set[Point],', 2677: '  domain: MeasurementInterval', 2678: '}', 2679: 'CountLawRow = {', 2680: '  marks: List[CountMark],', 2681: '  mass: List[R]', 2682: '}', 2683: 'CountMark = {', 2684: '  channel: str,', 2685: '  time_ns: int,', 2686: '  count: positive_integer', 2687: '}', 2688: '```', 2689: '', 2690: '`carrier_by_state` はモデルの joint の状態順に対応する。mass の順はそこに現れる carrier 名の重複を除いた正準順。各 mass は非負で、各 carrier について全行の和が 1。marks は channel と時刻で正準化し、同じ位置の件数は合算する。重複した marks の行は合算して一行にする。行の識別は正準 marks から導き、窓の分割番号から作らない。宣言された全 channel の marks の組を一つの行に置くため、過程間・区間間の依存も同時分布に残る。', 2691: '', 2692: '各 channel の domain.clock は対応する clock.source と run へ解決でき、marks の時刻はその domain 内にある。各 Claim の区間は当該 domain に含まれなければならない。route_configs は同じ channel の計数量を報告する設定の対応を宣言する。B の k・route・生成の証拠との一致を別途確かめる。単に epoch が異なる／同じという理由で同一性や独立を決めない。原 Claim から channel への対応は一意でなければならない: 原 Claim の過程・route・生成の対応に合う channel が法則に二つ以上あれば、その法則はその原 Claim の読み方に使えない (shape)。channel の id は名前であり、同じ計数量を二つの id で二重に持たない〔v0.23 FB23-R04〕。', 2693: '', 2694: '`frame_relation=independent_given_carrier` は、この具体法則の生成モデルの積の構成を意味する。Claim の標本経路と Frame の観測・遷移は carrier を条件に独立と宣言される。使用する Frame の核の非零成分は carrier を保存しなければならない。初期の共同分布はモデルの初期 joint と、この条件付き marks 分布の積である。この条件を宣言・検査できない混在や、Frame と Claim が同じ原生成を共有する混在を、この具体法則で独立に扱わない。必要な共同の読み方が未宣言なら missing_contract とする。Frame 自体の旧 `/1` や独立した Frame 更新の条件を変更する規則ではない。', 2695: '', 2696: '`extends=null` はこの法則系列の起点。非 null は同じモデル・carrier 対応を持つ前の count law を指す。既存 channel の過程・時計・計数量の意味を変えず、domain を拡張し、新しい channel を追加できる。新しい表を旧 channel と旧 domain に制限して marks を正準化した時、**各 carrier ごとの同時分布全体が旧表と厳密に一致すること**を要求する。個々の一変量周辺分布の一致だけでは足りない。これにより過去の連言の確率を変えずに有限の対象を広げられる。無関係な二つの法則系列を黙って掛けない。この具体契約で一つの更新系列が使う Claim の同時法則は、この拡張関係で結ばれた一つの系列とする。', 2697: '', 2698: '法則の about は model。basis は model、extends の非 null 参照、channels が使う Boot 宣言・route_config・時計の宣言。親はその宣言を作るために実使用した出来事の Front。法則はモデルの予測宣言であり、現実にその件数だったことの証明ではない。', 2699: '', 2700: '有限表の時刻・行数・domain は具体モデルのパラメータである。sui に固定周期・刻み幅・将来の固定上限・固定の行動候補を課すものではない。別の過程法則は別の版つき契約として追加する。', 2701: '', 2702: '**述語と原子。** 適用の意味は述語で持つ。区間の closure (開閉) を述語にそのまま残し、各標本経路の marks を直接数えて評価する。同じ channel の主張の端点から作る細分 (点セルと開区間セル、下の ClaimCell) は、両立性の検査 (§19-6) や計算に使ってよい導出物で、状態・digest・保存には入れない。別の時計・channel の座標を数値の一致だけで統合しない。', 2703: '', 2704: '```', 2705: 'CountPredicate = {', 2706: '  channel: str,', 2707: '  interval: MeasurementInterval,', 2708: '  lower: nonnegative_integer,', 2709: '  upper: nonnegative_integer', 2710: '}', 2711: 'ClaimCell =', 2712: '  {kind: point, value: {channel: str, time_ns: int}}', 2713: '  / {kind: open, value: {channel: str, start_ns: int, end_ns: int}}', 2714: '```', 2715: '', 2716: 'lower≤upper を要する。各標本経路について interval 内の marks の count を合計して述語を評価する。述語の意味は `lower ≤ Σ N(cell) ≤ upper`。到着なしは各対象原子の `N(cell)=0` の連言に分解できる。一般の範囲は和に対する述語のまま保持する。', 2717: '', 2718: '後着の端点で細分が変わっても、状態 (述語の集合) は変わらない。細分の変更は表現の変更であり、観測の追加ではない。旧述語は新しい細分の子セルの和として評価され、新しい適用単位を作らない。子セルを独立と仮定しない。同じ標本経路からセル値を求めるので、粗い分布と細かい分布の押し出しは一致する。', 2719: '', 2720: '**条件づけ。** carrier c における、適用済み述語の連言を A、新しい述語を E とし、上記の表から `Zc(A)` と `Zc(A∧E)` を求める。`Zc(A)>0` の部分では', 2721: '', 2722: '`Lc=Zc(A∧E)/Zc(A)`', 2723: '', 2724: 'で更新する。ここで c は具体法則が明示した条件づけ対象であり、既存 kernel の粗い outcome ID と同一視しない。現在の各状態 x の未正規化重みは `joint[x]×Lcarrier(x)`、その和を z として joint を正規化し、evidence_mass に z を掛ける。これはこの具体法則の独立・carrier 保存条件の下で、起点から全連言を条件づけた結果と一致する。', 2725: '', 2726: '分母が 0 の carrier は、正しく再構成した既状態でも重み 0 でなければならない。その部分で通常の割算をせず、起点の同時分布から再構成する。`0/0` を用いて重みを復活させない。全体の証拠質量が 0 なら model_falsified。', 2727: '', 2728: 'A が E を含意する時は数値適用の no-op。原報告・新しい Q の入力・対象 bytes の認証は省略しない。分からない意味・未証明の独立・不足した計算を no-op にしない。', 2729: '', 2730: '**適用済み状態と AppliedStep。**', 2731: '', 2732: '```', 2733: 'AppliedStep2 =', 2734: '  {kind: frame, value: {', 2735: '    transition_key: Digest,', 2736: '    input_digest: Digest,', 2737: '    measurements: Set[MID]', 2738: '  }}', 2739: '  / {kind: claim, value: {', 2740: '    transition_key: Digest,', 2741: '    input_digest: Digest,', 2742: '    source: ClaimKey,', 2743: '    law_root: Point,', 2744: '    predicate: CountPredicate,', 2745: '    before_event_digest: Digest,', 2746: '    after_event_digest: Digest', 2747: '  }}', 2748: '', 2749: 'ClaimState = {', 2750: '  law: Point,', 2751: '  predicates: Set[CountPredicate]', 2752: '}', 2753: '```', 2754: '', 2755: 'これらは一次入力から導く内部状態で、呼出し側が申告する正解表ではない。細分と、連言を満たす行の集合は (law, predicates) から計算し直せるので持たない。Claim の transition_key は法則系列の起点、正規化した channel・区間・述語の意味から導く。item_slot・B の Point・配送の番号を新しい数値適用の鍵にしない。input_digest はこの意味と読み方の版に結び、同一性を照合した別名は同じ正規形へ写す。法則の拡張は前記の同時周辺分布の一致を確かめてから旧状態を移し、旧の観測を再適用しない。', 2756: '', 2757: '`ClaimKey` は原 Claim の FAMILY-UNNAMED の鍵 `(segment,item_slot)`。Frame の MID と同じく、**同じ原 Claim は一つの導出系列で一つの出来事として効く**。別の reading で読み直しても、正準の channel・区間・述語が同じなら no-op、違えば食い違い (CL-APPLY) とし、別の観測として足さない。同じ原報告から別の命題を同時に取り出すには、その共同の読み方を宣言する (未宣言なら missing_contract)〔v0.23 FB23-R04。反例: 同じ計数量に id だけ違う channel u・v を置いた同時表で、同じ原 Claim を Nᵤ=0・Nᵥ=0 と二度読むと、原報告は増えていないのに事後が (3/4,1/4；1/2) から (9/10,1/10；5/16) へ動く〕。別 slot の原 Claim は別の報告で、同じ述語なら含意で no-op になる。', 2758: '', 2759: '異なる述語を同じ law_root に追加すること自体は食い違いではない。過程を共有する鍵と、一つの主張の適用を識別する鍵を区別する。一般の範囲を単なる適用済みセル集合へ潰さない。', 2760: '', 2761: '数値の `application_digest` は、モデル・origin・意味の版、順序を保った Frame の適用状態、現在の count law と連言が表す行集合を結ぶ。細分のセル番号・配送順・B の保存番号を含めない。Claim の監査用の適用手順と、現在の連言の正準な意味を混同しない。同じ法則で同じ連言を別の配送分割から作った時、数値結果とこの意味の digest は一致する。法則宣言自体を拡張した場合は、その新しい宣言への結合を別途保ち、旧認証物の digest を書き換えない。', 2762: '', 2763: 'application_digest の一致を、論理の状態の一致や含意の代わりにしない。法則が (N₁,N₂)=(0,0) だけに質量を置くと、`N₁=0` と `N₂=0` は同じ行集合になるが、`N₁=1` を足すと前者とは論理の矛盾 (§19-6)、後者とはモデル上の質量 0 (model_falsified) になる。この区別のために元の述語を状態に残す (M07)。', 2764: '', 2765: '数値適用の digest と、Q/R/全 P/Cq・原報告・宣言・入力の全 bytes を認証する digest は別である。数値が no-op でも後者の比較は省略しない。', 2766: '', 2767: '**失敗。** 未宣言の kind・生成の共有・共同法則・必要な読み方は rejected/missing_contract。宣言済みだが証拠・実装・予算が不足する時は insufficient。表の正規化違反、拡張の不一致、虚偽の対応は不正として分類し、不足や独立へ丸めない。', 2768: '', 2769: '**閉じる条件。** 同じ Frame の再配送、別 k、重なる無到着、件数 1、別 kind の同義、異なる過程・epoch、点セル、部分 Support、後着端点、法則の拡張、ゼロ分母を区別できること。CE1 の三結果を厳密に識別し、未宣言の法則で成功しないこと。対応：B:31、735–764、1033–1035、1060–1064、1160–1174、2144、2387、2414、2467；A:267–270、320。', 2770: '', 2771: '> たとえ: 隣の部屋のカメラのメモを、「どの時間帯のメモか」ではなく「その時間帯に猫が何回出入りしたか」という中身のまま束ねて持つ。重なったメモも、全部を同時に満たす場合だけを数えるので、重なりは 1 回だけ効き、新しいぶんはちゃんと効く。', 2772: '', 2773: '##### 19-2. 必須閉包', 2774: '', 2775: '**決定。** 用途別の型つき参照規則から必須閉包 C を独立に導く。Q.inputs=I は照合対象である。', 2776: '', 2777: '`finite_update/2` の直接の数値参照は model、previous_result の非 null 値、observations の binding/reading。各 reading から model、projection/generation の宣言済み参照へ進む。Claim の場合は count law、extends の鎖、channel の Boot 宣言・設定・時計へ進む。B からは k、原報告、route、用途に必要な生成・時計・Support の証拠へ進む。Ref の解決も固定像に結ぶ。数値表の文字列・digest・セル番号を Point として探索しない。', 2778: '', 2779: 'previous_result から前 Q/R/全 P/Cq と前 Q.inputs を含め、必要な依存を再帰的に閉じる。新しい Q 自身の将来の R/P/Cq/V を要求しない。取得・採用・認証の証拠は、その用途の閉包で追加し、全てを数値入力へ混ぜない。', 2780: '', 2781: 'I は重複なし、全項の実在・bytes・認証・必要な利用可能性を検査し、C⊆I を要求する。余分な I も入力 digest に結ぶが、observations にない追加観測にはしない。observations の順を I の整列順へ置き換えない。', 2782: '', 2783: 'Q の外側 inputs、R の about/basis、P の about/basis は既存 A-04 と本節の証明契約に従う。閉包の説明値を正解として別に持たせない。内部キャッシュは同じ一次入力から再構成できるものに限る。', 2784: '', 2785: '**失敗。** 申告 I の必要参照の欠落は unresolved_reference。必要本文が物理的に読めない時は missing_input。参照の意味の未宣言は missing_contract。閉包の循環を検査成功で打ち切らない。', 2786: '', 2787: '**閉じる条件。** 申告 I と独立に必要集合を求め、不足・余分・別 origin・別モデル・将来依存・参照の種類違いを区別すること。対応：B:1033–1035、1070–1076、2180、2303、2387、2467；A:149、158–166、245–254、267。', 2788: '', 2789: '> たとえ: 計算に何が要るかは、頼んだ側の申告とは別に、猫の見立ての手順書から自分でたどり直して、申告と照らし合わせる。', 2790: '', 2791: '##### 19-3. 前の結果と履歴', 2792: '', 2793: '**決定。** previous_result の意味は、モデルの起点から有限の導出系列を再構成した結果で定める。', 2794: '', 2795: 'null の時は model.initial、evidence_mass=1、Frame の適用履歴と Claim の連言は空。非 null の時は同じ model・origin の前 Q/R/全 P/Cq と必要な生成・認証を検査し、前 Q の一次入力から数値結果・適用済み状態を再構成する。R の joint だけを信頼して履歴を省かない。Claim の法則・原述語・細分・行集合も一次入力から復元する。', 2796: '', 2797: '旧 `/1` の前結果は旧契約と旧環境で検査する。`/1` の適用単位と `/2` の適用単位を接続する意味が必要な場合、宣言された接続なしに推測しない。', 2798: '', 2799: '検証済み接頭部は、同じ意味の別の証明として後で追加できる。対象・モデル・origin・bytes・適用履歴・Claim の連言と法則・reader 像・認証器・registry の版を結び、起点からの再構成と同じ主張を証明するものに限る。現在の具体 checker は全再構成だけを行い、接頭部の実装があるとはしない。', 2800: '', 2801: '**失敗。** 別系列・偽の前結果は proof_mismatch、保存主張との数値不一致は result_mismatch。必要な証明・計算量が不足する場合は insufficient。任意の保存信念を checkpoint として採用しない。', 2802: '', 2803: '**閉じる条件。** 連続更新、再配送、同じ Cq の再採用、別系列、長い履歴による不足を区別し、前の履歴を落として重複を新規適用しないこと。対応：B:1033、1092、1160–1164；A:232、267；`_f_world.py:2027–2046`。', 2804: '', 2805: '**後の行き先。** 起点からの再構成と reader の取り込み・閉包・取得採用系列が伸びる問題は F-a/F-b 共通で F-c「計算の予算と打ち切り」へ置く。外付けの表 R11 は参照行、検証済み接頭部・増分認証の具体方式の採用は未決。継続運転の測定は F-d。S5・S8 へは送らない。', 2806: '', 2807: '> たとえ: 前の見立ては信じて受け取らず、最初のメモから全部たどり直して同じになるかで確かめる。メモが増えて長くなる心配は F-c の宿題。', 2808: '', 2809: '##### 19-4. 時計', 2810: '', 2811: '**決定。** 一般の口として、宣言された有限の潜在時刻の同時法則を周辺化する読み方を認める。初回の具体契約は潜在時刻の法則を宣言しない。', 2812: '', 2813: '`time_projection=sui.fb.segment_value_only/1`、args={} とする。Frame で省く実測時刻・quality が追加情報を持たないか固定されていることを、測定・モデルの宣言から確かめる。必要な実測時刻の Unavailable を r・s・窓端で補わない。Claim の区間の座標、設定の実効、全窓の観測、生成・実取得に必要な時計は別途必要である。', 2814: '', 2815: '原報告の inline reading、B.clock の clock.source、保存した clock_reading、run、区間 i、実測 e、受信 r、保存 s、文脈 o/j を役割ごとに検査する。後から作った報告の生成時刻と、過去の観測窓の終端を等置しない。別の時計の同じ整数を同じ原子にしない。', 2816: '', 2817: '潜在時刻を周辺化する契約を追加する時は、時刻と他の隠れた変数の同時法則、観測射影、生成・使用時刻との結合を宣言する。周辺化の口があることを実装済みとしない。', 2818: '', 2819: '**失敗。** 必要時刻・整列の証拠不足は insufficient。確定した逆転・異なる run の偽の対応は shape/clock_unaligned。必要な時計の読み方自体が未宣言なら missing_contract。', 2820: '', 2821: '**閉じる条件。** 正常な遅着、Unavailable、端点の開閉、時計違い、後着報告、全窓の条件を区別すること。対応：B:735–764、2063–2066、2188–2191、2225、2231；A:183–214、233–234、270。', 2822: '', 2823: '> たとえ: 「何時に測ったか」は、どの時計の何時かまで確かめる。後から書いた報告の時刻を、見張っていた時間の終わりと取り違えない。', 2824: '', 2825: '##### 19-5. bootstrap の生成と Support', 2826: '', 2827: '**決定。** `sui.fb.bootstrap_generation/1` は、k・設定の実効・Started・原報告・時計を独立の実行証拠へ直接照合する。', 2828: '', 2829: '```', 2830: 'args = {scope: measurement/report/whole_window}', 2831: '```', 2832: '', 2833: 'scope は自由に証拠を弱める選択肢ではない。射影する原報告の意味が要求する scope と一致させる。Frame の測定、過去について報告を生成した出来事、窓全体の観測を区別する。no_arrival/1 と count_exactly_one/1 の具体射影は whole_window を要する。', 2834: '', 2835: 'B の generation.applied/started/ended、route、clock、k、原報告を解決し、宣言と実際の対応を EH/EW/EI の独立した控えで照合する。「認証済み」という保存値を根拠にしない。旧 `/1` の Attempt 条件は変更しない。', 2836: '', 2837: 'Support の入力は固定 X 内の保存済み証拠と宣言。EI はその証拠が表す出来事との対応の検査だけに使う。X に無い環境履歴を追加証拠にしない。Claim 自身を唯一の全窓の証拠にしない。', 2838: '', 2839: '今回の Claim 射影では、**元の述語が主張する全範囲を支えること**を要求する。Support が部分だけの場合、原 Claim を切り詰めて成功させない。不足と確定した虚偽を区別する。部分から別の命題を導く方法を足す場合は、その導出の意味を独立に宣言する。', 2840: '', 2841: '**閉じる条件。** 全窓の正しい対照、Started/Ended だけの偽の被覆、部分 Support、後から作った正しい報告、過去の Gap、後着証拠による別 X の再認証を区別すること。対応：B:737–764、1059–1064、1075、2082–2093、2229。', 2842: '', 2843: '> たとえ: 「ずっと見てた、猫は来なかった」というメモは、その時間ずっとカメラが動いていた別の証拠がある時だけ効く。一部しか見ていなかったら、メモを勝手に短く書き直して通さない。', 2844: '', 2845: '##### 19-6. 食い違い', 2846: '', 2847: '**決定。** 数値再構成は固定 Xnum、使用禁止は当該使用直前の Xuse の U/UE 依存で検査する。Xc の保存完了を待って食い違いを知ったことにしない。', 2848: '', 2849: 'Frame の MID、sequence、原報告の比較は既存の CL-SAME/CL-SEQ/CL-MEASUREMENT を維持する。Claim の同じ原報告の異内容は CL-SAME。数値の共有単位は、宣言した法則系列・channel・主張の意味へ展開する。別 slot、別 B、別取得意図だけでは Clash にしない。', 2850: '', 2851: '同じ過程について異なる述語が増えることは正当な情報追加になり得る。例えば `N(I)=1` と `N(I)≤1` は両立する。一方、同じ I・計数量について `N(I)=0` と `N(I)=1` は両立しない。区間が違う時は共通細分上の件数制約へ写し、原子の参照関係を保って両立性を検査する。現在の有限範囲述語では、関与する各原子の件数について非負整数の制約として確かめる。', 2852: '', 2853: '両立性は二つずつでなく、関与する述語の全部の連言で検査する。`N(I₁)=0`・`N(I₂)=0`・`N(I₁)+N(I₂)=1` は二つずつなら両立するが、三つ全体では矛盾する。', 2854: '', 2855: 'この論理的な不一致と、モデルがある両立可能な観測へ確率 0 を置いた場合を区別する。後者は model_falsified であり、それだけで報告間の Conflict を捏造しない。', 2856: '', 2857: 'affected は直接関与した報告・B・適用単位から独立に求め、下流へは UseDeps の最小閉包で伝える。E だけの診断参照を結論使用に昇格させない。古い根の再読を後着の食い違いで書き換えない。', 2858: '', 2859: '**閉じる条件。** 同値再提示、両立する範囲、論理的な矛盾、モデル反証、別 slot、後着 Xc、Xnum と Xuse の差を区別すること。対応：B:351–357、872–878、1070–1077、1160–1177、2301。', 2860: '', 2861: '> たとえ: 「1 回来た」と「1 回以下」は両立するけど、同じ時間帯の「0 回」と「1 回」は両立しない。この矛盾と、見立てが「ありえない」としていたことが起きた (見立ての反証) こととは別に扱う。', 2862: '', 2863: '##### 19-7. 実取得', 2864: '', 2865: '**決定。** W-22 の意味を維持する。数値入力に使う原測定・原 Claim の内容は、Wr が使用するまでに同じ origin が実取得していることを要する。B は対応・認証の根拠であり、B が存在するだけで元内容の実取得を証明しない。', 2866: '', 2867: '実取得 a とその通知 G の受信 r・保存 s を区別する。EA/EW により対象・origin・取得と Wr の使用の実対応を確かめる。a が使用より前でも G の保存が後になる正当な遅延を許す。G を一律に Wr 要求の親に追加しない。Wr が G の通知そのものを使用する場合は、その使用に A-08 を適用する。', 2868: '', 2869: 'R と全 P は対応 Cq の生成完了後に同じ origin が実取得する。Wp は保存した R を未認証の証明対象として使用でき、R の取得・未来の Cq/V を前提にしない。必要な G は Wv と採用の実祖先・時間条件に結ぶ。元の測定の周期的な取り直しは要求しない。', 2870: '', 2871: '**失敗。** 未取得の前提を preflight で知った場合は prerequisite_unavailable。未取得なのに採用した主張、別 origin・別対象の G の流用は proof_mismatch。必要な実祖先の欠落や物理的欠落は A-21 の区別に従う。', 2872: '', 2873: '**閉じる条件。** G の遅延保存、同内容の別 origin、取得意図だけ、R/P の Cq 前取得、Wp の循環、取り直しなしの合法例を区別すること。対応：B:370、374、1044–1048、2282、2322–2323；A:183–192、255。', 2874: '', 2875: '> たとえ: 計算に使ったメモは、使う時までに本当に手元に届いていたことを確かめる。届いた知らせの保存が少し遅れるのは正常。', 2876: '', 2877: '##### 19-8. 再計算と結果', 2878: '', 2879: '**決定。** 既存 `sui.f.finite_update_result/1` を、同じ数学的意味で再利用する。', 2880: '', 2881: '```', 2882: 'value = {joint: List[R], evidence_mass: R}', 2883: '```', 2884: '', 2885: 'joint はモデルの状態順の正規化した共同分布。evidence_mass は起点からの適用済みの全証拠の累積質量。各値・次元・正準性・和・非負性を検査し、一次入力から厳密に再計算して全比較する。丸めや部分比較を許さない。', 2886: '', 2887: 'Frame は核を合算して一度正規化する。Claim は §19-1 の連言を使用する。法則の拡張では、まず旧事象の同時分布が保持されることを検査し、表現の変更を追加尤度にしない。', 2888: '', 2889: '適用済み状態の違いは、結果の二欄だけでは識別できない場合があるため、§19-9 の statement と対象認証物で application_digest を結ぶ。MID・Claim の原子や述語を result/1 の欄へ追加しない。', 2890: '', 2891: '**CE1 の例 (試験の具体の宣言、v0.23 FB23-R02)。** 二つの carrier a・b、事前 (1/2,1/2)。一つの channel の時刻 1・2・3 の件数を `x1,x2,x3∈{0,1}` とし、`sui.fb.finite_joint_count_law/1` の表として次を宣言する (各位置の無到着の確率が a で 1/2・b で 1/4 の積の表と一致する。これがこの例の独立の明示で、宣言なしに独立を補ったのではない。時刻 1・2・3 はこのモデルの有限の標本経路の位置で、sui に周期を命じる値ではない)。', 2892: '', 2893: '| x1x2x3 | a | b |', 2894: '|---|---:|---:|', 2895: '| 000 | 1/8 | 1/64 |', 2896: '| 001 | 1/8 | 3/64 |', 2897: '| 010 | 1/8 | 3/64 |', 2898: '| 011 | 1/8 | 9/64 |', 2899: '| 100 | 1/8 | 3/64 |', 2900: '| 101 | 1/8 | 9/64 |', 2901: '| 110 | 1/8 | 9/64 |', 2902: '| 111 | 1/8 | 27/64 |', 2903: '', 2904: '先の Claim `N((0,2])=0` (x1=x2=0)、後の Claim `N((1,3])=0` (x2=x3=0)。Z(先)=(1/4,1/16)、Z(先∧後)=(1/8,1/64)、追加の尤度 (1/2,1/4)。', 2905: '', 2906: '| 計算 | 起点からの未正規化重み | joint；evidence_mass |', 2907: '|---|---|---|', 2908: '| 正しい連言 | (1/16,1/128) | (8/9,1/9；9/128) |', 2909: '| 独立として二重に適用 | (1/32,1/512) | (16/17,1/17；17/512) |', 2910: '| 後を捨てる | (1/8,1/32) | (4/5,1/5；5/32) |', 2911: '', 2912: 'M07 の例: 二つの原子の件数 (N₁,N₂) について、a は (1,0)・(0,1) に各 1/2、b は (0,0)・(1,1) に各 1/2、事前 (1/2,1/2)。`N₁+N₂=1` の事後は (1,0)、`N₁+N₂=0` の事後は (0,1)。覆う原子の集合はどちらも {I₁,I₂}。', 2913: '', 2914: '**閉じる条件。** CE1 の `(8/9,1/9;9/128)`、二重適用の `(16/17,1/17;17/512)`、追加を捨てた `(4/5,1/5;5/32)` を識別すること。同じ数値で適用履歴が違う対照も証明側で識別すること。対応：A:267、320、336；B:378、2318、2559；f.py:3753–3755。', 2915: '', 2916: '> たとえ: 結果は猫の機嫌の見立て (joint) と、ここまでの証拠の重さ (evidence_mass) の 2 つ。最初から計算し直して、ぴったり同じかを全部比べる。', 2917: '', 2918: '##### 19-9. 証明・返答・対象指定認証物', 2919: '', 2920: '**決定。** 証明する内容と、証明の方法を分ける。一つの認証物は一つの Q/R/全 P/Cq を対象に発行する。内部の再計算を共有してよい。', 2921: '', 2922: '```', 2923: 'sui.f.finite_update_statement/2', 2924: 'value = {', 2925: '  model: Point,', 2926: '  request: Point,', 2927: '  result: Point,', 2928: '  application_digest: Digest', 2929: '}', 2930: '', 2931: 'sui.f.finite_update_replay/2', 2932: 'args = {}', 2933: '', 2934: 'ProofOutput = {', 2935: '  role: normalization/query,', 2936: '  statement: ContractValue,', 2937: '  checker: ProofRef', 2938: '}', 2939: '```', 2940: '', 2941: '初回の正規化証明は上記 statement/2 と replay/2 を用いる。全再構成で結果と application_digest を比較する。ProofOutput、旧 computation_proof/1 の保存形を変えない。未宣言の query 証明を作らず、必要な query の意味が無い時は missing_contract とする。', 2942: '', 2943: 'statement/2 の proof の about は Q/R、basis は model/Q/R と、checker が直接依存すると宣言した追加参照の正確な集合。現在の replay/2 の args={} では追加参照はない。旧 statement/1 の厳密な basis の条件は変更しない。', 2944: '', 2945: '後で接頭部の checker を追加する場合、新しい ProofRef の名前・版・閉じた args・参照規則・registry の実装 identity を宣言する。同じ statement/2 の内容を証明できる場合に限り使用できる。現在の型に Any、自由な prefix_data、未検査の checkpoint を足さない。', 2946: '', 2947: '対象認証入口の契約を `sui.f.finite_update_target_check/1`、args={} とする。入力は保存済みの Wv 要求の Point と、明示した reader、registry、独立の実行・取得証拠、既存 RateBudget。Wv の Desc/VerificationArgs から対象・origin・Xnum・check_view・checker・acquisitions を解決する。認証入口が受け取った実際の budget も呼出しの一部として固定する。', 2948: '', 2949: '```', 2950: 'Target = {', 2951: '  request: Point,', 2952: '  result: Point,', 2953: '  proofs: Set[Point],', 2954: '  completion: Point', 2955: '}', 2956: 'CallBinding = {', 2957: '  work_request: Point,', 2958: '  budget: RateBudget,', 2959: '  call_digest: Digest', 2960: '}', 2961: 'CheckedProof = {proof: Point, checker: ProofRef}', 2962: '', 2963: 'UpdateCertificateDescription = {', 2964: '  contract: sui.f.target_update_certificate/1,', 2965: '  value: {', 2966: '    call: CallBinding,', 2967: '    target: Target,', 2968: '    model: Point,', 2969: '    origin: Point,', 2970: '    numerical_view: FixedView,', 2971: '    check_view: FixedView,', 2972: '    registry_key: str,', 2973: '    verifier: ProofRef,', 2974: '    checked_proofs: List[CheckedProof],', 2975: '    target_digest: Digest,', 2976: '    request_input_digest: Digest,', 2977: '    closure_digest: Digest,', 2978: '    result_digest: Digest,', 2979: '    application_digest: Digest,', 2980: '    acquisition_digest: Digest,', 2981: '    replay_mode: positive_dependencies/exact_environment', 2982: '  }', 2983: '}', 2984: '', 2985: 'VerificationResponse =', 2986: '  {kind: verified, value: UpdateCertificateDescription}', 2987: '  / {kind: rejected, value: {', 2988: '      call: CallBinding,', 2989: '      issues: NonEmptyList[RejectedIssue]', 2990: '    }}', 2991: '  / {kind: insufficient, value: {', 2992: '      call: CallBinding,', 2993: '      issues: NonEmptyList[InsufficientIssue]', 2994: '    }}', 2995: '', 2996: 'RejectedIssue = {', 2997: '  code: schema/shape/noncanonical/rational/unit/unknown_version/', 2998: '        normalization/unresolved_reference/reference_kind/', 2999: '        proof_mismatch/observation_binding_mismatch/', 3000: '        measurement_conflict/clock_unaligned/missing_contract/', 3001: '        model_falsified/outside_evaluation_type/result_mismatch,', 3002: '  fields: List[str],', 3003: '  evidence: Set[Point],', 3004: '  message: str', 3005: '}', 3006: 'InsufficientIssue = {', 3007: '  code: algorithm_unavailable/certificate_incomplete/', 3008: '        budget_exhausted/prerequisite_unavailable/clock_unaligned,', 3009: '  fields: List[str],', 3010: '  missing: List[VerificationNeed],', 3011: '  evidence: Set[Point],', 3012: '  message: str', 3013: '}', 3014: 'VerificationNeed =', 3015: '  {kind: capability, value: {', 3016: '      contract: ContractRef,', 3017: '      purpose: reading/generation/clock/replay/proof/authentication', 3018: '    }}', 3019: '  / {kind: evidence, value: {', 3020: '      target: Point,', 3021: '      purpose: generation/clock/support/acquisition/adoption_chain,', 3022: '      contract: ?ContractRef', 3023: '    }}', 3024: '  / {kind: budget, value: {', 3025: '      phase: reader/authentication/projection/replay/proof', 3026: '    }}', 3027: '', 3028: 'TargetVerificationReturn = {', 3029: '  response: VerificationResponse,', 3030: '  issued: VerifiedFiniteUpdate または None', 3031: '}', 3032: '```', 3033: '', 3034: 'RateBudget は既存の公開型と正準な値の規則をそのまま使う。fields は A-21 の JSON Pointer と重複なし正準順に従う。message と fields の文字列から追加参照を作らない。missing の target は、実在する Q/R 等の対象を指す。まだ存在しない証明や G の Point を捏造しない。', 3035: '', 3036: 'call_digest は、保存済み Wv 要求・解決した宣言と全引数・対象・実際の環境・budget を結ぶ。将来の自分の返答・V・認証物を入力に含めて循環させない。target_digest は Q/R/全 P/Cq の全 bytes。request_input_digest は余分な I を含む固定入力全体。closure_digest は独立に求めた必要閉包。result_digest は result/1 の全値。application_digest は §19-1 の意味。acquisition_digest は当該 origin・対象・取得意図・G・時計等の保存された対応を結ぶ。', 3037: '', 3038: 'これらの digest を、実行・実取得の独立証拠の代用品にしない。verified は factory が実際の検査の成功から発行した VerifiedFiniteUpdate を伴う場合だけ成立する。issued は verified でのみ非 None。他の枝では None。保存可能な説明値から生きた発行物を復元したことにしない。V の二欄 `{request,report}` は維持する。', 3039: '', 3040: 'replay_mode は検査が不在に依存したかから導く。呼出し側が有利な方を選ぶ欄ではない。', 3041: '', 3042: '**失敗の共通分類。**', 3043: '', 3044: '| 条件 | 扱い |', 3045: '|---|---|', 3046: '| 型・必須欄・正準性・単位・確率表の正規化違反 | 対応する FInputError。認証返答へ写す境界では rejected の該当 code |', 3047: '| 宣言の意味が無い、未知 kind を使用、未宣言の独立や共有が必要 | rejected/missing_contract |', 3048: '| 申告 inputs の欠落、必要実祖先なし | unresolved_reference |', 3049: '| 不正な生成対応、法則拡張の不一致、虚偽の証明・結果 | 対応する observation_binding_mismatch/shape/proof_mismatch/result_mismatch |', 3050: '| 報告や適用の確定した矛盾 | measurement_conflict と対応する Conflict の記録・伝播 |', 3051: '| 必要な実装・時刻・Support・証明・計算予算の不足 | insufficient の該当 code と具体的な missing |', 3052: '| 論理的に可能な証拠にモデルが質量 0 を置く | rejected/model_falsified |', 3053: '| 必須本文の物理的欠落、再読方法の喪失 | FReplayUnavailable(missing_input/method_unavailable)。通常の insufficient に潰さない |', 3054: '| 数値表現の障害 | failed/NumericalRange。内側の rejected と交換しない |', 3055: '| 予期しない例外・I/O 障害 | 元の例外を保つ。一律 insufficient にしない |', 3056: '', 3057: '入口で対象を構成できない不正や物理的欠落まで、無理に三枝の返答へ変換しない。仕事の実行 Failure/Unknown と、正常に返った rejected/insufficient の返答も区別する。', 3058: '', 3059: '**閉じる条件。** Q/R/P/Cq の差し替え、違う application_digest、自己申告の成功、別環境・budget、偽の発行物、proof checker の版違い、未宣言の prefix、内側返答と外側 Failure の取り違えを拒むこと。対応：B:374–384、1040–1047、2085–2086、2172–2173、2197–2198、2298–2299、2442、2479、2490、2558；A:244–256、493。', 3060: '', 3061: '> たとえ: PC の中で言うと、「何を証明するか」(statement) と「どの道具で確かめるか」(checker) を分けて書き、確かめた証明書は 1 回の計算の組だけを指す。', 3062: '', 3063: '##### 19-10. 採用と replay', 3064: '', 3065: '**決定。** 採用直前に現在の前採用・対象指定の発行物・同じ origin の実取得・必要祖先・Xuse の食い違いを照合する。', 3066: '', 3067: '新しい導出では Q.previous_result が実際の前採用の結果に一致しなければならない。同じ Cq の正当な再採用は新しい数値適用にせず、元の Q.previous_result を変更しない。予定の前状態が変わっていれば Stale とし、Conflict に置き換えない。', 3068: '', 3069: 'replay は A E-06 から導く。不在に依存しない成功は、正の依存の bytes・解決・契約の意味を保つ新しい reader で再認証できる。過去の不在・不足は当時の reader 像、registry の実装 identity、呼出しと budget で再現する。新しい能力や大きい budget によって過去の不足を成功へ書き換えない。', 3070: '', 3071: '旧 artifact は旧 bundle へ戻す。未知の registry_key を現在の registry に置き換えない。保存済みの成功の再認証と、現在その結果を採用してよいかの判定を分ける。現在の前採用や Xuse が変わっていれば、古い正しい結果でもそのまま採用できない。', 3072: '', 3073: '検証を四つに分ける：旧 `/1` と旧 registry、旧 artifact と旧 bundle、新 `/2` と新 registry、誤った組合せ。同一ホストの独立証拠が残る範囲を維持し、S5 の再起動後の発行物の復元を本節で実装したことにしない。', 3074: '', 3075: '**閉じる条件。** 再採用、Stale、新しい正の reader、古い不在、registry 差し替え、必要 bytes の喪失、現在の Conflict を区別すること。対応：B:347、355–357、484–491、877–878、1047–1048、2293–2294；A:232、235、493。', 3076: '', 3077: '> たとえ: PC の中で言うと、正しく確かめた古い結果でも、今の前提 (前に採用した結果) が変わっていたらそのまま採用しない。昔「足りなかった」確認を、今の道具で後から成功に書き換えない。', 3078: ''}
V23_CHANGED_LINES={367: '2. 結果の仕事 Wᵣ は、数値入力として使う原測定・原 Claim の内容を、その使用までに同じ origin が実取得していたことを前提として実行する。取得と使用の対応は EA/EW で検査し、取得通知 G の保存を一律に Wᵣ 要求より前とはしない。Wᵣ が結果と開始・終わりの読みを返す → 窓口が R (`computation_result/1`) を保存。**ここでは完了を作らない** (v0.23、§2-5-19-7)', 371: '6. 対応する Cq の生成完了後に、結果 R と全部の証明 P を同じ origin が実取得する。元の測定・原 Claim については、Wᵣ が数値入力として使うまでに当該 origin が実取得していたことを EA/EW の実対応で確かめ、その取得を表す G が Wᵥ・採用に必要な実祖先と時刻条件を満たすことを確認する。元内容の取り直しは要求しない。保存済み Q/R/全 P/Cq を対象に Wᵥ を走らせ、対象指定認証が成功し、採用直前の前採用・実取得・Xuse の条件が全て一致する時だけ採用する。実取得 a と、その通知 G の r/s を交換しない。B:2282 の Wᵣ の親式へ全 G を一律に足さない (v0.23、§2-5-19-7・10)', 1163: '| RIGHT-APPLY の /2 (v0.23) | §2-5-19-1 | `/2` の Frame は、版つきの読み方・生成の対応から transition_key、kernel、outcomes、MID 集合、input_digest を導く。Claim は §2-5-19-1 の法則系列・channel・述語へ射影し、既適用の連言を条件として追加する。共有する過程の鍵と、一つの主張の適用の鍵を区別する。同じ過程への異なる両立する Claim は追加の情報になり得る。細分の変更、同義の再提示、再配送を新しい観測の適用にしない。Frame 用の outcomes の tuple だけで Claim の連言の状態を代用しない。 |', 1176: '| CL-APPLY の /2 (v0.23) | §2-5-19-1・6 の法則系列・channel・述語 | 同じ原 Claim (ClaimKey) を別の読み方で違う正準の述語に写すことは Clash (FB23-R04)。同じ法則系列に新しい述語を足しただけでは Clash にしない。論理的に両立しない述語 (同じ区間・計数量の `N=0` と `N=1` 等) だけ。モデル上の証拠質量 0 (model_falsified) と、原報告同士の論理的な不一致を区別する | 直接関与した報告・B・適用単位 |', 2020: '`?T` は T または null。ほかの欄は非 nullable。`List[T]` は順序のある列、`Set[T]` は重複のない集合。`◆G-01` は v0.22 まで未定義だった型・意味の印で、v0.23 で §2-5-19 に定めた (各行の参照先を §2-5-19-n に置き換えた)。未宣言の意味を Any・自由 JSON・null で埋めない。`★` は今回の縦の一本の外。', 2147: '| inputs | MethodCall | 必要な入力・根拠、固定する Xnum、前の結果、引数の全内容を定める。/2 の Q 引数・読み方・法則・前の結果・必須閉包は §2-5-19-1〜3。B:623・626 |', 2200: '| ProofOutput | `{role:normalization/query,statement:ContractValue,checker:ProofRef}` | Q/R は ProofArgs と照合。/2 statement/checker は §2-5-19-9。query の未宣言の意味は補わない |', 2201: '| VerificationResponse | verified / rejected / insufficient の確定返答。各 payload は §2-5-19-9 | 実行 Failure/Unknown は外側。生きた認証物を裸の JSON で代替しない。B:374〜379、1137 |', 2301: '| proof_output/1 | 内側の値契約、ProofOutput。独立 Body なし | Wp の返答。statement/checker の /2 は §2-5-19-9 | 適用外 | B:363、373〜374 |', 2302: '| verification_response/1 | 内側の値契約、VerificationResponse。独立 Body なし | 枝は確定。payload・発行物の全結合は §2-5-19-9 (保存説明値と生きた発行物の対応を全比較) | 適用外 | B:374〜379、1137 |', 2304: "ConflictRule は `{id:CL-SAME/CL-SEQ/CL-MEASUREMENT/CL-EXECUTION/CL-DRAW/CL-APPLY,version:'1'}` とし、規則の本文は B:1163〜1172 に固定する。/2 の CL-APPLY の適用同一性と両立性は §2-5-19-1・6 (過程・原子の共有だけで矛盾を作らない)。Unknown＋後着値、正当な Stale、別 slot・別取得意図だけで Conflict を作らない。個数違反を Xc で代用しない。", 2306: '新しい D の inputs は、その確定が実使用する本文・宣言上の対象を認証して Ref 集合へ写す。各仕事要求では BootSlot の宣言 Point、reader、trigger、input_points、用途別 args の宣言された使用参照を照合する。selection では evaluated と、そこから解決して実使用する artifact・draw 等を照合する。取得意図は origin/contents、採用意図は origin/completion/planned_previous/verification/acquisitions を照合する。自由 JSON 全体を走査して作らない。/2 の方法別経路は §2-5-19-2。ほかの未宣言の経路は意味不足として残す（S5）。', 2320: '| sui.f.computation_requested/1〔Q〕 | D、`{origin:Point,purpose:belief/query/certificate,method:ContractRef,args:JSON,inputs:List[Point],algorithm_draws:List[Point],output_contract:ContractRef}` | Wr 要求から指す旧 Q。親 Front(Ev(実使用 trigger・origin・入力・許可))。/2 args は §2-5-19-1、閉包は §2-5-19-2 | A:61、158、B:360、482 |', 2376: '| E0-07、1010 | 未宣言の契約・用途 (/2 は §2-5-19-9 の失敗の共通分類) | 意味の境界で不足。原報告保存は継続 |', 2390: '| 1028 | 旧 Q.args の方法別宣言 | U。/2 は §2-5-19-1〜2 (法則・述語・前状態の依存を含む) |', 2417: '| 1055 | B と読み方の意味別展開 | UE。/2 は §2-5-19-1・4・5 (Support の部分だけで原 Claim を書き換えない) |', 2445: '| CMP-15、1137 | Wv Desc/args、V、EA の返答・実発行物 | payload・認証物は §2-5-19-9 (実呼出し・返答・説明値・発行物の全対応) |', 2470: '| QOBS、1088 | /2 の射影・閉包は §2-5-19-1〜2、数値の全比較は §2-5-19-8 |', 2482: '| LINK-ACQUISITION、1100 | 意図・G/V・EA・生きた認証物。/2 は §2-5-19-7・9 (保存値と EA/EW・生きた発行物を区別) |', 2493: '| 対象指定の発行済み認証物 | Q/R/全P/Cq・origin・固定像・registry・結果 digest に結合する F-a の新しい公開入口。生きた発行物と保存可能な説明値を分ける。§2-5-19-9 (宣言済み。実装・発行済みとは別) |', 2561: '- `verification_response/1` の全 payload と対象指定認証物の公開宣言は v0.23 で §2-5-19-9 に定めた (◆G-01-9 を閉じた)。宣言済みであることを実装・発行済みとしない。', 2562: '- `/2` の args、数値射影、閉包、結果、statement/checker、CL-APPLY の意味は v0.23 で §2-5-19 に定めた (◆G-01 を閉じた。§2-5-19 の独立の点検は未)。MethodCall/ContractValue の容器があることを意味の完成としない。', 3096: '### 3-2. 行の判定 (9 行 + v0.18 の R10。**R10 は §3 の独立の点検 (v0.16) の後に足したので、その点検の範囲の外**。v0.23 の R11 は参照の行で、同じく点検の範囲の外)', 3110: '| **R11 検証済み接頭部と増分認証** (v0.23、参照の行、仮称) | F-a / F-b 共通の、起点から伸びる再構成・reader の取り込み・必須閉包・取得採用系列の検査 | P1 の再構成可能性と同じ意味の証明を保つ。F-c「計算の予算と打ち切り」で扱い、継続運転の測定は F-d | 参照の行。具体方式の採用は未決。F-b は全再構成の checker だけ (§2-5-19-3)。数学の接頭部だけで全体の費用が一定になるとはしない (reader の取り込みも予算を使う) | 変えない (F-b の範囲は全再構成) | なし。S5・S8 へ送らない |'}
PROVENANCE=dict(PROVENANCE,version='5',spec_version='v0.23',spec_lines=V23_PROVENANCE['lines'],spec_sha256_lf=V23_PROVENANCE['sha256_lf'])

V23_TYPE_DECLARATIONS=(
    {'name': 'FiniteUpdate2Args', 'first': 2600, 'last': 2607, 'fields': ({'name': 'model', 'type': 'Point', 'line': 2601}, {'name': 'previous_result', 'type': '?Point', 'line': 2602}, {'name': 'observations', 'type': 'List[ObservationUse]', 'line': 2603}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'ObservationUse', 'first': 2605, 'last': 2605, 'fields': ({'name': 'binding', 'type': 'Point', 'line': 2605}, {'name': 'reading', 'type': 'Point', 'line': 2605}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'ObservationPlan2', 'first': 2610, 'last': 2619, 'fields': ({'name': 'model', 'type': 'Point', 'line': 2611}, {'name': 'projection', 'type': 'MethodCall', 'line': 2612}, {'name': 'generation', 'type': 'MethodCall', 'line': 2613}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'FiniteSegmentProjectionArgs', 'first': 2625, 'last': 2629, 'fields': ({'name': 'frame', 'type': '?FrameProjection', 'line': 2626}, {'name': 'claims', 'type': 'List[ClaimProjection]', 'line': 2627}, {'name': 'time_projection', 'type': 'MethodCall', 'line': 2628}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'FrameProjection', 'first': 2630, 'last': 2634, 'fields': ({'name': 'measurement_contract', 'type': 'ContractRef', 'line': 2631}, {'name': 'kernel', 'type': 'KernelRef', 'line': 2632}, {'name': 'cells', 'type': 'List[ProjectionCell]', 'line': 2633}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'ProjectionCell', 'first': 2635, 'last': 2639, 'fields': ({'name': 'id', 'type': 'str', 'line': 2636}, {'name': 'observation', 'type': 'ContractValue', 'line': 2637}, {'name': 'outcomes', 'type': 'Set[str]', 'line': 2638}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'ClaimProjection', 'first': 2640, 'last': 2644, 'fields': ({'name': 'meaning', 'type': 'ContractRef', 'line': 2641}, {'name': 'law', 'type': 'Point', 'line': 2642}, {'name': 'channel', 'type': 'str', 'line': 2643}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'FiniteJointCountLaw', 'first': 2665, 'last': 2698, 'fields': ({'name': 'model', 'type': 'Point', 'line': 2666}, {'name': 'extends', 'type': '?Point', 'line': 2667}, {'name': 'carrier_by_state', 'type': 'List[str]', 'line': 2668}, {'name': 'channels', 'type': 'List[CountChannel]', 'line': 2669}, {'name': 'rows', 'type': 'List[CountLawRow]', 'line': 2670}, {'name': 'frame_relation', 'type': 'independent_given_carrier', 'line': 2671}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'CountChannel', 'first': 2673, 'last': 2678, 'fields': ({'name': 'id', 'type': 'str', 'line': 2674}, {'name': 'process', 'type': 'BootSlot', 'line': 2675}, {'name': 'route_configs', 'type': 'Set[Point]', 'line': 2676}, {'name': 'domain', 'type': 'MeasurementInterval', 'line': 2677}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'CountLawRow', 'first': 2679, 'last': 2682, 'fields': ({'name': 'marks', 'type': 'List[CountMark]', 'line': 2680}, {'name': 'mass', 'type': 'List[R]', 'line': 2681}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'CountMark', 'first': 2683, 'last': 2687, 'fields': ({'name': 'channel', 'type': 'str', 'line': 2684}, {'name': 'time_ns', 'type': 'int', 'line': 2685}, {'name': 'count', 'type': 'positive_integer', 'line': 2686}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'CountPredicate', 'first': 2705, 'last': 2716, 'fields': ({'name': 'channel', 'type': 'str', 'line': 2706}, {'name': 'interval', 'type': 'MeasurementInterval', 'line': 2707}, {'name': 'lower', 'type': 'nonnegative_integer', 'line': 2708}, {'name': 'upper', 'type': 'nonnegative_integer', 'line': 2709}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'ClaimCell', 'first': 2711, 'last': 2714, 'fields': (), 'branches': ({'tag': 'point', 'payload': 'ClaimCell.point', 'line': 2712}, {'tag': 'open', 'payload': 'ClaimCell.open', 'line': 2713}), 'note': '導出物。状態/digest/保存に入れない。', 'paper_named': True},
    {'name': 'ClaimCell.point', 'first': 2712, 'last': 2712, 'fields': ({'name': 'channel', 'type': 'str', 'line': 2712}, {'name': 'time_ns', 'type': 'int', 'line': 2712}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'ClaimCell.open', 'first': 2713, 'last': 2713, 'fields': ({'name': 'channel', 'type': 'str', 'line': 2713}, {'name': 'start_ns', 'type': 'int', 'line': 2713}, {'name': 'end_ns', 'type': 'int', 'line': 2713}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'AppliedStep2', 'first': 2733, 'last': 2747, 'fields': (), 'branches': ({'tag': 'frame', 'payload': 'AppliedStep2.frame', 'line': 2734}, {'tag': 'claim', 'payload': 'AppliedStep2.claim', 'line': 2739}), 'note': '一次入力から導出する内部状態。呼出し側の一次入力ではない。', 'paper_named': True},
    {'name': 'AppliedStep2.frame', 'first': 2734, 'last': 2738, 'fields': ({'name': 'transition_key', 'type': 'Digest', 'line': 2735}, {'name': 'input_digest', 'type': 'Digest', 'line': 2736}, {'name': 'measurements', 'type': 'Set[MID]', 'line': 2737}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'AppliedStep2.claim', 'first': 2739, 'last': 2747, 'fields': ({'name': 'transition_key', 'type': 'Digest', 'line': 2740}, {'name': 'input_digest', 'type': 'Digest', 'line': 2741}, {'name': 'source', 'type': 'ClaimKey', 'line': 2742}, {'name': 'law_root', 'type': 'Point', 'line': 2743}, {'name': 'predicate', 'type': 'CountPredicate', 'line': 2744}, {'name': 'before_event_digest', 'type': 'Digest', 'line': 2745}, {'name': 'after_event_digest', 'type': 'Digest', 'line': 2746}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'ClaimState', 'first': 2749, 'last': 2755, 'fields': ({'name': 'law', 'type': 'Point', 'line': 2750}, {'name': 'predicates', 'type': 'Set[CountPredicate]', 'line': 2751}), 'branches': (), 'note': '内部状態。細分/満たす行集合を保存欄に追加しない。', 'paper_named': True},
    {'name': 'ClaimKey', 'first': 2757, 'last': 2757, 'fields': ({'name': 'segment', 'type': 'Point', 'line': 2757}, {'name': 'item_slot', 'type': 'str', 'line': 2757}), 'branches': (), 'note': '原ClaimのFAMILY-UNNAMED鍵 (segment,item_slot)。これは鍵の要素の列挙で、新しい保存objectではない。', 'paper_named': True},
    {'name': 'SegmentValueOnlyArgs', 'first': 2813, 'last': 2817, 'fields': (), 'branches': (), 'note': '空args={}。潜在時刻法則は今回未宣言。', 'paper_named': False},
    {'name': 'BootstrapGenerationArgs', 'first': 2827, 'last': 2839, 'fields': ({'name': 'scope', 'type': 'measurement/report/whole_window', 'line': 2830},), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'FiniteUpdateResult1', 'first': 2879, 'last': 2889, 'fields': ({'name': 'joint', 'type': 'List[R]', 'line': 2882}, {'name': 'evidence_mass', 'type': 'R', 'line': 2882}), 'branches': (), 'note': '既存result/1を再利用。applied/述語/細分の欄を追加しない。', 'paper_named': False},
    {'name': 'FiniteUpdateStatement2', 'first': 2923, 'last': 2929, 'fields': ({'name': 'model', 'type': 'Point', 'line': 2925}, {'name': 'request', 'type': 'Point', 'line': 2926}, {'name': 'result', 'type': 'Point', 'line': 2927}, {'name': 'application_digest', 'type': 'Digest', 'line': 2928}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'FiniteUpdateReplay2Args', 'first': 2931, 'last': 2932, 'fields': (), 'branches': (), 'note': '空args={}。具体checkerは全再構成。', 'paper_named': False},
    {'name': 'ProofOutput', 'first': 2934, 'last': 2943, 'fields': ({'name': 'role', 'type': 'normalization/query', 'line': 2935}, {'name': 'statement', 'type': 'ContractValue', 'line': 2936}, {'name': 'checker', 'type': 'ProofRef', 'line': 2937}), 'branches': (), 'note': '既存ProofOutputを再宣言。初回成功の証明はnormalizationだけ。未宣言query成功を作らない。', 'paper_named': True},
    {'name': 'FiniteUpdateTargetCheckArgs', 'first': 2947, 'last': 2947, 'fields': (), 'branches': (), 'note': '空args={}。実入口のWv Point/reader/registry/独立証拠/RateBudgetとは別。', 'paper_named': False},
    {'name': 'Target', 'first': 2950, 'last': 2955, 'fields': ({'name': 'request', 'type': 'Point', 'line': 2951}, {'name': 'result', 'type': 'Point', 'line': 2952}, {'name': 'proofs', 'type': 'Set[Point]', 'line': 2953}, {'name': 'completion', 'type': 'Point', 'line': 2954}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'CallBinding', 'first': 2956, 'last': 2960, 'fields': ({'name': 'work_request', 'type': 'Point', 'line': 2957}, {'name': 'budget', 'type': 'RateBudget', 'line': 2958}, {'name': 'call_digest', 'type': 'Digest', 'line': 2959}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'CheckedProof', 'first': 2961, 'last': 2961, 'fields': ({'name': 'proof', 'type': 'Point', 'line': 2961}, {'name': 'checker', 'type': 'ProofRef', 'line': 2961}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'UpdateCertificateDescription', 'first': 2963, 'last': 2983, 'fields': ({'name': 'contract', 'type': 'sui.f.target_update_certificate/1', 'line': 2964}, {'name': 'value', 'type': 'UpdateCertificateValue', 'line': 2965}), 'branches': (), 'note': '保存可能な説明値。生きた発行物とは別。contractは名前・版の結合。', 'paper_named': True},
    {'name': 'UpdateCertificateValue', 'first': 2965, 'last': 2982, 'fields': ({'name': 'call', 'type': 'CallBinding', 'line': 2966}, {'name': 'target', 'type': 'Target', 'line': 2967}, {'name': 'model', 'type': 'Point', 'line': 2968}, {'name': 'origin', 'type': 'Point', 'line': 2969}, {'name': 'numerical_view', 'type': 'FixedView', 'line': 2970}, {'name': 'check_view', 'type': 'FixedView', 'line': 2971}, {'name': 'registry_key', 'type': 'str', 'line': 2972}, {'name': 'verifier', 'type': 'ProofRef', 'line': 2973}, {'name': 'checked_proofs', 'type': 'List[CheckedProof]', 'line': 2974}, {'name': 'target_digest', 'type': 'Digest', 'line': 2975}, {'name': 'request_input_digest', 'type': 'Digest', 'line': 2976}, {'name': 'closure_digest', 'type': 'Digest', 'line': 2977}, {'name': 'result_digest', 'type': 'Digest', 'line': 2978}, {'name': 'application_digest', 'type': 'Digest', 'line': 2979}, {'name': 'acquisition_digest', 'type': 'Digest', 'line': 2980}, {'name': 'replay_mode', 'type': 'positive_dependencies/exact_environment', 'line': 2981}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'VerificationResponse', 'first': 2985, 'last': 2994, 'fields': (), 'branches': ({'tag': 'verified', 'payload': 'UpdateCertificateDescription', 'line': 2986}, {'tag': 'rejected', 'payload': 'VerificationResponse.rejected', 'line': 2987}, {'tag': 'insufficient', 'payload': 'VerificationResponse.insufficient', 'line': 2991}), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'VerificationResponse.rejected', 'first': 2987, 'last': 2990, 'fields': ({'name': 'call', 'type': 'CallBinding', 'line': 2988}, {'name': 'issues', 'type': 'NonEmptyList[RejectedIssue]', 'line': 2989}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'VerificationResponse.insufficient', 'first': 2991, 'last': 2994, 'fields': ({'name': 'call', 'type': 'CallBinding', 'line': 2992}, {'name': 'issues', 'type': 'NonEmptyList[InsufficientIssue]', 'line': 2993}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'RejectedIssue', 'first': 2996, 'last': 3005, 'fields': ({'name': 'code', 'type': 'schema/shape/noncanonical/rational/unit/unknown_version/normalization/unresolved_reference/reference_kind/proof_mismatch/observation_binding_mismatch/measurement_conflict/clock_unaligned/missing_contract/model_falsified/outside_evaluation_type/result_mismatch', 'line': 2997}, {'name': 'fields', 'type': 'List[str]', 'line': 3002}, {'name': 'evidence', 'type': 'Set[Point]', 'line': 3003}, {'name': 'message', 'type': 'str', 'line': 3004}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'InsufficientIssue', 'first': 3006, 'last': 3013, 'fields': ({'name': 'code', 'type': 'algorithm_unavailable/certificate_incomplete/budget_exhausted/prerequisite_unavailable/clock_unaligned', 'line': 3007}, {'name': 'fields', 'type': 'List[str]', 'line': 3009}, {'name': 'missing', 'type': 'List[VerificationNeed]', 'line': 3010}, {'name': 'evidence', 'type': 'Set[Point]', 'line': 3011}, {'name': 'message', 'type': 'str', 'line': 3012}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'VerificationNeed', 'first': 3014, 'last': 3026, 'fields': (), 'branches': ({'tag': 'capability', 'payload': 'VerificationNeed.capability', 'line': 3015}, {'tag': 'evidence', 'payload': 'VerificationNeed.evidence', 'line': 3019}, {'tag': 'budget', 'payload': 'VerificationNeed.budget', 'line': 3024}), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'VerificationNeed.capability', 'first': 3015, 'last': 3018, 'fields': ({'name': 'contract', 'type': 'ContractRef', 'line': 3016}, {'name': 'purpose', 'type': 'reading/generation/clock/replay/proof/authentication', 'line': 3017}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'VerificationNeed.evidence', 'first': 3019, 'last': 3023, 'fields': ({'name': 'target', 'type': 'Point', 'line': 3020}, {'name': 'purpose', 'type': 'generation/clock/support/acquisition/adoption_chain', 'line': 3021}, {'name': 'contract', 'type': '?ContractRef', 'line': 3022}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'VerificationNeed.budget', 'first': 3024, 'last': 3026, 'fields': ({'name': 'phase', 'type': 'reader/authentication/projection/replay/proof', 'line': 3025},), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': False},
    {'name': 'TargetVerificationReturn', 'first': 3028, 'last': 3038, 'fields': ({'name': 'response', 'type': 'VerificationResponse', 'line': 3029}, {'name': 'issued', 'type': 'VerifiedFiniteUpdate | None', 'line': 3030}), 'branches': (), 'note': '全欄は紙の当該宣言。nullable/列/集合を保存し、外側の契約・Bodyと区別。', 'paper_named': True},
    {'name': 'VerifiedFiniteUpdate', 'first': 3030, 'last': 3038, 'fields': (), 'branches': (), 'note': '生きた発行物の不透明な型。factoryの実検査成功が必要。公開の保存欄は宣言されておらず説明値から構築しない。', 'paper_named': True},
)
V23_CONTRACT_DECLARATIONS=(
    {'name': 'sui.f.finite_update', 'version': '2', 'line': 2599, 'category': 'method', 'payload': 'FiniteUpdate2Args', 'new': True},
    {'name': 'sui.f.observation_plan', 'version': '2', 'line': 2609, 'category': 'prediction', 'payload': 'ObservationPlan2', 'new': True},
    {'name': 'sui.fb.finite_segment_projection', 'version': '1', 'line': 2624, 'category': 'method', 'payload': 'FiniteSegmentProjectionArgs', 'new': True},
    {'name': 'sui.fb.no_arrival', 'version': '1', 'line': 2655, 'category': 'claim', 'payload': 'CoverageClaim', 'new': True},
    {'name': 'sui.fb.count_exactly_one', 'version': '1', 'line': 2656, 'category': 'claim', 'payload': 'CoverageClaim', 'new': True},
    {'name': 'sui.fb.finite_joint_count_law', 'version': '1', 'line': 2662, 'category': 'prediction', 'payload': 'FiniteJointCountLaw', 'new': True},
    {'name': 'sui.fb.segment_value_only', 'version': '1', 'line': 2813, 'category': 'method', 'payload': 'SegmentValueOnlyArgs', 'new': True},
    {'name': 'sui.fb.bootstrap_generation', 'version': '1', 'line': 2827, 'category': 'method', 'payload': 'BootstrapGenerationArgs', 'new': True},
    {'name': 'sui.f.finite_update_result', 'version': '1', 'line': 2879, 'category': 'reused', 'payload': 'FiniteUpdateResult1', 'new': False},
    {'name': 'sui.f.finite_update_statement', 'version': '2', 'line': 2923, 'category': 'statement', 'payload': 'FiniteUpdateStatement2', 'new': True},
    {'name': 'sui.f.finite_update_replay', 'version': '2', 'line': 2931, 'category': 'checker', 'payload': 'FiniteUpdateReplay2Args', 'new': True},
    {'name': 'sui.f.finite_update_target_check', 'version': '1', 'line': 2947, 'category': 'checker', 'payload': 'FiniteUpdateTargetCheckArgs', 'new': True},
    {'name': 'sui.f.target_update_certificate', 'version': '1', 'line': 2964, 'category': 'description', 'payload': 'UpdateCertificateValue', 'new': True},
)
V23_CLOSING_ITEMS=(
    {'id': 'V23-C01-01', 'section': 1, 'line': 2769, 'item': '同じFrameの再配送'},
    {'id': 'V23-C01-02', 'section': 1, 'line': 2769, 'item': '別k'},
    {'id': 'V23-C01-03', 'section': 1, 'line': 2769, 'item': '重なる無到着'},
    {'id': 'V23-C01-04', 'section': 1, 'line': 2769, 'item': '件数1'},
    {'id': 'V23-C01-05', 'section': 1, 'line': 2769, 'item': '別kindの同義'},
    {'id': 'V23-C01-06', 'section': 1, 'line': 2769, 'item': '異なる過程・epoch'},
    {'id': 'V23-C01-07', 'section': 1, 'line': 2769, 'item': '点セル'},
    {'id': 'V23-C01-08', 'section': 1, 'line': 2769, 'item': '部分Support'},
    {'id': 'V23-C01-09', 'section': 1, 'line': 2769, 'item': '後着端点'},
    {'id': 'V23-C01-10', 'section': 1, 'line': 2769, 'item': '法則の拡張'},
    {'id': 'V23-C01-11', 'section': 1, 'line': 2769, 'item': 'ゼロ分母'},
    {'id': 'V23-C01-12', 'section': 1, 'line': 2769, 'item': 'CE1の三結果'},
    {'id': 'V23-C01-13', 'section': 1, 'line': 2769, 'item': '未宣言の法則で成功しない'},
    {'id': 'V23-C02-01', 'section': 2, 'line': 2787, 'item': '申告Iから独立した必要集合'},
    {'id': 'V23-C02-02', 'section': 2, 'line': 2787, 'item': '不足'},
    {'id': 'V23-C02-03', 'section': 2, 'line': 2787, 'item': '余分'},
    {'id': 'V23-C02-04', 'section': 2, 'line': 2787, 'item': '別origin'},
    {'id': 'V23-C02-05', 'section': 2, 'line': 2787, 'item': '別モデル'},
    {'id': 'V23-C02-06', 'section': 2, 'line': 2787, 'item': '将来依存'},
    {'id': 'V23-C02-07', 'section': 2, 'line': 2787, 'item': '参照の種類違い'},
    {'id': 'V23-C03-01', 'section': 3, 'line': 2803, 'item': '連続更新'},
    {'id': 'V23-C03-02', 'section': 3, 'line': 2803, 'item': '再配送'},
    {'id': 'V23-C03-03', 'section': 3, 'line': 2803, 'item': '同じCqの再採用'},
    {'id': 'V23-C03-04', 'section': 3, 'line': 2803, 'item': '別系列'},
    {'id': 'V23-C03-05', 'section': 3, 'line': 2803, 'item': '長い履歴による不足'},
    {'id': 'V23-C03-06', 'section': 3, 'line': 2803, 'item': '前履歴を落として新規適用しない'},
    {'id': 'V23-C04-01', 'section': 4, 'line': 2821, 'item': '正常な遅着'},
    {'id': 'V23-C04-02', 'section': 4, 'line': 2821, 'item': 'Unavailable'},
    {'id': 'V23-C04-03', 'section': 4, 'line': 2821, 'item': '端点の開閉'},
    {'id': 'V23-C04-04', 'section': 4, 'line': 2821, 'item': '時計違い'},
    {'id': 'V23-C04-05', 'section': 4, 'line': 2821, 'item': '後着報告'},
    {'id': 'V23-C04-06', 'section': 4, 'line': 2821, 'item': '全窓の条件'},
    {'id': 'V23-C05-01', 'section': 5, 'line': 2841, 'item': '全窓の正しい対照'},
    {'id': 'V23-C05-02', 'section': 5, 'line': 2841, 'item': 'Started/Endedだけの偽の被覆'},
    {'id': 'V23-C05-03', 'section': 5, 'line': 2841, 'item': '部分Support'},
    {'id': 'V23-C05-04', 'section': 5, 'line': 2841, 'item': '後から作った正しい報告'},
    {'id': 'V23-C05-05', 'section': 5, 'line': 2841, 'item': '過去のGap'},
    {'id': 'V23-C05-06', 'section': 5, 'line': 2841, 'item': '後着証拠による別Xの再認証'},
    {'id': 'V23-C06-01', 'section': 6, 'line': 2859, 'item': '同値再提示'},
    {'id': 'V23-C06-02', 'section': 6, 'line': 2859, 'item': '両立する範囲'},
    {'id': 'V23-C06-03', 'section': 6, 'line': 2859, 'item': '論理的な矛盾'},
    {'id': 'V23-C06-04', 'section': 6, 'line': 2859, 'item': 'モデル反証'},
    {'id': 'V23-C06-05', 'section': 6, 'line': 2859, 'item': '別slot'},
    {'id': 'V23-C06-06', 'section': 6, 'line': 2859, 'item': '後着Xc'},
    {'id': 'V23-C06-07', 'section': 6, 'line': 2859, 'item': 'XnumとXuseの差'},
    {'id': 'V23-C07-01', 'section': 7, 'line': 2873, 'item': 'Gの遅延保存'},
    {'id': 'V23-C07-02', 'section': 7, 'line': 2873, 'item': '同内容の別origin'},
    {'id': 'V23-C07-03', 'section': 7, 'line': 2873, 'item': '取得意図だけ'},
    {'id': 'V23-C07-04', 'section': 7, 'line': 2873, 'item': 'R/PのCq前取得'},
    {'id': 'V23-C07-05', 'section': 7, 'line': 2873, 'item': 'Wpの循環'},
    {'id': 'V23-C07-06', 'section': 7, 'line': 2873, 'item': '取り直しなしの合法例'},
    {'id': 'V23-C08-01', 'section': 8, 'line': 2914, 'item': 'CE1正しい連言'},
    {'id': 'V23-C08-02', 'section': 8, 'line': 2914, 'item': 'CE1二重適用'},
    {'id': 'V23-C08-03', 'section': 8, 'line': 2914, 'item': 'CE1追加を捨てる'},
    {'id': 'V23-C08-04', 'section': 8, 'line': 2914, 'item': '同じ数値で適用履歴が違う対照'},
    {'id': 'V23-C09-01', 'section': 9, 'line': 3059, 'item': 'Q差し替え'},
    {'id': 'V23-C09-02', 'section': 9, 'line': 3059, 'item': 'R差し替え'},
    {'id': 'V23-C09-03', 'section': 9, 'line': 3059, 'item': 'P差し替え'},
    {'id': 'V23-C09-04', 'section': 9, 'line': 3059, 'item': 'Cq差し替え'},
    {'id': 'V23-C09-05', 'section': 9, 'line': 3059, 'item': '違うapplication_digest'},
    {'id': 'V23-C09-06', 'section': 9, 'line': 3059, 'item': '自己申告の成功'},
    {'id': 'V23-C09-07', 'section': 9, 'line': 3059, 'item': '別環境'},
    {'id': 'V23-C09-08', 'section': 9, 'line': 3059, 'item': '別budget'},
    {'id': 'V23-C09-09', 'section': 9, 'line': 3059, 'item': '偽の発行物'},
    {'id': 'V23-C09-10', 'section': 9, 'line': 3059, 'item': 'proof checkerの版違い'},
    {'id': 'V23-C09-11', 'section': 9, 'line': 3059, 'item': '未宣言のprefix'},
    {'id': 'V23-C09-12', 'section': 9, 'line': 3059, 'item': '内側返答と外側Failureの取り違え'},
    {'id': 'V23-C10-01', 'section': 10, 'line': 3075, 'item': '再採用'},
    {'id': 'V23-C10-02', 'section': 10, 'line': 3075, 'item': 'Stale'},
    {'id': 'V23-C10-03', 'section': 10, 'line': 3075, 'item': '新しい正のreader'},
    {'id': 'V23-C10-04', 'section': 10, 'line': 3075, 'item': '古い不在'},
    {'id': 'V23-C10-05', 'section': 10, 'line': 3075, 'item': 'registry差し替え'},
    {'id': 'V23-C10-06', 'section': 10, 'line': 3075, 'item': '必要bytesの喪失'},
    {'id': 'V23-C10-07', 'section': 10, 'line': 3075, 'item': '現在のConflict'},
)

V23_EXAMPLE_DATA={
    'CE1':dict(source=(2891,2910),prior=('1/2','1/2'),
        rows=(('000','1/8','1/64'),('001','1/8','3/64'),('010','1/8','3/64'),('011','1/8','9/64'),
              ('100','1/8','3/64'),('101','1/8','9/64'),('110','1/8','9/64'),('111','1/8','27/64')),
        first='x1=x2=0',later='x2=x3=0',
        paper_Z_first=('1/4','1/16'),paper_Z_conjunction=('1/8','1/64'),paper_increment=('1/2','1/4'),
        expected=dict(correct=dict(weights=('1/16','1/128'),joint=('8/9','1/9'),evidence_mass='9/128'),
                      double=dict(weights=('1/32','1/512'),joint=('16/17','1/17'),evidence_mass='17/512'),
                      discard=dict(weights=('1/8','1/32'),joint=('4/5','1/5'),evidence_mass='5/32'))),
    'M07':dict(source=(2912,2912),prior=('1/2','1/2'),
        rows=(((1,0),'1/2','0'),((0,1),'1/2','0'),((0,0),'0','1/2'),((1,1),'0','1/2')),
        predicates=('N1+N2=1','N1+N2=0'),paper_joint=(('1','0'),('0','1')),same_atoms=('I1','I2')),
    'overlap':dict(source=(2647,2647),prior=('1/2','1/2'),
        diagonal_u=('3/4','1/4'),diagonal_v=('1/4','3/4'),cells={'a':('u',),'b':('u','v')},
        paper_probabilities=('1/2','1'),paper_sum='3/2',
        negative='この重なるoutcomesを未宣言の報告生成法則のまま成功させる',
        nearest_legal='同じ核でcellのoutcomesを{u}/{v}の分割に直す（仕様から作る合法対照）'),
    'FB23-R04':dict(source=(2757,2757),
        before=dict(joint=('3/4','1/4'),evidence_mass='1/2'),
        after=dict(joint=('9/10','1/10'),evidence_mass='5/16'),
        primary_input_status='資料不足: u/vの同時表と事前分布はこの例に宣言されていない',
        arithmetic_scope='表示されたjointと累積質量から重み・追加尤度を逆算する整合確認だけ。原入力からの再計算ではない。',
        derived_weights_before=('3/8','1/8'),derived_weights_after=('9/32','1/32'),derived_ratio=('3/4','1/4'),
        negative='同じ原Claimを別channelへ写して二度適用し、数値がafterへ変わる',
        nearest_legal='同じClaimKey・同じ正準述語の再読はno-op。異なる正準述語ならCL-APPLYで成功させない'),
    'digest_logic':dict(source=(2761,2765),law_rows=(((0,0),'1'),),
        before=('N1=0','N2=0'),added='N1=1',same_model_row_set=((0,0),),
        expected=('論理的矛盾','model_falsified'),
        second_logical_witness=(1,0),note='digestのbytes値は紙にない。行集合の同一性と論理分類の相違を検査し、hash値を作らない'),
    'triple':dict(source=(2851,2855),predicates=('N1=0','N2=0','N1+N2=1'),
        pair_witnesses=(((0,1),(0,0)),((0,2),(0,1)),((1,2),(1,0))),
        all_conjunction='矛盾',note='第三式が非負整数N1,N2を0/1に制限する。二つずつの存在確認だけで全体を成功させない'),
}
GAPS['G-EXAMPLE-UV']=dict(classification='直すべき',status='未対応',
    message='FB23-R04の結果値は記載されているが、事前分布とu/v同時表が未記載。結果からの逆算を原入力からの独立再計算と数えない。',
    sources=(source(FB,2757),))

V23_SECTIONS=((1,2590,2772),(2,2773,2790),(3,2791,2808),(4,2809,2824),(5,2825,2844),
              (6,2845,2862),(7,2863,2876),(8,2877,2917),(9,2918,3062),(10,3063,3078))
V23_SECTION_RULES={
    1:('INV-6','INV-7','INV-12','背骨⑤'),2:('INV-5','INV-8','背骨⑤'),
    3:('INV-6','INV-8','背骨⑤'),4:('INV-12','INV-8','背骨⑤'),5:('INV-12.a','INV-7.b','背骨⑤'),
    6:('INV-7','INV-8','背骨⑤'),7:('INV-9','INV-5','背骨⑤'),8:('INV-6','背骨⑤'),
    9:('INV-3','INV-4','INV-9.a','背骨⑤'),10:('INV-6','INV-7','INV-8','INV-9','背骨⑤')}
def _v23_section(line):
    return next((n for n,a,b in V23_SECTIONS if a<=line<=b),10 if line>3078 else 1)
def _v23_add(id,kind,subject,first,last=None,**kw):
    sec=_v23_section(first)
    row=_wire_add(id,kind,subject,refs=(source(FB,first,last),),
                  rules=V23_SECTION_RULES[sec],entries=('I-2','I-3') if sec in (1,4,5,6) else ('I-3',),**kw)
    row['section']=sec;row['owner']=NA
    row['evidence']='v0.23の紙と公開宣言、独立な一次入力。実装出力を期待値の根にしない。'
    row['count_as_pass']=False
    return row

V23_TYPE_BY_NAME={d['name']:d for d in V23_TYPE_DECLARATIONS}
V23_TYPE_TARGETS={n:'T.v23.type.'+n for n in V23_TYPE_BY_NAME}
V23_REFERENCE_TARGETS={n:'T.wire.type.'+n for n in WIRE_TYPES}
V23_REFERENCE_TARGETS.update({n:'T.public.'+n for n in PUBLIC_CLASS_BY_NAME})
V23_REFERENCE_TARGETS.update({'RateBudget':'T.public.RateBudget','MID':'T.wire.type.MeasurementId'})
V23_REFERENCE_TARGETS.update(V23_TYPE_TARGETS)
V23_SCALARS={
    'Point':dict(meaning='EntryのCID。Refと交換しない。',source=source(FA,28)),
    'R':dict(meaning='既約・分母正の正準厳密有理数。',source=source(FA,27)),
    'Digest':dict(meaning='契約が指定する正準内容のdigest。',source=source(FB,2588)),
    'str':dict(meaning='文字列。参照として使う意味は宣言した欄だけ。',source=source(FB,3034)),
    'int':dict(meaning='整数。boolはintではない。',source=source(FA,27)),
    'positive_integer':dict(meaning='正整数。',source=source(FB,2686)),
    'nonnegative_integer':dict(meaning='非負整数。',source=source(FB,2708,2709)),
}
for _decl in V23_TYPE_DECLARATIONS:
    _name=_decl['name'];_tid=V23_TYPE_TARGETS[_name]
    _row=_v23_add(_tid,'relation',_name,_decl['first'],_decl['last'],use=_decl['note'],representation='v0.23の型宣言。紙の名前/匿名値の索引を区別')
    _row['paper_named']=_decl['paper_named']
    _children=[]
    for _field in _decl['fields']:
        _fid=_tid+'.field.'+_field['name'];_ann=_field['type'];_deps=tuple(dict.fromkeys(V23_REFERENCE_TARGETS[t] for t in _type_tokens(_ann) if t in V23_REFERENCE_TARGETS))
        _fr=_v23_add(_fid,'field',_name,_field['line'],_decl['last'] if _field['name']=='code' else _field['line'],
                    fields=_field['name'],value_type=_ann,use='宣言された欄の型は '+_ann+'。'+_decl['note'],
                    presence='必須・null可（省略不可）' if _ann.startswith('?') or ' | None' in _ann else '必須・非null（空の列/集合の許可は各意味条件に従う）',
                    related=(_tid,)+_deps,representation='v0.23の宣言欄')
        _fr['negative']='この欄だけの欠落・別型・非正準値・別対象。宣言の不正と必要証拠の不足を区別する。'
        _fr['nearest_legal']='同じ一次入力の他の欄を保ち、この欄が宣言された型・対象・presenceを満たす対照。'
        _children.append(_fid)
        _values=[]
        if _ann.startswith('?'):_values=[('null','null'),('value',_ann[1:])]
        elif _ann=='VerifiedFiniteUpdate | None':_values=[('issued','VerifiedFiniteUpdate'),('none','None')]
        elif '/' in _ann and not _ann.startswith('sui.'):_values=[(v,v) for v in _ann.split('/')]
        elif _ann=='independent_given_carrier':_values=[(_ann,_ann)]
        for _i,(_tag,_payload) in enumerate(_values):
            _bid=_fid+'.branch.'+_tag
            _br=_v23_add(_bid,'branch',_name+'.'+_field['name'],_field['line'],_decl['last'] if _field['name']=='code' else _field['line'],
                        fields=_field['name'],branch=_tag,value_type=_payload,use='宣言のnullable/Literal枝。別の枝を足さない。',related=(_fid,))
            _children.append(_bid)
    for _branch in _decl['branches']:
        _bid=_tid+'.branch.'+_branch['tag'];_payload=V23_TYPE_TARGETS[_branch['payload']]
        _v23_add(_bid,'branch',_name,_branch['line'],branch=_branch['tag'],value_type=_branch['payload'],
                 use='kind/valueの和型。枝ごとの全欄はpayload型へ。',related=(_tid,_payload))
        _children.append(_bid)
        for _field,_ann in (('kind',_branch['tag']),('value',_branch['payload'])):
            _fid=_bid+'.field.'+_field
            _v23_add(_fid,'field',_name,_branch['line'],fields=_field,branch=_branch['tag'],value_type=_ann,
                     use='和型の'+_field+'。kindの一致とvalueの全型を別々に照合する。',related=(_bid,_payload))
            _children.append(_fid)
    _row['related_targets']=tuple(_children)
    _decl['target']=_tid;_decl['children']=tuple(_children)

for _decl in V23_CONTRACT_DECLARATIONS:
    _tid='T.v23.contract.'+_decl['name']+'/'+_decl['version'];_decl['target']=_tid
    _decl['payload_target']=V23_REFERENCE_TARGETS[_decl['payload']]
    _row=_v23_add(_tid,'contract',_decl['name'],_decl['line'],contract=_decl['name']+'/'+_decl['version'],
                  body='Prediction' if _decl['category']=='prediction' else NA,
                  role='MODEL / PREDICTION' if _decl['category']=='prediction' else NA,
                  use=('既存の意味/保存形を再利用。' if not _decl['new'] else '紙が宣言した名前・版。')+' '+_decl['category']+'の契約。独立Bodyの新設を意味しない。',
                  related=(_decl['payload_target'],),representation='新規契約宣言' if _decl['new'] else '既存契約の再利用')
    _decl['parents']='Front(Ev(宣言に実使用した出来事))。Predictionを因果の親へ昇格させない' if _decl['category']=='prediction' else NA
    if _decl['category']=='claim':
        _tag='no_arrival' if _decl['line']==2655 else 'count_exactly_one'
        _row['branch']=_tag
        _v23_add(_tid+'.kind','branch',_decl['name'],_decl['line'],2660,fields='kind',branch=_tag,
                 use='既存Claimのkind/contract。lower/upperをClaimの保存欄に追加しない。',related=(_tid,'T.wire.type.CoverageClaim'))
    if _decl['category']=='prediction':
        _row['edges']=_decl['parents']+'。about/basisは19-1の各宣言に従う。'
for _field,_literal,_line in (('output_contract','sui.f.finite_update_result/1',2606),('algorithm_draws','[]',2607)):
    _v23_add('T.v23.method.'+_field,'field','finite_update/2の方法宣言',_line,fields=_field,
             value_type=_literal,use='Qの方法に固定する宣言値。args内へキーを増やさない。',related=('T.v23.contract.sui.f.finite_update/2',))

# 段落単位でも意味を保持する。コード/表の全欄とは別に、式・禁止・失敗を対象化。
V23_CLAUSES=[];_in_code=False
for _line,_text in V23_SECTION_LINES.items():
    if _text.startswith('```'):
        _in_code=not _in_code;continue
    if _in_code or not _text.strip() or _text.startswith(('#','|','>')):
        continue
    _tid='T.v23.clause.'+str(_line)
    _row=_v23_add(_tid,'relation','§19-'+str(_v23_section(_line))+'の意味条件',_line,use=_text,
                  related=tuple(d['target'] for d in V23_TYPE_DECLARATIONS if _v23_section(d['first'])==_v23_section(_line)))
    V23_CLAUSES.append(dict(line=_line,text=_text,target=_tid))
V23_CLAUSES=tuple(V23_CLAUSES)
V23_FAILURE_CLASSIFICATION=[]
for _line in range(3046,3056):
    _cols=V23_SECTION_LINES[_line].split('|')[1:-1];_tid='T.v23.failure.'+str(_line)
    _condition,_expected=(_c.strip() for _c in _cols)
    _row=_v23_add(_tid,'relation','失敗の共通分類',_line,use=_condition+' → '+_expected,
                  related=(V23_TYPE_TARGETS['RejectedIssue'],V23_TYPE_TARGETS['InsufficientIssue'],V23_TYPE_TARGETS['TargetVerificationReturn']))
    _row['negative']='この条件の返し方を別層・不足・成功に置換する。'
    _row['nearest_legal']='同じ原因を表の指定層・分類で返す。予期しない例外を通常返答に潰さない。'
    V23_FAILURE_CLASSIFICATION.append(dict(line=_line,condition=_condition,expected=_expected,target=_tid))
V23_FAILURE_CLASSIFICATION=tuple(V23_FAILURE_CLASSIFICATION)
for _item in V23_CLOSING_ITEMS:
    _tid='T.v23.close.'+_item['id'];_item['target']=_tid
    _clause='T.v23.clause.'+str(_item['line'])
    _row=_v23_add(_tid,'relation',_item['item'],_item['line'],use='閉じる条件の独立した項: '+_item['item'],
                  related=(_clause,),representation='紙の閉じる条件の項。新しい規則IDではない')
    _row['negative']='「'+_item['item']+'」を他の状態へ取り違える対照。正否・分類の根拠は当該19節の決定と失敗。'
    _row['nearest_legal']='他の一次入力を保ち、「'+_item['item']+'」の宣言条件/分類に従う対照。'
    _item['rules']=_row['rules'];_item['entries']=_row['entries']

V23_EXAMPLES=[]
for _name,_example in V23_EXAMPLE_DATA.items():
    _tid='T.v23.example.'+_name;_a,_b=_example['source']
    _row=_v23_add(_tid,'relation',_name,_a,_b,use='紙の具体例を固定した識別対照。fractionsによる独立計算はデータ自己点検で行う。',
                  status='未対応' if _name=='FB23-R04' else '整理済み',issues=('G-EXAMPLE-UV',) if _name=='FB23-R04' else (),
                  related=(V23_TYPE_TARGETS['CountPredicate'],V23_TYPE_TARGETS['ClaimState'],V23_TYPE_TARGETS['AppliedStep2']))
    _row['negative']=_example.get('negative',{
        'CE1':'重なりを独立として二重適用、または後の追加情報を捨てる。',
        'M07':'同じ原子集合なら同じ述語/事後とする。',
        'digest_logic':'同じモデル上の行集合/digestなら論理状態も同じとする。',
        'triple':'二つずつ両立すれば全部でも両立するとする。'}.get(_name,'未宣言の結果を成功にする。'))
    _row['nearest_legal']=_example.get('nearest_legal',{
        'CE1':'同じ表で全連言から(8/9,1/9;9/128)。',
        'M07':'原子集合は同じでも述語1/0を区別して事後(1,0)/(0,1)。',
        'digest_logic':'N1=1追加の論理矛盾とmodel_falsifiedを区別。',
        'triple':'二つだけの各合法な対と、三つ全体の矛盾を区別。'}.get(_name,'宣言条件を満たす対照。'))
    V23_EXAMPLES.append(dict(name=_name,target=_tid,source=source(FB,_a,_b),
                             calculation='partial' if _name=='FB23-R04' else 'checked',
                             count_as_pass=False,execution='not_run'))
V23_EXAMPLES=tuple(V23_EXAMPLES)
for _variant,_line in (('correct',2908),('double',2909),('discard',2910)):
    _v23_add('T.v23.example.CE1.'+_variant,'relation','CE1 '+_variant,_line,
             use='紙の数値: '+str(V23_EXAMPLE_DATA['CE1']['expected'][_variant]),
             related=('T.v23.example.CE1',),representation='正しい計算と二種の誤実装の識別値')

V23_CHANGED_DISPOSITIONS=[]
for _line,_text in V23_CHANGED_LINES.items():
    _tid='T.v23.changed.'+str(_line)
    _row=_v23_add(_tid,'relation','v0.23の関連差分',_line,use=_text,
                  status='未採用' if _line==3110 else '整理済み',issues=('G-R11',) if _line==3110 else (),
                  related=('T.v23.clause.2799',) if _line in (3096,3110) else ())
    V23_CHANGED_DISPOSITIONS.append(dict(line=_line,target=_tid,reason='R11の参照行。方式の採用は未決' if _line==3110 else '変更された条件をそのまま保持'))
V23_CHANGED_DISPOSITIONS=tuple(V23_CHANGED_DISPOSITIONS)
GAPS['G-R11']=dict(classification='後で',status='未採用',message='検証済み接頭部・増分認証の方式は未採用。F-bは全再構成。',sources=(source(FB,2805),source(FB,3110)))

# 全497行の所在。空行/見出し/コード境界/比喩以外は対象へ接続する。
V23_SOURCE_COVERAGE=[]
for _line,_text in V23_SECTION_LINES.items():
    _targets=tuple(r['id'] for r in _rows if r['id'].startswith('T.v23.') and any(s['path']==FB and s['first']<=_line<=s['last'] for s in r['sources']))
    if _targets:
        _reason='宣言/欄/枝/意味条件/失敗/閉じる条件/具体例に対応'
    elif not _text.strip() or _text.startswith(('#','```','>','|---')):
        _reason='適用外: 空行・見出し・コード境界・表の区切り・説明の比喩'
    elif _text.lstrip().startswith(('|','{','}','/')) or _text.strip() in ('args = {','value = {'):
        _reason='構文の補助行。節の型へ対応'
        _targets=tuple(d['target'] for d in V23_TYPE_DECLARATIONS if _v23_section(d['first'])==_v23_section(_line))
    else:
        _tid='T.v23.text.'+str(_line)
        _v23_add(_tid,'relation','未分割の紙の行',_line,use=_text,related=())
        _targets=(_tid,);_reason='独立の行として保持。欄の宣言は別に列挙する'
    V23_SOURCE_COVERAGE.append(dict(line=_line,targets=_targets,reason=_reason))
V23_SOURCE_COVERAGE=tuple(V23_SOURCE_COVERAGE)
TARGETS=tuple(_rows)
TARGET_BY_ID={r['id']:r for r in TARGETS}

# FBT-05: 旧90行を全件追跡し、旧IDから新宣言/意味条件へ接続する。
def _v23_type_id(name,field=None):
    return V23_TYPE_TARGETS[name]+('.field.'+field if field else '')
def _v23_clause(line):
    return 'T.v23.clause.'+str(line)
def _old_g01_links(row):
    id=row['id']
    if id.startswith('T.segment_binding') or id=='T.paper.472':
        return ('T.wire.type.SegmentBinding',_v23_clause(2619),_v23_clause(2835),_v23_clause(2839),_v23_clause(2815))
    if id=='T.finite_update2' or id=='T.rel.numeric_update2':
        return ('T.v23.contract.sui.f.finite_update/2',_v23_type_id('FiniteUpdate2Args'),_v23_clause(2777),_v23_clause(2795),_v23_clause(2885))
    if id.startswith('T.target_certificate') or id=='T.wire.unresolved.target_certificate':
        fields={'target.Q':('Target','request'),'target.R':('Target','result'),'target.proofs[]':('Target','proofs'),
                'target.Cq':('Target','completion'),'origin':('UpdateCertificateValue','origin'),
                'registry':('UpdateCertificateValue','registry_key'),'result_digest':('UpdateCertificateValue','result_digest')}
        if row['field'] in fields:return (_v23_type_id(*fields[row['field']]),_v23_clause(3036),_v23_clause(3038))
        if row['field']=='view':return (_v23_type_id('UpdateCertificateValue','numerical_view'),_v23_type_id('UpdateCertificateValue','check_view'),_v23_clause(3036))
        return (_v23_type_id('Target'),_v23_type_id('UpdateCertificateDescription'),_v23_type_id('TargetVerificationReturn'),_v23_clause(2947),_v23_clause(3038))
    if id=='T.verification.response':return (_v23_type_id('VerificationResponse'),_v23_clause(3038))
    if id=='T.verification.issued_certificate':return (_v23_type_id('TargetVerificationReturn','issued'),_v23_type_id('VerifiedFiniteUpdate'),_v23_clause(3038))
    if id.startswith('T.artifact'):
        mapping={'T.artifact_preflight':'FPreflightFacts','T.artifact_bridge':'FLegacyBridgeRequest','T.artifact_limit':'FLimitFactsRequest'}
        prefix=next((k for k in mapping if id==k or id.startswith(k+'.')),None)
        root='T.public.'+mapping[prefix] if prefix else 'T.wire.type.ExistingMathArtifact2'
        direct=root+'.field.'+row['field'].split('.')[0].removesuffix('[]')
        return (root,)+((direct,) if direct in TARGET_BY_ID else ())+(_v23_clause(3071),_v23_clause(3073))
    if id=='T.registry_new' or id in ('T.paper.479','T.paper.481','T.paper.482'):
        return (_v23_clause(2586),_v23_clause(3071),_v23_clause(3073))
    if id in ('T.rel.verify','T.paper.485','T.wire.unresolved.verification_payload'):
        return (_v23_type_id('VerificationResponse'),_v23_type_id('UpdateCertificateDescription'),_v23_clause(2947),_v23_clause(3038))
    if id in ('T.rel.coverage','T.wire.unresolved.binding_support','T.wire.logical.REF-1055'):
        return (_v23_clause(2813),_v23_clause(2833),_v23_clause(2837),_v23_clause(2839))
    if id in ('T.paper.182','T.paper.183','T.paper.184'):
        return (_v23_type_id('FiniteUpdate2Args'),_v23_type_id('ClaimState'),_v23_clause(2755),_v23_clause(2947))
    if id.startswith('T.wire.type.VerificationResponse'):
        suffix=id.removeprefix('T.wire.type.VerificationResponse')
        return (_v23_type_id('VerificationResponse')+suffix,_v23_clause(3038))
    if id=='T.wire.contract.verification_response':return (_v23_type_id('VerificationResponse'),_v23_clause(3038))
    if id=='T.wire.unresolved.proof_statement':return (_v23_type_id('FiniteUpdateStatement2'),_v23_type_id('FiniteUpdateReplay2Args'),_v23_clause(2941),_v23_clause(2943))
    if id=='T.wire.unresolved.cl_apply':return (_v23_clause(2757),_v23_clause(2851),_v23_clause(2853),_v23_clause(2855))
    if id in ('T.wire.unresolved.method_paths','T.wire.logical.REF-1028'):
        return (_v23_clause(2777),_v23_clause(2779),_v23_clause(2781),'T.v23.changed.2306')
    if id=='T.wire.logical.E0-07':return tuple(x['target'] for x in V23_FAILURE_CLASSIFICATION)
    if id=='T.wire.logical.CMP-15':return (_v23_type_id('CallBinding'),_v23_type_id('TargetVerificationReturn'),_v23_clause(3036),_v23_clause(3038))
    if id=='T.wire.logical.PATH-QOBS':return (_v23_clause(2619),_v23_clause(2777),_v23_clause(2885))
    if id=='T.wire.logical.PATH-LINK-ACQUISITION':return (_v23_clause(2865),_v23_clause(2867),_v23_clause(2869),_v23_clause(3036))
    if id=='T.wire.text.2583':return tuple(_v23_clause(line) for line in (2769,2787,2803,2821,2841,2859,2873,2914,3059,3075))
    raise ValueError('G-01の対応がない: '+id)
V23_G01_RESOLUTIONS=[]
for _id in DRAFT4_G01_IDS:
    _row=TARGET_BY_ID[_id];_old=DRAFT4_TARGET_BY_ID[_id]
    _links=_old_g01_links(_row)
    if not all(t in TARGET_BY_ID for t in _links):
        raise ValueError('新対応先がない: '+_id+' '+str(_links))
    _row['related_targets']=tuple(dict.fromkeys(_row.get('related_targets',())+_links))
    _row['sources']+=tuple(s for t in _links for s in TARGET_BY_ID[t]['sources'] if s['path']==FB)
    _row['issues']=tuple(i for i in _row['issues'] if not i.startswith('G-01'))
    _row['status']='整理済み' if not _row['issues'] else _row['status']
    if _id=='T.finite_update2':
        _row['body']=NA;_row['role']=NA
        _row['representation']='Qのmethod/argsの契約。独立Body・Role/Categoryなし'
    if _id.startswith('T.target_certificate.'):
        _row['presence']='必須・非null。対象のSet/固定像/registry等の全結合は19-9に従う'
    if _id.startswith('T.artifact') and _row['kind']=='field':
        _field=_row['field'];_public_name=None;_public_field=None
        if _id.startswith('T.artifact_preflight'):
            _public_name='RequiredCapability' if '.' in _field else 'FPreflightFacts'
            _public_field=_field.split('.')[-1].removesuffix('[]')
        elif _id.startswith('T.artifact_bridge'):
            _public_name='FLegacyBridgeRequest';_public_field=_field.removesuffix('[]')
        elif _id.startswith('T.artifact_limit'):
            _public_name='FLimitFactsRequest';_public_field='declaration'
        elif _field.startswith('environment.'):
            _public_name='FMathEnvironment';_public_field=_field.split('.')[-1]
        elif _field.startswith('calls[].'):
            _public_name='FMathCallV2';_public_field=_field.split('.')[-1]
        elif _field in ('contract','compiler','calls[]','output'):
            _public_name='FMathArtifactJSONV2';_public_field=_field.removesuffix('[]')
        if _public_name:
            _decl_field=next(f for f in PUBLIC_CLASS_BY_NAME[_public_name]['fields'] if f['name']==_public_field)
            _row['declared_type']=_decl_field['type']
            _row['presence']='必須・null可（公開入力の注釈。省略と交換しない）' if 'None' in _decl_field['type'] else '必須・非null（公開入力/包みの全欄）'
            _row['related_targets']+=('T.public.'+_public_name+'.field.'+_public_field,)
            _row['sources']+=TARGET_BY_ID['T.public.'+_public_name+'.field.'+_public_field]['sources']
        else:
            _row['presence']='必須・非null。input/claimの枝に従う全payloadは型別名の全枝へ展開'
            _alias='FMathInputV2' if _field.startswith('input.') else 'FMathClaimV2'
            _row['declared_type']=_alias+'の各枝の'+_field.split('.')[-1]
            _row['related_targets']+=(SUPPLEMENTAL_TYPE_RESOLUTIONS[_alias]['target'],)
    _row['resolution']='v0.23の明示した宣言・用途・失敗へ接続。宣言の整理済みと実装への接続/実行を区別。' 
    _row['use']='v0.23の対応先から欄・枝・意味・失敗を読む。原報告の保存、数値認証、実取得、採用を区別。'
    if _id.startswith('T.artifact'):
        _row['use']='F-a E-05の全欄/全枝を維持し、v0.23 19-10の旧bundle・registry・正の再読/不在再現へ接続。利用例への実接続は未実行。'
        _row['sources']+=(source(FA,391,412),source(FA,493),source(FB,2337))
        _row['implementation_connection']='未接続: 実装の段でartifact全閉包と各枝を確認'
    if _id in ('T.paper.182','T.paper.183','T.paper.184'):
        _row['use']=_old['use']+' v0.23の型付き一次入力と導出する内部状態を区別。'
    if _id=='T.wire.text.2583':
        _row['use']='旧「次回に決める問い」の表見出しはv0.23で置換。後継の10節へ対応する履歴索引。'
        _row['not_applicable_reason']='適用外: 旧見出し自体は現行の試験条件ではない。後継条件を別行で数える。'
    _row['count_as_pass']=False;_row['execution']='not_run'
    V23_G01_RESOLUTIONS.append(dict(target=_id,before_status=_old['status'],before_issues=_old['issues'],
                                    after_status=_row['status'],remaining_issues=_row['issues'],targets=_links,
                                    reason=_row['resolution'],sources=tuple(s for s in _row['sources'] if s['path']==FB),
                                    execution='not_run',count_as_pass=False))
V23_G01_RESOLUTIONS=tuple(V23_G01_RESOLUTIONS)
# 未定payloadを旧wireの入口からも辿れるようにする（新しい和型を重ねない）。
_vr=WIRE_TYPES['VerificationResponse']
_vr.update(issues=(),branches=tuple((b['tag'],b['payload']) for b in V23_TYPE_BY_NAME['VerificationResponse']['branches']),
           note='v0.23 19-9で三枝の全payloadを宣言。',sources=(source(FB,2985,2994),),
           type_references=tuple(V23_TYPE_TARGETS[b['payload']] for b in V23_TYPE_BY_NAME['VerificationResponse']['branches']))
for _tag,_payload in _vr['branches']:
    _bid='T.wire.type.VerificationResponse.branch.'+_tag
    TARGET_BY_ID[_bid]['declared_type']=_payload
    TARGET_BY_ID[_bid+'.field.value']['declared_type']=_payload
    TARGET_BY_ID[_bid+'.field.kind']['declared_type']=_tag
for _resolution in FBT01B_RESOLUTIONS:
    if _resolution['target'] in DRAFT4_G01_IDS:
        _updated=next(x for x in V23_G01_RESOLUTIONS if x['target']==_resolution['target'])
        for _key in ('after_status','remaining_issues','targets','reason','sources'):_resolution[_key]=_copy_tree(_updated[_key])
FBT01B_REMAINING=tuple(x for x in FBT01B_RESOLUTIONS if x['after_status'] in ('未決','未対応'))
FBT01B_UNCLOSED=tuple(x['target'] for x in FBT01B_REMAINING if set(x['remaining_issues'])<={'G-02','G-05','D-01'})
for _bridge in BRIDGES:
    _bridge['prerequisite_issues']=tuple(i for i in _bridge['prerequisite_issues'] if not i.startswith('G-01'))
    _bridge['execution']='not_run'
GAPS['G-01']=dict(classification='後で',status='解消',message='v0.23 19-1〜10で90行を宣言へ接続。実装の試験は未実行。',sources=(source(FB,2582,3078),))
FBT04_DISPOSITIONS['unresolved_meaning']='旧G-01はv0.23へ接続済み。未採用R10は引き続き未採用。'
V23_FINDINGS=(
    dict(id='G-EXAMPLE-UV',classification='直すべき',status='未対応',targets=('T.v23.example.FB23-R04',),
         message=GAPS['G-EXAMPLE-UV']['message'],sources=(source(FB,2757),)),
    dict(id='V23-REVIEW-LABEL',classification='後で',status='記載の不一致',targets=(),
         message='版履歴3行は点検pass、2584行と2562行は「独立の点検は未」。意味の規則はこの表示から決めない。',
         sources=(source(FB,3),source(FB,2562),source(FB,2584))),
)
V23_PUBLIC_RESULT_DECLARATION=dict(
    name='FiniteUpdateResult',
    sources=(source(DECLARATIONS_PATH,1303,1305),),
    excerpt={
        1303:'L3753: @_dataclass(frozen=True, slots=True, kw_only=True) class FiniteUpdateResult(_FactsDTO):',
        1304:'    joint: tuple[_Fraction, ...]',
        1305:'    evidence_mass: _Fraction',
    },
    fields=(
        dict(name='joint',type='tuple[_Fraction, ...]',line=1304,source=source(DECLARATIONS_PATH,1304)),
        dict(name='evidence_mass',type='_Fraction',line=1305,source=source(DECLARATIONS_PATH,1305)),
    ),
)
V23_PUBLIC_COMPARISONS=(
    dict(subject='finite_update_result/1',status='一致',paper=source(FB,2879,2889),public=source(DECLARATIONS_PATH,1303,1305),
         detail='joint/evidence_massの二欄を維持。内部AppliedStep2/ClaimStateを保存結果に追加しない。'),
    dict(subject='finite_update/1 vs /2',status='版の違い',paper=source(FB,2586,2607),public=source(DECLARATIONS_PATH,1298,1301),
         detail='/1のobservations:Point列と/2のObservationUse列は別版。既存の型の書換えとしない。'),
    dict(subject='finite_update_statement/1 vs /2',status='版の違い',paper=source(FB,2923,2943),public=source(DECLARATIONS_PATH,1307,1313),
         detail='/2のapplication_digestを/1へ追加しない。旧checker/basis条件も保持。'),
    dict(subject='認証返答と失敗層',status='一致',paper=source(FB,3042,3057),public=source(FA,240,256),
         detail='物理欠落・数値障害・予期しない例外を三枝の通常返答に潰さない。'),
    dict(subject='math_artifact/2とreplay',status='一致',paper=source(FB,3069,3073),public=source(FA,391,493),
         detail='E-05の全型とE-06の正の依存/不在像を維持。資料の読了はE-05/E-06の該当部分。'),
)
CATALOG_LAYERS['v23']='V23_TYPE_DECLARATIONS/V23_CONTRACT_DECLARATIONSから宣言を辿り、V23_CLOSING_ITEMSとV23_EXAMPLESで識別条件を読む。'
CATALOG_LAYERS['citations']='既存v0.22引用はFB22写しへ固定。新しい仕様条件はFBのv0.23行。B:nを新本文の同じ番号へ読み替えない。'
CATALOG_LAYERS['historical']='DRAFT1〜DRAFT4_DENOMINATORは固定履歴。現在の値はTARGETS。'
SESSION_NOTE=dict(DRAFT4_SESSION_NOTE,
    artifact_version='FBT draft 5 / paper v0.23',
    decision='旧G-01の90行を追跡。新契約12・再利用1、紙の名前23型/匿名索引込み43型、閉じる条件74項、失敗分類10行を独立列挙。',
    unresolved='FB23-R04のu/v同時表と事前が紙にない。結果値の算術整合だけを確認し、原入力からの再計算は未対応として残す。',
    verification='第五稿の自己点検36件passed (Python 3.12.10 / pytest 9.1.1)。Fractionによる値の照合と論理例の点検を含む。u/vは部分確認。実装/模型はnot_run。',
    failed_attempts='初回34 passed/2 failed: 比較用公開宣言の保存漏れと引用版の比較ヘルパーのlist/tuple変換。宣言の該当3行を追加し容器型を維持して修正。期待値は変更なし。',
    reuse='有効: 旧版の分母/試験を固定し、原報告・保存説明値・実行の事実・発行物を区別。',
    read_scope='v0.23 §2-5-19 2582–3078全文、関連差分24行、F-a紙/提供された公開宣言の該当部分。v0.22写しは差分照合。禁止実装は未読。Webなし。',
    next='u/v例の一次入力が紙へ宣言されたら再計算。実装の段でこの一覧から適合試験を書く。',
    assumptions={'name_only':0,'meaning_change':0})
DENOMINATOR_KEYS=DENOMINATOR_KEYS+('V23_PROVENANCE','V23_SECTION_LINES','V23_CHANGED_LINES','V23_TYPE_DECLARATIONS',
    'V23_CONTRACT_DECLARATIONS','V23_CLOSING_ITEMS','V23_EXAMPLE_DATA','V23_EXAMPLES','V23_FAILURE_CLASSIFICATION',
    'V23_SOURCE_COVERAGE','V23_G01_RESOLUTIONS','V23_PUBLIC_COMPARISONS','V23_PUBLIC_RESULT_DECLARATION','V23_SCALARS')
DENOMINATOR_SHA256='4dd991ceac8933a8afe20ce8f1ed0edac1b1f843d3120c29fa82f2a225f774ed'

def fifth_revision_summary():
    return dict(previous=DRAFT4_SUMMARY,current=summary_counts(),
        g01=dict(previous=len(DRAFT4_G01_IDS),resolved=sum(r['after_status']=='整理済み' for r in V23_G01_RESOLUTIONS),
                 remaining=tuple(r for r in V23_G01_RESOLUTIONS if r['after_status'] in ('未対応','未決'))),
        unresolved_by_issue={status:dict(Counter(i for r in TARGETS if r['status']==status for i in r['issues'])) for status in ('未決','未対応','未採用')},
        new_contracts=sum(d['new'] for d in V23_CONTRACT_DECLARATIONS),reused_contracts=sum(not d['new'] for d in V23_CONTRACT_DECLARATIONS),
        types=len(V23_TYPE_DECLARATIONS),paper_named_types=sum(d['paper_named'] for d in V23_TYPE_DECLARATIONS),
        fields=sum(len(d['fields']) for d in V23_TYPE_DECLARATIONS),union_branches=sum(len(d['branches']) for d in V23_TYPE_DECLARATIONS),
        closing_items=len(V23_CLOSING_ITEMS),closing_by_section=dict(Counter(i['section'] for i in V23_CLOSING_ITEMS)),
        failure_rows=len(V23_FAILURE_CLASSIFICATION),example_families=len(V23_EXAMPLES),
        assumptions={'name_only':0,'meaning_change':0})


# FBT draft 6: 同版v0.23へのu/v入力表の追記と点検表示の訂正だけを反映。
# DRAFT5はその時点の分母を保存。現在の行IDは変えず、出典の物理行だけを追随する。
DRAFT5_DENOMINATOR={key:_copy_tree(globals()[key]) for key in DENOMINATOR_KEYS}
DRAFT5_DENOMINATOR_SHA256=DENOMINATOR_SHA256
DRAFT5_TARGET_BY_ID={r['id']:r for r in DRAFT5_DENOMINATOR['TARGETS']}
DRAFT5_SUMMARY=summary_counts()
DRAFT5_FINDINGS=_copy_tree(V23_FINDINGS)
DRAFT5_SESSION_NOTE=_copy_tree(SESSION_NOTE)
DRAFT5_BRIDGES=_copy_tree(BRIDGES)
DRAFT5_TEST_CHECKS={'test_target_ids_and_required_columns': '9b4a228a57ea409df8a06fd4d1bf6ade27a79693bfe6a6d35964acb3b77e231c',
 'test_not_applicable_and_unresolved_cells_are_explicit': '4f206621d18353375ba35dd53465e06592a93794ce92018652b085bae93ee21b',
 'test_rule_entry_and_target_references_exist': '3bc95e4ca061392126344666514c4c39c5ae9e3db3f9347198bfe01df3c0dc5a',
 'test_paper_source_units_have_dispositions': 'f805d7c5b645d1324eae399c305d085a763122a2c02b191ea04e3ba93d63aa9f',
 'test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap': 'b7bd79b4ff2a7523a2397e73f7a10f729b0764c7f955f2e2871d577b00815549',
 'test_denominator_was_not_changed_by_the_model_bridge': '39919f501a144203f801bcad119cde35e5cfa4c4ce4540dfbd1dc361944f5028',
 'test_bridge_source_universe_independent_counts_and_selectors': '6cd010c6a863183fd0bcaa60862dbfc5d6b73584e343cdbc232b1476c7e13c27',
 'test_every_bridge_item_has_exactly_one_disposition': 'b2c9e1cb516572475e9dbc7fcabd07bb208a0faadd1eb9e4906a7513971f19b2',
 'test_numeric_remainders_and_unadopted_branches_not_promoted': 'ce33cee576d69273a7a66c57dbbd75b70b11c70ec404db428391a8d0dd7b7b98',
 'test_supplemental_scope_holes_remain_separate_from_107_7_79': '7bddb16f3dee4eea45f48753fadb79882868386b0710d2ffd77fbbc65110f190',
 'test_disagreement_is_reported_without_choosing_an_expected_type': 'ad6441b71c897ff01015ff52dd349d569ba454fbef12c2fb6c770b51cc370e01',
 'test_data_module_has_no_model_or_implementation_import': 'e9edd0c72d82ad8c8052100d67d55b11f0f509e3af6305001c85a27b202be486',
 'test_revision_accounts_for_every_original_affected_row_and_reports_unclosed': '28b6110259c5cbd61db250050fb4cd70b1d32c89abb1d2be0367bfeeb813fe50',
 'test_wire_contract_universe_is_counted_from_paper_and_every_declaration_has_target': '6d4c1857943277f973c55180194e1599392075b84e0cf6230941eb4385196a49',
 'test_wire_nested_fields_nullable_and_union_branches_are_all_addressable': 'a1f0c9b40f085c6fdfa4d1e07e8de682d946fa8d3c02de83f3950cdbc07cb481',
 'test_all_91_logical_rows_and_entire_wire_section_have_dispositions': 'b4c69f22efe9485b5fb4ad53714fbbdef11bb788296ddf2b7bcea9217fca230f',
 'test_public_class_declarations_expand_fields_literals_unions_and_keep_unknown_types': '095d4646fb16314488e66d33059fa232696fcddcf7c83cd84cd282044e7f0fb5',
 'test_d7_connections_are_conditions_and_observation_not_automatic_success': 'f080272e75eb2b069dd586b75a7c24709976643e70b45dd0779241a08c51eb9c',
 'test_revision_preserves_all_bridge_sources_targets_checks_and_remainders': '092a9f6732bd42fd1531eab674d58a9fe3f4234691611825613d7da22eb0749c',
 'test_revision3_retains_all_19_previous_checks_and_their_fixed_baselines': '170c7dc24f13e71b9b65bdea3a3e3ae9c1d7f02569a5fed4e8410631292fc6d9',
 'test_supplemental_alias_graph_matches_saved_declarations_and_declaration_time_binding': '43f5a496f334938ef1eb9f13e5eb4c16a4c33498a425e38f706039cada39391d',
 'test_rate_declarations_and_all_14_previously_missing_names_have_concrete_targets': '08df505051b98ad46725cbc4d47a1ddbebd04b69afd4b799b150f5efbce1c39f',
 'test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved': '6b70fb6680aac4f5ad53f2bd75696f938d0c5a3e265e4a2e0b09d395f387def5',
 'test_legacy_style_matches_contract_shape_and_keeps_import_semantics_separate': '4e801d89f4782143e2ca0782746b940ffd3e862642e0b0828838f1a12f227f94',
 'test_revision4_preserves_23_checks_and_changes_only_old_style_and_its_children': 'f6d876eea9083b6963c905987757763a746917fdc055faa89fe520483d1166bc',
 'test_v23_accounts_for_all_90_g01_rows_and_does_not_promote_execution': '1a8b260a7e43fabf60f162b5e6a9149d1bfdd15d4bbb6dffc870ac17d2858a7a',
 'test_v23_contracts_are_counted_from_the_paper_excerpt_not_existing_registry': 'd751b932ba6962e24ad67d712096e370dcf364e639d6dda2716a6b90a99f1026',
 'test_v23_named_types_fields_union_payloads_and_literals_are_addressable': '7c0821259742a9e6f63751e62992c56bf3e42220b5a6ac7cd7b2fc85dc5aec5c',
 'test_v23_all_497_lines_74_closing_items_and_10_failures_have_dispositions': 'e808879d948be0afdd3bc37f835f17bb86527b8f933c2c1061044d8a17de1649',
 'test_v23_ce1_recomputes_all_three_paper_results_from_the_eight_row_law': 'afb16feccc31c4bb420733486b96efd147b7b39a344e7fd767136ce5bf920504',
 'test_v23_m07_recomputes_different_posteriors_for_the_same_atom_set': 'fff85b6ce1bf76dd83329f8010497e0dcedb6bd0427b406e12bf432012852685',
 'test_v23_overlapping_outcomes_recompute_three_halves_and_a_legal_partition': 'afc73618e7af5cd5fbae534a8f5796a82fe073f9d69aa77e2f572b0c8ec1bbfa',
 'test_v23_uv_numbers_are_only_reverse_arithmetic_not_a_replayed_unspecified_law': 'b0ea19cb44821eb1a80adf49e5349828c80365294f1e7fd4c5b08959c404da92',
 'test_v23_equal_model_row_sets_do_not_replace_logical_predicates': '21c8cbaad203e506bfb41e69cdcb903c1d8ba70399d4916754a81d19b5891e4d',
 'test_v23_pairwise_witnesses_do_not_make_the_three_way_conjunction_consistent': '333f4dfdc2d535195d52b24ea7b787da214b36dc6525728864e602afe989d7fa',
 'test_v23_keeps_all_25_prior_checks_and_the_bridge_universe_and_old_citations': 'c31995c9aa551097e6801761aedc4e651608ef32f546e18236a6b5e2d5351328'}
DRAFT5_AMENDED_TEST_SOURCE={'test_v23_all_497_lines_74_closing_items_and_10_failures_have_dispositions': 'def test_v23_all_497_lines_74_closing_items_and_10_failures_have_dispositions():\n    assert set(data.V23_SECTION_LINES) == set(range(2582, 3079))\n    coverage = {item["line"]: item for item in data.V23_SOURCE_COVERAGE}\n    assert set(coverage) == set(data.V23_SECTION_LINES) and len(coverage) == 497\n    for item in coverage.values():\n        assert item["targets"] or item["reason"].startswith("適用外:")\n        assert set(item["targets"]) <= data.TARGET_BY_ID.keys()\n    closing_lines = {n for n, text in data.V23_SECTION_LINES.items() if text.startswith("**閉じる条件。**")}\n    assert len(closing_lines) == 10 and {i["line"] for i in data.V23_CLOSING_ITEMS} == closing_lines\n    assert Counter(i["section"] for i in data.V23_CLOSING_ITEMS) == {1:13, 2:7, 3:6, 4:6, 5:6, 6:7, 7:6, 8:4, 9:12, 10:7}\n    assert len({i["id"] for i in data.V23_CLOSING_ITEMS}) == 74\n    for item in data.V23_CLOSING_ITEMS:\n        row = data.TARGET_BY_ID[item["target"]]\n        assert item["item"] in row["use"] and row["negative"] and row["nearest_legal"]\n        assert item["rules"] and set(item["rules"]) <= data.RULES.keys()\n        assert item["entries"] and set(item["entries"]) <= data.ENTRY_POINTS.keys()\n        assert any(s["path"] == data.FB and s["first"] == item["line"] for s in row["sources"])\n    assert len(data.V23_FAILURE_CLASSIFICATION) == 10\n    for failure in data.V23_FAILURE_CLASSIFICATION:\n        raw = data.V23_SECTION_LINES[failure["line"]]\n        assert failure["condition"] in raw and failure["expected"] in raw\n        assert failure["target"] in data.TARGET_BY_ID\n    assert {d["line"] for d in data.V23_CHANGED_DISPOSITIONS} == set(data.V23_CHANGED_LINES)\n    assert data.TARGET_BY_ID["T.v23.changed.3110"]["status"] == "未採用"', 'test_v23_uv_numbers_are_only_reverse_arithmetic_not_a_replayed_unspecified_law': 'def test_v23_uv_numbers_are_only_reverse_arithmetic_not_a_replayed_unspecified_law():\n    ex = data.V23_EXAMPLE_DATA["FB23-R04"]\n    weights = []\n    for key, derived in (("before","derived_weights_before"),("after","derived_weights_after")):\n        joint = tuple(map(Fraction,ex[key]["joint"]))\n        assert sum(joint) == 1\n        w = tuple(p*Fraction(ex[key]["evidence_mass"]) for p in joint)\n        assert w == tuple(map(Fraction,ex[derived]))\n        weights.append(w)\n    assert tuple(b/a for a,b in zip(*weights)) == tuple(map(Fraction,ex["derived_ratio"]))\n    assert "資料不足" in ex["primary_input_status"] and "原入力からの再計算ではない" in ex["arithmetic_scope"]\n    assert data.TARGET_BY_ID["T.v23.example.FB23-R04"]["status"] == "未対応"\n    assert any(r["id"] == "G-EXAMPLE-UV" for r in data.V23_FINDINGS)\n    assert next(r for r in data.V23_EXAMPLES if r["name"] == "FB23-R04")["calculation"] == "partial"'}
REVISION6_PAPER_UPDATES={3: '- 版: **v0.23 (2026-10-18 17:2x、Claude)**: **G-01 の意味を §2-5-19 に入れた** (旧「G-01 に渡す10項目」を置換)。Codex `sui-fb-update2` '
    '1〜3 通目 (Claude の 10 の決定 → 反例照合 → CE1 重なる無到着の主張の二重数え `(16/17,1/17)` / 追加を捨てる `(4/5,1/5)` / 正解 `(8/9,1/9)` → '
    '置換本文の候補) に、Claude の技術判断 M07 (適用済みの状態は原子の集合でなく主張の述語の連言。細分・満たす行は持たない) を入れた。併せて §2-4 の段 2・段 6、RIGHT-APPLY・CL-APPLY の '
    '/2 の行、§2-5 の G-01 の 18 か所を §2-5-19-n へ、§3 に R11 (参照の行)。ゆうの価値の問い 0。W-22 の意味は変えない。17:3x に §2-5-19 の独立の点検 '
    '`sui-fb-update2-check` 1 通目 (BLOCKER 2・直すべき 1、M07 と条件づけの数学は pass) を直した: FB23-R01 観測セルの outcomes は互いに素で和が全体 / '
    'FB23-R02 CE1 と M07 の例の表を 19-8 に収録 / FB23-R03 B は読み方の args に結ばず、args は Q の reading に固定。点検の確認から 2 文 (数値の digest '
    'を論理の状態の代わりにしない・両立性は全部の連言で)。17:4x に 2 通目 (R01〜R03 は閉じた・BLOCKER 1) の FB23-R04 を直した: 同じ原 Claim を別の読み方で別 channel '
    'に写す二重数え → 原 Claim から channel への対応は一意・AppliedStep の claim に source (原 Claim の鍵) を持ち、同じ原 Claim は一つの出来事 (Frame の MID '
    'と同じ形)。**17:4x に 3 通目で R04 も閉じた・新しい指摘 0 = §2-5-19 の独立の点検は pass**。18:1x に `sui-fb-targets` 5 通目の指摘 2 件で、FB23-R04 '
    'の例の表を 19-8 に収録・本文の「点検は未」の表示を pass に',
 2562: '- `/2` の args、数値射影、閉包、結果、statement/checker、CL-APPLY の意味は v0.23 で §2-5-19 に定めた (◆G-01 を閉じた。§2-5-19 の独立の点検は 3 '
       '通目で pass)。MethodCall/ContractValue の容器があることを意味の完成としない。',
 2584: '本節は、保存の形に残した G-01 の意味を定める (v0.23。Codex `sui-fb-update2` 1〜3 通目の下書きに Claude の決定と修正を入れた。独立の点検 '
       '`sui-fb-update2-check` は 3 通目で pass。本節の `B:n` は v0.22 の行番号、`A:n` は F-a の紙、`P:n` は '
       'ROADMAP)。宣言・計算・証明・認証・採用は別の段である。ここに契約を書いたことを実装の存在・認証成功・実取得の証拠にしない。',
 2757: '`ClaimKey` は原 Claim の FAMILY-UNNAMED の鍵 `(segment,item_slot)`。Frame の MID と同じく、**同じ原 Claim '
       'は一つの導出系列で一つの出来事として効く**。別の reading で読み直しても、正準の channel・区間・述語が同じなら no-op、違えば食い違い (CL-APPLY) '
       'とし、別の観測として足さない。同じ原報告から別の命題を同時に取り出すには、その共同の読み方を宣言する (未宣言なら missing_contract)〔v0.23 FB23-R04。反例: 同じ計数量に id だけ違う '
       'channel u・v を置いた同時表で、同じ原 Claim を Nᵤ=0・Nᵥ=0 と二度読むと、原報告は増えていないのに事後が (3/4,1/4；1/2) から (9/10,1/10；5/16) へ動く。表は '
       '19-8 の FB23-R04 の例〕。別 slot の原 Claim は別の報告で、同じ述語なら含意で no-op になる。',
 2914: 'FB23-R04 の例: carrier a・b の事前 (1/2,1/2)。一つの法則に、id だけ違い process・route_configs・domain が同じ channel u・v を置き、区間 '
       'I=(0,1] の件数の同時表を次とする (各列の和は 1)。',
 2915: '',
 2916: '| (Nᵤ,Nᵥ) | a | b |',
 2917: '|---|---:|---:|',
 2918: '| (0,0) | 9/16 | 1/16 |',
 2919: '| (0,1) | 3/16 | 3/16 |',
 2920: '| (1,0) | 3/16 | 3/16 |',
 2921: '| (1,1) | 1/16 | 9/16 |',
 2922: '',
 2923: '同じ原 Claim を `Nᵤ(I)=0` と読むと (3/4,1/4；1/2)、続けて `Nᵥ(I)=0` と読むと連言の確率 (9/16,1/16) から (9/10,1/10；5/16)。19-1 の '
       'channel 対応の一意性により、この法則はこの原 Claim の読み方に使えず shape で止まる (二重適用まで進まない)。',
 2924: ''}
REVISION6_PAPER_SHA256='b8faf0a738cc741f7d3483c31933a8837e387d44a55e8b2beb1e9d0851e7fa8a'
REVISION6_PAPER_SHA256_LF='b4fc4b82c2765221d42c5b1c5330ddc54b0f073bbfebbbb09e597a3a0a2c197e'

def _revision6_line(line):
    return line+11 if line>=2914 else line

# 出典dictは共有されるので一度だけ移す。固定したDRAFT群には触れない。
_revision6_seen=set()
def _revision6_sources(value):
    if not isinstance(value,(dict,list,tuple)) or id(value) in _revision6_seen:
        return
    _revision6_seen.add(id(value))
    if isinstance(value,dict):
        if value.get('path')==FB:
            value['first']=_revision6_line(value['first'])
            value['last']=_revision6_line(value['last'])
        for child in value.values():_revision6_sources(child)
    else:
        for child in value:_revision6_sources(child)

for _key in DENOMINATOR_KEYS+('FBT01B_RESOLUTIONS','V23_CLAUSES','V23_CHANGED_DISPOSITIONS'):
    _revision6_sources(globals()[_key])

# 宣言索引の裸の行番号も現在の紙に合わせる。型名/ID/規則/意味は変えない。
_revision6_index_seen=set()
def _revision6_index_lines(value):
    if not isinstance(value,(dict,list,tuple)) or id(value) in _revision6_index_seen:
        return
    _revision6_index_seen.add(id(value))
    if isinstance(value,dict):
        if 'path' in value:return  # 上で更新済みの出典dict
        for key,child in value.items():
            if key in ('line','first','last') and isinstance(child,int):
                value[key]=_revision6_line(child)
            else:_revision6_index_lines(child)
    else:
        for child in value:_revision6_index_lines(child)

for _key in ('V23_TYPE_DECLARATIONS','V23_CONTRACT_DECLARATIONS','V23_CLOSING_ITEMS',
             'V23_FAILURE_CLASSIFICATION','V23_SOURCE_COVERAGE','V23_CLAUSES','V23_CHANGED_DISPOSITIONS'):
    _revision6_index_lines(globals()[_key])
V23_SECTIONS=tuple((n,_revision6_line(a),_revision6_line(b)) for n,a,b in V23_SECTIONS)
V23_SECTION_LINES={_revision6_line(n):text for n,text in V23_SECTION_LINES.items()}
V23_SECTION_LINES.update({n:text for n,text in REVISION6_PAPER_UPDATES.items() if 2582<=n<=3089})
V23_SECTION_LINES=dict(sorted(V23_SECTION_LINES.items()))
V23_CHANGED_LINES={_revision6_line(n):text for n,text in V23_CHANGED_LINES.items()}
V23_CHANGED_LINES[2562]=REVISION6_PAPER_UPDATES[2562]
for _clause in V23_CLAUSES:
    if _clause['line'] in (2584,2757):
        _clause['text']=REVISION6_PAPER_UPDATES[_clause['line']]
        TARGET_BY_ID[_clause['target']]['use']=_clause['text']
TARGET_BY_ID['T.v23.changed.2562']['use']=REVISION6_PAPER_UPDATES[2562]

V23_PROVENANCE.update(lines=3216,sha256_lf=REVISION6_PAPER_SHA256_LF,sha256_bytes=REVISION6_PAPER_SHA256,
    read_scope='§2-5-19は第五稿で全文、今回差分全文を読了。現在2582–3089。関連する表示2562行・参照2757行も照合。')
PROVENANCE.update(version='6',spec_lines=3216,spec_sha256_lf=REVISION6_PAPER_SHA256_LF,
                  spec_sha256_bytes=REVISION6_PAPER_SHA256)

_uv=V23_EXAMPLE_DATA['FB23-R04']
_uv.update(source=(2914,2923),prior=('1/2','1/2'),
    rows=(((0,0),'9/16','1/16'),((0,1),'3/16','3/16'),((1,0),'3/16','3/16'),((1,1),'1/16','9/16')),
    row_lines=(2918,2919,2920,2921),
    channels=('u','v'),same_channel_identity=('process','route_configs','domain'),interval='(0,1]',
    paper_Z_first=('3/4','1/4'),paper_Z_conjunction=('9/16','1/16'),
    primary_input_status='紙に宣言済み: 事前分布とu/v同時表から独立に再計算する',
    arithmetic_scope='一次入力の表を周辺化・連言で絞り、事前から重みと事後と累積質量を再計算。旧逆算の整合確認も保持。',
    expected_stop_stage='shape',numerical_application_permitted=False,
    negative='同じ計数量をidだけ違うu/vへ重複宣言した法則をshapeで止めず、同じ原Claimの二重適用へ進める',
    nearest_legal='一意な正準channelで同じClaimKey・同じ正準述語を再読しno-op。異なる正準述語はCL-APPLYで成功させない')
_uvrow=TARGET_BY_ID['T.v23.example.FB23-R04']
_uvrow.update(status='整理済み',issues=(),
    use='19-8の事前・4行同時表から表示された二結果を再計算。これはshapeで止める負例の数値説明であり、実装が数値適用へ進む合法例ではない。',
    negative=_uv['negative'],nearest_legal=_uv['nearest_legal'])
_uvrow['sources']=_uvrow['sources']+(source(FB,2914,2923),source(FB,2692))
for _example in V23_EXAMPLES:
    if _example['name']=='FB23-R04':
        _example.update(source=source(FB,2914,2923),calculation='checked')
V23_SOURCE_COVERAGE=tuple(sorted(V23_SOURCE_COVERAGE+tuple(
    dict(line=n,targets=('T.v23.example.FB23-R04',),reason='追記された一次入力表・反例の停止段階を同じ対象行に接続')
    for n in range(2914,2925)),key=lambda r:r['line']))
GAPS['G-EXAMPLE-UV'].update(status='解消',
    message='19-8に事前と同時表が宣言された。Fractionによる一次入力からの再計算に接続。shapeで止める反例として保持。',
    sources=(source(FB,2757),source(FB,2914,2923)))
REVISION6_RESOLUTIONS=(
    dict(id='G-EXAMPLE-UV',status='解消',targets=('T.v23.example.FB23-R04',),
         sources=(source(FB,2757),source(FB,2914,2923)),execution='not_run',count_as_pass=False),
    dict(id='V23-REVIEW-LABEL',status='解消',targets=('T.v23.changed.2562','T.v23.clause.2584'),
         sources=(source(FB,3),source(FB,2562),source(FB,2584)),execution='not_run',count_as_pass=False),
)
V23_FINDINGS=()
CATALOG_LAYERS['citations']='v0.22引用はFB22写しに固定。現行v0.23は同版追記後3216行。T.v23.*内の数字は安定IDで、現在の物理行はsourcesに保持。'
SESSION_NOTE=dict(DRAFT5_SESSION_NOTE,
    artifact_version='FBT draft 6 / paper v0.23 UV table supplement',
    decision='u/vの一次入力表を同じ対象行に接続し、shapeで止める負例として明記。表示の不一致2箇所も閉じる。',
    unresolved='今回の2指摘は解消。既存のG-RUN-CODEC/G-04と未採用は変更なし。',
    verification='第六稿の自己点検39 passed in 1.23s (Python 3.12.10 / pytest 9.1.1)。u/v表と事前からFractionで二結果が一致。紙のbytes/LF二種SHA-256・新節508行・関連24行も現物と照合。実装/模型はnot_run。',
    failed_attempts='今回なし。',
    read_scope='v0.23の追記表2914–2923全文、表示3・2562・2584、参照2757を読了。第五稿の保存した新節497行との差分全文を照合。禁止実装は未読。Webなし。',
    next='実装の段へ一覧を引き継ぐ。実装の適合試験と保留項目の合格判定は未実行。')
DENOMINATOR_KEYS=DENOMINATOR_KEYS+('REVISION6_PAPER_UPDATES','REVISION6_PAPER_SHA256',
    'REVISION6_PAPER_SHA256_LF','REVISION6_RESOLUTIONS','V23_FINDINGS','V23_CLAUSES','V23_CHANGED_DISPOSITIONS','V23_SECTIONS')
DENOMINATOR_SHA256='4b8852be68800636b09f39792b65e00750be984fbbef84c2c6c5d4892cb5c724'

def sixth_revision_summary():
    return dict(previous=DRAFT5_SUMMARY,current=summary_counts(),
                resolutions=REVISION6_RESOLUTIONS,findings=V23_FINDINGS,
                assumptions={'name_only':0,'meaning_change':0})
