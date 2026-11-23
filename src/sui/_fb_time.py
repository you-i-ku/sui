"""時刻を読む最初の本の数 (紙 F-b K38 決定 1〜8)。公開の口は `FThreadHost.belief_expression`・`query_belief`・
`verify_belief_value`・`same_belief` と、入口 U の時刻を読む版 (`f_update2.compute_timed_update`)。

信念の正本は「法則と原記録の適用の列」(units と entries)。そこから計算する量は、どれも有理数の係数と有理数の指数の
指数多項式 Σ c·exp(−q) (`Poly`) で厳密に表せる (固定の Poisson 源・一様の測定核・有限の法則の場合、K38 決定 4)。
exp(−q) は異なる有理数 q で有理数の上で一次独立 (Lindemann–Weierstrass) なので、正準な形で係数が全部 0 の時だけ値が 0:
構造の 0 は形から証明でき、区間の下端が 0 になったことで枝を消さない (決定 6)。照会は精度を指定した有理数の上下界 (決定 5)。

件数の分け方 (決定 4): 列で使う最大のカーソル c について C = max c + 1 とし、件数を 0..C−1 と「C 以上」にまとめる。
件数は減らず、列の判定は C 未満の閾値しか使わないので、その列について正確な集約。照会でもっと細かい件数が要る時は、
正本 (法則と列) から C を上げて作り直す。一様の判定時刻の取得区間の核は、区間に n 件届いた時に判定時刻の件数が
{k..k+n} の一様になることから、K[j,k] = P(n = j−k) · #{m ∈ [k, j] : 判定が m で成り立つ} / (n + 1)。
"""

from fractions import Fraction as _Q

from . import f as _f
from . import fb as _fb

_UNAVAILABLE = "unavailable_called"   # 源を呼んだが読めなかった: 独立の故障の核 (決定 2)
_MISSING = "unavailable_missing"      # 源が差されていない: 独立の「つながっていない」の核 (K38-c ②)
_UNREAD = (_UNAVAILABLE, _MISSING)


# --- 指数多項式 Σ c·exp(−q) (c, q は有理数、q ≥ 0) ---

class Poly:
    __slots__ = ("terms",)

    def __init__(self, terms=None):
        self.terms = {q: c for q, c in (terms or {}).items() if c}

    @staticmethod
    def const(c):
        return Poly({_Q(0): _Q(c)})

    def __add__(self, other):
        out = dict(self.terms)
        for q, c in other.terms.items():
            out[q] = out.get(q, 0) + c
        return Poly(out)

    def __sub__(self, other):
        return self + other.scale(-1)

    def scale(self, r):
        return Poly({q: c * r for q, c in self.terms.items()}) if r else Poly()

    def __mul__(self, other):
        out = {}
        for q1, c1 in self.terms.items():
            for q2, c2 in other.terms.items():
                out[q1 + q2] = out.get(q1 + q2, 0) + c1 * c2
        return Poly(out)

    def __eq__(self, other):
        return isinstance(other, Poly) and self.terms == other.terms

    def __hash__(self):
        return hash(frozenset(self.terms.items()))

    @property
    def zero(self) -> bool:
        return not self.terms

    def encode(self):
        return [[_f._encode(q), _f._encode(c)] for q, c in sorted(self.terms.items())]

    def enclose(self, bits):
        lo = hi = _Q(0)
        for q, c in self.terms.items():
            a, b = _exp_neg(q, bits)
            lo, hi = (lo + c * a, hi + c * b) if c > 0 else (lo + c * b, hi + c * a)
        return lo, hi


    def shift(self, q0):
        """exp(q0) を掛ける (指数を q0 だけずらす。負の指数も持てる)。"""
        return Poly({q - q0: c for q, c in self.terms.items()})

    def exact_real(self):
        """F-a の厳密式 (ExactReal) にする。"""
        from .f import ExactReal, _add, _mul, _r
        return _add(*(_r(c) if not q else _mul(_r(c), ExactReal(op="exp", arg=_r(-q)))
                      for q, c in sorted(self.terms.items()))) if self.terms else _r(0)


class Ratio:
    """指数多項式の比 num / den (den は形で 0 でない)。採用された時刻を読む信念の確率を、考える側 (F-a の評価) へそのまま
    渡す数 (K38 採用条件「考える側が実際にその信念を使う」)。四則・形での 0 の判定・符号 (形で 0 でなければ精度を上げて
    必ず決まる) を持ち、F-a の厳密式へは `exact_real` で写る (`f._r` の口)。有理数の値は有理数の式になる。"""
    __slots__ = ("num", "den")

    def __init__(self, num, den=None):
        den = Poly.const(1) if den is None else den
        if den.zero:
            raise ZeroDivisionError("structurally zero denominator")
        if len(den.terms) == 1:   # 単項の分母は割り切る (正準に近い形)
            (q0, c0), = den.terms.items()
            num, den = num.shift(q0).scale(1 / c0), Poly.const(1)
        r = _ratio_rational(num, den)
        if r is not None:
            num, den = Poly.const(r), Poly.const(1)
        self.num, self.den = num, den

    @staticmethod
    def of(value):
        if isinstance(value, Ratio):
            return value
        if isinstance(value, (int, _Q)) and not isinstance(value, bool):
            return Ratio(Poly.const(value))
        return None

    def rational(self):
        return _ratio_rational(self.num, self.den)

    def __add__(self, other):
        o = Ratio.of(other)
        return NotImplemented if o is None else Ratio(self.num * o.den + o.num * self.den, self.den * o.den)

    __radd__ = __add__

    def __neg__(self):
        return Ratio(self.num.scale(-1), self.den)

    def __sub__(self, other):
        o = Ratio.of(other)
        return NotImplemented if o is None else self + (-o)

    def __rsub__(self, other):
        o = Ratio.of(other)
        return NotImplemented if o is None else o + (-self)

    def __mul__(self, other):
        o = Ratio.of(other)
        return NotImplemented if o is None else Ratio(self.num * o.num, self.den * o.den)

    __rmul__ = __mul__

    def __truediv__(self, other):
        o = Ratio.of(other)
        return NotImplemented if o is None else Ratio(self.num * o.den, self.den * o.num)

    def __rtruediv__(self, other):
        o = Ratio.of(other)
        return NotImplemented if o is None else o / self

    def __bool__(self):
        return not self.num.zero

    def __eq__(self, other):
        o = Ratio.of(other)
        return o is not None and self.num * o.den == o.num * self.den

    def __hash__(self):
        r = self.rational()
        return hash(r) if r is not None else hash(("ratio", len(self.num.terms), len(self.den.terms)))

    def sign(self):
        """形で 0 なら 0、そうでなければ精度を上げて符号を決める (0 でない値は必ず決まる)。"""
        if self.num.zero:
            return 0
        bits = 64
        while True:
            lo, hi = _enclose_ratio(self.num, self.den, bits)
            if lo is not None and (lo > 0 or hi < 0):
                return 1 if lo > 0 else -1
            bits *= 2

    def _cmp(self, other):
        o = Ratio.of(other)
        return None if o is None else (self - o).sign()

    def __lt__(self, other):
        s = self._cmp(other)
        return NotImplemented if s is None else s < 0

    def __le__(self, other):
        s = self._cmp(other)
        return NotImplemented if s is None else s <= 0

    def __gt__(self, other):
        s = self._cmp(other)
        return NotImplemented if s is None else s > 0

    def __ge__(self, other):
        s = self._cmp(other)
        return NotImplemented if s is None else s >= 0

    def exact_real(self):
        from .f import _div, _r
        r = self.rational()
        if r is not None:
            return _r(r)
        return _div(self.num.exact_real(), self.den.exact_real())

    def __repr__(self):
        return f"Ratio({self.num.terms!r} / {self.den.terms!r})"


def joint(spec):
    """採用された信念の同時の確率 q_i = W_i / Z (Ratio の列、並びの状態の順)。考える側の出発点 (F-a の initial_joint)。"""
    W, Z = weights(spec)
    return tuple(Ratio(w, Z) for w in W)


def _outward(lo, hi, bits):
    scale = 1 << bits
    return _Q((lo.numerator * scale) // lo.denominator, scale), _Q(-((-hi.numerator * scale) // hi.denominator), scale)


def _exp_neg(q, bits):
    """exp(−q) (q ≥ 0 の有理数) を含む有理数の区間。幅はおよそ 2^−bits 以下 (外向きの丸め)。"""
    if not q:
        return _Q(1), _Q(1)
    if q < 0:   # exp(|q|) = 1 / exp(−|q|)
        lo, hi = _exp_neg(-q, bits + 8)
        return 1 / hi, 1 / lo
    k, y = 0, _Q(q)
    while y > _Q(1, 2):
        y, k = y / 2, k + 1
    w = bits + 2 * k + 16
    total, term, i = _Q(1), _Q(1), 0
    eps = _Q(1, 1 << w)
    while True:
        i += 1
        term = term * y / i
        if term < eps:
            break
        total += -term if i % 2 else term
    lo, hi = _outward(max(total - term, _Q(0)), total + term, w)   # 交代級数: 誤差は次の項以下
    for _ in range(k):
        lo, hi = _outward(lo * lo, hi * hi, w)
    return lo, hi


def _ratio_rational(n, d):
    """n / d が有理数なら、その値 (n = r·d が形で成り立つ時だけ)。"""
    if n.zero:
        return _Q(0)
    q0 = next(iter(d.terms))
    if q0 not in n.terms:
        return None
    r = n.terms[q0] / d.terms[q0]
    return r if n == d.scale(r) else None


# --- 件数の法則 (決定 1・2・4・7) ---

def _poisson_matrix(x, C, kernel=None):
    """件数の分け方 0..C (C は「C 以上」) の上の推移 (kernel=None は時間 x の発展、kernel=(c, taken) は一様の判定時刻の
    取得区間の核)。x = 率 × 経過時間 (有理数)。[行 j][列 k] の Poly。"""
    m = [[Poly() for _ in range(C + 1)] for _ in range(C + 1)]
    fact = [1]
    for i in range(1, C + 2):
        fact.append(fact[-1] * i)

    def p(n):   # e^{−x} x^n / n!
        return Poly({x: x ** n / fact[n]})

    def survive(n0):   # P(n ≥ n0) = 1 − Σ_{n<n0} e^{−x} x^n / n!
        return Poly.const(1) - sum((p(n) for n in range(n0)), Poly())

    def s1(n0):   # Σ_{n≥n0} e^{−x} x^n / (n+1)! (n0 ≥ 1)。x = 0 は 0 (別の厳密な枝)
        if not x:
            return Poly()
        return Poly({_Q(0): 1 / x}) - sum((p(i) for i in range(n0 + 1)), Poly()).scale(1 / x)

    for k in range(C):
        for j in range(k, C):
            n = j - k
            if kernel is None:
                m[j][k] = p(n)
            else:
                c, taken = kernel
                count = max(0, j - max(k, c + 1) + 1) if taken else max(0, min(j, c) - k + 1)
                m[j][k] = p(n).scale(_Q(count, n + 1))
        n0 = C - k
        if kernel is None:
            m[C][k] = survive(n0)
        else:
            c, taken = kernel
            m[C][k] = survive(n0) - s1(n0).scale(max(0, c + 1 - k)) if taken else s1(n0).scale(max(0, c - k + 1))
    m[C][C] = Poly.const(1) if kernel is None or kernel[1] else Poly()
    return m


def _apply(m, v):
    return [sum((m[j][k] * v[k] for k in range(len(v)) if not v[k].zero and not m[j][k].zero), Poly())
            for j in range(len(m))]


def _source_factor(unit, symbol):
    """1 回の取得の結果の、状態と件数に依らない因子 (K38 決定 2・K38-c ②・K38-d)。正規化された 1 つの表:
    つながっていない c / つながっていて呼んだ後の故障 (1−c)·p / つながっていて taken・empty (1−c)·(1−p)·(件数の核)。
    宣言の無い核は確率 0 として表に入る (c = 0・p = 0 を宣言したのと同じ答え)。2 つの法則が同じこの 1 か所を使う。"""
    c, p = unit["disconnection"] or 0, unit["failure"] or 0
    return c if symbol == _MISSING else (1 - c) * (p if symbol == _UNAVAILABLE else 1 - p)


def _poisson(unit, entries, terminal_ns, C):
    law = unit["law"]
    rate, origin, scale = law["rate"], law["origin_ns"], law["time_unit"]
    v = [Poly() for _ in range(C + 1)]
    v[min(law["initial_count"], C)] = Poly.const(1)
    t = _Q(0)
    for e in entries:
        if e["kind"] == "step":
            v = [x.scale(e["factors"][unit["index"]]) for x in v]
            continue
        b, a = (e["before_ns"] - origin) * scale, (e["after_ns"] - origin) * scale
        v = _apply(_poisson_matrix(rate * (b - t), C), v)
        # 源の件数を読まない取得は件数を after まで進めるだけ、読む取得は一様の判定時刻の核。どちらも状態に依らない因子を掛ける
        kernel = None if e["symbol"] in _UNREAD else (e["cursor"], e["symbol"] == "taken")
        v = [x.scale(_source_factor(unit, e["symbol"])) for x in _apply(_poisson_matrix(rate * (a - b), C, kernel), v)]
        t = a
    return _apply(_poisson_matrix(rate * ((terminal_ns - origin) * scale - t), C), v)


def _finite(unit, entries, terminal_ns, C):
    """決まった時刻に高々 1 件ずつ届く法則 (決定 7): 届き方の組ごとに、取得区間の中で判定が成り立つ長さの割合を掛ける。"""
    law = unit["law"]
    v = [Poly() for _ in range(C + 1)]
    for path, weight in zip(law["paths"], law["weights"]):
        times = [pos for pos, bit in zip(law["positions_ns"], path) if bit]

        def count(u):
            return law["initial_count"] + sum(1 for pos in times if pos <= u)
        value = weight
        for e in entries:
            if not value:
                break
            if e["kind"] == "step":
                value *= e["factors"][unit["index"]]
                continue
            value *= _source_factor(unit, e["symbol"])
            if e["symbol"] in _UNREAD:
                continue
            b, a, c, taken = e["before_ns"], e["after_ns"], e["cursor"], e["symbol"] == "taken"
            if a == b:
                share = _Q(int((count(b) > c) == taken))
            else:
                cuts = [b, *(pos for pos in times if b < pos <= a), a]
                share = sum((_Q(r - l) for l, r in zip(cuts, cuts[1:]) if (count(l) > c) == taken), _Q(0)) / (a - b)
            value *= share
        if value:
            v[min(count(terminal_ns), C)] += Poly.const(value)
    return v


def classes(spec, need=0):
    """正本 spec ({units, entries, terminal_ns}) から、状態ごとの件数の分け方 0..C の重み (事前を掛ける前) と C。"""
    cursors = [e["cursor"] for e in spec["entries"] if e["kind"] == "acquisition"]
    C = max([*(c + 1 for c in cursors), need + 1, 1])
    run = {"poisson": _poisson, "finite": _finite}
    return C, [run[u["law"]["kind"]](u, spec["entries"], spec["terminal_ns"], C) for u in spec["units"]]


def weights(spec):
    """状態ごとの正規化する前の重み W_i = 事前_i × L_i と、証拠の質量 Z。"""
    _C, vs = classes(spec)
    W = [sum(v, Poly()).scale(u["prior"]) for u, v in zip(spec["units"], vs)]
    return W, sum(W, Poly())


# --- 正本を作る (入口 U が使う) ---

def unit_law(law, state):
    """法則の状態 state の件数の法則を正本の形 (dict) にする。対応していない法則は None。"""
    i = law.states.index(state)
    if isinstance(law, _fb.PoissonLaw):
        out = {"kind": "poisson", "rate": law.rates[i], "origin_ns": law.origin_ns, "time_unit": law.time_unit,
               "initial_count": law.initial_count}
    elif isinstance(law, _fb.FiniteCountLaw):
        out = {"kind": "finite", "origin_ns": law.origin_ns, "initial_count": law.initial_count,
               "positions_ns": law.positions_ns, "paths": law.paths, "weights": law.weights_by_state[i]}
    else:
        return None
    return out


def encode_spec(spec):
    def unit(u):
        return {**{k: v for k, v in u.items() if k not in ("law", "prior", "failure", "disconnection")},
                "prior": _f._encode(u["prior"]), "failure": None if u["failure"] is None else _f._encode(u["failure"]),
                "disconnection": None if u["disconnection"] is None else _f._encode(u["disconnection"]),
                "law": {k: _f._encode(v) for k, v in u["law"].items()}}

    def entry(e):
        return {k: ([_f._encode(x) for x in v] if k == "factors" else v) for k, v in e.items()}
    return {"units": [unit(u) for u in spec["units"]], "entries": [entry(e) for e in spec["entries"]],
            "terminal_ns": spec["terminal_ns"]}


def decode_spec(value):
    def q(x):
        return _f._decode(x, _Q)

    def law(raw):
        out = dict(raw)
        for key in ("rate", "time_unit"):
            if key in out:
                out[key] = q(out[key])
        if "weights" in out:
            out["weights"] = tuple(q(x) for x in out["weights"])
            out["paths"] = tuple(tuple(p) for p in out["paths"])
        return out
    units = [{**u, "prior": q(u["prior"]), "failure": None if u["failure"] is None else q(u["failure"]),
              "disconnection": None if u["disconnection"] is None else q(u["disconnection"]),
              "law": law(u["law"])} for u in value["units"]]
    entries = [{**e, **({"factors": [q(x) for x in e["factors"]]} if e["kind"] == "step" else {})}
               for e in value["entries"]]
    return {"units": units, "entries": entries, "terminal_ns": value["terminal_ns"]}


def result(spec, root, observations):
    """R* の値 (`sui.fb.timed_update_result/1`): 正本と、根と、適用した原記録の Point と、証拠の質量の正準な形。"""
    _W, Z = weights(spec)
    return {"contract": _f._encode(_c().TIMED_UPDATE_RESULT), "root": root, "observations": list(observations),
            **encode_spec(spec), "mass": Z.encode()}


def is_result(value) -> bool:
    """R* の値が時刻を読む信念の正本か (旧い有限の結果 finite_update_result/1 と分ける)。"""
    from .f_update2 import _json
    return hasattr(value, "get") and _json(value.get("contract")) == _f._encode(_c().TIMED_UPDATE_RESULT)


def _c():
    from . import fb_contracts
    return fb_contracts


# --- 照会 (決定 5・6) ---

def _quantity(spec, quantity):
    """照会する量の (分子, 分母) の Poly。分母は証拠の質量 Z (mass は分母 1)。"""
    kind = quantity.kind
    units = spec["units"]
    if kind == "mass":
        return weights(spec)[1], Poly.const(1)
    if kind == "count":
        if type(quantity.count) is not int or quantity.count < 0:
            raise _fb.TimeBeliefError(kind="invalid", reason="count must be a non-negative int", field="count")
        C, vs = classes(spec, quantity.count + 1)
        keep = [i for i, u in enumerate(units) if (quantity.state is None or u["state"] == quantity.state)
                and (quantity.candidate is None or u["candidate"] == quantity.candidate)]
        k = quantity.count
        n = sum(((sum(vs[i][k:], Poly()) if quantity.at_least else vs[i][k]).scale(units[i]["prior"])
                 for i in keep), Poly())
        Z = sum((sum(v, Poly()).scale(u["prior"]) for u, v in zip(units, vs)), Poly())
        return n, Z
    W, Z = weights(spec)
    key = {"state": "state", "candidate": "candidate"}.get(kind)
    target = quantity.state if kind == "state" else quantity.candidate
    if key is None or target not in {u[key] for u in units}:
        raise _fb.TimeBeliefError(kind="invalid", reason="unknown quantity", field=kind)
    return sum((w for w, u in zip(W, units) if u[key] == target), Poly()), Z


def query(spec, root, quantity, budget):
    """照会の答え (BeliefValue)。分母 Z が形で 0 なら model_falsified (採用された信念には起きない)。精度は 2^−64 から倍に
    していき、幅が budget.tolerance 以下になった所で返す。max_refinements の回数で届かなければ incomplete (モデルの誤り
    ではない)。"""
    n, d = _quantity(spec, quantity)
    if d.zero:
        raise _fb.TimeBeliefError(kind="model_falsified", reason="the evidence mass is structurally zero")
    exact = _ratio_rational(n, d)
    if exact is not None:
        return _fb.BeliefValue(root=root, quantity=quantity, lower=exact, upper=exact, exact=exact,
                               proof=_f._freeze({"exact": True}))
    tolerance, limit = budget.tolerance, budget.max_refinements
    bits, rounds = 64, 0
    while True:
        lo, hi = _enclose_ratio(n, d, bits)
        if lo is not None and hi - lo <= tolerance:
            return _fb.BeliefValue(root=root, quantity=quantity, lower=lo, upper=hi, exact=None,
                                   proof=_f._freeze({"precision_bits": bits}))
        rounds += 1
        if limit is not None and rounds > limit:
            raise _fb.TimeBeliefError(kind="incomplete", reason="precision not reached within the budget")
        bits *= 2


def _enclose_ratio(n, d, bits):
    nl, nh = n.enclose(bits)
    dl, dh = d.enclose(bits)
    if dl <= 0:
        return None, None
    values = (nl / dl, nl / dh, nh / dl, nh / dh)
    return _outward(min(values), max(values), bits + 8)


def contains(spec, quantity, lower, upper) -> bool:
    """[lower, upper] が真の値を含むか (根から作り直して決める。端点が真の値に等しいかは形で確かめる)。"""
    n, d = _quantity(spec, quantity)
    if d.zero or lower > upper:
        return False
    exact = _ratio_rational(n, d)
    if exact is not None:
        return lower <= exact <= upper
    bits = 64
    while True:
        lo, hi = _enclose_ratio(n, d, bits)
        if lo is not None:
            if lower <= lo and hi <= upper:
                return True
            if hi < lower or upper < lo:
                return False
        bits *= 2


def step_reading_fault(declaration, kid):
    """行う一歩の宣言で、核 kid の一歩が E_y(s) ⊗ I_N と宣言されているか (K38 決定 9)。時刻を読む一歩の宣言
    (TimedExecutionDeclaration) で、その核の源の件数の読みが無い・干渉すると宣言されていれば理由の語、それ以外は None。
    実行の前 (`_fb_act.classify`)・起動 (`_fb_boot.execution_reading_fault`) が同じこの判定を使い、更新 (入口 U) は保存した
    宣言から読んだ同じ読みを `noninterfering` で照らす。"""
    if not isinstance(declaration, _fb.TimedExecutionDeclaration):
        return None
    reading = declaration.source_readings.get(kid)
    if not isinstance(reading, _fb.SourceCountReading):
        return "source_reading_missing"
    return None if noninterfering(reading) else "source_reading_interferes"


def noninterfering(reading) -> bool:
    """一歩の結果の核が E_y(s) ⊗ I_N の形と宣言されているか (K38 決定 9・K38-c ③): 結果が S を条件に源の件数と独立で、
    件数を動かさない。行列の値は宣言に持たない (値の出どころはモデルの核の 1 か所)。S の上で対角なことは核の側で確かめる。"""
    return reading.independent_of_count is True and reading.count_shift == 0


# --- ホストの読む口 (決定 5) ---

def _json(value):
    from .f_update2 import _json as plain
    return plain(value)


class _InputsReader:
    """保存した更新要求 Q* が申告した入力 (と Q* 自身) だけを読む読み手 (入口 U の作り直しと同じ範囲)。"""

    def __init__(self, ledger, allowed):
        self._ledger, self._allowed = ledger, frozenset(allowed)

    def record(self, cid):
        if cid not in self._allowed:
            raise KeyError(cid)
        return self._ledger.record(cid)


def _saved(state, point):
    """保存した R* の時刻を読む信念の正本を、その更新要求 Q* から入口 U と同じ作り直しで導き直し、保存した結果・根と全比較
    して認証した値 (K38-b R5: 照会・数の証明の検査・同じ信念の判定は、保存した R* の自己申告を信じない)。読めない・時刻を読む
    信念でない・作り直しと違う時は TimeBeliefError。"""
    from . import fb_contracts as c
    from . import f_update2 as u
    try:
        record = state.ledger.record(point)
    except (KeyError, TypeError):
        raise _fb.TimeBeliefError(kind="unavailable", reason="the belief record is not readable", targets=(point,)) from None
    saved = _json(record.body.content.as_json()) if record.body.contract == c.UPDATE_RESULT else {}
    if not is_result(saved.get("result")):
        raise _fb.TimeBeliefError(kind="unsupported", reason="not a timed belief", targets=(point,))
    request = saved.get("request")
    try:
        desc = _json(state.ledger.record(request).body.content.as_json())["desc"]
        reader = _InputsReader(state.ledger, {request, *desc["input_points"]})
        derived = u._replay(reader, request)
        model, origin = desc["args"]["model"], desc["reader"]
        value = _json(u._encode_result(derived, model, origin))
    except u._Issue as issue:
        raise _fb.TimeBeliefError(kind="model_falsified" if issue.code == "model_falsified" else "unavailable",
                                  reason=issue.code, targets=(point, request)) from None
    except (KeyError, TypeError):
        raise _fb.TimeBeliefError(kind="unavailable", reason="the belief's request is not readable",
                                  targets=(point,)) from None
    if derived.mode != "timed" or not u.saved_matches(saved, request, derived, model, origin):
        raise _fb.TimeBeliefError(kind="invalid", reason="the saved belief differs from its recomputation",
                                  targets=(point,))
    return value


_STOP_KINDS = {"model_falsified": "model_falsified", "missing_contract": "unsupported"}


def belief_expression(state, boot, boundary):
    from . import _fb_pool, _fb_update
    with state.lock:
        try:
            plan = _fb_pool._boot(state, boot)
            seen = _fb_pool._seen(state, boundary)
            pool = _fb_pool.resolve(state, plan, boundary)
        except (_fb.CandidateInputError, _fb.CandidatePoolError) as exc:
            raise _fb.TimeBeliefError(kind="unavailable", reason=exc.reason,
                                      targets=getattr(exc, "targets", ())) from None
        update = next((p for p in state.updates.values() if p.boot is plan), None)
        if update is None:
            raise _fb.TimeBeliefError(kind="unavailable", reason="no belief update plan", targets=(boot,))
        stop = _fb_update.pool_stop(state, update, pool, seen)
        if stop is not None:
            # 名指しは記録の Point と、その Point を持つ候補の名前 (読めない候補を黙って外さない、決定 10)
            named = tuple(m["id"] for m in pool.members if m["model"] in stop[1])
            raise _fb.TimeBeliefError(kind=_STOP_KINDS.get(stop[0], "unavailable"), reason=stop[0],
                                      targets=(*stop[1], *named))
        head = _fb_update.pool_head(update, pool, seen)
        if head is None:
            raise _fb.TimeBeliefError(kind="unavailable", reason="no adopted belief yet", targets=(pool.point,))
        result = _json(state.ledger.record(head).body.content.as_json())["result"]
        value = _saved(state, result)
        return _fb.BeliefExpression(point=result, root=value["root"], model=pool.model, pool=pool.point,
                                    adoption=head, result=result, observations=tuple(value["observations"]),
                                    terminal_ns=value["terminal_ns"])


def _spec(state, belief):
    value = _saved(state, belief.point)
    if value["root"] != belief.root:
        raise _fb.TimeBeliefError(kind="invalid", reason="the expression's root differs from its record",
                                  targets=(belief.point,))
    return decode_spec(value)


def query_belief(state, belief, quantity, budget):
    if not isinstance(quantity, _fb.BeliefQuantity):
        raise _fb.TimeBeliefError(kind="invalid", reason="BeliefQuantity required", field="quantity")
    with state.lock:
        spec = _spec(state, belief)
    return query(spec, belief.root, quantity, budget)


def verify_belief_value(state, belief, value) -> bool:
    if not isinstance(value, _fb.BeliefValue) or value.root != belief.root:
        return False
    with state.lock:
        try:
            spec = _spec(state, belief)
        except _fb.TimeBeliefError:
            return False
    if not (isinstance(value.lower, _Q) and isinstance(value.upper, _Q)):
        return False
    if value.exact is not None and not value.lower == value.exact == value.upper:
        return False
    return contains(spec, value.quantity, value.lower, value.upper)


def same_belief(state, left, right) -> bool:
    with state.lock:
        _spec(state, left), _spec(state, right)
    return left.root == right.root


def query_selection(state, selection, budget):
    """選択が使った評価の情報量・G・方策の確率を、保存した厳密式から精度 budget.tolerance 以下の幅で包む (決定 5)。
    belief_root はその評価の出発点の採用が指す時刻を読む信念の根。"""
    from . import f_contracts as fc, fb_contracts as c
    from .f_entry import f_from_json
    with state.lock:
        try:
            chosen = state.ledger.record(selection)
            if chosen.body.contract != c.SELECTION:
                raise KeyError(selection)
            evaluated = state.ledger.record(_json(chosen.body.content.as_json())["evaluated"])
            artifact = state.ledger.record(_json(evaluated.body.content.as_json())["artifact"])
            value = f_from_json(_f._dumps(_json(artifact.body.content.as_json())["claim"]), contract=fc.VALUE_FACTS)
        except (KeyError, TypeError, _f.FInputError):
            raise _fb.TimeBeliefError(kind="invalid", reason="not a saved selection", targets=(selection,)) from None
        belief = value.root.K.belief
        entries = state.ledger.entries_of(belief) if belief is not None else ()
        if len(entries) != 1:
            raise _fb.TimeBeliefError(kind="unsupported", reason="the evaluation did not start from a timed belief",
                                      targets=(selection,))
        root = _saved(state, entries[0].cid)["root"]
    evaluation = value.evaluation
    groups = ([i.total_information for i in evaluation.information], evaluation.G, evaluation.q_star)
    enclosed = tuple(tuple(_enclose_expression(q, budget) for q in group) for group in groups)
    return _fb.SelectionValues(belief_root=root, candidates=evaluation.candidates, information=enclosed[0],
                               G=enclosed[1], probabilities=enclosed[2], proof=_f._freeze({"evaluation": selection}))


def _enclose_expression(quantity, budget):
    """F-a の厳密式を、幅 budget.tolerance 以下の有理数の区間で包む (精度を上げていく。回数は max_refinements まで)。"""
    if quantity.exact is None:
        raise _fb.TimeBeliefError(kind="incomplete", reason="the evaluation value has no exact expression")
    precision, rounds = budget.tolerance / 4, 0
    while True:
        try:
            bounds = _f._ExpressionWork(budget, precision=precision).enclose(quantity.exact)
        except _f._EnclosureShort:   # 端点を分けられない囲みは精度の不足 (下で精度を上げる)
            bounds = None
        except _f.FIncomplete as exc:
            raise _fb.TimeBeliefError(kind="incomplete", reason=exc.reason) from None
        if bounds is not None and bounds.upper - bounds.lower <= budget.tolerance:
            return bounds
        rounds += 1
        if budget.max_refinements is not None and rounds > budget.max_refinements:
            raise _fb.TimeBeliefError(kind="incomplete", reason="precision not reached within the budget")
        precision /= 16
