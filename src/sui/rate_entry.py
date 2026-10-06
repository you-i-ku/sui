"""Model.9 raw history, public decisions and version-fixed persistence."""

from dataclasses import replace as _replace, fields as _fields, is_dataclass as _is_dataclass
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from fractions import Fraction as _Fraction
from types import MappingProxyType as _MappingProxyType
import hashlib as _hashlib
import json as _json
import re as _re

from .rate import (RateBudget, RateContext, RateHistory, RateScope, RateInputError,
                   RateSpecificationMissing, RateIncomplete, RateModelFalsified, _freeze)
from .rate_model import RateModel, _load, _object, _id, _integer, _text
from .records import (Record, Observed, AttemptStarted, Preference, Category,
                      Prediction, Decided, JobOpened, Payload, Role)
from .ids import Ref, RefKind
from .s4_contracts import BOOT
from .s1_contracts import ATTEMPT
from .clock_contracts import SOURCE
from .s4b_contracts import (RATE_REPORT, RATE_ARRIVAL, RATE_BELIEF, RATE_DECISION,
                            RATE_JOB, RATE_REFINEMENT)


def read_rate(model, records, *, unread_preferences=()):
    """model.9 の原記録の読み (Reading)。旧の read より先に分岐する。"""
    from .agent import Reading
    if not isinstance(model, RateModel): raise RateInputError("schema", "RateModel required", "model")
    if not isinstance(records, _Iterable): raise RateInputError("schema", "records must be iterable")
    by_id = {}
    for record in records:
        if not isinstance(record, Record): raise RateInputError("schema", "Record required", "records")
        if record.id in by_id and record != by_id[record.id]:
            raise RateInputError("shape", "one Record ID has different bodies", "records")
        by_id[record.id] = record
    raw = tuple(sorted((r for r in by_id.values() if r.category in (Category.FACT, Category.INTENTION, Category.PREFERENCE)),
                       key=lambda r: (r.at.run_index, r.at.mono_ns, r.at.seq, str(r.id))))
    d = _json.loads(model.declaration)
    for record in raw:
        body = record.body
        if isinstance(body, Observed):
            if body.contract not in (BOOT, SOURCE, RATE_REPORT, RATE_ARRIVAL):
                if body.contract.name in {c.name for c in (BOOT, SOURCE, RATE_REPORT, RATE_ARRIVAL)}:
                    raise RateInputError("unknown_version", "unknown raw record version", "records.contract")
                raise RateSpecificationMissing("missing_kernel", "undeclared raw observation contract", "records.contract")
            if body.content.media_type != "application/json": raise RateInputError("schema", "raw record must contain JSON")
            content = _load(body.content.data)
            if body.contract == BOOT:
                _object(content, (), "boot.content")
                if body.caused_by is not None: raise RateInputError("shape", "BOOT has an attempt")
            elif body.contract == RATE_REPORT:
                _report_spec(d, record, content)
            elif body.contract == RATE_ARRIVAL:
                _arrival_spec(d, record, content)
        elif isinstance(body, AttemptStarted):
            if body.contract != ATTEMPT:
                raise RateSpecificationMissing("missing_kernel", "unknown attempt law")
            _object(_load(body.content.data), (), "attempt.content")
    jobs = read_jobs(model, raw)
    arrived = {r.body.caused_by for r in raw if isinstance(r.body, Observed)
               and r.body.contract == RATE_REPORT}
    pending = {r.id: jobs[r.body.job] for r in raw if isinstance(r.body, AttemptStarted)
               and r.body.job in jobs and r.id not in arrived}
    return Reading(n={}, unread={}, pending=pending, rate_records=raw,
                   preferences=tuple(r for r in raw if isinstance(r.body, Preference)),
                   unread_preferences=tuple(unread_preferences))


def rate_history(model, reading, *, context: RateContext) -> RateHistory:
    from .agent import Reading
    if not isinstance(model, RateModel) or not isinstance(reading, Reading) or not isinstance(context, RateContext):
        raise RateInputError("schema", "RateModel, Reading and RateContext required")
    if not isinstance(context.run, Ref) or context.run.kind != RefKind.RUN:
        raise RateInputError("shape", "context.run must be a run Ref")
    if type(context.now_ns) is not int or type(context.observed_ns) is not int or context.observed_ns > context.now_ns:
        raise RateInputError("schema", "invalid now/observed run readings")
    # Revalidate a public Reading; the factory never trusts a populated field.
    raw = read_rate(model, reading.rate_records, unread_preferences=reading.unread_preferences).rate_records
    if any(r.at.run != context.run for r in raw):
        raise RateIncomplete("history_scope", "multiple runs require a joint clock/instance law")
    boots = [r for r in raw if isinstance(r.body, Observed) and r.body.contract == BOOT]
    if not boots: raise RateIncomplete("history_scope", "a BOOT origin is required")
    boot_values = {r.at.mono_ns for r in boots}
    if len(boot_values) != 1: raise RateModelFalsified("clock_contradiction", "different BOOT origins in one run")
    boot_ns = boots[0].at.mono_ns
    if context.observed_ns < boot_ns or context.now_ns < boot_ns:
        raise RateInputError("shape", "context precedes BOOT")
    sources = [r for r in raw if isinstance(r.body, Observed) and r.body.contract == SOURCE]
    d = _json.loads(model.declaration)
    for record in sources:
        p = _load(record.body.content.data)
        _object(p, ("run", "provider", "implementation", "python_version", "resolution_s", "monotonic", "adjustable", "measurement"), "clock_source")
        from .rate_model import _rational, _spec
        for key in ("provider", "implementation", "python_version"): _text(p[key], "clock_source." + key)
        _rational(p["resolution_s"], "clock_source.resolution_s", positive=True)
        if type(p["monotonic"]) is not bool or type(p["adjustable"]) is not bool:
            raise RateInputError("schema", "clock source flags")
        if p["run"] != str(context.run): raise RateModelFalsified("clock_contradiction", "clock source belongs to another run")
        if p["measurement"] is not None:
            _spec(p["measurement"], {"exact", "tick"}, "clock_source.measurement")
            expected = {"name": d["records"][0]["clock"]["name"], "version": d["records"][0]["clock"]["version"]} if d["records"] else None
            if expected is not None and p["measurement"] != expected:
                raise RateModelFalsified("clock_contradiction", "source and model clock differ")
    if sources and any(r.body.content.data != sources[0].body.content.data for r in sources[1:]):
        raise RateModelFalsified("clock_contradiction", "different clock sources in one run")
    if context.clock_source is not None and (not isinstance(context.clock_source, Ref) or
            context.clock_source not in {r.id for r in sources}):
        raise RateInputError("shape", "clock_source is not an adopted SOURCE record")
    for record in raw:
        if record.at.mono_ns > context.now_ns:
            raise RateInputError("shape", "frozen history contains a later-created record")
        if isinstance(record.body, Observed) and record.body.contract != SOURCE:
            if record.body.received_ns is None:
                raise RateIncomplete("history_scope", "raw observation has no receipt reading")
            if record.body.received_ns > context.observed_ns:
                raise RateInputError("shape", "observation received after frozen boundary")
            if record.body.received_ns > record.at.mono_ns:
                raise RateModelFalsified("clock_contradiction", "record created before receipt")
    by_ref = {str(r.id): r for r in raw}
    if not isinstance(context.fact_ancestors, _Mapping):
        raise RateInputError("schema", "fact_ancestors must be a mapping")
    ancestors = {}
    for cid, refs in context.fact_ancestors.items():
        if not isinstance(cid, str) or _re.fullmatch(r"sha256:[0-9a-f]{64}", cid) is None:
            raise RateInputError("schema", "ancestry keys must be ledger CIDs")
        if not isinstance(refs, frozenset) or any(not isinstance(ref, str) or ref not in by_ref or
                by_ref[ref].category != Category.FACT or
                isinstance(by_ref[ref].body, Observed) and by_ref[ref].body.contract == SOURCE for ref in refs):
            raise RateInputError("shape", "ancestry contains unknown facts or clock metadata")
        ancestors[cid] = refs
    if not isinstance(context.check_events, tuple): raise RateInputError("schema", "check_events must be tuple")
    if not context.check_events: raise RateIncomplete("history_scope", "receipt boundary requires check provenance")
    for source in context.check_events:
        if not isinstance(source, _Mapping): raise RateInputError("schema", "check event must be object")
        if set(source) == {"fact"}:
            if not isinstance(source["fact"], str): raise RateInputError("schema", "check fact must be a Ref string")
            record = by_ref.get(source["fact"])
            if (record is None or not isinstance(record.body, Observed) or record.body.contract == SOURCE or
                    record.body.received_ns != context.observed_ns):
                raise RateInputError("shape", "check fact must be a receipt at observed_ns")
        elif set(source) == {"unrecorded"}:
            p = source["unrecorded"]
            if (not isinstance(p, _Mapping) or set(p) != {"kind", "reading", "after"} or
                    p["kind"] not in ("tick", "thought") or type(p["reading"]) is not int or
                    p["reading"] != context.observed_ns or not isinstance(p["after"], (list, tuple)) or
                    any(not isinstance(cid, str) or cid not in ancestors for cid in p["after"]) or list(p["after"]) != sorted(set(p["after"]))):
                raise RateInputError("schema", "invalid unrecorded check provenance")
        else: raise RateInputError("schema", "unknown check source shape")
    frozen_context = _replace(context, check_events=_freeze(context.check_events), fact_ancestors=_MappingProxyType(ancestors))
    facts = tuple(r.id for r in raw if r.category == Category.FACT and
                  not (isinstance(r.body, Observed) and r.body.contract == SOURCE))
    material = {"model": model.ref, "run": str(context.run), "now_ns": context.now_ns,
                "observed_ns": context.observed_ns, "clock_source": None if context.clock_source is None else str(context.clock_source),
                "check_events": [_plain(e) for e in context.check_events],
                "ancestors": {cid: sorted(refs) for cid, refs in ancestors.items()},
                "records": [_record_material(r) for r in raw]}
    key = "sha256:" + _hashlib.sha256(_json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    result = object.__new__(RateHistory)
    for name, value in (("model_ref", model.ref), ("context", frozen_context), ("fact_ids", facts),
                        ("evidence_key", key), ("_records", raw), ("_boot_ns", boot_ns)):
        object.__setattr__(result, name, value)
    return result


def _plain(value):
    if hasattr(value, "items"): return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_plain(v) for v in value]
    return value


def _record_material(record):
    def encode(value):
        if isinstance(value, Ref): return str(value)
        if isinstance(value, bytes): return value.hex()
        if _is_dataclass(value):
            return {field.name: encode(getattr(value, field.name)) for field in _fields(value)}
        if isinstance(value, (list, tuple)): return [encode(v) for v in value]
        return value
    return {"body_type": type(record.body).__name__, **encode(record)}


def _report_spec(d, record, content):
    _object(content, ("channel", "experiment", "window_start_ns", "window_end_ns", "arrival_count", "outcome", "completion_ns"), "rate_report")
    _id(content["channel"], "rate_report.channel")
    _id(content["experiment"], "rate_report.experiment")
    _integer(content["completion_ns"], "rate_report.completion_ns")
    spec = next((r for r in d["records"] if r["id"] == content["channel"]), None)
    if spec is None or spec["experiment"] != content["experiment"] or spec["kernel"]["name"] == "exact-arrival":
        raise RateInputError("shape", "channel/experiment does not identify a report kernel")
    cell = {"arrival_count": content["arrival_count"], "outcome": content["outcome"]}
    count = content["arrival_count"]
    if count is not None:
        _object(count, ("kind", "value"), "rate_report.arrival_count")
        if count["kind"] not in ("exact", "at_least"): raise RateInputError("schema", "unknown count kind")
        _integer(count["value"], "rate_report.arrival_count.value", int(count["kind"] == "at_least"))
    if content["outcome"] is not None: _text(content["outcome"], "rate_report.outcome")
    if cell not in spec["alphabet"]["values"]: raise RateInputError("shape", "report is not a declared alphabet cell")
    if spec["kernel"]["name"] == "saturating-count":
        for key in ("window_start_ns", "window_end_ns"): _integer(content[key], "rate_report." + key)
        if content["window_start_ns"] >= content["window_end_ns"]:
            raise RateInputError("unit", "report window must have positive duration")
        arrival = next(p for p in d["processes"] if p["id"] == spec["kernel"]["params"]["arrival_process"])
        if record.body.route != arrival["params"]["route"]: raise RateInputError("shape", "report route")
    elif content["window_start_ns"] is not None or content["window_end_ns"] is not None:
        raise RateInputError("shape", "constant report has a count window")
    elif record.body.route not in {p["params"]["route"] for p in d["processes"] if p["family"]["name"] == "marked-arrival"}:
        raise RateSpecificationMissing("missing_kernel", "constant completion's experiment route is not declared")
    generator = next(p for p in d["processes"] if p["id"] == spec["generator"])
    if generator["family"]["name"] == "marked-arrival" and record.body.caused_by is not None:
        raise RateInputError("shape", "exogenous report has an attempt")
    if generator["family"]["name"] == "fixed-completion" and record.body.caused_by is None:
        raise RateInputError("shape", "completion report requires an attempt")
    return spec


def _arrival_spec(d, record, content):
    _object(content, ("process", "mark", "event_ns"), "rate_arrival")
    _id(content["process"], "rate_arrival.process")
    _integer(content["event_ns"], "rate_arrival.event_ns")
    process = next((p for p in d["processes"] if p["id"] == content["process"] and p["family"]["name"] == "marked-arrival"), None)
    specs = [r for r in d["records"] if r["kernel"]["name"] == "exact-arrival" and r["kernel"]["params"]["arrival_process"] == content["process"]]
    if process is None or not specs: raise RateInputError("shape", "arrival process lacks an exact record kernel")
    if record.body.route != process["params"]["route"]: raise RateInputError("shape", "arrival route")
    if content["mark"] is not None:
        _text(content["mark"], "rate_arrival.mark")
        marks = process["params"]["marks"]
        if marks is None or content["mark"] not in marks["labels"] or not any(r["kernel"]["params"]["include_mark"] for r in specs):
            raise RateInputError("shape", "arrival mark outside declared alphabet")
    return process


def _fixed_events(d, history):
    """Resolve declared windows and physical events without inventing silence."""
    unit_ns = _Fraction(*d["units"]["time"]["seconds"]) * 10**9
    def time(ns): return _Fraction(ns - history._boot_ns) / unit_ns
    horizon = time(history.context.observed_ns)
    processes = {p["id"]: p for p in d["processes"]}
    specs = {r["id"]: r for r in d["records"]}
    attempts = {r.id: r for r in history._records if isinstance(r.body, AttemptStarted)}
    seen, raw_reports, raw_arrivals = {}, [], []
    for record in history._records:
        body = record.body
        if not isinstance(body, Observed) or body.contract not in (RATE_REPORT, RATE_ARRIVAL): continue
        p = _load(body.content.data)
        event_ns = p["completion_ns"] if body.contract == RATE_REPORT else p["event_ns"]
        # The declared record kernel already supplies its physical label.
        # source_time_ns is an optional copy, not a second observation or a
        # substitute for an absent label in the raw content.
        if body.source_time_ns is not None and body.source_time_ns != event_ns:
            raise RateModelFalsified("clock_contradiction", "source and event readings disagree")
        if event_ns > body.received_ns or event_ns < history._boot_ns:
            raise RateModelFalsified("clock_contradiction", "physical event outside BOOT/receipt order")
        if body.source_id is not None:
            tag = (body.route, body.source_id)
            physical = (body.contract, body.content.data, body.caused_by, event_ns)
            if tag in seen:
                if seen[tag] != physical: raise RateModelFalsified("event_contradiction", "conflicting physical redelivery")
                continue
            seen[tag] = physical
        if body.contract == RATE_REPORT:
            spec = specs[p["channel"]]
            generator = processes[spec["generator"]]
            if generator["family"]["name"] == "fixed-completion":
                attempt = attempts.get(body.caused_by)
                if attempt is None: raise RateInputError("shape", "report attempt absent from frozen records")
                start = time(attempt.at.mono_ns)
                if time(event_ns) != start + _Fraction(*generator["params"]["duration"]):
                    raise RateModelFalsified("event_contradiction", "completion does not match fixed duration")
            else: start = None
            raw_reports.append((time(event_ns), spec, p, start))
        else: raw_arrivals.append((time(event_ns), p["process"], p["mark"], body.caused_by))
    # A fixed window/attempt emits one report, even if notified repeatedly.
    report_keys = set()
    windows, reports = [], []
    for event_time, spec, p, start in raw_reports:
        key = spec["id"]
        if key in report_keys:
            raise RateModelFalsified("event_contradiction", "multiple physical reports for one declared experiment")
        report_keys.add(key)
        reports.append((event_time, {"probe": spec["probe"], "outcome": p["outcome"]}))
        if spec["kernel"]["name"] == "constant-report": continue
        declared = next(w for w in d["coverage"]["intervals"] if w["record"] == spec["id"])
        left, right = _Fraction(*declared["start"]), _Fraction(*declared["end"])
        if (time(p["window_start_ns"]), time(p["window_end_ns"]), event_time) != (left, right, right):
            raise RateModelFalsified("event_contradiction", "report window differs from declared experiment")
        if start is not None and start != left: raise RateModelFalsified("event_contradiction", "attempt does not start the declared choice window")
        params = spec["kernel"]["params"]
        windows.append({"record": spec["id"], "process": params["arrival_process"], "start": left,
                        "end": right, "kind": "count", "cap": params["cap"], "count": p["arrival_count"]["value"]})
    # Exogenous exact coverage is known independently of arrivals. Choice
    # coverage needs an actual choice/attempt, which this minimal encoding
    # cannot infer from a bare timestamp or route.
    for window in d["coverage"]["intervals"]:
        spec = specs[window["record"]]
        if spec["kernel"]["name"] != "exact-arrival": continue
        if window["source"]["kind"] != "exogenous":
            raise RateIncomplete("history_scope", "exact choice coverage needs a command/attempt binding")
        left, right = _Fraction(*window["start"]), _Fraction(*window["end"])
        if left < horizon:
            windows.append({"record": spec["id"], "process": spec["kernel"]["params"]["arrival_process"],
                            "start": left, "end": min(right, horizon), "kind": "exact"})
    arrivals = []
    for t, pid, mark, caused_by in raw_arrivals:
        if caused_by is not None: raise RateIncomplete("history_scope", "exact arrivals with attempt binding are outside this evaluator")
        if not any(w["kind"] == "exact" and w["process"] == pid and w["start"] < t <= w["end"] for w in windows):
            raise RateModelFalsified("event_contradiction", "arrival is outside declared active coverage")
        arrivals.append((t, pid, mark))
    arrivals.sort(key=lambda e: (e[0], list(processes).index(e[1])))
    if any(a[0] == b[0] for a, b in zip(arrivals, arrivals[1:])):
        raise RateIncomplete("history_scope", "exact tied arrivals require a joint subspace measure")
    return windows, arrivals, reports, horizon


def certify_rate_scope(view, candidates, resolved, *, budget: RateBudget) -> RateScope:
    from .rate import RateOutsideEvaluationType, RateRuntimeUnverified
    from .contracts import ContractRef
    try:
        cfg, choices, context, gamma = _rate_evaluation_inputs(view, candidates, resolved, budget)
        # The declaration alone cannot certify the frozen raw history.
        history = rate_history(view.model, view.reading, context=context)
        windows, arrivals, reports, horizon = _fixed_events(cfg, history)
        if (arrivals or len(windows) != 1 or windows[0]["record"] != cfg["_root"]["id"] or
                len(reports) != 1 or horizon != cfg["_duration"]):
            raise RateIncomplete("history_scope", "C1 evaluation starts at its root count report")
    except RateIncomplete as exc:
        return RateScope("incomplete", None, exc.reason, (exc.detail,))
    except RateSpecificationMissing as exc:
        return RateScope("missing_spec", None, exc.reason, (exc.detail,))
    except RateOutsideEvaluationType as exc:
        return RateScope("outside_evaluation", None, exc.reason, (exc.detail,))
    except RateRuntimeUnverified as exc:
        return RateScope("runtime_unverified", None, exc.reason, (exc.detail,))
    return RateScope("certified", ContractRef("sui.s4b.rate_c1", "1"), None,
                     ("shared-law", "joint-law-state-target", "finite-record-mass",
                      "one-completion", "blank-cost", "rational-series"))


def _rate_evaluation_inputs(view, candidates, resolved, budget):
    from .agent import View, Reading
    from .preference import Resolved, current
    from .rate import _rate_budget, _c1_config
    from math import isfinite
    _rate_budget(budget)
    if not isinstance(view, View) or not isinstance(resolved, Resolved):
        raise RateInputError("schema", "View and Resolved required")
    if not isinstance(view.model, RateModel) or not isinstance(view.reading, Reading):
        raise RateInputError("schema", "rate View requires RateModel and Reading")
    if not isinstance(candidates, tuple) or not candidates or any(not isinstance(c, str) for c in candidates):
        raise RateInputError("unknown_candidate", "nonempty candidate tuple required", "candidates")
    if any(c not in view.model.choices for c in candidates):
        raise RateInputError("unknown_candidate", "candidate is not declared", "candidates")
    choices = tuple(c for c in view.model.choices if c in candidates)
    cfg = _c1_config(view.model)
    if any(isinstance(r.body, AttemptStarted) for r in view.reading.rate_records):
        raise RateIncomplete("history_scope", "C1 root evaluation does not certify existing attempts or concurrent completions")
    duration_ns = cfg["_duration"] * cfg["_unit_seconds"] * 10**9
    if resolved.H_ns is not None:
        if type(resolved.H_ns) is not int or resolved.H_ns < 0:
            raise RateInputError("shape", "invalid horizon", "H_ns")
        if not duration_ns <= resolved.H_ns < 2 * duration_ns:
            raise RateIncomplete("depth_scope", "C1 lookahead must contain exactly one completion")
    if (isinstance(resolved.gamma, bool) or not isinstance(resolved.gamma, (int, float, _Fraction)) or
            resolved.gamma < 0 or isinstance(resolved.gamma, float) and not isfinite(resolved.gamma)):
        raise RateInputError("shape", "finite nonnegative gamma required", "gamma")
    preferences = current(view.preferences)
    try:
        raw_preferences = tuple(r.body.content.as_json() for r in view.reading.preferences)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RateIncomplete("cost_certificate", "unreadable preferences have no certified cost adapter") from exc
    if (resolved.items or preferences.items or preferences.unread or preferences.ambiguous or
            view.reading.unread_preferences or
            any(not isinstance(p, dict) or p.get("kind") != "style" for p in raw_preferences)):
        raise RateIncomplete("cost_certificate", "nonblank preferences need a certified cost adapter")
    boots = [r for r in view.reading.rate_records if isinstance(r.body, Observed) and r.body.contract == BOOT]
    if not boots:
        raise RateIncomplete("history_scope", "C1 requires its BOOT origin")
    sources = [r for r in view.reading.rate_records if isinstance(r.body, Observed) and r.body.contract == SOURCE]
    for source in sources:
        provenance = _load(source.body.content.data)
        if provenance.get("implementation") != "FakeClock":
            from .rate import RateRuntimeUnverified
            raise RateRuntimeUnverified("clock_fit", "model.9 source clock has no certified runtime fit")
    if view.now_ns is None or view.observed_ns is None:
        raise RateIncomplete("history_scope", "frozen now/observed readings required")
    context = RateContext(boots[0].at.run, view.now_ns, view.observed_ns, view.check_events,
                          view.fact_ancestors, sources[0].id if sources else None)
    return cfg, choices, context, _Fraction(resolved.gamma)


def resolve_budget(model, budget):
    from .rate import default_rate_budget, _rate_budget
    if not isinstance(model, RateModel):
        if budget is not None:
            raise RateInputError("invalid_budget", "rate_budget requires model.9", "rate_budget")
        return None
    budget = default_rate_budget() if budget is None else budget
    _rate_budget(budget)
    return budget


def candidate_names(model, candidates):
    if isinstance(candidates, str) or not isinstance(candidates, _Iterable):
        raise RateInputError("unknown_candidate", "candidate iterable required", "candidates")
    candidates = tuple(candidates)
    if not candidates or any(not isinstance(c, str) or c not in model.choices for c in candidates):
        raise RateInputError("unknown_candidate", "unknown or empty candidates", "candidates")
    return tuple(c for c in model.choices if c in candidates)


def _encode(value):
    """Exact rational JSON; no display number enters selection or persistence."""
    from .rate import Certificate, RationalInterval
    if isinstance(value, _Fraction): return [value.numerator, value.denominator]
    if isinstance(value, Ref): return str(value)
    if isinstance(value, frozenset): return [_encode(v) for v in sorted(value)]
    if isinstance(value, Certificate):
        return {"scheme": "sui.s4b.rate_certificate.1",
                **{f.name: _encode(getattr(value, f.name)) for f in _fields(value)}}
    if isinstance(value, RationalInterval):
        return {"lower": _encode(value.lower), "upper": _encode(value.upper)}
    if _is_dataclass(value):
        return {f.name: _encode(getattr(value, f.name)) for f in _fields(value)}
    if isinstance(value, _Mapping): return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_encode(v) for v in value]
    return value


def _interval_pair(value):
    return [_encode(value.lower), _encode(value.upper)]


def _command(model, choice, context, boot_ns):
    d = _json.loads(model.declaration)
    item = next(c for c in d["controls"]["choices"] if c["id"] == choice)
    time = _Fraction(context.observed_ns - boot_ns) / (_Fraction(*d["units"]["time"]["seconds"]) * 10**9)
    return {"choice": choice, "action": item["action"], "reservation_rule": item["reservation"],
            "execution": {"family": {"name": "immediate-start", "version": "1"},
                          "completion_process": item["completion_process"],
                          "start": {"time": _encode(time), "causal_stage": 0, "causal_position": 0}},
            "effect": "identity"}


def _values(candidates, certificate):
    """Use the final certified enclosures, including selector refinements."""
    from .rate import RationalInterval, CertifiedQuantity
    encl = certificate.enclosures
    result = []
    for index, c in enumerate(candidates):
        quantities = {}
        for name in ("expected_cost", "information", "G", "J", "q_star"):
            bounds = ({"lower": [0, 1], "upper": [0, 1]} if name == "expected_cost" else
                      encl["J" if name == "G" else name][index])
            interval = RationalInterval(_Fraction(*bounds["lower"]), _Fraction(*bounds["upper"]))
            support = ("zero" if interval.lower == interval.upper == 0 else
                       "signed" if name in ("G", "J") else
                       "positive" if interval.lower > 0 else "unproved")
            quantities[name] = _encode(CertifiedQuantity("finite", interval, support, None, None, certificate))
        result.append({"candidate": c, **quantities})
    return result


def _root(view, resolved, history):
    return {"model": view.model.ref, "belief": str(view.belief), "parents": sorted(view.frontier),
            "facts": list(map(str, history.fact_ids)), "context": _encode(history.context),
            "items": [{"id": str(item.id), "rule": _encode(item.rule)} for item in resolved.items],
            "style": None if resolved.style is None else str(resolved.style),
            "evaluation": "one_step" if resolved.H_ns is None else "lookahead",
            "H_ns": resolved.H_ns, "gamma": _encode(_Fraction(resolved.gamma))}


def public_evaluate(view, candidates, resolved, *, u, budget: RateBudget):
    """Create a B3 Draft without changing the ledger or agent (§3-10-7)."""
    return _public_evaluate(view, candidates, resolved, u=u, budget=budget)


def _execution_budget(saved, available):
    if available is None: return saved
    return _replace(saved, **{key: min(getattr(saved, key), getattr(available, key))
                             for key in ("max_cells", "max_terms", "max_refinements")})


def _public_evaluate(view, candidates, resolved, *, u, budget, available=None):
    from .agent import Draft
    from .rate import _evaluate_rate, _certify_computed_choice, _choice_u
    u = _choice_u(u)
    candidates = candidate_names(view.model, candidates)
    execution_budget = _execution_budget(budget, available)
    evaluation, engine = _evaluate_rate(view, candidates, resolved, execution_budget, require_width=False)
    choice = _certify_computed_choice(evaluation, engine, u=u)
    choice = _replace(choice, certificate=_replace(choice.certificate, budget=budget))
    _, _, context, _ = _rate_evaluation_inputs(view, candidates, resolved, budget)
    history = rate_history(view.model, view.reading, context=context)
    commands = [_command(view.model, c, history.context, history._boot_ns) for c in evaluation.candidates]
    content = {"root": _root(view, resolved, history),
        "candidates": [{"id": c, "command": command} for c, command in zip(evaluation.candidates, commands)],
        "u": _encode(choice.u), "values": _values(evaluation.candidates, choice.certificate), "display": None,
        "selection": {"index": choice.index, "chosen": choice.choice,
                      "previous": _interval_pair(choice.previous), "current": _interval_pair(choice.current)},
        "intent": commands[choice.index], "certificate": _encode(choice.certificate)}
    inputs = tuple(item.id for item in resolved.items) + (() if resolved.style is None else (resolved.style,))
    return Draft(parents=view.frontier, belief=view.belief, contract=RATE_DECISION,
                 preference_inputs=inputs, content=Payload.json(content))


def read_jobs(model, records):
    jobs = {}
    for record in records:
        if isinstance(record.body, JobOpened) and record.body.contract == RATE_JOB:
            data = _load(record.body.content.data)
            _object(data, ("choice", "action", "reservation_rule", "execution", "effect"), "rate_job")
            choices = _json.loads(model.declaration)["controls"]["choices"]
            item = next((c for c in choices if c["id"] == data.get("choice")), None)
            if item is None or data.get("action") != item["action"]:
                raise RateInputError("shape", "rate job has an undeclared choice/action")
            execution = data["execution"]
            _object(execution, ("family", "completion_process", "start"), "rate_job.execution")
            _object(execution["start"], ("time", "causal_stage", "causal_position"), "rate_job.execution.start")
            if (data["reservation_rule"] != item["reservation"] or data["effect"] != "identity" or
                    execution["family"] != {"name": "immediate-start", "version": "1"} or
                    execution["completion_process"] != item["completion_process"]):
                raise RateInputError("shape", "rate job differs from the model control")
            _fraction(execution["start"]["time"], "intent")
            for key in ("causal_stage", "causal_position"):
                _integer(execution["start"][key], "rate_job.execution.start." + key)
            jobs[record.id] = item["action"]
    return jobs


def fact_ancestors(ledger, frontier, reading):
    refs = {r.id for r in reading.rate_records if r.category == Category.FACT
            and not (isinstance(r.body, Observed) and r.body.contract == SOURCE)}
    result = {}
    for entry in ledger.between((), frontier):
        result[entry.cid] = frozenset(str(e.id) for e in ledger.between((), (entry.cid,)) if e.id in refs)
    return _MappingProxyType(result)


def _reading_context(reading, ancestry):
    boots = [r for r in reading.rate_records if isinstance(r.body, Observed) and r.body.contract == BOOT]
    if not boots: return None
    run = boots[0].at.run
    receipts = [r for r in reading.rate_records if isinstance(r.body, Observed)
                and r.body.contract != SOURCE and r.body.received_ns is not None and r.at.run == run]
    if not receipts: return None
    observed = max(r.body.received_ns for r in receipts)
    now = max(r.at.mono_ns for r in reading.rate_records if r.at.run == run)
    sources = [r for r in reading.rate_records if isinstance(r.body, Observed) and r.body.contract == SOURCE]
    return RateContext(run, now, observed,
        tuple({"fact": str(r.id)} for r in receipts if r.body.received_ns == observed),
        ancestry, sources[0].id if sources else None)


def derive(model, reading, *, budget, ancestry=None):
    from .rate import (rebuild_rate_belief, state_marginal, RateOutsideEvaluationType,
                       RateRuntimeUnverified)
    from .action_types import FixedLabel
    ancestry = {} if ancestry is None else ancestry
    context = _reading_context(reading, ancestry)
    content = {"model": model.ref, "states": list(model.states), "status": "prior", "reason": None,
               "context": _encode(context), "derivation_budget": _encode(budget),
               "evidence": None, "state_marginal": None,
               "parameter_moments": None, "structure_weights": None,
               "unread": [{"id": str(ref), "reason": reason} for ref, reason in reading.unread.items()]}
    if context is None:
        if reading.rate_records: content.update(status="no_axis", reason="history_scope")
        return None, {}, content
    try:
        _check_attempt_bindings(model, reading, context)
        belief = rebuild_rate_belief(model, reading, context=context, budget=budget)
        content["context"] = _encode(belief.history.context)
        content["evidence"] = _encode(belief.evidence)
        time = _Fraction(context.observed_ns - belief.history._boot_ns, 10**9)
        target = FixedLabel(time_s=time, causal_stage=0, causal_position=0, side="post")
        marginal = state_marginal(belief, targets=(target,), budget=budget)
        content["state_marginal"] = {"targets": [_encode(target)],
            "values": [{"states": list(states), "quantity": _encode(q)} for states, q in marginal]}
        content["status"] = "complete"
    except RateModelFalsified as exc:
        content.update(status="unexplained", reason=exc.reason)
    except (RateIncomplete, RateSpecificationMissing, RateOutsideEvaluationType, RateRuntimeUnverified) as exc:
        content.update(status="incomplete", reason=exc.reason)
    return None, {}, content


def _check_attempt_bindings(model, reading, context):
    from .rate import RateRuntimeUnverified
    jobs = {r.id: r for r in reading.rate_records if isinstance(r.body, JobOpened) and r.body.contract == RATE_JOB}
    decisions = {r.id: r for r in reading.rate_records if isinstance(r.body, Decided) and r.body.contract == RATE_DECISION}
    attempts = {r.id: r for r in reading.rate_records if isinstance(r.body, AttemptStarted)}
    d = _json.loads(model.declaration)
    boot_ns = min(r.at.mono_ns for r in reading.rate_records if isinstance(r.body, Observed) and r.body.contract == BOOT)
    for attempt in attempts.values():
        job = jobs.get(attempt.body.job)
        if job is None or job.body.decision not in decisions:
            raise RateIncomplete("history_scope", "actual attempt requires its saved rate job and decision")
        command = job.body.content.as_json()
        if command != decisions[job.body.decision].body.content.as_json().get("intent"):
            raise RateRuntimeUnverified("record_fit", "attempt job is not its decision's command")
        start = command["execution"]["start"]
        planned_ns = boot_ns + _fraction(start["time"], "intent") * _Fraction(*d["units"]["time"]["seconds"]) * 10**9
        if (attempt.at.run != context.run or attempt.at.mono_ns != planned_ns or
                start["causal_stage"] != 0 or start["causal_position"] != 0):
            raise RateRuntimeUnverified("dispatch_fit", "actual attempt did not meet the declared immediate start")
    choices = {c["id"]: c for c in d["controls"]["choices"]}
    for record in reading.rate_records:
        if isinstance(record.body, Observed) and record.body.contract == RATE_REPORT and record.body.caused_by in attempts:
            attempt = attempts[record.body.caused_by]
            command = jobs[attempt.body.job].body.content.as_json()
            if record.body.content.as_json()["channel"] not in choices[command["choice"]]["observation_records"]:
                raise RateRuntimeUnverified("record_fit", "completion report does not belong to the chosen command")


def rate_view(agent, now_ns, observed_ns, check_events):
    from .agent import View
    context = _reading_context(agent._reading, agent._fact_ancestors)
    # A view can be inspected without supplying a new time. Evaluation still
    # checks its actual provenance; these defaults use existing receipts only.
    if context is not None:
        now_ns = context.now_ns if now_ns is None else now_ns
        observed_ns = context.observed_ns if observed_ns is None else observed_ns
        if not check_events and observed_ns == context.observed_ns: check_events = context.check_events
    return View(model=agent._model, frontier=agent.frontier, belief=agent._belief.id,
                reading=agent._reading, preferences=agent._preferences, now_ns=now_ns,
                observed_ns=observed_ns, check_events=tuple(check_events), fact_ancestors=agent._fact_ancestors)


def adopt(agent, ledger, *, clock, ids, through):
    _check_simulation_clock(clock)
    from .agent import _preference_view
    from .ledger import DerivedParent
    target = ledger.heads() if through is None else ledger.maximal(through)
    if any(not ledger.entry(cid).is_event for cid in target): raise DerivedParent("rate adopt requires events")
    new, old = ledger.ancestors(target), ledger.ancestors(agent.frontier)
    if not old <= new: raise RateInputError("shape", "adopt cannot move behind its frontier")
    if old == new:
        agent._rate_refinements = _read_refinements(agent._model, ledger, target, agent.rate_budget)
        return None
    snapshot = ledger.snapshot(target)
    reading = read_rate(agent._model, snapshot.records, unread_preferences=snapshot.unread_preferences)
    ancestry = fact_ancestors(ledger, target, reading)
    q, a, content = derive(agent._model, reading, budget=agent.rate_budget, ancestry=ancestry)
    refinements = _read_refinements(agent._model, ledger, target, agent.rate_budget)
    record = agent._belief_record(reading, q, a, agent.revision + 1, clock=clock, ids=ids, lattice=content)
    ledger.append(record, target)
    agent._frontier, agent._reading, agent._q, agent._a = target, reading, q, a
    agent._revision, agent._belief = agent.revision + 1, record
    agent._preferences = _preference_view(ledger, target)
    agent._fact_ancestors, agent._lattice = ancestry, content
    agent._rate_refinements = refinements
    return record


def _mismatch(field, detail):
    from .rate import RateReplayMismatch
    raise RateReplayMismatch(field, detail, field, fields=(field,))


def _fraction(value, field):
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(v) is not int for v in value) or value[1] <= 0):
        _mismatch(field, "canonical rational pair required")
    result = _Fraction(*value)
    if _encode(result) != list(value): _mismatch(field, "noncanonical rational pair")
    return result


def _get(ledger, cid):
    from .rate import RateReplayUnavailable
    from .ledger import UnknownEntry, CorruptEntry
    from .records import SchemaMismatch
    try: return ledger.entry(cid), ledger.record(cid)
    except (UnknownEntry, KeyError) as exc:
        raise RateReplayUnavailable("missing_reference", "saved entry or content is unavailable", str(cid)) from exc
    except SchemaMismatch as exc:
        raise RateReplayUnavailable("unknown_version", "saved record schema is unavailable", str(cid)) from exc
    except CorruptEntry as exc:
        _mismatch("evidence", "saved record integrity differs: " + str(exc))


def _saved_budget(certificate, available):
    from .rate import _rate_budget, RateReplayUnavailable
    _rate_budget(available)
    if not isinstance(certificate, dict): _mismatch("interval", "certificate object required")
    if (certificate.get("scheme") != "sui.s4b.rate_certificate.1" or
            certificate.get("method") != {"name": "sui.s4b.rate_c1", "version": "1"} or
            certificate.get("arithmetic") != {"name": "rational-series", "version": "1"}):
        raise RateReplayUnavailable("unknown_version", "saved method/arithmetic version is unavailable")
    try:
        data = certificate["budget"]
        _object(data, ("tolerance", "max_cells", "max_terms", "max_refinements"), "certificate.budget")
        budget = RateBudget(_fraction(data["tolerance"], "interval"),
                            data["max_cells"], data["max_terms"], data["max_refinements"])
        trace = certificate["trace"]
        if not isinstance(trace, list): _mismatch("interval", "trace array required")
        terms = sum(step["terms"] or 0 for step in trace if step["operation"] == "series")
        cells = len(certificate["enclosures"]["rate_cells"])
        refinements = (int(bool(cells)) + sum(step["operation"] == "split" or
                       step["dimension"] == "refine-elementary-series" for step in trace) +
                       max(0, sum(step["operation"] == "tail" and step["dimension"] == "conditional-entropy"
                                  for step in trace) - 1))
    except (KeyError, TypeError, AttributeError, RateInputError) as exc:
        _mismatch("interval", "malformed saved budget/trace: " + str(exc))
    if terms > available.max_terms or cells > available.max_cells or refinements > available.max_refinements:
        raise RateIncomplete("budget", "replay resource limits cannot execute the saved trace")
    return budget


def _frozen_view(model, ledger, parents, belief):
    from .agent import View, _preference_view
    from .rate import RateReplayUnavailable
    from .ledger import CorruptEntry
    from .records import SchemaMismatch
    try:
        snapshot = ledger.snapshot(parents)
        entries = ledger.entries_of(belief)
    except KeyError as exc:
        raise RateReplayUnavailable("missing_reference", "saved root is unavailable") from exc
    except SchemaMismatch as exc:
        raise RateReplayUnavailable("unknown_version", "saved root record schema is unavailable") from exc
    except CorruptEntry as exc:
        _mismatch("evidence", "saved root integrity differs: " + str(exc))
    if not entries: raise RateReplayUnavailable("missing_reference", "belief reference is unavailable")
    matching = [e for e in entries if e.parents == parents and e.body_type is Prediction]
    if not matching: _mismatch("inputs", "belief is not a leaf of the saved parents")
    _, record = _get(ledger, min(matching, key=lambda e: e.cid).cid)
    if record.body.contract.name == RATE_BELIEF.name and record.body.contract != RATE_BELIEF:
        raise RateReplayUnavailable("unknown_version", "saved rate belief contract version is unavailable")
    if record.body.target != "belief" or record.body.contract != RATE_BELIEF:
        _mismatch("inputs", "rate belief required")
    if record.body.content.as_json().get("model") != model.ref:
        _mismatch("root", "belief model differs")
    try:
        reading = read_rate(model, snapshot.records, unread_preferences=snapshot.unread_preferences)
    except RateInputError as exc:
        if exc.reason == "unknown_version":
            raise RateReplayUnavailable("unknown_version", "saved raw record version is unavailable") from exc
        _mismatch("evidence", "saved raw records are malformed: " + str(exc))
    return View(model=model, frontier=parents, belief=belief, reading=reading,
                preferences=_preference_view(ledger, parents), fact_ancestors=fact_ancestors(ledger, parents, reading))


def _decision_view(model, ledger, parents, body):
    from .preference import current, resolve
    from .rate_model import rate_model_ref
    if not isinstance(model, RateModel): raise RateInputError("schema", "RateModel required")
    if rate_model_ref(model) != model.ref: _mismatch("root", "model bytes digest differs")
    if body.contract != RATE_DECISION:
        from .rate import RateReplayUnavailable
        if body.contract.name == RATE_DECISION.name:
            raise RateReplayUnavailable("unknown_version", "rate decision contract version is unavailable")
        _mismatch("root", "rate decision required")
    try:
        data = _load(body.content.data)
    except RateInputError as exc:
        _mismatch("root", "malformed saved decision content: " + str(exc))
    if not isinstance(data, dict): _mismatch("root", "decision content object required")
    if not body.inputs: _mismatch("inputs", "belief input required")
    view = _frozen_view(model, ledger, parents, body.inputs[0])
    try:
        root = data["root"]
        if root["model"] != model.ref or root["parents"] != sorted(parents):
            _mismatch("root", "saved model/parents differ")
        context = root["context"]
        view = _replace(view, now_ns=context["now_ns"], observed_ns=context["observed_ns"],
                        check_events=tuple(context["check_events"]))
        resolved = resolve(current(view.preferences), view)
        candidates = tuple(c["id"] for c in data["candidates"])
        if candidates != candidate_names(model, candidates): _mismatch("root", "candidate order differs")
        u = _fraction(data["u"], "selection")
        if not 0 <= u < 1: _mismatch("selection", "saved u outside [0,1)")
        if data.get("certificate", {}).get("enclosures", {}).get("selection", {}).get("u") != data["u"]:
            _mismatch("selection", "saved u differs from its selection proof")
    except (KeyError, TypeError, AttributeError) as exc:
        _mismatch("root", "malformed saved root: " + str(exc))
    except RateInputError as exc:
        _mismatch("root", "invalid saved root inputs: " + str(exc))
    return view, resolved, candidates, u, data


def _verify_body(model, ledger, parents, body, available):
    view, resolved, candidates, u, data = _decision_view(model, ledger, parents, body)
    budget = _saved_budget(data.get("certificate"), available)
    try:
        rebuilt = _public_evaluate(view, candidates, resolved, u=u, budget=budget, available=available)
    except RateInputError as exc:
        _mismatch("root", "invalid saved evaluation inputs: " + str(exc))
    expected = rebuilt.content.as_json()
    if data["root"].get("facts") != expected["root"]["facts"]:
        _mismatch("evidence", "saved raw facts differ from parent reconstruction")
    for key, field in (("root", "root"), ("candidates", "intent"), ("values", "interval"),
                       ("certificate", "interval"), ("selection", "selection"), ("intent", "intent")):
        if data.get(key) != expected[key]: _mismatch(field, "version-fixed reexecution differs in " + key)
    if (rebuilt.belief, *rebuilt.preference_inputs) != body.inputs:
        _mismatch("inputs", "Decided.inputs differ from adopted belief/preferences")
    if set(data) != set(expected): _mismatch("root", "decision has unexpected or missing keys")
    # Display is deliberately outside the mathematical proof. Its initial
    # null encoding is checked separately from proof/trace/selection equality.
    if body.content != rebuilt.content: _mismatch("interval", "canonical bytes were not regenerated")
    return rebuilt


def prepare(agent, draft, clock, ids):
    _check_simulation_clock(clock)
    from .agent import Commit, Draft
    if not isinstance(draft, Draft) or draft.contract != RATE_DECISION:
        raise RateInputError("shape", "model.9 Draft required")
    data = _load(draft.content.data)
    _object(data, ("root", "candidates", "u", "values", "display", "selection", "intent", "certificate"), "decision")
    root = data["root"]
    _object(root, ("model", "belief", "parents", "facts", "context", "items", "style", "evaluation", "H_ns", "gamma"), "decision.root")
    if (root.get("belief") != str(draft.belief) or root.get("parents") != sorted(draft.parents) or
            root.get("model") != agent.model_ref):
        _mismatch("root", "Draft root differs from its handles")
    expected_inputs = [i["id"] for i in root["items"]] + ([] if root["style"] is None else [root["style"]])
    if list(map(str, draft.preference_inputs)) != expected_inputs: _mismatch("inputs", "Draft preferences differ")
    decided = Record(id=ids.new(RefKind.DECISION), at=clock.now(), writer=Role.MODEL, producer=agent.producer,
                     body=Decided(inputs=(draft.belief, *draft.preference_inputs), contract=RATE_DECISION, content=draft.content))
    job = Record(id=ids.new(RefKind.JOB), at=clock.now(), writer=Role.MODEL, producer=agent.producer,
                 body=JobOpened(decision=decided.id, step=0, contract=RATE_JOB, content=Payload.json(data["intent"])))
    return Commit(parents=draft.parents, decided=decided, job=job)


def _check_job(decided, job, intent):
    if (isinstance(job.body, JobOpened) and job.body.contract.name == RATE_JOB.name and
            job.body.contract != RATE_JOB):
        from .rate import RateReplayUnavailable
        raise RateReplayUnavailable("unknown_version", "saved rate job contract version is unavailable")
    if (not isinstance(job.body, JobOpened) or job.body.contract != RATE_JOB or
            job.body.decision != decided.id or job.body.step != 0 or job.body.content != Payload.json(intent)):
        _mismatch("intent", "JobOpened differs from the certified decision intent")


def commit(agent, prepared, ledger, *, available=None):
    from .clock import precedes
    from .records import admit
    if not isinstance(prepared.decided.body, Decided): raise RateInputError("shape", "Decided required")
    for cid in prepared.parents:
        entry, _ = _get(ledger, cid)
        if not entry.is_event: _mismatch("root", "decision parents must be events")
    draft = _verify_body(agent._model, ledger, prepared.parents, prepared.decided.body,
                         agent.rate_budget if available is None else available)
    _check_job(prepared.decided, prepared.job, draft.content.as_json()["intent"])
    for record in (prepared.decided, prepared.job):
        for existing in ledger.entries_of(record.id):
            admit(ledger.record(existing.cid), record)
    known_decisions = ledger.entries_of(prepared.decided.id)
    if any(e.parents != prepared.parents for e in known_decisions): _mismatch("root", "existing decision parents differ")
    for existing in ledger.entries_of(prepared.job.id):
        if not known_decisions or existing.parents != frozenset({known_decisions[0].cid}):
            _mismatch("intent", "existing job has different decision parents")
    for cid in prepared.parents:
        parent = ledger.entry(cid)
        if parent.at.run == prepared.decided.at.run and not precedes(parent.at, prepared.decided.at):
            _mismatch("root", "decision does not follow its saved parent")
    if prepared.decided.at.run == prepared.job.at.run and not precedes(prepared.decided.at, prepared.job.at):
        _mismatch("intent", "job does not follow its decision")
    entry = ledger.append(prepared.decided, prepared.parents)
    ledger.append(prepared.job, {entry.cid})


def verify_rate_decision(*, model, ledger, decision: str, budget: RateBudget):
    """Replay the saved parents/method/trace; return the original certified Draft."""
    entry, record = _get(ledger, decision)
    if not isinstance(record.body, Decided): _mismatch("root", "Decided required")
    draft = _verify_body(model, ledger, entry.parents, record.body, budget)
    jobs = [e for e in ledger.entries() if e.body_type is JobOpened and
            (decision in e.parents or _json.loads(e.header)["body"]["decision"] == str(record.id))]
    if not jobs:
        from .rate import RateReplayUnavailable
        raise RateReplayUnavailable("missing_reference", "corresponding rate job is unavailable")
    if len(jobs) != 1: _mismatch("intent", "decision must open exactly one rate job")
    for job_entry in jobs:
        _, job = _get(ledger, job_entry.cid)
        if job_entry.parents != frozenset({decision}): _mismatch("intent", "job has different decision parents")
        _check_job(record, job, draft.content.as_json()["intent"])
    return draft


def restore(cls, *, model, lineage, ledger, belief, component, budget):
    from .agent import _preference_view, ModelMismatch
    entry, record = _get(ledger, belief)
    if not isinstance(record.body, Prediction) or record.body.target != "belief" or record.body.contract != RATE_BELIEF:
        raise RateInputError("shape", "rate belief Prediction required")
    if record.producer.state is None: raise RateInputError("shape", "belief producer.state required")
    data = _load(record.body.content.data)
    if data.get("model") != model.ref: raise ModelMismatch("belief: model reference differs")
    subject = cls(model=model, lineage=lineage, component=component, rate_budget=budget)
    snapshot = ledger.snapshot(entry.parents)
    reading = read_rate(model, snapshot.records, unread_preferences=snapshot.unread_preferences)
    ancestry = fact_ancestors(ledger, entry.parents, reading)
    # Reproduce the saved derivation even when it stopped before producing an
    # evidence certificate. A larger current budget may improve later queries;
    # it must not turn an authentic incomplete summary into a replay mismatch.
    try:
        b = data["derivation_budget"]
        _object(b, ("tolerance", "max_cells", "max_terms", "max_refinements"), "belief.derivation_budget")
        derivation_budget = RateBudget(_fraction(b["tolerance"], "evidence"),
                                      b["max_cells"], b["max_terms"], b["max_refinements"])
    except (KeyError, TypeError, RateInputError) as exc:
        _mismatch("evidence", "malformed saved derivation budget: " + str(exc))
    if any(getattr(derivation_budget, key) > getattr(subject.rate_budget, key)
           for key in ("max_cells", "max_terms", "max_refinements")):
        raise RateIncomplete("budget", "available budget cannot reproduce saved belief")
    q, a, content = derive(model, reading, budget=derivation_budget, ancestry=ancestry)
    if Payload.json(content) != record.body.content: _mismatch("evidence", "saved belief differs from raw reconstruction")
    subject._frontier, subject._reading, subject._q, subject._a = entry.parents, reading, q, a
    subject._revision, subject._belief = record.producer.state.revision, record
    subject._preferences, subject._fact_ancestors, subject._lattice = _preference_view(ledger, entry.parents), ancestry, content
    subject._rate_refinements = _read_refinements(model, ledger, entry.parents, subject.rate_budget)
    return subject


def decide(agent, candidates, *, u, clock, ids, ledger, now_ns, observed_ns, check_events, budget):
    from .agent import plan
    _check_simulation_clock(clock)
    if type(now_ns) is not int or type(observed_ns) is not int or not check_events:
        raise RateInputError("shape", "decide requires explicit now, observed and check provenance")
    boots = [r for r in agent._reading.rate_records if isinstance(r.body, Observed) and r.body.contract == BOOT]
    if not boots or boots[0].at.run != clock.run: raise RateInputError("shape", "decide clock run differs from BOOT")
    draft = plan(agent.view(now_ns=now_ns, observed_ns=observed_ns, check_events=check_events),
                 candidates, u=u, rate_budget=budget)
    prepared = agent.prepare(draft, clock=clock, ids=ids)
    commit(agent, prepared, ledger, available=budget)
    return prepared.decided, prepared.job


def _check_simulation_clock(clock):
    from .rate import RateRuntimeUnverified
    from .clock import FakeClock
    if not isinstance(clock, FakeClock):
        raise RateRuntimeUnverified("clock_fit", "model.9 real clock has not been certified")


def verify_rate_refinement(*, model, ledger, refinement: str, budget: RateBudget):
    """Verify a derived sheet, then intersect; never alter the original decision."""
    from .rate import _evaluate_rate, _trace, Certificate, RateReplayUnavailable
    entry, record = _get(ledger, refinement)
    if not isinstance(record.body, Prediction) or record.body.target != "decision_refinement":
        raise RateInputError("shape", "decision_refinement Prediction required")
    if record.body.contract != RATE_REFINEMENT:
        raise RateReplayUnavailable("unknown_version", "rate refinement contract unavailable")
    data = _load(record.body.content.data)
    _object(data, ("decision", "problem_key", "values", "certificate"), "refinement")
    original = verify_rate_decision(model=model, ledger=ledger, decision=data["decision"], budget=budget)
    de, decided = _get(ledger, data["decision"])
    if data["decision"] not in ledger.ancestors(entry.parents): _mismatch("root", "refinement has no causal decision parent")
    old = original.content.as_json()
    view, resolved, candidates, u, _ = _decision_view(model, ledger, de.parents, decided.body)
    saved_budget = _saved_budget(data["certificate"], budget)
    # Replay the saved refinement trace from the initial enclosure. Its actual
    # refinements, rather than a fresh width requirement, define the proof.
    evaluation, engine = _evaluate_rate(view, candidates, resolved, _execution_budget(saved_budget, budget),
                                        require_width=False)
    selection = data["certificate"].get("enclosures", {}).get("selection")
    trace = data["certificate"].get("trace", [])
    base_trace = trace[:-1] if selection is not None else trace
    while _encode(evaluation.certificate.trace) != base_trace:
        if len(evaluation.certificate.trace) >= len(base_trace): _mismatch("interval", "refinement trace differs")
        engine.refine()
        evaluation = engine.evaluation()
    certificate = evaluation.certificate
    if selection is not None:
        index = selection.get("index")
        if type(index) is not int or not 0 <= index < len(candidates): _mismatch("selection", "invalid refinement selection")
        previous, current = evaluation.cumulative[index:index+2]
        proof_u = _fraction(selection.get("u"), "selection")
        if not previous.upper <= proof_u < current.lower:
            _mismatch("selection", "refinement's auxiliary selection is not certified")
        rebuilt_selection = {"index": index, "choice": candidates[index], "u": _encode(proof_u),
            "previous": {"lower": _encode(previous.lower), "upper": _encode(previous.upper)},
            "current": {"lower": _encode(current.lower), "upper": _encode(current.upper)}}
        steps = [dict(s) for s in certificate.trace]
        _trace(steps, "select", dimension=candidates[index])
        certificate = Certificate(certificate.problem_key, certificate.method, certificate.arithmetic,
            certificate.budget, tuple(steps), {**certificate.enclosures, "selection": rebuilt_selection}, certificate.residuals)
    certificate = _replace(certificate, budget=saved_budget)
    if (data["problem_key"] != old["certificate"]["problem_key"] or
            data["problem_key"] != certificate.problem_key): _mismatch("root", "refinement problem differs")
    values = _values(candidates, certificate)
    if data["certificate"] != _encode(certificate) or data["values"] != values:
        _mismatch("interval", "refinement proof differs from reexecution")
    result = []
    for before, after in zip(old["values"], values):
        row = {"candidate": before["candidate"]}
        for name in ("expected_cost", "information", "G", "J", "q_star"):
            b, a = before[name]["bounds"], after[name]["bounds"]
            lo = max(_fraction(b["lower"], "interval"), _fraction(a["lower"], "interval"))
            hi = min(_fraction(b["upper"], "interval"), _fraction(a["upper"], "interval"))
            if lo > hi: _mismatch("interval", "certified refinement intervals do not intersect")
            row[name] = {**after[name], "bounds": {"lower": _encode(lo), "upper": _encode(hi)}}
        result.append(row)
    return _freeze(result)


def _read_refinements(model, ledger, frontier, budget):
    ancestors = ledger.ancestors(frontier)
    result = {}
    for entry in ledger.entries():
        if (entry.body_type is Prediction and entry.parents <= ancestors and
                _json.loads(entry.header)["body"]["target"] == "decision_refinement"):
            _, record = _get(ledger, entry.cid)
            if record.body.target == "decision_refinement":
                result[entry.cid] = verify_rate_refinement(model=model, ledger=ledger, refinement=entry.cid, budget=budget)
    return _MappingProxyType(result)
