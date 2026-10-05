"""Strict model.8 declaration loader. Validity is separate from certification."""
import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction as F
from itertools import product

from .action_types import ActionInputError, ActionIncompatible, integer


def error(reason, detail, field=None):
    raise ActionInputError(reason=reason, detail=detail, field=field)


def keys(value, names, field):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        error("schema", "expected exactly " + names, field)


def names(value, field):
    if not isinstance(value, list) or not value or any(type(x) is not str or not x for x in value) or len(set(value)) != len(value):
        error("shape", "unique nonempty string array required", field)
    return value


def rational(value, field, *, positive=False, signed=False):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(x) is not int for x in value) or value[1] <= 0:
        error("unit", "expected rational [integer, positive denominator]", field)
    result = F(*value)
    if [result.numerator, result.denominator] != list(value):
        error("noncanonical", "rational must be reduced", field)
    if (not signed and result < 0) or (positive and result <= 0):
        error("unit", "expected " + ("positive" if positive else "nonnegative") + " rational", field)
    return result


def number(value, field, *, positive=False, nonnegative=False):
    if type(value) not in (float, int) or not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        error("schema", "invalid finite number", field)
    return value


def normalized(values, field):
    if sum(values, F(0)) != 1:
        error("normalization", "probabilities must sum exactly to one", field)


def table(value, dimensions, field):
    if not dimensions:
        return rational(value, field)
    if not isinstance(value, list) or len(value) != dimensions[0]:
        error("shape", f"expected dimension {dimensions[0]}", field)
    return [table(x, dimensions[1:], field) for x in value]


def family(value, field, allowed):
    keys(value, "name version", field)
    if value["name"] not in allowed:
        raise ActionIncompatible(reason="unsupported_family_encoding", detail="undeclared family", field=field)
    if value["version"] != allowed[value["name"]]:
        error("unknown_version", "unknown family version", field)


def reservation(value, field):
    if not isinstance(value, dict):
        error("schema", "reservation object required", field)
    kind = value.get("kind")
    if kind == "next":
        keys(value, "kind step_ns", field)
        if type(value["step_ns"]) is not int or value["step_ns"] != 1:
            error("schema", "next step_ns must be 1", field)
    elif kind == "offset":
        keys(value, "kind offset_ns", field)
        integer(value["offset_ns"], field=field, minimum=0)
    elif kind == "at":
        keys(value, "kind not_before_ns", field)
        integer(value["not_before_ns"], field=field)
    elif kind == "immediate":
        keys(value, "kind", field)
    else:
        error("schema", "unknown reservation rule", field)


def points(value, field, *, delay=False):
    if not isinstance(value, list) or not value:
        error("shape", "nonempty points required", field)
    seen, masses = set(), []
    for p in value:
        if not isinstance(p, list) or len(p) != 2:
            error("shape", "point must have coordinate and probability", field)
        x, mass = p
        if delay:
            x = "+inf" if x == "+inf" else rational(x, field)
        elif x is not None:
            integer(x, field=field, minimum=0)
        if x in seen:
            error("shape", "duplicate point", field)
        seen.add(x)
        masses.append(rational(mass, field))
    normalized(masses, field)


def delay(value, field, axes):
    keys(value, "given rows", field)
    given = value["given"]
    if not isinstance(given, list) or any(x not in axes for x in given) or len(set(given)) != len(given):
        error("schema", "unknown or duplicate context axis", field)
    if not isinstance(value["rows"], list):
        error("shape", "rows required", field)
    expected = set(product(*(axes[x] for x in given)))
    seen = set()
    for row in value["rows"]:
        keys(row, "when points", field)
        if not isinstance(row["when"], list) or len(row["when"]) != len(given):
            error("shape", "full context tuple required", field)
        for axis, item in zip(given, row["when"]):
            if axis in ("rho", "lambda") and type(item) is not int:
                error("shape", "integer candidate index required", field)
            if axis in ("state", "mode") and type(item) is not str:
                error("shape", "context name required", field)
        tag = tuple(row["when"])
        if tag not in expected or tag in seen:
            error("shape", "unknown or duplicate context row", field)
        seen.add(tag)
        points(row["points"], field, delay=True)
    if seen != expected:
        error("shape", "every supported context needs one row", field)


def _validate(d):
    keys(d, "scheme states outcomes actions a learnable D log_C gamma work completion clock activity effects execution choices arrivals", "model")
    if d["scheme"] != "sui.model.8":
        error("unknown_version", "expected sui.model.8", "scheme")
    states, outcomes, actions = (names(d[k], k) for k in ("states", "outcomes", "actions"))
    ns, ny, na = len(states), len(outcomes), len(actions)
    learn = d["learnable"]
    if not isinstance(learn, list) or any(x not in actions for x in learn) or learn != sorted(set(learn)):
        error("schema", "learnable must be sorted action subset", "learnable")
    if not isinstance(d["a"],dict) or set(d["a"])!=set(actions):
        error("shape","all action axes required","a")
    for a in actions:
        a_values = table(d["a"][a], (ny, ns), "a." + a)
        for col in zip(*a_values):
            if a in learn:
                if not any(col): error("normalization", "empty Dirichlet support", "a." + a)
            else: normalized(col, "a." + a)
    normalized(table(d["D"], (ns,), "D"), "D")
    if not isinstance(d["log_C"], list) or len(d["log_C"]) != ny:
        error("shape", "outcome log_C array required", "log_C")
    for x in d["log_C"]:
        if x != "-inf": number(x, "log_C")
    number(d["gamma"], "gamma", positive=True)
    for field in ("work", "effects"):
        if not isinstance(d[field], dict) or set(d[field]) != set(actions):
            error("shape", "all actions required", field)
    for a, w in d["work"].items():
        if w.get("kind") == "known":
            keys(w, "kind points", "work." + a); points(w["points"], "work." + a)
        elif w.get("kind") == "dp":
            keys(w, "kind alpha base", "work." + a)
            rational(w["alpha"], "work.alpha", positive=True)
            b = w["base"]; keys(b, "name version params", "work.base")
            if b["version"] != "1": error("unknown_version", "base version", "work.base")
            if b["name"] == "atoms":
                keys(b["params"], "points", "base.params"); points(b["params"]["points"], "base.points")
            elif b["name"] == "piecewise":
                p = b["params"]; keys(p, "edges_ns masses tail p_inf", "base.params")
                if not isinstance(p["edges_ns"], list) or len(p["edges_ns"]) < 2:
                    error("shape", "at least two edges required", "base.edges_ns")
                for edge in p["edges_ns"]: integer(edge, field="base.edges_ns", minimum=0)
                if p["edges_ns"] != sorted(set(p["edges_ns"])): error("shape", "increasing edges required", "base.edges_ns")
                masses = table(p["masses"], (len(p["edges_ns"])-1,), "base.masses")
                keys(p["tail"], "kind kappa mass", "base.tail")
                if p["tail"]["kind"] != "pareto": error("schema", "pareto tail required", "base.tail")
                rational(p["tail"]["kappa"], "base.tail.kappa", positive=True)
                normalized([*masses, rational(p["tail"]["mass"], "base.tail.mass"), rational(p["p_inf"], "base.p_inf")], "base")
            else: error("unknown_version", "unknown base family", "work.base")
        else: error("schema", "unknown work kind", "work." + a)
    c = d["completion"]
    keys(c, "name version actions states work_unit time_unit speed_unit candidates weights share max_speed", "completion")
    family({k:c[k] for k in ("name", "version")}, "completion", {"progress":"1"})
    if c["actions"] != actions or c["states"] != states: error("shape", "completion axes must match", "completion")
    if any(type(c[k]) is not str or not c[k] for k in ("work_unit", "time_unit", "speed_unit")) or c["speed_unit"] != f'{c["work_unit"]}/{c["time_unit"]}':
        error("unit", "explicit coherent speed units required", "completion")
    if c["share"] != "all_actions": error("schema", "all_actions sharing required", "completion")
    if not isinstance(c["candidates"], list) or not c["candidates"]: error("shape", "speed candidates required", "completion")
    bound = rational(c["max_speed"], "completion.max_speed")
    for candidate in c["candidates"]:
        t = table(candidate, (na,ns), "completion.candidates")
        if any(x > bound for row in t for x in row): error("unit", "speed exceeds declared bound", "completion")
    weights = table(c["weights"], (len(c["candidates"]),), "completion.weights")
    if any(w <= 0 for w in weights): error("normalization", "positive speed weights required", "completion")
    normalized(weights, "completion.weights")
    clock = d["clock"]
    if clock.get("kind") == "clock-process":
        keys(clock, "kind version share candidates", "clock")
        if clock["version"] != "1": error("unknown_version", "clock version", "clock")
        if clock["share"] != "run": error("schema", "run clock sharing required", "clock")
        if not isinstance(clock["candidates"], list) or not clock["candidates"]: error("shape", "clock candidates required", "clock")
        cw = []
        for p in clock["candidates"]:
            keys(p, "weight kind width_ns phase_ns", "clock.candidate")
            cw.append(rational(p["weight"], "clock.weight", positive=True))
            if p["kind"] == "exact":
                if p["width_ns"] is not None or p["phase_ns"] is not None: error("schema", "exact width and phase must be null", "clock")
            elif p["kind"] == "tick":
                width = integer(p["width_ns"], field="clock.width_ns", minimum=1)
                if p["phase_ns"] != "uniform":
                    phase = rational(p["phase_ns"], "clock.phase_ns")
                    if phase >= width: error("unit", "phase outside bin", "clock.phase_ns")
            else: error("schema", "unknown clock kind", "clock")
        normalized(cw, "clock.weights")
    elif clock.get("kind") == "legacy-measure":
        keys(clock, "kind measure", "clock")
        m = clock["measure"]; keys(m, "share candidates", "clock.measure")
        if m["share"] != "all_actions" or not isinstance(m["candidates"], list) or not m["candidates"]: error("schema", "legacy measure sharing/candidates", "clock.measure")
        cw = []
        for p in m["candidates"]:
            keys(p, "name version params weight", "clock.measure.candidate")
            family({k:p[k] for k in ("name", "version")}, "clock.measure", {"exact":"1", "tick":"1"})
            cw.append(rational(p["weight"], "clock.weight", positive=True))
            if p["name"] == "exact": keys(p["params"], "", "clock.params")
            else:
                v=p["params"]; keys(v, "width_ns phase check", "clock.params")
                width=integer(v["width_ns"], field="clock.width_ns", minimum=1)
                if v["check"] != "uniform_in_tick": error("schema", "unknown legacy check", "clock.params")
                if v["phase"] != "uniform":
                    keys(v["phase"], "point_ns", "clock.phase")
                    phase=integer(v["phase"]["point_ns"], field="clock.phase", minimum=0)
                    if phase >= width: error("unit", "phase outside bin", "clock.phase")
        normalized(cw, "clock.weights")
    else: error("schema", "unknown clock law", "clock")
    v=d["activity"]; keys(v, "modes initial_given_state Q_by_mode calendar", "activity")
    modes=names(v["modes"], "activity.modes")
    initial=table(v["initial_given_state"], (len(modes),ns), "activity.initial")
    for col in zip(*initial): normalized(col, "activity.initial")
    if not isinstance(v["Q_by_mode"],dict) or set(v["Q_by_mode"]) != set(modes): error("shape", "all modes required", "activity.Q")
    for mode,q in v["Q_by_mode"].items():
        if not isinstance(q,list) or len(q)!=ns or any(not isinstance(row,list) or len(row)!=ns for row in q): error("shape", "square generator required", "activity.Q")
        for i,row in enumerate(q):
            for j,x in enumerate(row):
                number(x, "activity.Q")
                if (i!=j and x<0) or (i==j and x>0): error("normalization", "invalid generator sign", "activity.Q")
        if any(abs(math.fsum(col))>1e-12 for col in zip(*q)): error("normalization", "generator columns must sum to zero", "activity.Q")
    if not isinstance(v["calendar"],list): error("schema", "calendar array required", "activity.calendar")
    last=None
    for p in v["calendar"]:
        keys(p,"at_s mode","activity.calendar"); t=rational(p["at_s"],"activity.calendar",signed=True)
        if p["mode"] not in modes or (last is not None and t<=last): error("shape","calendar must be strictly increasing with known modes","activity.calendar")
        last=t
    for a,e in d["effects"].items():
        keys(e,"family B marks notice measure mode_on_dispatch mode_on_completion response_rate_s progress_start","effects."+a)
        family(e["family"],"effects.family",{"start-impulse":"2","response-wait":"1"})
        keys(e["B"],"kind values","effects.B")
        b=table(e["B"]["values"],(ns,ns),"effects.B")
        if e["B"]["kind"] not in ("known","dirichlet"): error("schema","unknown B kind","effects.B")
        for col in zip(*b):
            if e["B"]["kind"]=="known": normalized(col,"effects.B")
            elif not any(col): error("normalization","empty B support","effects.B")
        ne=0
        if e["marks"] is not None:
            keys(e["marks"],"labels probability","effects.marks")
            ne=len(names(e["marks"]["labels"],"effects.marks.labels"))
            t=table(e["marks"]["probability"],(ne,ns,ns),"effects.marks")
            for i in range(ns):
                for j in range(ns): normalized([t[k][i][j] for k in range(ne)],"effects.marks")
        if e["notice"] is not None:
            if not ne: error("schema","notice requires marks","effects.notice")
            keys(e["notice"],"labels probability","effects.notice")
            nn=len(names(e["notice"]["labels"],"effects.notice.labels"))
            t=table(e["notice"]["probability"],(nn,ne,ns,ns),"effects.notice")
            for k in range(ne):
                for i in range(ns):
                    for j in range(ns): normalized([t[y][k][i][j] for y in range(nn)],"effects.notice")
        keys(e["measure"],"at side","effects.measure")
        if e["measure"]["at"] not in ("start","report") or e["measure"]["side"] not in ("pre","post"): error("schema","unknown measurement position","effects.measure")
        for k in ("mode_on_dispatch","mode_on_completion"):
            if not isinstance(e[k],dict) or set(e[k])!=set(modes) or any(x not in modes for x in e[k].values()): error("shape","full mode map required","effects."+k)
        if e["family"]["name"]=="start-impulse":
            if e["response_rate_s"] is not None or e["progress_start"]!="dispatch": error("schema","start impulse response fields","effects")
        else:
            if not isinstance(e["response_rate_s"],list) or len(e["response_rate_s"])!=ns: error("shape","state response rates required","effects")
            for x in e["response_rate_s"]: number(x,"effects.response_rate_s",nonnegative=True)
            if e["progress_start"] not in ("dispatch","response"): error("schema","unknown progress start","effects")
    ex=d["execution"]; keys(ex,"family late think receipt chi confirmations","execution")
    family(ex["family"],"execution.family",{"wait-dispatch":"1","immediate-start":"1"})
    keys(ex["confirmations"],"reservation receipt dispatch","execution.confirmations")
    axes={"state":states,"mode":modes,"rho":range(len(c["candidates"])),"lambda":range(len(clock["candidates"] if clock["kind"]=="clock-process" else clock["measure"]["candidates"]))}
    if ex["family"]["name"]=="immediate-start":
        if any(ex[k] is not None for k in ("late","think","receipt","chi")) or any(x is not None for x in ex["confirmations"].values()): error("schema","immediate start must have null kernels","execution")
    else:
        if ex["late"]!="send_when_ready": error("schema","send_when_ready required","execution.late")
        for k in ("think","receipt"): delay(ex[k],"execution."+k,axes)
        chi=ex["chi"]; keys(chi,"share candidates","execution.chi")
        if chi["share"]!="all_actions" or not isinstance(chi["candidates"],list) or not chi["candidates"]: error("shape","chi candidates sharing required","execution.chi")
        cw=[]
        for p in chi["candidates"]:
            keys(p,"weight delay","execution.chi.candidate")
            cw.append(rational(p["weight"],"execution.chi.weight",positive=True)); delay(p["delay"],"execution.chi.delay",axes)
        normalized(cw,"execution.chi.weights")
        for k,p in ex["confirmations"].items():
            if p is not None: delay(p,"execution.confirmations."+k,axes)
    if not isinstance(d["choices"],dict) or not d["choices"] or any(type(k) is not str or not k for k in d["choices"]): error("shape","named choices required","choices")
    for k,p in d["choices"].items():
        keys(p,"action reservation","choices."+k)
        if p["action"] not in actions: error("unknown_candidate","unknown physical action","choices."+k)
        reservation(p["reservation"],"choices."+k)
        if (p["reservation"]["kind"]=="immediate") != (ex["family"]["name"]=="immediate-start"): error("schema","reservation incompatible with execution family","choices."+k)
    if not isinstance(d["arrivals"],dict): error("schema","arrival route map required","arrivals")
    for k,p in d["arrivals"].items():
        if type(k) is not str or not k: error("schema","arrival route name required","arrivals")
        keys(p,"alpha beta_s","arrivals"); number(p["alpha"],"arrivals.alpha",positive=True); number(p["beta_s"],"arrivals.beta_s",positive=True)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")


def load_canonical(data):
    if type(data) is not bytes: error("schema","expected bytes")
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: error("schema","duplicate JSON key",k)
            d[k]=v
        return d
    try:
        value=json.loads(data.decode("utf-8"),object_pairs_hook=pairs,
            parse_constant=lambda x:error("schema","nonfinite JSON constant",x))
        if canonical(value)!=data: error("noncanonical","canonical bytes required")
        return value
    except ActionInputError: raise
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError) as exc:
        error("schema",str(exc))


@dataclass(frozen=True,slots=True,kw_only=True)
class ActionModel:
    declaration: bytes

    def __post_init__(self):
        try: _validate(load_canonical(self.declaration))
        except (ActionInputError,ActionIncompatible): raise
        except (TypeError,ValueError,KeyError,AttributeError,OverflowError) as exc: error("schema",str(exc))

    @property
    def states(self): return tuple(load_canonical(self.declaration)["states"])
    @property
    def outcomes(self): return tuple(load_canonical(self.declaration)["outcomes"])
    @property
    def actions(self): return tuple(load_canonical(self.declaration)["actions"])
    @property
    def choices(self): return tuple(sorted(load_canonical(self.declaration)["choices"]))
    @property
    def ref(self): return "sha256:"+hashlib.sha256(self.declaration).hexdigest()


def action_model_from_json(data: bytes) -> ActionModel:
    return ActionModel(declaration=data)


def action_model_json(model: ActionModel) -> bytes:
    if not isinstance(model,ActionModel): error("schema","expected ActionModel")
    return model.declaration


def action_model_ref(model: ActionModel) -> str:
    return "sha256:"+hashlib.sha256(action_model_json(model)).hexdigest()
