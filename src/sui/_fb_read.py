"""取得の列を読む本 (紙 F-b §6-10 K26・K26-a・K26-b)。公開の口は `fb.read_acquisition_sequence`。

保存した観測モデルの記録 (Prediction / MODEL) と、K25 でホストが預けた取得の結果の Frame の列を読み、初期の隠れた
状態ごとの L(d | u, s0) = Σ_{s1..sn} Π_i K_{u_i}(y_i, s_i | s_{i-1}) を Fraction で厳密に返す。選択の因子は含めない。
核の計算は F-a と同じ向き (arrival 行 / departure 列、`f.py` の観測の適用) で、正規化はしない。F-a の観測の読み口
(`read_f_observations`) には登録しない・`FiniteObservation` のハンドルは作らない (K26 の新しい決定 2)。
純粋な関数: 台帳に何も書かず、ホストの状態を読まない。読めない時は理由を返し、空・取れなかった・有効な確率で埋めない。
"""

from fractions import Fraction as _Fraction

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from ._fb_wire import dumps as _dumps
from .contracts import ContractRef as _ContractRef
from .ids import Ref as _Ref
from .records import Observed as _Observed, Prediction as _Prediction

_VALUE_ONLY = _ContractRef("sui.f.value_only", "1")
_SAMPLING_COMPONENT = "source_acquisition"   # K25 の取得の Frame の MeasurementId.component
# 合法な 4 組 (K25 (2)(c)) → control_rule の after の鍵
_SYMBOLS = {("taken", True): "taken", ("empty", True): "empty",
            ("unavailable", True): "unavailable_called", ("unavailable", False): "unavailable_missing"}


class _Unreadable(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def read(records, *, model, run, route_epoch, through_seq) -> _fb.AcquisitionReadResult:
    used, contracts = [], []
    try:
        declaration, boot = _declaration(records, model, used, contracts)
        observations = _sequence(records, run=run, route_epoch=route_epoch, through_seq=through_seq, used=used)
        _route(records, boot, declaration, route_epoch, used, contracts)
        _time_projection(declaration)
        controls = _controls(declaration, observations)
        _independence(declaration)
    except _Unreadable as exc:
        return _fb.AcquisitionReadResult(kind="unreadable", reason=exc.reason, observations=(), initial_states=(),
                                         likelihood=None, controls=(), used_records=(), contracts=())
    likelihood = _likelihood(declaration, observations, controls)
    contracts += [_c.ACQUISITION_RESULT_PROJECTION, _c.ACQUISITION_RESULT_SAMPLING, declaration.control_rule.contract,
                  declaration.independence.contract, declaration.time_projection]
    return _fb.AcquisitionReadResult(
        kind="read" if any(likelihood) else "model_zero", reason=None, observations=observations,
        initial_states=declaration.states, likelihood=likelihood, controls=tuple(u.id for u in controls),
        used_records=tuple(dict.fromkeys(used)), contracts=tuple(dict.fromkeys(contracts)))


# --- 1・2. 宣言と、その中身の検査 ---

def _declaration(records, model, used, contracts):
    record = records.get(model)
    # Prediction の書き手は MODEL だけ (records の型が構築で断る) なので、書き手は別に見ない (K26-e (オ))
    if (record is None or not isinstance(record.body, _Prediction)
            or record.body.contract != _c.ACQUISITION_OBSERVATION_MODEL):
        raise _Unreadable("missing_declaration")
    try:
        content = record.body.content.as_json()
        value = _f._decode(content["value"], _fb.AcquisitionObservationModel, "/value")
        boot = content["declared_at"]["declaration"]
    except (_f.FInputError, ValueError, TypeError, KeyError):
        raise _Unreadable("shape") from None
    if value.projection != _c.ACQUISITION_RESULT_PROJECTION or value.time_projection != _VALUE_ONLY:
        raise _Unreadable("missing_declaration")
    _check_model(value)
    used.append(model)
    contracts += [_c.ACQUISITION_OBSERVATION_MODEL]
    return value, boot


def _check_model(model) -> None:
    """有限の状態・核の列の和・セルの分け方・セルの観測値 (合法な 4 組) を検査する。外れたら shape。"""
    n = len(model.states)
    ids = [u.id for u in model.controls]
    if n == 0 or len(set(model.states)) != n or not ids or len(set(ids)) != len(ids):
        raise _Unreadable("shape")
    for control in model.controls:
        outcomes = control.kernel.outcomes
        names = [o.id for o in outcomes]
        if not outcomes or len(set(names)) != len(names):
            raise _Unreadable("shape")
        for o in outcomes:
            if len(o.matrix) != n or any(len(row) != n or any(x < 0 for x in row) for row in o.matrix):
                raise _Unreadable("shape")
        # 出発の状態 (列) ごとに、全 outcome・全到着の質量の和が 1
        if any(sum(o.matrix[i][j] for o in outcomes for i in range(n)) != 1 for j in range(n)):
            raise _Unreadable("shape")
        covered = [name for cell in control.cells for name in cell.outcomes]
        if (any(not cell.outcomes for cell in control.cells)   # セルは空でない (:2660、K26-d (エ))
                or len(covered) != len(set(covered)) or set(covered) != set(names)):
            raise _Unreadable("shape")
        observed = [_symbol(cell.observation) for cell in control.cells]
        if None in observed or len(set(observed)) != len(observed):
            raise _Unreadable("shape")


def _symbol(observation):
    """セルの観測値 → 合法な 4 組の名前。合法でなければ None。"""
    if observation.kind != "measurement":
        return None
    value = observation.value
    if not hasattr(value, "keys") or set(value.keys()) != {"result", "source_called"}:
        return None
    if type(value["result"]) is not str or type(value["source_called"]) is not bool:
        return None
    return _SYMBOLS.get((value["result"], value["source_called"]))


# --- 3・4. 列を集めて観測にする ---

def _sequence(records, *, run, route_epoch, through_seq, used):
    if type(through_seq) is not int or through_seq < 0:
        raise _Unreadable("shape")
    frames = {}   # sample_seq → {正準 bytes: Point}
    for point in sorted(records):
        record = records[point]
        if not isinstance(record.body, _Observed) or record.body.contract != _c.SEGMENT_REPORT:
            continue
        try:
            item = record.body.content.as_json()["item"]
            if item["kind"] != "frame":
                continue
            mid = _f._decode(item["value"]["measurement_id"], _f.MeasurementId, "/measurement_id")
        except (_f.FInputError, ValueError, TypeError, KeyError):
            continue   # この列の Frame と名乗っていない記録は読まない
        if (mid.component != _SAMPLING_COMPONENT or mid.origin != run or mid.route_epoch != route_epoch
                or not 0 <= mid.sample_seq <= through_seq):
            continue
        # 同じ取得の再配送・同じ記録は 1 つとして数える。中身の違う Frame は食い違い
        frames.setdefault(mid.sample_seq, {}).setdefault(_dumps(item["value"]), point)
    observations, cursor = [], 0
    for seq in range(through_seq + 1):
        found = frames.get(seq)
        if not found:
            raise _Unreadable("missing_record")
        if len(found) > 1:
            raise _Unreadable("conflict")
        (raw_value, point), = found.items()
        observation = _observation(records, records[point], point, seq, run, route_epoch)
        if observation.cursor != cursor:   # 源の番号は taken の時だけ進む (K25)
            raise _Unreadable("conflict")
        cursor += observation.result == "taken"
        observations.append(observation)
        used += [point] + ([observation.received] if observation.received is not None else [])
    return tuple(observations)


def _observation(records, record, point, seq, run, route_epoch):
    try:
        frame = _f._decode(record.body.content.as_json()["item"]["value"], _f.MeasurementFrame, "/item/value")
    except (_f.FInputError, ValueError, TypeError, KeyError):
        raise _Unreadable("shape") from None
    value = frame.value
    if (frame.sample_seq != seq or frame.measurement_id.sample_seq != seq
            or frame.route_epoch != frame.measurement_id.route_epoch
            or isinstance(value, _f.Unavailable) or not isinstance(frame.actual_time, _f.ClockReading)
            or not hasattr(value, "keys") or not {"cursor", "source_called", "clock_source", "result"} <= set(value.keys())):
        raise _Unreadable("shape")
    interval, actual = frame.measurement_interval, frame.actual_time
    # K25 の取得の Frame: 区間は [before, after]、actual_time = after、どれも列の run の時計 (K26-d (ウ))
    if (interval.closure != "[start,end]" or interval.clock != run or actual.run != run
            or not interval.start_ns <= interval.end_ns or actual.time_ns != interval.end_ns):
        raise _Unreadable("shape")
    result = value["result"]
    cursor, called, source = value["cursor"], value["source_called"], value["clock_source"]
    if (not hasattr(result, "keys") or type(result.get("kind")) is not str or type(called) is not bool
            or type(cursor) is not int or cursor < 0 or type(source) is not str
            or (result["kind"], called) not in _SYMBOLS):
        raise _Unreadable("shape")
    received_id = received = None
    if result["kind"] == "taken":
        try:
            received_id = _f._decode(result["received"], _Ref, "/result/received")
        except (_f.FInputError, KeyError):
            raise _Unreadable("shape") from None
        received = _received(records, received_id, run=run, route_epoch=route_epoch, after_ns=actual.time_ns)
    before = _fb.ReadingClock(source=source, reading=_f.ClockReading(run=interval.clock, time_ns=interval.start_ns))
    after = _fb.ReadingClock(source=source, reading=frame.actual_time)
    return _fb.AcquisitionReadItem(sample_seq=seq, cursor=cursor, result=result["kind"], source_called=called,
                                      before=before, after=after, received_id=received_id,
                                      measurement_id=frame.measurement_id, frame=point, received=received)


def _received(records, received_id, *, run, route_epoch, after_ns):
    """taken の原文の Point (K26-d (イ))。同じ名札の記録を範囲の全部から集める。無ければ欠け、2 つ以上・Received でない・
    別の口・別の run・受信の時刻が after でない、は Frame と原文の食い違い (別の口・run の原文で埋めない)。"""
    found = [p for p, r in records.items() if r.id == received_id]
    if not found:
        raise _Unreadable("missing_record")
    if len(found) > 1:
        raise _Unreadable("conflict")
    record = records[found[0]]
    body = record.body
    if not isinstance(body, _Observed) or body.contract != _c.RECEIVED or record.at.run != run \
            or body.received_ns != after_ns:
        raise _Unreadable("conflict")
    try:
        epoch = body.content.as_json()["route_epoch"]
    except (ValueError, TypeError, KeyError):
        raise _Unreadable("shape") from None
    if epoch != route_epoch:
        raise _Unreadable("conflict")
    return found[0]


def _route(records, boot, model, route_epoch, used, contracts) -> None:
    """観測モデルは同じ Boot の route_slot の口の宣言。その口の route_epoch でない列には使わない。"""
    record = records.get(boot) if type(boot) is str else None
    if record is None or record.body.contract != _c.BOOT_DECLARATION:
        raise _Unreadable("missing_record")
    try:
        routes = record.body.content.as_json()["routes"]
        epochs = [r["declaration"]["value"]["config"]["route_epoch"] for r in routes if r["slot"] == model.route_slot]
    except (ValueError, TypeError, KeyError):
        raise _Unreadable("shape") from None
    if epochs != [route_epoch]:
        raise _Unreadable("missing_declaration")
    used.append(boot)
    contracts.append(_c.BOOT_DECLARATION)


# --- 5. 時刻の条件 (K26-a (ケ)) ---

def _time_projection(model) -> None:
    for control in model.controls:
        elapsed = {o.id: o.elapsed_ns for o in control.kernel.outcomes}
        for cell in control.cells:
            if len({elapsed[name] for name in cell.outcomes}) > 1:
                raise _Unreadable("time_projection_unproved")


# --- 6・7. 制御と、選び方が状態に依存しない根拠 ---

def _controls(model, observations):
    rule = model.control_rule
    if rule.contract != _c.ACQUISITION_CONTROL_TABLE:
        raise _Unreadable("missing_declaration")
    args = rule.args
    keys = set(args.keys()) if hasattr(args, "keys") else None
    # 表の形は、使う行だけでなく全部を先に確かめる (K26-d (ア)、レビュー 2 通目 R1-remains)
    if keys == {"schedule"} and _rows(args["schedule"]) and all(_options(row) for row in args["schedule"]):
        table = args["schedule"]
        candidates = [table[i] if i < len(table) else () for i in range(len(observations))]
    elif (keys == {"first", "after"} and _options(args["first"]) and hasattr(args["after"], "keys")
          and set(args["after"].keys()) <= set(_SYMBOLS.values()) and all(map(_options, args["after"].values()))):
        after = args["after"]
        names = [_SYMBOLS[(o.result, o.source_called)] for o in observations]
        candidates = [args["first"]] + [after.get(name, ()) for name in names[:-1]]
    else:
        raise _Unreadable("shape")
    by_id = {u.id: u for u in model.controls}
    chosen = []
    for options in candidates:
        if len(options) != 1:
            raise _Unreadable("control_ambiguous")
        if options[0] not in by_id:
            raise _Unreadable("missing_declaration")
        chosen.append(by_id[options[0]])
    return tuple(chosen)


def _rows(value) -> bool:
    return not isinstance(value, str) and isinstance(value, (list, tuple))


def _options(value) -> bool:
    """制御の候補の列 = 文字列の列。"""
    return _rows(value) and all(type(u) is str for u in value)


def _independence(model) -> None:
    """初期の状態ごとの選び方の重みの行が全部等しく、正規化されている時だけ根拠あり。重みは L に掛けない。"""
    basis = model.independence
    try:
        if basis.contract != _c.STATE_INDEPENDENT_CONTROL_SELECTION or set(basis.args.keys()) != {"weights_by_initial_state"}:
            raise _Unreadable("control_independence_unproved")
        rows = _f._decode(basis.args["weights_by_initial_state"], tuple[tuple[_Fraction, ...], ...], "/weights")
    except (_f.FInputError, AttributeError, TypeError):
        raise _Unreadable("control_independence_unproved") from None
    if (len(rows) != len(model.states) or len(set(rows)) != 1 or len(rows[0]) != len(model.controls)
            or any(w < 0 for w in rows[0]) or sum(rows[0]) != 1):
        raise _Unreadable("control_independence_unproved")


# --- 8. L ---

def _likelihood(model, observations, controls):
    """各 s0 から α を単位ベクトルで始め、観測ごとに α'[s'] = Σ_s α[s] · Σ_{o ∈ セル(y)} M_o[s'][s] で進め、
    終わりの状態で足す。観測値のセルが無ければ、その観測の確率は 0 (モデルが出さない観測)。"""
    n = len(model.states)
    steps = []
    for observation, control in zip(observations, controls):
        name = _SYMBOLS[(observation.result, observation.source_called)]
        cell = next((c for c in control.cells if _symbol(c.observation) == name), None)
        members = set(cell.outcomes) if cell is not None else set()
        steps.append([o.matrix for o in control.kernel.outcomes if o.id in members])
    likelihood = []
    for s0 in range(n):
        alpha = [_Fraction(int(s == s0)) for s in range(n)]
        for matrices in steps:
            alpha = [sum((m[i][j] * alpha[j] for m in matrices for j in range(n)), _Fraction(0)) for i in range(n)]
        likelihood.append(sum(alpha, _Fraction(0)))
    return tuple(likelihood)
