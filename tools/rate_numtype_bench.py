"""Compare private C1 arithmetic adapters in bounded, serial subprocesses."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import queue
import statistics
import subprocess
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sui import rate, rate_entry


CANDIDATES = ("F", "a1", "a2", "b128", "b192", "b256", "c")
SCENES = ("n0", "n1", "n2", "saturated", "u14_25", "u3_5", "u61_100")


def canonical(value):
    def plain(item):
        if isinstance(item, Mapping):
            return {k: plain(v) for k, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [plain(v) for v in item]
        return item
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pair(value):
    return [value.numerator, value.denominator]


def rational_hash(numerator, denominator):
    modulus = sys.hash_info.modulus
    value = abs(numerator) % modulus * pow(denominator, -1, modulus) % modulus
    value = -value if numerator < 0 else value
    return -2 if value == -1 else value


@dataclass(frozen=True, slots=True)
class _Dyadic:
    """[lo*2**exponent, hi*2**exponent], rounded by integer inequalities."""
    lo: int
    hi: int
    exponent: int
    bits: int

    @classmethod
    def rounded(cls, lo, hi, exponent, bits):
        if lo > hi:
            raise ValueError("reversed binary interval")
        while max(abs(lo), abs(hi)).bit_length() > bits:
            shift = max(abs(lo), abs(hi)).bit_length() - bits
            scale = 1 << shift
            lo, hi, exponent = lo // scale, -((-hi) // scale), exponent + shift
        if lo == hi == 0:
            return cls(0, 0, 0, bits)
        common = abs(lo) | abs(hi)
        shift = (common & -common).bit_length() - 1
        return cls(lo >> shift, hi >> shift, exponent + shift, bits)

    @classmethod
    def rational(cls, numerator, denominator, bits):
        if denominator == 0:
            raise ZeroDivisionError("zero denominator")
        if denominator < 0:
            numerator, denominator = -numerator, -denominator
        if numerator == 0:
            return cls(0, 0, 0, bits)
        exponent = abs(numerator).bit_length() - denominator.bit_length() - bits + 1
        if exponent < 0:
            numerator <<= -exponent
        else:
            denominator <<= exponent
        return cls.rounded(numerator // denominator, -((-numerator) // denominator), exponent, bits)

    def convert(self, value):
        if isinstance(value, _Dyadic):
            if value.bits != self.bits:
                raise ValueError("mixed binary precisions")
            return value
        if isinstance(value, Fraction):
            return self.rational(value.numerator, value.denominator, self.bits)
        if type(value) is not int:
            raise TypeError("binary arithmetic requires integers or exact fractions")
        return self.rational(value, 1, self.bits)

    def aligned(self, other):
        other = self.convert(other)
        exponent = min(self.exponent, other.exponent)
        return (self.lo << (self.exponent-exponent), self.hi << (self.exponent-exponent),
                other.lo << (other.exponent-exponent), other.hi << (other.exponent-exponent), exponent)

    def __add__(self, other):
        a, b, c, d, exponent = self.aligned(other)
        return self.rounded(a+c, b+d, exponent, self.bits)

    __radd__ = __add__

    def __neg__(self):
        return _Dyadic(-self.hi, -self.lo, self.exponent, self.bits)

    def __sub__(self, other):
        return self + -self.convert(other)

    def __rsub__(self, other):
        return self.convert(other) + -self

    def __mul__(self, other):
        other = self.convert(other)
        products = (self.lo*other.lo, self.lo*other.hi, self.hi*other.lo, self.hi*other.hi)
        return self.rounded(min(products), max(products), self.exponent+other.exponent, self.bits)

    __rmul__ = __mul__

    def reciprocal(self):
        if self.lo <= 0 <= self.hi:
            raise ZeroDivisionError("binary interval contains zero")
        a = self.rational(1, self.hi, self.bits)
        b = self.rational(1, self.lo, self.bits)
        a = _Dyadic(a.lo, a.hi, a.exponent-self.exponent, self.bits)
        b = _Dyadic(b.lo, b.hi, b.exponent-self.exponent, self.bits)
        lo, _, _, hi, exponent = a.aligned(b)
        return self.rounded(lo, hi, exponent, self.bits)

    def __truediv__(self, other):
        return self * self.convert(other).reciprocal()

    def __rtruediv__(self, other):
        return self.convert(other) * self.reciprocal()

    def __pow__(self, exponent):
        if type(exponent) is not int or exponent < 0:
            raise ValueError("nonnegative integer power required")
        if exponent == 0:
            return self.convert(1)
        values = self.lo**exponent, self.hi**exponent
        lower = values[0] if exponent % 2 else 0 if self.lo <= 0 <= self.hi else min(values)
        return self.rounded(lower, max(values), self.exponent*exponent, self.bits)

    def __abs__(self):
        lower = 0 if self.lo <= 0 <= self.hi else min(abs(self.lo), abs(self.hi))
        return _Dyadic(lower, max(abs(self.lo), abs(self.hi)), self.exponent, self.bits)

    def __bool__(self):
        return self.lo != 0 or self.hi != 0

    def __eq__(self, other):
        if not isinstance(other, (_Dyadic, int, Fraction)):
            return NotImplemented
        a, b, c, d, _ = self.aligned(other)
        return a == b == c == d

    def __hash__(self):
        if self.lo == self.hi:
            return rational_hash(*self.ratio())
        return hash((self.lo, self.hi, self.exponent, self.bits))

    def __lt__(self, other):
        _, b, c, _, _ = self.aligned(other)
        return b < c

    def __le__(self, other):
        _, b, c, _, _ = self.aligned(other)
        return b <= c

    def __gt__(self, other):
        return self.convert(other) < self

    def __ge__(self, other):
        return self.convert(other) <= self

    def ratio(self, upper=False):
        numerator = self.hi if upper else self.lo
        if self.exponent >= 0:
            return numerator << self.exponent, 1
        return numerator, 1 << -self.exponent


@dataclass(frozen=True, slots=True)
class _BinaryArithmetic(rate._InformationArithmetic):
    bits: int = 128

    def number(self, numerator=0, denominator=None):
        if isinstance(numerator, _Dyadic) and denominator is None:
            if numerator.bits != self.bits:
                raise ValueError("mixed binary precisions")
            return numerator
        if denominator is None:
            if isinstance(numerator, Fraction):
                numerator, denominator = numerator.numerator, numerator.denominator
            else:
                denominator = 1
        return _Dyadic.rational(int(numerator), int(denominator), self.bits)

    def endpoints(self, value):
        value = self.number(value)
        return (_Dyadic.rounded(value.lo, value.lo, value.exponent, self.bits),
                _Dyadic.rounded(value.hi, value.hi, value.exponent, self.bits))

    def ratio(self, value, *, upper=False):
        return self.number(value).ratio(upper)

    def extremum(self, values, maximum):
        if len(values) == 1:
            values = tuple(values[0])
        if all(type(v) is int for v in values):
            return (max if maximum else min)(values)
        values = tuple(self.number(v) for v in values)
        exponent = min(v.exponent for v in values)
        choose = max if maximum else min
        lo = choose(v.lo << (v.exponent-exponent) for v in values)
        hi = choose(v.hi << (v.exponent-exponent) for v in values)
        return _Dyadic.rounded(lo, hi, exponent, self.bits)

    def minimum(self, *values):
        return self.extremum(values, False)

    def maximum(self, *values):
        return self.extremum(values, True)

    def order_key(self, value):
        return self.endpoints(value)[0]


class _ArbScalar:
    """Ball basic operations with explicit, directed endpoint comparisons."""
    __slots__ = ("value", "arithmetic")

    def __init__(self, value, arithmetic):
        self.value, self.arithmetic = value, arithmetic

    def convert(self, other):
        return self.arithmetic.number(other)

    def __add__(self, other):
        return _ArbScalar(self.value+self.convert(other).value, self.arithmetic)

    __radd__ = __add__

    def __neg__(self):
        return _ArbScalar(-self.value, self.arithmetic)

    def __sub__(self, other):
        return self+-self.convert(other)

    def __rsub__(self, other):
        return self.convert(other)+-self

    def __mul__(self, other):
        return _ArbScalar(self.value*self.convert(other).value, self.arithmetic)

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self.convert(other)
        if other.value.lower() <= 0 <= other.value.upper():
            raise ZeroDivisionError("Arb divisor contains zero")
        return _ArbScalar(self.value/other.value, self.arithmetic)

    def __rtruediv__(self, other):
        return self.convert(other)/self

    def __pow__(self, exponent):
        if type(exponent) is not int or exponent < 0:
            raise ValueError("nonnegative integer power required")
        return _ArbScalar(self.value**exponent, self.arithmetic)

    def __abs__(self):
        return _ArbScalar(abs(self.value), self.arithmetic)

    def __bool__(self):
        return not (self.value.lower() == self.value.upper() == 0)

    def __eq__(self, other):
        if not isinstance(other, (_ArbScalar, int, Fraction)):
            return NotImplemented
        other = self.convert(other)
        return self.value.lower() == self.value.upper() == other.value.lower() == other.value.upper()

    def __hash__(self):
        lo, hi = self.arithmetic.endpoints(self)
        if lo == hi:
            return rational_hash(*self.arithmetic.ratio(lo))
        return hash((tuple(self.value.lower().man_exp()), tuple(self.value.upper().man_exp())))

    def __lt__(self, other):
        return bool(self.value.upper() < self.convert(other).value.lower())

    def __le__(self, other):
        return bool(self.value.upper() <= self.convert(other).value.lower())

    def __gt__(self, other):
        return self.convert(other) < self

    def __ge__(self, other):
        return self.convert(other) <= self


@dataclass(frozen=True, slots=True)
class _ArbArithmetic(rate._InformationArithmetic):
    module: object = None

    def number(self, numerator=0, denominator=None):
        if isinstance(numerator, _ArbScalar) and denominator is None:
            return numerator
        if denominator is None:
            if isinstance(numerator, Fraction):
                numerator, denominator = numerator.numerator, numerator.denominator
            else:
                denominator = 1
        value = self.module.arb(int(numerator))/self.module.arb(int(denominator))
        return _ArbScalar(value, self)

    def endpoints(self, value):
        value = self.number(value)
        return _ArbScalar(value.value.lower(), self), _ArbScalar(value.value.upper(), self)

    def ratio(self, value, *, upper=False):
        value = self.number(value)
        endpoint = value.value.upper() if upper else value.value.lower()
        mantissa, exponent = map(int, endpoint.man_exp())
        return (mantissa << exponent, 1) if exponent >= 0 else (mantissa, 1 << -exponent)

    def extremum(self, values, maximum):
        if len(values) == 1:
            values = tuple(values[0])
        if all(type(v) is int for v in values):
            return (max if maximum else min)(values)
        values = tuple(self.number(v) for v in values)
        choose = max if maximum else min
        lo = choose(v.value.lower() for v in values)
        hi = choose(v.value.upper() for v in values)
        return _ArbScalar(lo.union(hi), self)

    def minimum(self, *values):
        return self.extremum(values, False)

    def maximum(self, *values):
        return self.extremum(values, True)

    def order_key(self, value):
        return self.endpoints(value)[0]


def adapter(candidate):
    if candidate == "F":
        return rate._InformationArithmetic(Fraction), {}
    if candidate == "a1":
        import gmpy2
        return rate._InformationArithmetic(gmpy2.mpq), {
            "gmpy2": importlib.metadata.version("gmpy2"), "gmp": gmpy2.mp_version()}
    if candidate == "a2":
        import flint
        return rate._InformationArithmetic(flint.fmpq), {
            "python-flint": importlib.metadata.version("python-flint"),
            "flint": getattr(flint, "__FLINT_VERSION__", None)}
    if candidate.startswith("b"):
        return _BinaryArithmetic(bits=int(candidate[1:])), {"binary_bits": int(candidate[1:])}
    if candidate == "c":
        import flint
        flint.ctx.prec = 192
        return _ArbArithmetic(module=flint), {
            "python-flint": importlib.metadata.version("python-flint"), "arb_bits": 192,
            "flint": getattr(flint, "__FLINT_VERSION__", None)}
    raise ValueError("unknown candidate")


def build_input(scene, declaration):
    from sui.agent import View
    from sui.clock import FakeClock
    from sui.clock_contracts import ClockSource, SOURCE
    from sui.contracts import ContractRef
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.preference import current, resolve
    from sui.rate_model import rate_model_from_json
    from sui.records import Observed, Payload, Producer, Record, Role
    from sui.s4_contracts import BOOT
    from sui.s4b_contracts import RATE_REPORT

    n = {"n0": 0, "n1": 1, "n2": 2, "saturated": 3}.get(scene, 0)
    ns = 10**9
    run = Ref(RefKind.RUN, "c1")
    clock = FakeClock(run=run, run_index=0, mono_ns=0)
    ids, ledger = SequentialIds("c1"), Ledger(salts=SequentialSalts())
    producer = Producer(component="test.s4b2", code_version="1")

    def record(content, contract, route, *, source_id=None, source_ns=None, received_ns=0):
        body = Observed(route=route, content=Payload.json(content), contract=contract,
                        source_id=source_id, source_time_ns=source_ns, received_ns=received_ns)
        result = Record(id=ids.new(RefKind.OBSERVATION), at=clock.now(), writer=Role.MEMBRANE,
                        producer=producer, body=body)
        ledger.accept(result)
        return result

    boot = record({}, BOOT, "membrane")
    clock_spec = declaration["records"][0]["clock"]
    provenance = ClockSource(run=run, provider="test.c1", implementation="FakeClock",
        python_version=platform.python_version(), resolution_s=Fraction(1, ns),
        monotonic=True, adjustable=False, measurement=ContractRef(clock_spec["name"], clock_spec["version"]))
    source = record(provenance.as_json(), SOURCE, "membrane")
    clock.advance(ns)
    root = record({"channel": "root-report", "experiment": "root-window",
        "window_start_ns": 0, "window_end_ns": ns,
        "arrival_count": {"kind": "exact" if n < 3 else "at_least", "value": n},
        "outcome": None, "completion_ns": ns}, RATE_REPORT, "c1",
        source_id=f"c1-root-{n}", source_ns=ns, received_ns=ns)
    ancestry = {}
    for entry in ledger.entries():
        ancestors = ledger.ancestors((entry.cid,)) | {entry.cid}
        ancestry[entry.cid] = frozenset(str(ledger.record(cid).id) for cid in ancestors
            if ledger.record(cid).body.contract in (BOOT, RATE_REPORT))
    model = rate_model_from_json(canonical(declaration).encode("utf-8"))
    view = View(model=model, frontier=ledger.heads(), belief=Ref(RefKind.INTERPRETATION, "evaluation-query"),
        reading=rate_entry.read_rate(model, (boot, source, root)), now_ns=ns, observed_ns=ns,
        check_events=({"fact": str(root.id)},), fact_ancestors=ancestry)
    resolved = resolve(current(view.preferences), view)
    u = {"u14_25": Fraction(14, 25), "u3_5": Fraction(3, 5), "u61_100": Fraction(61, 100)}.get(scene)
    inputs = {"declaration": declaration, "records": [rate_entry._encode(r) for r in (boot, source, root)],
        "frontier": sorted(view.frontier), "belief": str(view.belief), "candidates": ["read", "wait"],
        "u": None if u is None else pair(u), "budget": rate_entry._encode(rate.default_rate_budget()),
        "gamma": [1, 1], "H_ns": None}
    # Record payloads are bytes; the model declaration and report content are JSON inputs.
    for item in inputs["records"]:
        item["body"]["content"]["data"] = item["body"]["content"]["data"].decode("utf-8")
    return view, resolved, u, n, digest(canonical(inputs))


def evaluation_json(evaluation):
    fields = ("expected_cost", "information", "G", "J", "q_star")
    return {"values": [{"candidate": candidate, **{field: rate_entry._encode(getattr(evaluation, field)[i])
            for field in fields}} for i, candidate in enumerate(evaluation.candidates)],
            "certificate": rate_entry._encode(evaluation.certificate)}


def selection_json(view, resolved, evaluation, choice):
    _, _, context, _ = rate_entry._rate_evaluation_inputs(view, evaluation.candidates, resolved,
                                                        choice.certificate.budget)
    history = rate_entry.rate_history(view.model, view.reading, context=context)
    commands = [rate_entry._command(view.model, c, history.context, history._boot_ns)
                for c in evaluation.candidates]
    return {"root": rate_entry._root(view, resolved, history),
        "candidates": [{"id": c, "command": command} for c, command in zip(evaluation.candidates, commands)],
        "u": rate_entry._encode(choice.u),
        "values": rate_entry._values(evaluation.candidates, choice.certificate), "display": None,
        "selection": {"index": choice.index, "chosen": choice.choice,
                      "previous": rate_entry._interval_pair(choice.previous),
                      "current": rate_entry._interval_pair(choice.current)},
        "intent": commands[choice.index], "certificate": rate_entry._encode(choice.certificate)}


def measure(arithmetic, built):
    view, resolved, u, n, input_hash = built
    start = time.perf_counter()
    evaluation, engine = rate._evaluate_rate(view, ("read", "wait"), resolved,
        rate.default_rate_budget(), require_width=u is None, _arithmetic=arithmetic)
    if u is None:
        certificate, chosen = evaluation.certificate, None
        output = evaluation_json(evaluation)
    else:
        choice = rate._certify_computed_choice(evaluation, engine, u=u)
        certificate, chosen = choice.certificate, choice.choice
        output = selection_json(view, resolved, evaluation, choice)
    encoded_certificate = rate_entry._encode(certificate)
    certificate_bytes = canonical(encoded_certificate)
    output_bytes = canonical(output)
    elapsed = time.perf_counter()-start
    enclosures = encoded_certificate["enclosures"]
    qs = enclosures["q_star"]
    widths = [pair(Fraction(*q["upper"])-Fraction(*q["lower"])) for q in qs]
    return {"status": "ok", "seconds": elapsed, "cells": len(engine.cells), "terms": engine.work.terms,
        "refinements": engine.refinements, "splits": sum(s["operation"] == "split" for s in certificate.trace),
        "q_star": qs, "q_star_widths": widths, "chosen": chosen,
        "certificate_sha256": digest(certificate_bytes), "output_sha256": digest(output_bytes),
        "input_sha256": input_hash, "root_n": n,
        "_certificate_bytes": certificate_bytes, "_output_bytes": output_bytes}


def error_result(exc):
    return {"status": "exception", "exception": type(exc).__name__, "message": str(exc),
            "reason": getattr(exc, "reason", None), "field": getattr(exc, "field", None)}


def worker(args):
    versions = {"python": platform.python_version(), "implementation": platform.python_implementation(),
                "platform": platform.platform()}
    try:
        arithmetic, libraries = adapter(args.worker)
        arithmetic_report = {
            "default_scalar": f"{rate._InformationScalar.__module__}.{rate._InformationScalar.__name__}",
            "matches_default": args.worker in ("F", "a1", "a2") and
                               arithmetic.scalar is rate._InformationScalar,
        }
        versions.update(libraries)
        declaration = json.loads(args.declaration.read_text(encoding="utf-8"))
        built = build_input(args.scene, declaration)
    except ModuleNotFoundError as exc:
        print(canonical({"status": "not_installed", "label": "未導入", "module": exc.name,
                         "versions": versions}), flush=True)
        return
    except Exception as exc:
        print(canonical({**error_result(exc), "versions": versions}), flush=True)
        return
    print(canonical({"status": "ready", "versions": versions, "arithmetic": arithmetic_report}), flush=True)
    for line in sys.stdin:
        if line.strip() == "stop":
            return
        start = time.perf_counter()
        try:
            result = measure(arithmetic, built)
        except Exception as exc:
            result = error_result(exc)
            result["seconds"] = time.perf_counter()-start
            result["input_sha256"] = built[-1]
            result["root_n"] = built[-2]
        result["versions"] = versions
        result["arithmetic"] = arithmetic_report
        print(canonical(result), flush=True)


class _Worker:
    def __init__(self, candidate, scene, declaration, timeout):
        self.timeout = timeout
        self.messages = queue.Queue()
        self.errors = []
        self.started = time.perf_counter()
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", candidate, "--scene", scene, "--declaration", str(declaration)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env={**os.environ, "PYTHONHASHSEED": "0"})

        def drain_output():
            for line in self.process.stdout:
                self.messages.put(line)
            self.messages.put(None)

        def drain_errors():
            for line in self.process.stderr:
                self.errors.append(line)

        self.output_thread = threading.Thread(target=drain_output, daemon=True)
        self.error_thread = threading.Thread(target=drain_errors, daemon=True)
        self.output_thread.start()
        self.error_thread.start()
        self.ready = self.receive()
        self.ready.setdefault("versions", {"python": platform.python_version(),
            "implementation": platform.python_implementation(), "platform": platform.platform(),
            "libraries": "unknown: worker initialization did not finish"})

    def receive(self, timeout=None):
        try:
            message = self.messages.get(timeout=self.timeout if timeout is None else max(0, timeout))
        except queue.Empty:
            self.close(kill=True)
            return {"status": "timeout", "limit_seconds": self.timeout}
        if message is None:
            return {"status": "worker_exit", "exit_code": self.process.poll(), "stderr": "".join(self.errors)[-8000:]}
        try:
            return json.loads(message)
        except json.JSONDecodeError:
            return {"status": "protocol_error", "message": message[:2000]}

    def run(self, cold=False):
        if self.ready["status"] != "ready":
            return dict(self.ready)
        if self.process.poll() is not None or self.process.stdin.closed:
            return {"status": "worker_unavailable", "exit_code": self.process.poll(),
                    "reason": "previous measurement ended the worker", "versions": self.ready["versions"]}
        start = time.perf_counter()
        try:
            self.process.stdin.write("run\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            return {**error_result(exc), "versions": self.ready["versions"]}
        remaining = self.timeout-(time.perf_counter()-self.started) if cold else self.timeout
        result = self.receive(remaining)
        result["wall_seconds"] = time.perf_counter()-start
        result.setdefault("versions", self.ready["versions"])
        result.setdefault("arithmetic", self.ready["arithmetic"])
        return result

    def close(self, kill=False):
        if self.process.poll() is None:
            if kill:
                self.process.kill()
            else:
                try:
                    self.process.stdin.write("stop\n")
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not self.process.stdin:
                (self.output_thread if stream is self.process.stdout else self.error_thread).join(timeout=5)
            stream.close()


def source_hashes():
    paths = sorted((ROOT / "src" / "sui").glob("*.py")) + [Path(__file__).resolve()]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def load_oracles(args):
    if args.oracle_json is None:
        raise ValueError("--oracle-json is required: four independent q*(read) intervals as rational pairs")
    raw = json.loads(args.oracle_json.read_text(encoding="utf-8"))
    values = raw["q_read"]
    if len(values) != 4:
        raise ValueError("oracle q_read must have four root intervals")
    for value in values:
        lo, hi = Fraction(*value["lower"]), Fraction(*value["upper"])
        if not 0 <= lo <= hi <= 1:
            raise ValueError("invalid oracle interval")
    return values, {"path": str(args.oracle_json.resolve()), "sha256": hashlib.sha256(args.oracle_json.read_bytes()).hexdigest(),
                    "provenance": raw.get("provenance")}


def check_result(result, reference, oracles, mathematical, input_hash):
    result.setdefault("input_sha256", input_hash)
    result["same_input"] = result["input_sha256"] == input_hash
    if result["status"] != "ok":
        return result
    own_certificate = result.pop("_certificate_bytes")
    own_output = result.pop("_output_bytes")
    result["F_certificate_bytes_equal"] = None if reference is None else own_certificate == reference["_certificate_bytes"]
    result["F_output_bytes_equal"] = None if reference is None else own_output == reference["_output_bytes"]
    result["F_chosen_equal"] = None if reference is None else result["chosen"] == reference["chosen"]
    oracle = oracles[result["root_n"]]
    q = result["q_star"][0]
    result["oracle_contained"] = Fraction(*q["lower"]) <= Fraction(*oracle["lower"]) <= Fraction(*oracle["upper"]) <= Fraction(*q["upper"])
    result["width_at_most_1e_6"] = all(Fraction(*v) <= Fraction(1, 10**6) for v in result["q_star_widths"])
    result["width_requirement_applies"] = mathematical
    result["width_requirement_pass"] = not mathematical or result["width_at_most_1e_6"]
    return result


def benchmark(args):
    output = args.output.resolve()
    if output == ROOT or output.is_relative_to(ROOT):
        raise ValueError("--output must be outside the repository")
    if output.exists():
        raise ValueError("--output already exists; choose a fresh result path")
    if not output.parent.is_dir():
        raise ValueError("--output parent directory must exist")
    oracles, oracle_source = load_oracles(args)
    candidates = list(dict.fromkeys(["F", *args.candidates]))
    result = {"schema": "sui.rate_numtype_bench.1", "timeout_seconds": args.timeout,
        "warm_repeats": args.repeats, "order": "serial, alternating F/candidate; cold processes are separate",
        "source_sha256": source_hashes(), "oracle_source": oracle_source,
        "declaration_sha256": hashlib.sha256(args.declaration.read_bytes()).hexdigest(),
        "declaration_path": str(args.declaration.resolve()),
        "versions": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                     "platform": platform.platform(), "numpy": importlib.metadata.version("numpy"),
                     "scipy": importlib.metadata.version("scipy")}, "scenes": []}

    def save():
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")

    save()
    for scene in args.scenes:
        mathematical = scene in ("n0", "n1", "n2", "saturated")
        rows, workers, cold_reference, warm_references = {}, {}, None, {}
        declaration = json.loads(args.declaration.read_text(encoding="utf-8"))
        input_hash = build_input(scene, declaration)[-1]
        scene_result = {"scene": scene, "input_sha256": input_hash, "candidates": rows}
        result["scenes"].append(scene_result)
        try:
            for candidate in candidates:
                cold = _Worker(candidate, scene, args.declaration.resolve(), args.timeout)
                try:
                    sample = cold.run(cold=True)
                    sample["cold_start_seconds"] = time.perf_counter()-cold.started
                    if candidate == "F" and sample["status"] == "ok":
                        cold_reference = dict(sample)
                    sample = check_result(sample, cold_reference, oracles, mathematical, input_hash)
                finally:
                    cold.close()
                rows[candidate] = {"production_proof": candidate in ("F", "a1", "a2"),
                    "rounding_residuals_recorded": False if candidate.startswith("b") or candidate == "c" else True,
                    "role": "reference_only" if candidate == "c" else "prototype" if candidate.startswith("b") else "exact",
                    "cold": sample, "warmup": None, "warm": [], "comparison_references": []}
                if sample["status"] == "not_installed":
                    print(f"{scene} {candidate}: 未導入", file=sys.stderr, flush=True)
                    continue
                worker_process = _Worker(candidate, scene, args.declaration.resolve(), args.timeout)
                workers[candidate] = worker_process
                warmup = worker_process.run()
                if candidate == "F" and warmup["status"] == "ok":
                    warm_references[-1] = dict(warmup)
                rows[candidate]["warmup"] = check_result(warmup, warm_references.get(-1), oracles, mathematical, input_hash)
                save()
            for repeat in range(args.repeats):
                # Rotate the candidate order while retaining a Fraction reference each round.
                alternatives = [v for v in candidates if v != "F" and v in workers]
                if alternatives:
                    offset = repeat % len(alternatives)
                    alternatives = alternatives[offset:]+alternatives[:offset]
                order = ["F"]
                for candidate in alternatives:
                    order.extend((candidate, "F"))
                for position, candidate in enumerate(order):
                    worker_process = workers.get(candidate)
                    if worker_process is None:
                        continue
                    sample = worker_process.run()
                    if candidate == "F" and sample["status"] == "ok":
                        warm_references[repeat] = dict(sample)
                    checked = check_result(sample, warm_references.get(repeat), oracles, mathematical, input_hash)
                    checked["round"] = repeat
                    collection = "comparison_references" if candidate == "F" and position > 0 else "warm"
                    rows[candidate][collection].append(checked)
                    save()
            for candidate, row in rows.items():
                samples = row["warm"]
                complete = len(samples) == args.repeats and all(v["status"] == "ok" for v in samples)
                times = [v["seconds"] for v in samples if v["status"] == "ok"]
                row["timing"] = {"complete": complete, "successful_samples": len(times), "total_samples": len(samples),
                    "median_seconds": statistics.median(times) if complete else None,
                    "max_seconds": max(times) if complete else None,
                    "successful_only_median_seconds": statistics.median(times) if times else None,
                    "successful_only_max_seconds": max(times) if times else None,
                    "cold_start_seconds": row["cold"].get("cold_start_seconds")}
                all_samples = [row["cold"], row["warmup"], *samples, *row["comparison_references"]]
                successes = [v for v in all_samples if v is not None and v["status"] == "ok"]
                all_complete = all(v is not None and v["status"] == "ok" for v in all_samples)
                row["deterministic_across_processes"] = all_complete and len(successes) >= 2 and len({v["output_sha256"] for v in successes}) == 1
                row["correctness_pass"] = complete and all_complete and bool(successes) and all(
                    v["same_input"] and v["oracle_contained"] and v["width_requirement_pass"] and v["F_chosen_equal"] is True and
                    (v["F_output_bytes_equal"] is True if candidate in ("F", "a1", "a2") else True) for v in successes)
                print(f"{scene} {candidate}: {row['timing']['median_seconds']} s, correctness={row['correctness_pass']}",
                      file=sys.stderr, flush=True)
            save()
        finally:
            for worker_process in workers.values():
                worker_process.close()
    result["source_unchanged"] = result["source_sha256"] == source_hashes()
    result["input_files_unchanged"] = (
        result["declaration_sha256"] == hashlib.sha256(args.declaration.read_bytes()).hexdigest() and
        oracle_source["sha256"] == hashlib.sha256(args.oracle_json.read_bytes()).hexdigest())
    result["all_requested_candidates_pass"] = result["source_unchanged"] and result["input_files_unchanged"] and all(
        row["correctness_pass"] and row["deterministic_across_processes"]
        for scene in result["scenes"] for row in scene["candidates"].values())
    save()
    print(str(output))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new JSON result path outside the repository")
    parser.add_argument("--oracle-json", type=Path, help='JSON: {"q_read":[{"lower":[n,d],"upper":[n,d]}, ...],"provenance":...}')
    parser.add_argument("--declaration", type=Path, default=ROOT / "tests" / "s4b2_c1_declaration.json")
    parser.add_argument("--candidates", nargs="+", choices=CANDIDATES, default=list(CANDIDATES))
    parser.add_argument("--scenes", nargs="+", choices=SCENES, default=list(SCENES))
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--worker", choices=CANDIDATES, help=argparse.SUPPRESS)
    parser.add_argument("--scene", choices=SCENES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.timeout <= 240 or args.repeats < 1:
        parser.error("timeout must be in (0,240], repeats must be positive")
    if args.worker is None and args.output is None:
        parser.error("--output is required")
    if args.worker is not None and args.scene is None:
        parser.error("worker requires --scene")
    return args


def main():
    args = parse_args()
    if args.worker is not None:
        worker(args)
    else:
        benchmark(args)


if __name__ == "__main__":
    main()
