"""Validated immutable declarations for sui.model.9 (S4b2 v0.6 §3-10-3)."""

from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
import hashlib as _hashlib
import json as _json
import re as _re

from .contracts import ContractRef as _ContractRef

SCHEME = "sui.model.9"
CONTRACT = _ContractRef("sui.s4b.rate_model", "1")
# 最上位は scheme と B1 の 12 欄、全 13 キー (§3-10-3)
KEYS = ("scheme", "contract", "units", "state_space", "variables", "processes", "controls",
        "records", "coverage", "order", "targets", "measure", "certificate_capabilities")


@_dataclass(frozen=True, slots=True, init=False)
class RateModel:
    """検査済みの正準 JSON を保持する不変値。軸と候補は宣言から得る (§3-10-10 G5)。

    outcomes は probe・marks の観測名、actions は choices の action、どちらも最初の出現順で一意化。
    choices は choices.id の宣言順。旧 GenerativeModel の Q・a 等をダミーで持たない。
    """
    declaration: bytes
    ref: str
    states: tuple
    outcomes: tuple
    actions: tuple
    choices: tuple

    def __init__(self, *, declaration: bytes) -> None:
        value = _load(declaration)
        try:
            _validate(value)
        except (TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError) as exc:
            _fail("schema", "malformed declaration: " + str(exc), "declaration")
        names = []
        for process in value["processes"]:
            params = process["params"]
            labels = (params["labels"] if process["family"]["name"] == "shared-probe" else
                      params["marks"]["labels"] if process["family"]["name"] == "marked-arrival"
                      and params["marks"] is not None else ())
            names.extend(label for label in labels if label not in names)
        choices = value["controls"]["choices"]
        for name, item in (("declaration", declaration),
                           ("ref", "sha256:" + _hashlib.sha256(declaration).hexdigest()),
                           ("states", tuple(value["state_space"]["states"])),
                           ("outcomes", tuple(names)),
                           ("actions", tuple(dict.fromkeys(c["action"] for c in choices))),
                           ("choices", tuple(c["id"] for c in choices))):
            object.__setattr__(self, name, item)


def rate_model_from_json(data: bytes) -> RateModel:
    return RateModel(declaration=data)


def rate_model_json(model: RateModel) -> bytes:
    if not isinstance(model, RateModel):
        _fail("schema", "expected RateModel", "model")
    return model.declaration


def rate_model_ref(model: RateModel) -> str:
    return "sha256:" + _hashlib.sha256(rate_model_json(model)).hexdigest()


def _fail(reason, detail, field):
    # Lazy imports keep model/agent dispatch independent of this loader.
    from .rate import RateInputError
    raise RateInputError(reason, detail, field)


def _unsupported(detail, field):
    from .rate import RateOutsideEvaluationType
    raise RateOutsideEvaluationType("unsupported_encoding", detail, field)


def _object(value, keys, field):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail("schema", "expected exactly " + ", ".join(keys), field)
    return value


def _array(value, field):
    if not isinstance(value, list):
        _fail("schema", "expected array", field)
    return value


def _text(value, field):
    if not isinstance(value, str) or not value:
        _fail("schema", "expected nonempty string", field)
    return value


def _id(value, field):
    if not isinstance(value, str) or _re.fullmatch(r"[a-z0-9_.-]{1,128}", value) is None:
        _fail("schema", "invalid ID", field)
    return value


def _integer(value, field, minimum=0):
    if type(value) is not int:
        _fail("schema", "expected integer (not bool)", field)
    if value < minimum:
        _fail("unit", "integer outside support", field)
    return value


def _rational(value, field, *, positive=False, nonnegative=False):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(item) is not int for item in value)):
        _fail("schema", "expected [integer, integer]", field)
    if value[1] <= 0:
        _fail("noncanonical", "denominator must be positive", field)
    number = _Fraction(*value)
    if [number.numerator, number.denominator] != value:
        _fail("noncanonical", "rational must be reduced", field)
    if (positive and number <= 0) or (nonnegative and number < 0):
        _fail("unit", "rational outside support", field)
    return number


def _names(value, field, *, ids=False, nonempty=True):
    items = _array(value, field)
    for index, item in enumerate(items):
        (_id if ids else _text)(item, f"{field}[{index}]")
    if (nonempty and not items) or len(set(items)) != len(items):
        _fail("shape", "empty or duplicate axis", field)
    return items


_FAMILIES = {
    "sui.s4b.rate_model", "gamma", "dirichlet", "point", "finite-ctmc",
    "marked-arrival", "shared-probe", "fixed-completion", "saturating-count",
    "constant-report", "exact-arrival", "exact", "tick", "choice-gated-window",
    "causal-ties", "finite-record-counting", "marked-arrival-density",
    "sui.s4b.rate_fixed_mmpp", "sui.s4b.rate_c1", "rational-series",
}


def _spec(value, families, field, *, named=False, capability=False):
    _object(value, ("name", "version", "params") if named else ("name", "version"), field)
    name = _id(value["name"], field + ".name")
    version = _text(value["version"], field + ".version")
    if version != version.strip():
        _fail("schema", "version has surrounding whitespace", field)
    if name in _FAMILIES and version != "1":
        _fail("unknown_version", "unregistered version of " + name, field)
    if name not in families and not capability:
        if name in _FAMILIES:
            _fail("shape", "wrong kind of registered family", field)
        from .rate import RateSpecificationMissing
        raise RateSpecificationMissing("missing_kernel", "unregistered family " + name, field)
    if named and not isinstance(value["params"], dict):
        _fail("schema", "params must be object", field + ".params")
    return name


def _clock(value, field):
    name = _spec(value, {"exact", "tick"}, field, named=True)
    params = value["params"]
    if name == "exact":
        _object(params, (), field + ".params")
    else:
        _object(params, ("width_ns", "phase", "check"), field + ".params")
        width = _integer(params["width_ns"], field + ".width_ns", 1)
        phase = params["phase"]
        if phase != "uniform":
            _object(phase, ("point_ns",), field + ".phase")
            if _integer(phase["point_ns"], field + ".phase.point_ns") >= width:
                _fail("unit", "phase outside tick", field)
        if params["check"] != "uniform_in_tick":
            _unsupported("unknown tick check law", field)


def _load(data):
    if type(data) is not bytes:
        _fail("schema", "expected bytes", "declaration")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("schema", "duplicate JSON key", key)
            result[key] = value
        return result
    def bad_constant(value):
        _fail("schema", "nonfinite JSON number " + value, "declaration")
    try:
        value = _json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad_constant)
    except (UnicodeError, _json.JSONDecodeError, RecursionError) as exc:
        _fail("schema", str(exc), "declaration")
    def no_floats(item):
        if isinstance(item, float):
            _fail("schema", "floating numbers are not declaration values", "declaration")
        if isinstance(item, dict):
            for child in item.values(): no_floats(child)
        elif isinstance(item, list):
            for child in item: no_floats(child)
    no_floats(value)
    try:
        canonical = _json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        _fail("schema", str(exc), "declaration")
    if canonical != data:
        _fail("noncanonical", "expected canonical UTF-8 JSON", "declaration")
    return value


def _validate(d):
    _object(d, KEYS, "declaration")
    if d["scheme"] != SCHEME:
        _fail("unknown_version" if isinstance(d["scheme"], str) else "schema", "expected " + SCHEME, "scheme")
    _spec(d["contract"], {CONTRACT.name}, "contract")
    units = _object(d["units"], ("time", "rate", "record", "information", "cost"), "units")
    for key in ("rate", "record", "information", "cost"): _text(units[key], "units." + key)
    _object(units["time"], ("name", "seconds"), "units.time")
    time_unit = _text(units["time"]["name"], "units.time.name")
    _rational(units["time"]["seconds"], "units.time.seconds", positive=True)
    if (units["rate"] != time_unit + "^-1" or units["record"] != "ns" or
            units["information"] != "nat" or units["cost"] != "nat"):
        _fail("unit", "inconsistent units", "units")
    space = _object(d["state_space"], ("states", "initial"), "state_space")
    states = _names(space["states"], "state_space.states")
    n = len(states)
    def probabilities(values, length, field):
        _array(values, field)
        if len(values) != length: _fail("shape", "axis length", field)
        numbers = [_rational(v, field, nonnegative=True) for v in values]
        if any(number > 1 for number in numbers): _fail("unit", "probability outside [0,1]", field)
        if sum(numbers) != 1: _fail("normalization", "probabilities must sum to one", field)
    probabilities(space["initial"], n, "state_space.initial")
    def index(items, keys, field):
        result = {}
        for i, item in enumerate(_array(items, field)):
            path = f"{field}[{i}]"
            _object(item, keys, path)
            ident = _id(item["id"], path + ".id")
            if ident in result: _fail("shape", "duplicate ID", path)
            result[ident] = item
        return result
    variables = index(d["variables"], ("id", "domain", "unit", "role", "scope", "prior", "generated_by"), "variables")
    processes = index(d["processes"], ("id", "family", "parents", "outputs", "params"), "processes")
    records = index(d["records"], ("id", "generator", "kernel", "experiment", "clock", "alphabet", "probe"), "records")
    def reference(ident, table, field, family=None):
        _id(ident, field)
        if ident not in table or (family and table[ident]["family"]["name"] != family):
            _fail("shape", "missing or wrong-kind reference", field)
        return table[ident]
    for ident, variable in variables.items():
        field = "variables." + ident
        domain = variable["domain"]
        if not isinstance(domain, dict) or "kind" not in domain:
            _fail("schema", "expected domain", field)
        kind = _text(domain["kind"], field + ".domain.kind")
        axis = "labels" if kind in ("simplex", "finite") else "states" if kind == "state-path" else None
        if kind not in ("positive-real", "nonnegative-real", "simplex", "finite", "state-path", "event-stream", "event"):
            _unsupported("unknown domain", field + ".domain")
        _object(domain, ("kind", axis) if axis else ("kind",), field + ".domain")
        if axis: _names(domain[axis], field + ".domain." + axis)
        if kind == "state-path" and domain["states"] != states:
            _fail("shape", "state path axis", field)
        for key in ("role", "scope", "unit"): _text(variable[key], field + "." + key)
        if variable["role"] not in ("law", "auxiliary") or variable["scope"] not in ("model", "run", "attempt", "event"):
            _fail("schema", "invalid role/scope", field)
        if (variable["unit"] not in (units["rate"], time_unit, "1") or
                (axis or kind in ("event-stream", "event")) and variable["unit"] != "1"):
            _fail("unit", "domain unit", field)
        prior, generator = variable["prior"], variable["generated_by"]
        if (prior is None) == (generator is None) or variable["role"] == "law" and generator is not None:
            _fail("shape", "expected a prior or one generator", field)
        if generator is not None: reference(generator, processes, field + ".generated_by")
        if prior is None: continue
        name = _spec(prior, {"gamma", "dirichlet", "point"}, field + ".prior", named=True)
        p = prior["params"]
        if name == "gamma":
            _object(p, ("shape", "rate"), field + ".prior.params")
            if kind != "positive-real": _fail("unit", "gamma support", field)
            for key in p: _rational(p[key], field + ".prior." + key, positive=True)
        elif name == "dirichlet":
            _object(p, ("alpha",), field + ".prior.params")
            if kind != "simplex": _fail("unit", "dirichlet support", field)
            alpha = _array(p["alpha"], field + ".prior.alpha")
            if len(alpha) != len(domain["labels"]): _fail("shape", "dirichlet axis", field)
            for item in alpha: _rational(item, field + ".prior.alpha", positive=True)
        else:
            _object(p, ("value",), field + ".prior.params")
            if kind == "simplex": probabilities(p["value"], len(domain["labels"]), field + ".prior.value")
            elif kind in ("positive-real", "nonnegative-real"):
                _rational(p["value"], field + ".prior.value", positive=kind == "positive-real", nonnegative=True)
            else: _fail("unit", "numerical prior on nonnumerical domain", field)
    families = {"finite-ctmc", "marked-arrival", "shared-probe", "fixed-completion"}
    for ident, process in processes.items():
        field = "processes." + ident
        _spec(process["family"], families, field + ".family")
        for key in ("parents", "outputs"):
            _names(process[key], field + "." + key, ids=True, nonempty=False)
            for item in process[key]: reference(item, variables, field + "." + key)
        if not isinstance(process["params"], dict): _fail("schema", "expected params", field)
    state_processes = [p for p in processes.values() if p["family"]["name"] == "finite-ctmc"]
    if len(state_processes) != 1: _fail("shape", "expected exactly one CTMC", "processes")
    state_process = state_processes[0]
    sp = state_process["params"]
    _object(sp, ("modes", "initial_mode", "off_diagonal"), "processes." + state_process["id"] + ".params")
    modes = _names(sp["modes"], "processes.modes")
    _text(sp["initial_mode"], "processes.initial_mode")
    if sp["initial_mode"] not in modes: _fail("shape", "initial mode", "processes.initial_mode")
    dependencies = {}
    def expression(expr, field, used):
        if not isinstance(expr, dict) or "kind" not in expr: _fail("schema", "expected expression", field)
        _text(expr["kind"], field + ".kind")
        if expr["kind"] == "constant":
            _object(expr, ("kind", "value"), field)
            _rational(expr["value"], field + ".value", nonnegative=True)
        elif expr["kind"] == "scaled_variable":
            _object(expr, ("kind", "variable", "coefficient"), field)
            variable = reference(expr["variable"], variables, field + ".variable")
            if variable["domain"]["kind"] not in ("positive-real", "nonnegative-real") or variable["unit"] != units["rate"]:
                _fail("unit", "rate expression needs an inverse-time scalar", field)
            if variable["scope"] in ("attempt", "event"):
                _fail("shape", "rate expression has no scope instance", field)
            _rational(expr["coefficient"], field + ".coefficient", positive=True)
            used.add(variable["id"])
        else: _unsupported("unknown expression", field)
    def output(process, kind, scope, field):
        if len(process["outputs"]) != 1: _fail("shape", "expected one output", field)
        variable = variables[process["outputs"][0]]
        if (variable["generated_by"] != process["id"] or variable["domain"]["kind"] != kind or
                variable["scope"] != scope or variable["role"] != "auxiliary"):
            _fail("shape", "output domain/scope/generator", field)
        return variable
    state_variable = output(state_process, "state-path", "run", "processes." + state_process["id"])
    for ident, process in processes.items():
        field, p, family = "processes." + ident, process["params"], process["family"]["name"]
        used = set()
        if family == "finite-ctmc":
            _object(p["off_diagonal"], modes, field + ".off_diagonal")
            for mode, matrix in p["off_diagonal"].items():
                _array(matrix, field + "." + mode)
                if len(matrix) != n: _fail("shape", "CTMC row axis", field)
                for i, row in enumerate(matrix):
                    _array(row, field)
                    if len(row) != n: _fail("shape", "CTMC column axis", field)
                    for j, expr in enumerate(row):
                        expression(expr, f"{field}.{mode}[{i}][{j}]", used)
                        if i == j and expr != {"kind": "constant", "value": [0, 1]}:
                            _fail("shape", "diagonal must be constant zero", field)
        elif family == "marked-arrival":
            _object(p, ("state_process", "route", "boundary", "rates", "marks"), field + ".params")
            reference(p["state_process"], processes, field, "finite-ctmc")
            _text(p["route"], field + ".route")
            _text(p["boundary"], field + ".boundary")
            if p["boundary"] != "membrane": _unsupported("arrival boundary", field)
            _object(p["rates"], modes, field + ".rates")
            for rates in p["rates"].values():
                _array(rates, field)
                if len(rates) != n: _fail("shape", "arrival rate axis", field)
                for expr in rates: expression(expr, field + ".rates", used)
            if p["marks"] is not None:
                marks = _object(p["marks"], ("labels", "probabilities"), field + ".marks")
                labels = _names(marks["labels"], field + ".marks.labels")
                matrix = _array(marks["probabilities"], field + ".marks.probabilities")
                if len(matrix) != len(labels): _fail("shape", "mark row axis", field)
                for row in matrix:
                    if len(_array(row, field)) != n: _fail("shape", "mark column axis", field)
                for j in range(n): probabilities([row[j] for row in matrix], len(labels), field + ".marks")
            used.add(state_variable["id"])
            output(process, "event-stream", "run", field)
        elif family == "shared-probe":
            _object(p, ("state_process", "probability_variable", "labels"), field + ".params")
            reference(p["state_process"], processes, field, "finite-ctmc")
            variable = reference(p["probability_variable"], variables, field)
            labels = _names(p["labels"], field + ".labels")
            if variable["domain"] != {"kind": "simplex", "labels": labels}:
                _fail("shape", "probe probability axis", field)
            if variable["scope"] in ("attempt", "event"):
                _fail("shape", "probe probability has no shared scope instance", field)
            measured = output(process, "finite", "attempt", field)
            if measured["domain"]["labels"] != labels: _fail("shape", "probe output axis", field)
            used.update((state_variable["id"], variable["id"]))
        else:
            _object(p, ("action", "duration", "effect", "probe", "count_record", "constant_notice"), field + ".params")
            _text(p["action"], field + ".action")
            _text(p["effect"], field + ".effect")
            _rational(p["duration"], field + ".duration", positive=True)
            if p["effect"] != "identity": _unsupported("completion effect", field)
            output(process, "event", "attempt", field)
            used.add(state_variable["id"])
            if p["count_record"] is None:
                if p["probe"] is not None: _fail("shape", "probe without count report", field)
                _text(p["constant_notice"], field + ".constant_notice")
            else:
                record = reference(p["count_record"], records, field + ".count_record")
                if record["generator"] != ident: _fail("shape", "completion/report link", field)
                _spec(record["kernel"], {"saturating-count"}, field + ".count_record.kernel", named=True)
                arrival_id = record["kernel"]["params"].get("arrival_process")
                arrival = reference(arrival_id, processes, field, "marked-arrival")
                used.update(arrival["outputs"])
                if p["constant_notice"] is not None: _fail("shape", "notice with count report", field)
                if p["probe"] is not None:
                    probe = reference(p["probe"], processes, field, "shared-probe")
                    used.update(probe["outputs"])
        expected = [vid for vid in variables if vid in used]
        if process["parents"] != expected: _fail("shape", "parents must match direct dependencies in variable order", field + ".parents")
        dependencies[ident] = {variables[v]["generated_by"] for v in used if variables[v]["generated_by"] is not None}
    for ident, variable in variables.items():
        if variable["generated_by"] is not None and ident not in processes[variable["generated_by"]]["outputs"]:
            _fail("shape", "generated_by/output backlink", "variables." + ident)
    remaining = dict(dependencies)
    while remaining:
        ready = {ident for ident, deps in remaining.items() if not deps.intersection(remaining)}
        if not ready: _fail("shape", "cyclic generation dependency", "processes")
        remaining = {ident: deps for ident, deps in remaining.items() if ident not in ready}
    record_arrivals = {}
    clock = None
    for ident, record in records.items():
        field = "records." + ident
        generator = reference(record["generator"], processes, field + ".generator")
        name = _spec(record["kernel"], {"saturating-count", "constant-report", "exact-arrival"}, field + ".kernel", named=True)
        p = record["kernel"]["params"]
        _id(record["experiment"], field + ".experiment")
        _clock(record["clock"], field + ".clock")
        if clock is not None and clock != record["clock"]: _fail("shape", "records must share one run clock", field)
        clock = record["clock"]
        probe = None if record["probe"] is None else reference(record["probe"], processes, field + ".probe", "shared-probe")
        if name == "constant-report":
            _object(p, ("notice",), field + ".kernel.params")
            _text(p["notice"], field + ".notice")
            if (generator["family"]["name"] != "fixed-completion" or probe is not None or
                    generator["params"]["constant_notice"] != p["notice"] or generator["params"]["count_record"] is not None):
                _fail("shape", "constant completion/report correspondence", field)
            expected_alphabet = {"kind": "finite", "values": [{"arrival_count": None, "outcome": None}]}
        else:
            keys = ("arrival_process", "cap", "report_at", "clock") if name == "saturating-count" else ("arrival_process", "clock", "include_mark")
            _object(p, keys, field + ".kernel.params")
            arrival = reference(p["arrival_process"], processes, field, "marked-arrival")
            record_arrivals[ident] = arrival["id"]
            _clock(p["clock"], field + ".kernel.clock")
            if p["clock"] != record["clock"]: _fail("shape", "kernel and record clock differ", field)
            if name == "saturating-count":
                cap = _integer(p["cap"], field + ".cap", 1)
                _text(p["report_at"], field + ".report_at")
                if p["report_at"] != "window_end": _unsupported("count report position", field)
                if generator["family"]["name"] == "fixed-completion":
                    if generator["params"]["count_record"] != ident or generator["params"]["probe"] != record["probe"]:
                        _fail("shape", "completion/probe/report correspondence", field)
                elif generator["id"] != arrival["id"] or probe is not None:
                    _fail("shape", "root count generator/probe", field)
                labels = (None,) if probe is None else probe["params"]["labels"]
                alphabet = _object(record["alphabet"], ("kind", "values"), field + ".alphabet")
                if len(_array(alphabet["values"], field + ".alphabet.values")) != (cap + 1) * len(labels):
                    _fail("shape", "alphabet length must cover the count/probe product", field + ".alphabet")
                expected_alphabet = {"kind": "finite", "values": [
                    {"arrival_count": {"kind": "exact" if k < cap else "at_least", "value": k}, "outcome": label}
                    for k in range(cap + 1) for label in labels]}
            else:
                if type(p["include_mark"]) is not bool: _fail("schema", "include_mark must be bool", field)
                if generator["id"] != arrival["id"] or probe is not None: _fail("shape", "arrival generator/probe", field)
                marks = arrival["params"]["marks"]
                if p["include_mark"] and marks is None: _fail("shape", "marked record without marks", field)
                expected_alphabet = {"kind": "arrival", "marks": marks["labels"] if p["include_mark"] else None}
        alphabet = record["alphabet"]
        _object(alphabet, expected_alphabet.keys(), field + ".alphabet")
        _text(alphabet["kind"], field + ".alphabet.kind")
        if alphabet["kind"] == "finite":
            for cell in _array(alphabet["values"], field + ".alphabet.values"):
                _object(cell, ("arrival_count", "outcome"), field + ".alphabet.cell")
                if cell["outcome"] is not None: _text(cell["outcome"], field + ".alphabet.outcome")
                if cell["arrival_count"] is not None:
                    count = _object(cell["arrival_count"], ("kind", "value"), field + ".alphabet.count")
                    _text(count["kind"], field + ".alphabet.count.kind")
                    if count["kind"] not in ("exact", "at_least"): _fail("schema", "count variant", field)
                    _integer(count["value"], field + ".alphabet.count", int(count["kind"] == "at_least"))
        elif alphabet["kind"] == "arrival":
            if alphabet["marks"] is not None: _names(alphabet["marks"], field + ".alphabet.marks")
        else: _fail("schema", "alphabet variant", field)
        if alphabet != expected_alphabet: _fail("shape", "alphabet must enumerate every cell once in order", field + ".alphabet")
    encodings = {}
    for ident, arrival in record_arrivals.items():
        encodings.setdefault(arrival, set()).add(records[ident]["kernel"]["name"])
    if any(len(names) > 1 for names in encodings.values()): _unsupported("overlapping exact/count record paths", "records")
    controls = _object(d["controls"], ("choices", "calendar"), "controls")
    choices = index(controls["choices"], ("id", "action", "reservation", "completion_process", "observation_records"), "controls.choices")
    if not choices: _fail("shape", "empty choices", "controls.choices")
    for ident, choice in choices.items():
        field = "controls.choices." + ident
        _text(choice["action"], field + ".action")
        _object(choice["reservation"], ("kind",), field + ".reservation")
        _text(choice["reservation"]["kind"], field + ".reservation.kind")
        if choice["reservation"]["kind"] != "immediate": _unsupported("reservation variant", field)
        completion = reference(choice["completion_process"], processes, field, "fixed-completion")
        if completion["params"]["action"] != choice["action"]: _fail("shape", "choice action", field)
        reports = _names(choice["observation_records"], field + ".observation_records", ids=True, nonempty=False)
        for rid in reports:
            if reference(rid, records, field)["generator"] != completion["id"]: _fail("shape", "another choice's report", field)
        if set(reports) != {r["id"] for r in records.values() if r["generator"] == completion["id"]}:
            _fail("shape", "choice report set", field)
    calendar_keys = []
    for change in _array(controls["calendar"], "controls.calendar"):
        _object(change, ("state_process", "time", "mode"), "controls.calendar")
        reference(change["state_process"], processes, "controls.calendar", "finite-ctmc")
        time = _rational(change["time"], "controls.calendar.time", nonnegative=True)
        _text(change["mode"], "controls.calendar.mode")
        if change["mode"] not in modes: _fail("shape", "calendar mode", "controls.calendar")
        calendar_keys.append((time, change["state_process"]))
    if calendar_keys != sorted(set(calendar_keys)): _fail("shape", "calendar order/duplicates", "controls.calendar")
    coverage = _object(d["coverage"], ("intervals", "policy"), "coverage")
    _spec(coverage["policy"], {"choice-gated-window"}, "coverage.policy", named=True)
    _object(coverage["policy"]["params"], ("left", "right"), "coverage.policy.params")
    if coverage["policy"]["params"] != {"left": "open", "right": "closed"}: _unsupported("coverage boundaries", "coverage.policy")
    windows = {ident: [] for ident in records}
    arrival_windows = {}
    for window in _array(coverage["intervals"], "coverage.intervals"):
        _object(window, ("record", "start", "end", "source"), "coverage.intervals")
        record = reference(window["record"], records, "coverage.record")
        if record["id"] not in record_arrivals: _fail("shape", "constant report has count coverage", "coverage")
        start = _rational(window["start"], "coverage.start", nonnegative=True)
        end = _rational(window["end"], "coverage.end", nonnegative=True)
        if start >= end: _fail("unit", "coverage start must precede end", "coverage")
        source = _object(window["source"], ("kind", "id"), "coverage.source")
        _text(source["kind"], "coverage.source.kind")
        _id(source["id"], "coverage.source.id")
        if source["kind"] == "exogenous":
            if source["id"] != record["experiment"] or processes[record["generator"]]["family"]["name"] != "marked-arrival":
                _fail("shape", "exogenous experiment", "coverage.source")
        elif source["kind"] == "choice":
            choice = reference(source["id"], choices, "coverage.source")
            if record["id"] not in choice["observation_records"]: _fail("shape", "choice window/report", "coverage.source")
            duration = _Fraction(*processes[choice["completion_process"]]["params"]["duration"])
            if end - start != duration: _fail("shape", "choice window/duration", "coverage")
        else: _unsupported("coverage source law", "coverage.source")
        windows[record["id"]].append((start, end))
        arrival_windows.setdefault(record_arrivals[record["id"]], []).append((start, end))
    for ident, record in records.items():
        if record["kernel"]["name"] == "saturating-count" and len(windows[ident]) != 1:
            _fail("shape", "one window per count record", "coverage." + ident)
    for intervals in arrival_windows.values():
        ordered = sorted(intervals)
        if any(b[0] < a[1] for a, b in zip(ordered, ordered[1:])):
            _unsupported("overlapping observation windows", "coverage")
    order = _object(d["order"], ("time", "causal", "side", "ties"), "order")
    for key in ("time", "causal", "side"): _text(order[key], "order." + key)
    _spec(order["ties"], {"causal-ties"}, "order.ties")
    if (order["time"], order["causal"], order["side"]) != ("declared_physical_time", "declared_stage_position", "explicit"):
        _unsupported("time/causal order", "order")
    targets = _object(d["targets"], ("laws", "state_positions"), "targets")
    laws = _names(targets["laws"], "targets.laws", ids=True, nonempty=False)
    if laws != [v["id"] for v in variables.values() if v["role"] == "law"]:
        _fail("shape", "all laws in declaration order", "targets.laws")
    target_records = set()
    for target in _array(targets["state_positions"], "targets.state_positions"):
        _object(target, ("record", "position", "side"), "targets.state_positions")
        reference(target["record"], records, "targets.record")
        if target["record"] in target_records: _fail("shape", "duplicate state position", "targets")
        target_records.add(target["record"])
        position = _object(target["position"], ("time", "causal_stage", "causal_position"), "targets.position")
        _rational(position["time"], "targets.position.time", nonnegative=True)
        for key in ("causal_stage", "causal_position"): _integer(position[key], "targets.position." + key)
        _text(target["side"], "targets.side")
        if target["side"] not in ("pre", "post"): _fail("schema", "target side", "targets")
    measure = _object(d["measure"], ("family", "conditioning"), "measure")
    name = _spec(measure["family"], {"finite-record-counting", "marked-arrival-density"}, "measure.family")
    if _array(measure["conditioning"], "measure.conditioning"): _unsupported("conditioning adapter", "measure")
    kinds = {r["kernel"]["name"] for r in records.values()}
    if (name == "finite-record-counting" and "exact-arrival" in kinds or
            name == "marked-arrival-density" and "saturating-count" in kinds):
        _fail("unit", "record kernel and reference measure disagree", "measure")
    seen = set()
    for cap in _array(d["certificate_capabilities"], "certificate_capabilities"):
        _spec(cap, {"sui.s4b.rate_fixed_mmpp", "sui.s4b.rate_c1"}, "certificate_capabilities", capability=True)
        key = (cap["name"], cap["version"])
        if key in seen: _fail("shape", "duplicate capability", "certificate_capabilities")
        seen.add(key)
