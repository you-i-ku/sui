"""F-b の記録の形の検査 (A1-SHAPE、紙 F-b v0.42 Z33 ③ (c))。

記録の content を契約ごとのふつうのコードで復号し、形の違反を {kind, field, detail} の列で返す (正常は空列)。sui.f.* の記録は
F-a の厳しい復号 (`f_entry.f_from_json`) に任せ、ここは F-b の記録 (sui.fb.*・観測の計画 /2・時計の宣言・s4.boot) を読む。
保存の書き方は `_fb_wire.encode` の逆。規則の表 (CONTRACT_STRUCTURE_BINDINGS) は本番では読まない: 試験の側が表を機械で
読んで欄ごとに壊し、ここが落とすことを確かめる (人が写すのは本体だけ = 写し間違いは試験で落ちる)。
違反の kind は F-a A-20/A-21 の構造検査の型つきの理由 (schema・shape・noncanonical・rational・unit・unknown_version・
normalization)。最初の違反で止め、修理して通さない。
"""

from . import f as _f
from .f import FInputError as _Bad

_CID = __import__("re").compile(r"sha256:[0-9a-f]{64}")
_STAGES = ("measure_segment", "candidate_generation", "belief_result", "belief_proof", "verification",
           "evaluation_prepare", "selection_draw", "evaluation", "belief_update")
_CLOSURES = ("[start,end)", "(start,end]", "[start,end]", "(start,end)")


# ---------------------------------------------------------------- 葉

def _keys(value, names, field):
    _f._keys(value, names, field)


def _str(value, field):
    if type(value) is not str:
        raise _Bad("shape", "str required", field)
    return value


def _int(value, field, minimum=None):
    if type(value) is not int:
        raise _Bad("shape", "int required", field)
    if minimum is not None and value < minimum:
        raise _Bad("shape", f"int >= {minimum} required", field)
    return value


def _bool(value, field):
    if type(value) is not bool:
        raise _Bad("shape", "bool required", field)


def _point(value, field):
    if type(value) is not str or _CID.fullmatch(value) is None:
        raise _Bad("shape", "Point required", field)
    return value


def _nullable(value, field, decode):
    return None if value is None else decode(value, field)


def _ref(value, field):
    _f._decode(value, _f._Ref, field)


def _refs(value, field):
    _f._array(value, field)
    for i, item in enumerate(value):
        _ref(item, f"{field}/{i}")


def _contract(value, field):
    _keys(value, ("name", "version"), field)
    _str(value["name"], field + "/name")
    _str(value["version"], field + "/version")
    return value


def _literal_contract(value, field, name, version):
    _contract(value, field)
    if value["name"] != name or value["version"] != version:
        raise _Bad("unknown_version", f"{name}/{version} required", field)


def _json(value, field):
    _f._freeze(value)


def _enum(value, field, values):
    if type(value) is not str or value not in values:
        raise _Bad("shape", "unknown enum value", field)
    return value


def _rational(value, field, minimum=None, exclusive=False):
    _f._decode(value, _f._Fraction, field)
    n, d = value
    if minimum is not None and (n * minimum[1] < minimum[0] * d or exclusive and n * minimum[1] == minimum[0] * d):
        raise _Bad("shape", "rational below its minimum", field)


def _array(value, field, item):
    _f._array(value, field)
    for i, v in enumerate(value):
        item(v, f"{field}/{i}")


def _set(value, field, item):
    """集合 = 重複なしで、全要素の正準 JSON UTF-8 bytes 順の配列 (正本 SET-ORDER、fb_full_value_json_utf8_v1)。"""
    _array(value, field, item)
    encoded = [_f._dumps(v) for v in value]
    if len(set(encoded)) != len(encoded):
        raise _Bad("shape", "duplicate set items", field)
    if encoded != sorted(encoded):
        raise _Bad("noncanonical", "set order", field)


def _tagged(value, field, branches):
    _keys(value, ("kind", "value"), field)
    decode = branches.get(value["kind"]) if type(value["kind"]) is str else None
    if decode is None:
        raise _Bad("shape", "unknown union tag", field + "/kind")
    decode(value["value"], field + "/value")


def _object(fields):
    """{名前: 復号} の閉じた object (全欄が要る、知らない欄は拒む)。"""
    def decode(value, field):
        _keys(value, tuple(fields), field)
        for name, item in fields.items():
            item(value[name], f"{field}/{name}")
    return decode


# ---------------------------------------------------------------- 入れ子

def _clock_reading(value, field):
    _keys(value, ("run", "time_ns"), field)
    _ref(value["run"], field + "/run")
    _int(value["time_ns"], field + "/time_ns")


_unavailable = _object({"reason": _str, "basis": _refs})
_reading_evidence = lambda v, f: _tagged(v, f, {   # noqa: E731
    "clock": _object({"source": _point, "reading": _clock_reading}), "unavailable": _unavailable})
_clock_or_unavailable = lambda v, f: _tagged(v, f, {"clock": _clock_reading, "unavailable": _unavailable})   # noqa: E731
_contract_value = _object({"contract": _contract, "value": _json})
_method_call = _object({"contract": _contract, "args": _json})
_boot_slot = _object({"declaration": _point, "slot": _str})
_trigger = _object({"point": _point, "slot": _str})


def _interval(value, field):
    _keys(value, ("clock", "start_ns", "end_ns", "closure"), field)
    _ref(value["clock"], field + "/clock")
    _int(value["start_ns"], field + "/start_ns")
    _int(value["end_ns"], field + "/end_ns")
    _enum(value["closure"], field + "/closure", _CLOSURES)


def _rate_budget(value, field):
    from .rate import RateBudget, RateInputError
    try:
        _f._decode(value, RateBudget, field)
    except RateInputError as exc:   # RateBudget の値の検査 (正の誤差・正の上限) も形の違反
        raise _Bad("shape", str(exc), field) from None


def _update_budget(value, field):
    _keys(value, ("contract", "logical_limit", "numerical"), field)
    _literal_contract(value["contract"], field + "/contract", "sui.fb.update_budget", "1")
    _int(value["logical_limit"], field + "/logical_limit", minimum=0)
    _rate_budget(value["numerical"], field + "/numerical")


def _fixed_view(value, field):
    _keys(value, ("boundary", "environment"), field)
    _set(value["boundary"], field + "/boundary", _point)
    _keys(value["environment"], ("reader_view_key", "registry_key"), field + "/environment")
    _str(value["environment"]["reader_view_key"], field + "/environment/reader_view_key")
    _nullable(value["environment"]["registry_key"], field + "/environment/registry_key", _str)


def _quantity(value, field):
    _keys(value, ("contract", "value"), field)
    _literal_contract(value["contract"], field + "/contract", "sui.fb.seats", "1")
    _int(value["value"], field + "/value", minimum=0)


def _slot(contract_name, decode):
    def slot(value, field):
        _keys(value, ("slot", "declaration"), field)
        _str(value["slot"], field + "/slot")
        _keys(value["declaration"], ("contract", "value"), field + "/declaration")
        _literal_contract(value["declaration"]["contract"], field + "/declaration/contract", contract_name, "1")
        decode(value["declaration"]["value"], field + "/declaration/value")
    return slot


_allocation = _object({"scope_slot": _str, "amount": _quantity})
_slot_allocation = _slot("sui.fb.allocation", _allocation)


def _resource_scope(value, field):
    _keys(value, ("quantity_contract", "need"), field)
    _literal_contract(value["quantity_contract"], field + "/quantity_contract", "sui.fb.seats", "1")
    _method_call(value["need"], field + "/need")


def _route_config(value, field):
    names = ("route_epoch", "origin", "version", "sampling_contract", "clock_contract", "loss_contract", "args",
             "decision", "execution")
    _keys(value, names, field)
    _str(value["route_epoch"], field + "/route_epoch")
    _enum(value["origin"], field + "/origin", ("bootstrap", "selected"))
    _str(value["version"], field + "/version")
    for name in ("sampling_contract", "clock_contract", "loss_contract"):
        _contract(value[name], f"{field}/{name}")
    _json(value["args"], field + "/args")
    _nullable(value["decision"], field + "/decision", _ref)
    _nullable(value["execution"], field + "/execution", _ref)
    bootstrap = value["origin"] == "bootstrap"
    if bootstrap != (value["decision"] is None and value["execution"] is None) \
            or (not bootstrap and (value["decision"] is None or value["execution"] is None)):
        raise _Bad("shape", "bootstrap needs null decision/execution, selected needs both", field)


_bootstrap_route = _object({"config": _route_config, "process_slot": _str, "allocation": _slot_allocation,
                            "reading_contract": _contract})
_slotted_method = _object({"slot": _str, "method": _method_call})
_initial_process = _object({
    "process_slot": _str, "reader_slot": _str, "model": _point, "generator": _method_call, "method": _method_call,
    "draw": _method_call, "prepare_budget": _rate_budget,
    "prepare_replay_logical_limit": lambda v, f: _int(v, f, minimum=0), "evaluate_budget": _rate_budget,
    "update_budget": _update_budget, "allocation": _slot_allocation, "derivation": _slotted_method,
    "continuation": lambda v, f: _nullable(v, f, _method_call)})
_environment = _object({"data": _json})


def _ffacts_request(value, field):
    _f._decode(value, _f.FFactsRequest, field)


def _draw_request(value, field):
    _f._decode(value, _f.DrawRequest, field)


_segment_args = _object({"route": _point, "start_reason": _str,
                         "requested": lambda v, f: _tagged(v, f, {"finite": _interval,
                                                                   "ongoing": _object({"clock": _ref})})})
_candidate_args = _object({"model": _point, "generator_args": _json, "basis": lambda v, f: _array(v, f, _point)})
_update_args = _object({"model": _point, "prior": lambda v, f: _nullable(v, f, _point),
                        "observations": lambda v, f: _array(v, f, _object({"binding": _point, "reading": _point})),
                        "budget": _update_budget})
_prepare_args = _object({"input": _ffacts_request, "compiler": _contract, "budget": _rate_budget,
                         "replay_logical_limit": lambda v, f: _int(v, f, minimum=0)})
_evaluation_args = _object({"evaluation_request": _point, "prepared": _point, "draw": _point, "budget": _rate_budget})
_draw_args = _object({"prepared": _point, "stream_id": _str, "request": _draw_request})
_result_args = _object({"request": _point})
_proof_args = _object({"request": _point, "result": _point, "checker": lambda v, f: _f._decode(v, _f.ProofRef, f)})
_verification_args = _object({
    "target": _object({"request": _point, "result": _point, "proofs": lambda v, f: _set(v, f, _point),
                       "completion": _point}),
    "check_view": _fixed_view, "checker": lambda v, f: _f._decode(v, _f.ProofRef, f),
    "acquisitions": lambda v, f: _set(v, f, _point)})
_ARGS = {"measure_segment": _segment_args, "candidate_generation": _candidate_args, "belief_update": _update_args,
         "evaluation_prepare": _prepare_args, "selection_draw": _draw_args, "evaluation": _evaluation_args,
         "belief_result": _result_args, "belief_proof": _proof_args, "verification": _verification_args}


def _desc(value, field):
    names = ("work_id", "process", "trigger", "purpose", "stage_slot", "reader", "method", "output_contract", "args",
             "input_points", "numerical_view", "allocation", "permissions")
    _keys(value, names, field)
    _str(value["work_id"], field + "/work_id")
    _boot_slot(value["process"], field + "/process")
    _set(value["trigger"], field + "/trigger", _trigger)
    purpose = _enum(value["purpose"], field + "/purpose", _STAGES)
    _str(value["stage_slot"], field + "/stage_slot")
    _nullable(value["reader"], field + "/reader", _point)
    _contract(value["method"], field + "/method")
    _contract(value["output_contract"], field + "/output_contract")
    _ARGS[purpose](value["args"], field + "/args")
    _set(value["input_points"], field + "/input_points", _point)
    _nullable(value["numerical_view"], field + "/numerical_view", _fixed_view)
    _boot_slot(value["allocation"], field + "/allocation")
    _set(value["permissions"], field + "/permissions", _boot_slot)


def _requested(purposes):
    def decode(value, field):
        _keys(value, ("desc",), field)
        _desc(value["desc"], field + "/desc")
        if value["desc"]["purpose"] not in purposes:
            raise _Bad("shape", "purpose of another request contract", field + "/desc/purpose")
    return decode


_failure = _object({"failure_kind": _str, "content": _json,
                    "readings": lambda v, f: _array(v, f, _reading_evidence), "basis": _refs})
_unknown = _object({"reason": _str, "basis": _refs})
_boundary = _object({"work": _str, "reading": _reading_evidence, "reason": _str, "evidence": _refs})
def _sequence_range(value, field):
    _f._array(value, field)
    if len(value) != 2:
        raise _Bad("shape", "tuple length", field)
    _int(value[0], field + "/0")
    _int(value[1], field + "/1")


_gap = _object({"route_epoch": _str, "interval": _interval, "reason": _str, "evidence": _refs,
                "sequence_range": _sequence_range})
_frame = _object({
    "route_epoch": _str, "sample_seq": _int,
    "measurement_id": _object({"origin": _ref, "route_epoch": _str, "sample_seq": _int, "component": _str}),
    "measurement_interval": _interval, "actual_time": _clock_or_unavailable,
    "value": lambda v, f: _tagged(v, f, {"value": _json, "unavailable": _unavailable}),
    "quality": _contract_value, "gap": lambda v, f: _nullable(v, f, _gap), "source_cursor": _contract_value})
_segment_item = lambda v, f: _tagged(v, f, {   # noqa: E731
    "started": _boundary, "ended": _boundary,
    "route_applied": _object({"config": _point, "reading": _reading_evidence, "reason": _str, "evidence": _refs}),
    "frame": _frame, "gap": _gap,
    "measurement_unavailable": _object({"route_epoch": _str, "requested_interval": _interval, "reason": _str,
                                        "evidence": _refs}),
    "claim": _object({"route_epoch": _str, "interval": _interval, "kind": _str, "contract": _contract,
                      "evidence": _refs}),
    "coverage_unproved": _object({"route_epoch": _str, "interval": _interval,
                                  "missing_contracts": lambda v2, f2: _array(v2, f2, _contract), "evidence": _refs})})


def _count_law(value, field):
    names = ("model", "extends", "carrier_by_state", "channels", "rows", "frame_relation")
    _keys(value, names, field)
    _point(value["model"], field + "/model")
    _nullable(value["extends"], field + "/extends", _point)
    _array(value["carrier_by_state"], field + "/carrier_by_state", _str)
    _array(value["channels"], field + "/channels", _object({
        "id": _str, "process": _boot_slot, "route_configs": lambda v, f: _set(v, f, _point), "domain": _interval}))
    _array(value["rows"], field + "/rows", _object({
        "marks": lambda v, f: _array(v, f, _object({"channel": _str, "time_ns": _int,
                                                     "count": lambda v2, f2: _int(v2, f2, minimum=1)})),
        "mass": lambda v, f: _array(v, f, lambda v2, f2: _rational(v2, f2, minimum=(0, 1)))}))
    if value["frame_relation"] != "independent_given_carrier":
        raise _Bad("shape", "frame_relation literal", field + "/frame_relation")


def _terminal(value, field):
    names = ("work", "request", "stage", "first_receipt", "terminal_kind", "returned", "basis", "view")
    _keys(value, names, field)
    _str(value["work"], field + "/work")
    _point(value["request"], field + "/request")
    _enum(value["stage"], field + "/stage", _STAGES)
    _point(value["first_receipt"], field + "/first_receipt")
    kind = _enum(value["terminal_kind"], field + "/terminal_kind", ("outputs", "value", "failure", "unknown"))
    _nullable(value["returned"], field + "/returned", lambda v, f: _tagged(v, f, {
        "output": _contract_value, "point": _point, "draw_value": _json}))
    _object({"generation": lambda v, f: _nullable(v, f, _object({"started": _reading_evidence,
                                                                 "finished": _reading_evidence})),
             "failure": lambda v, f: _nullable(v, f, _failure),
             "unknown": lambda v, f: _nullable(v, f, _unknown)})(value["basis"], field + "/basis")
    _fixed_view(value["view"], field + "/view")
    basis = value["basis"]
    if kind in ("failure", "unknown"):
        if value["returned"] is not None or basis[kind] is None \
                or basis["unknown" if kind == "failure" else "failure"] is not None:
            raise _Bad("shape", "failure/unknown terminal needs null returned and only its own basis", field)
    elif basis["failure"] is not None or basis["unknown"] is not None:
        raise _Bad("shape", "a known output carries no failure/unknown basis", field)


def _clock_source(value, field):
    names = ("run", "provider", "implementation", "python_version", "resolution_s", "monotonic", "adjustable",
             "measurement")
    _keys(value, names, field)
    _ref(value["run"], field + "/run")
    for name in ("provider", "implementation", "python_version"):
        _str(value[name], f"{field}/{name}")
    _rational(value["resolution_s"], field + "/resolution_s", minimum=(0, 1), exclusive=True)
    _bool(value["monotonic"], field + "/monotonic")
    _bool(value["adjustable"], field + "/adjustable")
    _nullable(value["measurement"], field + "/measurement", _contract)


def _boot_declaration(value, field):
    _keys(value, ("capacity", "scope", "routes", "initial", "environment"), field)
    _quantity(value["capacity"], field + "/capacity")
    _slot("sui.fb.resource_scope", _resource_scope)(value["scope"], field + "/scope")
    _array(value["routes"], field + "/routes", _slot("sui.fb.bootstrap_route", _bootstrap_route))
    _nullable(value["initial"], field + "/initial", _slot("sui.fb.initial_process", _initial_process))
    _slot("sui.fb.environment", _environment)(value["environment"], field + "/environment")


def _empty(value, field):
    _keys(value, (), field)


# 契約 → (外側の Body の型, 書き手の役割, content の復号)。外側は CSB の entries の body/roles を本体に写したもの
# (試験が表と照らす)。sui.f.* の残りは F-a の f_from_json。
_FB = {
    "sui.clock.source/1": ("Observed", "membrane", _clock_source),
    "sui.f.observation_plan/2": ("Prediction", "model",
                                 _object({"model": _point, "projection": _method_call, "generation": _method_call})),
    "sui.fb.belief_adopted/1": ("Decided", "model", _object({
        "origin": _point, "model": _point, "previous": lambda v, f: _nullable(v, f, _point), "request": _point,
        "result": _point, "acquisition": _point})),
    "sui.fb.boot_declaration/1": ("Observed", "membrane", _boot_declaration),
    "sui.fb.candidate_request/1": ("Decided", "model", _requested(("candidate_generation",))),
    "sui.fb.clock_notice/1": ("Observed", "membrane", _clock_source),
    "sui.fb.draw_report/1": ("Observed", "membrane", _object({"work": _str, "outcome": lambda v, f: _tagged(v, f, {
        "value": _json, "failure": _failure, "unknown": _unknown})})),
    "sui.fb.draw_requested/1": ("Decided", "model", _requested(("selection_draw",))),
    "sui.fb.evaluated/1": ("Observed", "membrane", _object({"request": _point, "report": _point, "artifact": _point})),
    "sui.fb.evaluation_requested/1": ("Decided", "model", _requested(("evaluation_prepare",))),
    "sui.fb.finite_joint_count_law/1": ("Prediction", "model", _count_law),
    "sui.fb.monitor_span/1": ("Observed", "membrane", _object({
        "segment": _point, "work": _str, "route": _point, "clock": _point, "entered_ns": _int, "observed_ns": _int})),
    "sui.fb.prepared/1": ("Observed", "membrane", _object({"request": _point, "report": _point, "artifact": _point})),
    "sui.fb.segment_binding/1": ("Observed", "membrane", _object({
        "segment": _point, "report": _point, "route": _point, "reading_contract": _contract,
        "evidence": lambda v, f: _set(v, f, _point),
        "generation": _object({"applied": lambda v, f: _nullable(v, f, _point),
                               "started": lambda v, f: _nullable(v, f, _point),
                               "ended": lambda v, f: _nullable(v, f, _point)}),
        "clock": lambda v, f: _set(v, f, _point), "view": _fixed_view})),
    "sui.fb.segment_report/1": ("Observed", "membrane", _object({"segment": _point, "item_slot": _str,
                                                                "item": _segment_item})),
    "sui.fb.segment_requested/1": ("Decided", "model", _requested(("measure_segment",))),
    "sui.fb.selection/1": ("Decided", "model", _object({"evaluated": _point})),
    "sui.fb.update_result/1": ("Prediction", "model", _object({
        "request": _point,
        "result": lambda v, f: _f._decode(v, _f.FiniteUpdateResult, f),
        "application_digest": lambda v, f: _point(v, f),   # Digest: sha256: + 64 hex (参照の辺は作らない)
        "numerical_view": _fixed_view, "registry_key": _str})),
    "sui.fb.work_report/1": ("Observed", "membrane", _object({
        "work": _str, "started": _reading_evidence, "finished": _reading_evidence,
        "outcome": lambda v, f: _tagged(v, f, {"outputs": _contract_value, "failure": _failure,
                                               "unknown": _unknown})})),
    "sui.fb.work_requested/1": ("Decided", "model", _requested(
        ("belief_result", "belief_proof", "verification", "evaluation", "belief_update"))),
    "sui.fb.work_terminal/1": ("Observed", "membrane", _terminal),
    "sui.s4.boot/1": ("Observed", "membrane", _empty),
}


def shape_of_record(contract_name, record, content) -> list:
    """(契約の名前/版, Record, content の JSON) → 形の違反の列 (正常は空列)。未知の契約は None (呼んだ側が missing_contract に)。"""
    from .contracts import ContractRef
    from .f_entry import _wire_types
    known = _FB.get(contract_name)
    try:
        if known is None:
            name, version = contract_name.rsplit("/", 1)
            if ContractRef(name, version) not in _wire_types()[0]:
                return None
            from .f_entry import f_from_json
            f_from_json(record.body.content.data, contract=ContractRef(name, version))
            return []
        body, role, decode = known
        if type(record.body).__name__ != body:
            raise _Bad("shape", f"{body} body required", "/body")
        if getattr(record.writer, "value", record.writer) != role:
            raise _Bad("shape", f"writer {role} required", "/writer")
        decode(content, "")
    except _Bad as exc:
        return [{"kind": exc.reason, "field": getattr(exc, "field", None), "detail": str(exc)}]
    except (_f.FSpecificationMissing,) as exc:
        return [{"kind": "unknown_version", "field": None, "detail": str(exc)}]
    return []
