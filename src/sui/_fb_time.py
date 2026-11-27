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

時計の部品 (紙 F-b K40): 時計のオンの枝の unit の法則は時計の形 (周期・区切りの始まり・倍率) を持ち、件数の発展は累積の率
で、取得区間の核は区切りの境目で判定時刻の積分を分けて足す (`_poisson`・`_read`)。時計の形が点の事前なら、ここまで全部が
有理数の係数と指数の指数多項式のまま厳密。

スイッチの族 (紙 F-b K39): units は (候補, スイッチの列 z, 状態) ごとで、z を当てた後の率と P(z) を掛けた事前を持つ (枝と
状態の対応は候補の解決 `f_update2.describe_candidate`)。z は取得ごとに引き直さない (同じ unit の率で列全体を読む)。
スイッチと p の照会は候補 M に条件づける (`_conditional`、公開の口は `FThreadHost.query_switch_belief`・`p_distribution`・
`verify_p_distribution`)。候補の解決の公開の口は `fb.resolve_belief_candidates` (`resolve_public`)。
"""

from fractions import Fraction as _Q
from functools import lru_cache as _lru_cache

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
        if not isinstance(other, Poly):
            return NotImplemented
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


def joint(spec, at_ns=None):
    """採用された信念の同時の確率 q_i = W_i / Z (並びの状態の順)。考える側の出発点 (F-a の initial_joint)。

    時計の連続の事前の unit を含む正本では、q_i は積分を含む比 (`IntegralRatio`) で、連続の事前の unit の重みは、積分が
    指数多項式に閉じる時 (回転だけ連続・尤度が θ によらない) も積分の項のまま持つ (K40 決定 12: θ を積分した有限の重みだけを
    渡さない)。考える側は同じ項の上で、評価の仮の結果を条件に付けて I(Q; Y | h) を直接評価する (`information`)。F-a の厳密式へは
    版つきの積分の式 (ExactReal の integral) として写る。連続の事前の unit が無ければ指数多項式の比 (`Ratio`)。"""
    if at_ns is not None and spec["terminal_ns"] is not None and at_ns > spec["terminal_ns"]:
        # 考える側の評価の根 j (K41 決定 6): 採用済みの終端から j まで無観測で進める (静的な unit の質量は変わらない)
        spec = {**spec, "terminal_ns": at_ns}
    _C, vs = classes(spec)
    space = _space(spec)

    def mass(i, u):   # 積分・鎖の unit は積分の項のまま (畳まない、K40 決定 12)
        if continuous(u) or chained(u):
            return Form(Poly(), {(i, None): _Q(1)} if space.integral(i, None).positive() else {}, space)
        return sum(vs[i], Poly())
    W = [_weighted(u, mass(i, u)) for i, u in enumerate(spec["units"])]
    Z = sum(W, Poly())
    if not any(isinstance(x, Form) for x in W):
        return tuple(Ratio(w, Z) for w in W)
    return tuple(IntegralRatio(w, Z) for w in W)


class IntegralRatio:
    """積分を含む比 num / den (Form、den は形で 0 でない)。時計の連続の事前の信念の確率を考える側へ渡す数 (K40 決定 12)。
    F-a の評価が使う演算だけを持つ: 有理数との四則、同じ分母どうしの和・差・比 (仮の結果で条件づけた共同の信念は、同じ分母の
    W_i の一次結合のまま)。それ以外の組み合わせは名指して止まる。0 の判定は形 (項の積分は正と証明済み)、比較の符号は決定 12 の
    4 つの区別: 形で 0 / 形で正 (項の係数と指数多項式の係数が全部正) / 上下界で分けられた / 予算の中で分けられない
    (`FIncomplete`)。F-a の厳密式へは `exact_real` (版つきの積分の式)。"""
    __slots__ = ("num", "den")

    def __init__(self, num, den):
        num, den = _as_form(num), _as_form(den)
        if den.zero:
            raise ZeroDivisionError("structurally zero denominator")
        self.num, self.den = num, den

    @staticmethod
    def of(value):
        if isinstance(value, IntegralRatio):
            return value
        if isinstance(value, Ratio):
            return IntegralRatio(value.num, value.den)
        if isinstance(value, (int, _Q)) and not isinstance(value, bool):
            return IntegralRatio(Poly.const(value), Poly.const(1))
        return None

    def _constant(self):
        return _form_rational(self.num, self.den)

    def _join(self, other, op):
        o = IntegralRatio.of(other)
        if o is None:
            return NotImplemented
        if self.den == o.den:
            return IntegralRatio(op(self.num, o.num), self.den)
        r = o._constant()
        if r is not None:
            return IntegralRatio(op(self.num, self.den.scale(r)), self.den)
        r = self._constant()
        if r is not None:
            return IntegralRatio(op(o.den.scale(r), o.num), o.den)
        return _unsupported()

    def __add__(self, other):
        return self._join(other, lambda a, b: a + b)

    __radd__ = __add__

    def __sub__(self, other):
        return self._join(other, lambda a, b: a - b)

    def __rsub__(self, other):
        return (-self) + other

    def __neg__(self):
        return IntegralRatio(self.num.scale(-1), self.den)

    def __mul__(self, other):
        o = IntegralRatio.of(other)
        if o is None:
            return NotImplemented
        r = o._constant()
        if r is not None:
            return IntegralRatio(self.num.scale(r), self.den)
        r = self._constant()
        if r is not None:
            return IntegralRatio(o.num.scale(r), o.den)
        return _unsupported()

    __rmul__ = __mul__

    def __truediv__(self, other):
        o = IntegralRatio.of(other)
        if o is None:
            return NotImplemented
        if self.den == o.den:
            return IntegralRatio(self.num, o.num)
        r = o._constant()
        if r is not None:
            return IntegralRatio(self.num.scale(1 / r), self.den)
        return _unsupported()

    def __rtruediv__(self, other):
        o = IntegralRatio.of(other)
        return NotImplemented if o is None else o / self

    def __bool__(self):
        return not self.num.zero

    def __eq__(self, other):
        """形で等しいか (同じ分母か有理数との比較だけを形で決める。決められない時は False = 等しいと証明していない)。"""
        o = IntegralRatio.of(other)
        if o is None:
            return False
        if self.den == o.den:
            return self.num == o.num
        r = o._constant()
        return r is not None and self.num == self.den.scale(r)

    __hash__ = None

    def sign(self):
        return _sign(self.num) * _sign(self.den)

    def _cmp(self, other):
        o = IntegralRatio.of(other)
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
        r = self._constant()
        if r is not None:
            return _r(r)
        return _div(_form_exact(self.num), _form_exact(self.den))

    def __repr__(self):
        return f"IntegralRatio({self.num.poly.terms!r} + {self.num.leaves!r} / {self.den.poly.terms!r} + {self.den.leaves!r})"


def _unsupported():
    from .f import FSpecificationMissing
    raise FSpecificationMissing("missing_contract", "clock_integral_product")


_SIGN_REGIONS = 1 << 14


def _sign(form):
    """Form の符号 (決定 12 の比較の区別)。形で 0 → 0、形で正・負 (積分の項は正と証明済みなので、全部の係数が同じ符号) → ±1、
    そうでなければ上下界を細かくして分ける (箱を倍にする回ごとに数の精度も上げる、`_fb_clock.precision_bits`)。_SIGN_REGIONS の
    箱で分けられなければ FIncomplete (未証明の比較)。"""
    if form.zero:
        return 0
    signs = {c > 0 for c in form.leaves.values()} | {c > 0 for c in form.poly.terms.values()}
    if len(signs) == 1 and (not form.poly.terms or form.leaves):
        return 1 if signs.pop() else -1
    integrals = _integrals(form)
    regions, rounds = _first_level(), 0
    while regions <= _SIGN_REGIONS:
        lo, hi = _enclose_form(form, integrals, _num(None, rounds), regions)
        if lo is not None and (lo > 0 or hi < 0):
            return 1 if lo > 0 else -1
        regions, rounds = regions * 2, rounds + 1
    from .f import FIncomplete
    raise FIncomplete("certificate_incomplete", "clock_integral_comparison_unproven")


def _form_exact(form):
    """Form を F-a の厳密式に: 指数多項式 + Σ c · (版つきの積分の式)。"""
    from .f import ExactReal, _add, _mul, _r
    form = _as_form(form)
    terms = [form.poly.exact_real()] if not form.poly.zero else []
    for (i, selector), c in sorted(form.leaves.items(), key=lambda x: _f._dumps(x[0])):
        terms.append(_mul(_r(c), ExactReal(op="integral", formula=form.space.formula(i, selector))))
    return _add(*terms) if terms else _r(0)


INTEGRAL_FORMULA = {"name": "sui.fb.clock_integral", "version": "1"}   # 積分の式の版 (契約の名前と版の形)


CHAIN_FORMULA = {"name": "sui.fb.state_chain_mass", "version": "1"}
CHAIN_INFORMATION_FORMULA = {"name": "sui.fb.state_chain_information", "version": "1"}   # 遷移のある群の情報量の積分の式の版   # 遷移のある群の unit の質量の式の版 (K41 決定 4)


INFORMATION_FORMULA = {"name": "sui.fb.clock_information", "version": "1"}   # 情報量の積分の式の版


def information(labels, cells):
    """一歩の情報量 I(Q; Y | h) = H(Y | h) − E[H(Y | Q, h)] の厳密式 (紙 F-b K40 決定 8・K40-g)、または None。cells は一歩の結果の
    類 y ごとの正規化しない共同の信念 (並びの状態の順の列)、labels は状態の知る対象。知る対象 Q は、θ を持たない状態では状態の
    知る対象、時計の連続の事前の unit では (θ, 知る対象) (解決した法則が θ ごとに違う。θ の別名は同じ尤度・同じ状態の比を
    持つので、P(Y | Q, h) は θ 1 点の値で読める)。同じ Q の状態を θ ごとにまとめた P(Y | Q, h) が θ によらないと構造から言える
    類しか無い時は None で、呼ぶ側の有限の重みの形 H(Q) − Σ_y P(y) H(Q | y) がそのまま同じ値 (評価器の特別な場合)。そうでなければ
    類ごとの E[H(Y | Q, h)] を足し、θ に依る類は情報量の積分 (`_fb_clock.Information`、版つきの式) の項にする。"""
    split = _split(labels, cells)
    if split is None or all(entry["finite"] for entry in split[2].values()):
        return None
    from .f import ExactReal, _add, _div, _neg, _r
    den, space, classes = split
    n = len(cells)
    terms = []
    for entry in classes.values():
        atoms, groups = entry["atoms"], entry["groups"]
        if entry["finite"]:
            terms.append(_phi_exact([IntegralRatio(Form(atoms[y], {k: col[y] for g in groups.values() for k, col in g.items()},
                                                        space), den) for y in range(n)]))
            continue
        if any(not a.zero for a in atoms):   # θ を持たない状態 (別の法則): θ の類とは別の Q
            terms.append(_phi_exact([IntegralRatio(a, den) for a in atoms]))
        for group in groups.values():
            keys = sorted(group)
            if _flat(space, group):
                terms.append(_phi_exact([IntegralRatio(Form(Poly(), {k: group[k][y] for k in keys}, space), den)
                                         for y in range(n)]))
            else:
                matrix = [[group[k][y] for k in keys] for y in range(n)]
                integral = ExactReal(op="integral", formula=_information_formula(space, keys, matrix))
                terms.append(_div(integral, _form_exact(den)))
    masses = [sum(cell) for cell in cells]
    total = sum(masses)
    value = _add(_phi_exact(masses), _neg(_add(*terms)))
    return value if total == 1 else _div(value, _r(total))


def lumped(labels, joint) -> bool:
    """θ ごとにまとめた知る対象の分布が θ に依る類があるか (結果が状態を名指す一歩でも `information` が有限の形に落ちないか)。
    知る対象の周辺 (有限の重み) だけを持つ道 (路の表・尾の確かめ・吸収) が、そう言えない信念を受け取らないための判定。"""
    cells = [tuple(x if j == k else _Q(0) for j, x in enumerate(joint)) for k in range(len(joint))]
    split = _split(labels, cells)
    return split is not None and not all(entry["finite"] for entry in split[2].values())


def _split(labels, cells):
    """結果の類ごとの共同の信念を、知る対象の類ごとに、θ を持たない部分 (atoms: 類 y ごとの指数多項式) と、θ の空間ごとの積分の
    項の係数 (groups: 空間 → {項: 類 y ごとの係数}) に分ける。積分の項が無ければ None。finite は、その類の P(Y | Q, h) が θ に
    よらないと構造から言えるか (θ の空間が 1 つで θ を持たない部分が無く、`_flat`)。"""
    den = space = None
    classes = {}
    for y, cell in enumerate(cells):
        for i, x in enumerate(cell):
            if not isinstance(x, IntegralRatio):
                if x:
                    return None   # 有限の数 (Ratio・有理数) の信念
                continue
            if x.num.zero:
                continue
            if den is None:
                den = x.den
            elif not x.den == den:
                _unsupported()
            entry = classes.setdefault(labels[i], {"atoms": [Poly() for _ in cells], "groups": {}})
            entry["atoms"][y] = entry["atoms"][y] + x.num.poly
            for key, c in x.num.leaves.items():
                space = space or x.num.space
                law = space.spec["units"][key[0]]["law"]
                # θ の空間の識別 (時計の無い遷移の群の項は時計の欄を持たない、K41。θ に依らない項は `_flat` で有限の形へ)
                theta = _f._digest({k: _f._encode(law.get(k)) for k in ("clock", "origin_ns", "time_unit")})
                entry["groups"].setdefault(theta, {}).setdefault(key, [_Q(0)] * len(cells))[y] += c
    if space is None:
        return None
    for entry in classes.values():
        groups = entry["groups"]
        entry["finite"] = not groups or (len(groups) == 1 and all(a.zero for a in entry["atoms"])
                                         and _flat(space, next(iter(groups.values()))))
    return den, space, classes


def _flat(space, group):
    """θ の空間 1 つの項の組で、類 y ごとの量 c_y(θ) = Σ_k a_yk L_k(θ) が θ によらない比を持つと構造から言えるか: 全部の項の
    尤度が θ によらない (`Integral.blind`)、または係数の列 a_·k が全部比例 (c(θ) = (Σ_k λ_k L_k(θ)) · v)。"""
    if all(space.integral(*key).blind for key in group):
        return True
    columns = list(group.values())
    y0 = next(y for y, a in enumerate(columns[0]) if a)
    return all(col == [columns[0][y] * (col[y0] / columns[0][y0]) for y in range(len(col))] for col in columns)


def _phi_exact(cs):
    """Σ_y c_y log(Σc / c_y) (正規化しない条件つきのエントロピー) の厳密式。"""
    from .f import _add, _log, _mul, _r
    cs = [c for c in cs if c]
    s = sum(cs)
    return _add(*(_mul(_r(c), _log(s / c)) for c in cs))


def _information_formula(space, keys, matrix):
    """情報量の積分の版つきの式 (正準な JSON の文字列): θ の空間を共有する unit (法則・故障の核。事前は係数の側)・全原記録の
    参照・端の時刻・結果の類ごとの係数 (全部 0 の類は省く)。固定の読み手 (`_formula_integral`) がこれだけで作り直す。"""
    if any(chained(space.spec["units"][k]) for k, _selector in keys):
        # 遷移のある群の項 (K41 決定 8): 項は群の初期の事前を含むので、群の unit を事前つきで全部持ち、項は番号で名指す
        group = sorted({j for k, _selector in keys for j in space.spec["units"][k]["law"]["transitions"]["units"]})
        encoded = encode_spec({"units": [space.spec["units"][j] for j in group], "entries": space.spec["entries"],
                               "terminal_ns": space.spec["terminal_ns"]})
        return _f._dumps({**CHAIN_INFORMATION_FORMULA, "units": encoded["units"], "keys": [k for k, _s in keys],
                          "entries": encoded["entries"], "terminal_ns": space.spec["terminal_ns"],
                          "cells": [[_f._encode(a) for a in row] for row in matrix if any(row)]}).decode("utf-8")
    units = [{**space.spec["units"][k], "prior": _Q(1)} for k, _selector in keys]
    encoded = encode_spec({"units": units, "entries": space.spec["entries"], "terminal_ns": space.spec["terminal_ns"]})
    return _f._dumps({**INFORMATION_FORMULA,
                      "units": [{k: u[k] for k in ("index", "law", "failure", "disconnection")} for u in encoded["units"]],
                      "entries": encoded["entries"], "terminal_ns": space.spec["terminal_ns"],
                      "cells": [[_f._encode(a) for a in row] for row in matrix if any(row)]}).decode("utf-8")


def enclose_integral(formula, precision, budget, regions_cap=None):
    """F-a の厳密式 integral の値の上下界 (K40 決定 12): 版つきの式 (法則・事前・全原記録の参照・端の時刻・量) から積分を作り直し、
    箱を倍にして幅を precision 以下にする (None は 2^−20)。予算の箱の数 (max_cells、None は 2^16) で届かなければ、その時の
    上下界を返す (幅の不足は呼ぶ側の精度の確かめが incomplete にする)。数の精度は precision から決める (`_fb_clock.precision_bits`、
    正の量の下界が 0 から分けられなければ `_EnclosureShort` で、呼ぶ側が precision を細かくする)。上下界は (式, 精度, 予算) だけで
    決まる (`_fb_clock._Table.at` の段、F-a の評価を作り直すと同じ数になる)。F-a の評価の精度 (10^−24 から) は箱の数の上限で
    止まる。"""
    integral = _formula_integral(formula)
    target = _Q(1, 1 << 20) if precision is None else _Q(precision)
    cap = budget.max_cells if budget is not None and budget.max_cells is not None         else regions_cap or _EVALUATION_REGIONS
    from ._fb_clock import Num, precision_bits
    table = integral.table(Num(precision_bits(target)))   # この呼び出しだけの計算表 (段をまたいで使い直す)
    regions = _first_level()
    while True:
        lo, hi = table.at(regions)
        if hi - lo <= target or regions * 2 > cap:
            return lo, hi
        regions *= 2


def integral_sign(formula):
    """F-a の厳密式 integral の構造の符号 (K40 決定 12 の比較の「構造から証明した 0・正」): 被積分の量は非負で、内部の 1 点で
    形が 0 なら積分は 0、そうでなければ正 (`Integral.positive`、K38 決定 6)。"""
    return int(_formula_integral(formula).positive())


def _formula_integral(formula):
    """版つきの積分の式 (尤度の積分 `_Space.formula`、情報量の積分 `_information_formula`) から積分を作り直す。読めない式は
    F-a の入力の不正。情報量の積分は式の識別で控える (段ごとの上下界を F-a の評価の作り直しで使い直す)。"""
    import json
    from .f import FInputError
    try:
        value = json.loads(formula)
        if {k: value[k] for k in INFORMATION_FORMULA} == INFORMATION_FORMULA:
            key = _f._digest({"information": formula})
            found = _INTEGRALS.get(key)
            if found is None:
                from ._fb_clock import Information
                units = [{**u, "prior": [1, 1]} for u in value["units"]]
                space = _Space(decode_spec({"units": units, "entries": value["entries"],
                                            "terminal_ns": value["terminal_ns"]}))
                cells = [[_f._decode(a, _Q) for a in row] for row in value["cells"]]
                if len(_INTEGRALS) > 256:
                    _INTEGRALS.clear()
                found = _INTEGRALS[key] = Information([space.integral(k, None) for k in range(len(units))], cells)
            return found
        if {k: value.get(k) for k in CHAIN_INFORMATION_FORMULA} == CHAIN_INFORMATION_FORMULA:
            key = _f._digest({"information": formula})
            found = _INTEGRALS.get(key)
            if found is None:
                from ._fb_clock import Information
                space = _Space(_placed(value))
                cells = [[_f._decode(a, _Q) for a in row] for row in value["cells"]]
                if len(_INTEGRALS) > 256:
                    _INTEGRALS.clear()
                found = _INTEGRALS[key] = Information([space.integral(k, None) for k in value["keys"]], cells)
            return found
        if {k: value.get(k) for k in CHAIN_FORMULA} == CHAIN_FORMULA:
            selector = value["selector"]
            return _Space(_placed(value)).integral(value["unit"], None if selector is None else tuple(selector))
        if {k: value[k] for k in INTEGRAL_FORMULA} != INTEGRAL_FORMULA:
            raise KeyError("version")
        unit = {**value["unit"], "prior": [1, 1]}
        spec = decode_spec({"units": [unit], "entries": value["entries"], "terminal_ns": value["terminal_ns"]})
        selector = value["selector"]
        if selector is not None:
            selector = (selector[0], *(x if type(x) is int else _f._decode(x, _Q) for x in selector[1:]))
        return _Space(spec).integral(0, selector)
    except (KeyError, TypeError, ValueError, IndexError):
        raise FInputError("shape", "unreadable clock integral formula") from None


def _placed(value):
    """鎖の式 (群の unit だけを持つ) から正本を作り直す: 各 unit を自分の番号 index の位置に置く (群の unit の番号・一歩の因子の
    列は並び全体の番号のまま、K41)。群の外の位置は使わない。"""
    spec = decode_spec({"units": value["units"], "entries": value["entries"], "terminal_ns": value["terminal_ns"]})
    units = [None] * (max(u["index"] for u in spec["units"]) + 1)
    for u in spec["units"]:
        units[u["index"]] = u
    return {**spec, "units": units}


_EVALUATION_REGIONS = 1 << 12   # F-a の評価の中の積分の箱の数の上限 (予算の max_cells が無い時)


def _outward(lo, hi, bits):
    scale = 1 << bits
    return _Q((lo.numerator * scale) // lo.denominator, scale), _Q(-((-hi.numerator * scale) // hi.denominator), scale)


@_lru_cache(maxsize=1 << 14)
def _exp_neg(q, bits):
    """exp(−q) (q ≥ 0 の有理数) を含む有理数の区間。幅はおよそ 2^−bits 以下 (外向きの丸め)。同じ引数の値は控える (情報量の
    積分は格子の点の値を隣の区間・段で読み直す)。"""
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
    """固定の Poisson 源 (K38 決定 4) と、時計の倍率を持つ非一様の率 (K40 決定 6)。件数の発展は累積の率 x(t) = 率 × ∫c だけで
    決まり、取得区間の核は率が一定の小区間に分けて足す (`_read`)。時計が無ければ x(t) = 率 × t で、区間は分かれない。"""
    law = unit["law"]
    rate, origin, scale, clock = law["rate"], law["origin_ns"], law["time_unit"], law.get("clock")

    def x(s):
        return rate * _clock_integral(clock, s)
    v = [Poly() for _ in range(C + 1)]
    v[min(law["initial_count"], C)] = Poly.const(1)
    t = _Q(0)
    for e in entries:
        if e["kind"] == "step":
            v = [y.scale(e["factors"][unit["index"]]) for y in v]
            continue
        b, a = (e["before_ns"] - origin) * scale, (e["after_ns"] - origin) * scale
        v = _evolve(v, x(b) - x(t), C)
        # 源の件数を読まない取得は件数を after まで進めるだけ、読む取得は一様の判定時刻の核。どちらも状態に依らない因子を掛ける
        if e["symbol"] in _UNREAD:
            v = _evolve(v, x(a) - x(b), C)
        else:
            v = _read(v, x, _clock_cuts(clock, b, a), C, (e["cursor"], e["symbol"] == "taken"))
        v = [y.scale(_source_factor(unit, e["symbol"])) for y in v]
        t = a
    return _evolve(v, x((terminal_ns - origin) * scale) - x(t), C)


def _evolve(v, x, C):
    """時間の発展 (累積の率 x の Poisson の到着)。x = 0 は恒等。"""
    return _apply(_poisson_matrix(x, C), v) if x else v


def _read(v, x, cuts, C, kernel):
    """一様の判定時刻の取得区間 [b, a] の核 (K38 決定 3・4、K40 決定 6)。cuts = (b, 境目…, a) は率が一定の小区間の端で、判定
    時刻 U がその小区間にある確率 (長さの比) × (小区間の前の発展 → 小区間の一様の核 → 後の発展) を足す (判定は 1 回。区切り
    ごとに観測を数えて掛けない)。幅 0 の区間は点の判定。"""
    b, a = cuts[0], cuts[-1]
    if a == b:
        return _apply(_poisson_matrix(_Q(0), C, kernel), v)
    out = [Poly() for _ in v]
    for left, right in zip(cuts, cuts[1:]):
        w = _evolve(_apply(_poisson_matrix(x(right) - x(left), C, kernel), _evolve(v, x(left) - x(b), C)),
                    x(a) - x(right), C)
        out = [o + y.scale((right - left) / (a - b)) for o, y in zip(out, w)]
    return out


def _clock_integral(clock, t):
    """∫_0^t c(φ(s)) ds (t は起点からの経過時間、K40 決定 1・2)。c は区切り j の上で倍率 f_j / w_j の区分一定で、1 周の
    平均は 1 なので、n 周で n·T。時計が無ければ t。"""
    if clock is None:
        return t
    period = clock["period"]
    turns = t // period
    phase = t / period - turns
    starts, rates = clock["starts"], clock["multipliers"]
    edges = [_Q(0), *starts, _Q(1)]
    heights = [rates[-1], *rates]   # [0, 最初の始まり) は最後の区切りの続き (円)
    inside = sum((h * (min(phase, r) - l) for l, r, h in zip(edges, edges[1:], heights) if phase > l), _Q(0))
    return period * (turns + inside)


def _clock_cuts(clock, b, a):
    """区間 [b, a] の中の時計の区切りの境目 (経過時間、昇順) を両端と並べた列。時計が無ければ (b, a)。"""
    if clock is None or a == b:
        return (b, a)
    period = clock["period"]
    inner = {period * (n + s) for n in range(int(b // period), int(a // period) + 1) for s in clock["starts"]}
    return (b, *sorted(c for c in inner if b < c < a), a)


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
    """正本 spec ({units, entries, terminal_ns}) から、状態ごとの件数の分け方 0..C の重み (事前を掛ける前) と C。時計の連続の
    事前の unit (θ を積分する、K40 決定 7) は None (`unit_mass` が積分の項にする)。"""
    cursors = [e["cursor"] for e in spec["entries"] if e["kind"] == "acquisition"]
    C = max([*(c + 1 for c in cursors), need + 1, 1])
    run = {"poisson": _poisson, "finite": _finite}
    return C, [None if continuous(u) or chained(u) else run[u["law"]["kind"]](u, spec["entries"], spec["terminal_ns"], C)
               for u in spec["units"]]


def chained(unit) -> bool:
    """遷移のある調子の群の unit か (K41 決定 1。R = 0 は候補の解決で外してあり、既存の道を通る)。"""
    from ._fb_chain import chained as is_chained
    return is_chained(unit)


def continuous(unit) -> bool:
    """時計の連続の事前の unit か (法則の時計の形が θ の事前を持つ、K40 決定 4・5)。"""
    clock = unit["law"].get("clock")
    return clock is not None and "segments" in clock


def unit_mass(spec, vs, i, selector=None):
    """unit i の事前を掛ける前の量 (selector は `_fb_clock.Integral` と同じ: None = 全件数、("eq", k)・("ge", k) = 件数の類、
    ("share", lo, hi) = 1 周の割合との積)。有限の unit は Poly、連続の事前の unit は積分の項 (Form)。"""
    if continuous(spec["units"][i]):
        return _space(spec).form(i, selector)
    v = vs[i]
    if selector is None:
        return sum(v, Poly())
    return v[selector[1]] if selector[0] == "eq" else sum(v[selector[1]:], Poly())


def unit_weight(spec, vs, i, selector=None):
    """unit i の正規化する前の重み (事前を掛けた量、`_weighted`)。"""
    return _weighted(spec["units"][i], unit_mass(spec, vs, i, selector) if not chained(spec["units"][i])
                     else _space(spec).form(i, selector))


def _weighted(unit, mass):
    """unit の量 mass に事前を掛けた重み。静的な unit は事前_i × L_i。遷移のある群の unit の量は群の初期の事前を含む
    Σ_{s0} 事前(s0) · L(s0 → i) なので、そのまま (K41 決定 3。事前は状態 i の外の初期の状態にもかかるので、unit の事前だけを
    外に出せない)。照会の重み (`unit_weight`) と考える側の出発点 (`joint`) が同じこの判断を使う (レビュー R8)。"""
    return mass if chained(unit) else mass.scale(unit["prior"])


def weights(spec):
    """状態ごとの正規化する前の重み W_i (`unit_weight`) と、証拠の質量 Z。連続の事前・遷移のある群の unit の W_i は積分の項 (Form)。"""
    _C, vs = classes(spec)
    W = [unit_weight(spec, vs, i) for i in range(len(spec["units"]))]
    return W, sum(W, Poly())


# --- 積分を含む量 (K40 決定 7・12) ---

class Form:
    """指数多項式と、時計の連続の事前の積分の項の有理数の係数の一次結合 poly + Σ c_l · I_l (I_l は `_fb_clock.Integral` の量)。
    積分の項は正と証明したものだけを持つ (形で 0 の積分は項にしない、`_Space.form`)。値の上下界は予算つき (`_enclose_forms`)。
    形で 0 (項が無く poly が 0) の時だけ値 0 と言う。項の係数が全部正の時、値は正。"""
    __slots__ = ("poly", "leaves", "space")

    def __init__(self, poly, leaves, space):
        self.poly, self.space = poly, space
        self.leaves = {k: c for k, c in leaves.items() if c}

    def __add__(self, other):
        if isinstance(other, Poly):
            return Form(self.poly + other, self.leaves, self.space)
        if not isinstance(other, Form):
            return NotImplemented
        out = dict(self.leaves)
        for k, c in other.leaves.items():
            out[k] = out.get(k, 0) + c
        return Form(self.poly + other.poly, out, self.space or other.space)

    __radd__ = __add__

    def __sub__(self, other):
        return self + other.scale(-1)

    def __rsub__(self, other):
        return other + self.scale(-1)

    def scale(self, r):
        return Form(self.poly.scale(r), {k: c * r for k, c in self.leaves.items()}, self.space)

    def __eq__(self, other):
        if isinstance(other, Poly):
            return not self.leaves and self.poly == other
        return isinstance(other, Form) and self.poly == other.poly and self.leaves == other.leaves

    __hash__ = None

    @property
    def zero(self) -> bool:
        return self.poly.zero and not self.leaves

    def encode(self):
        return {"poly": self.poly.encode(), "integrals": [[i, _f._encode(sel), _f._encode(c)] for (i, sel), c
                                                          in sorted(self.leaves.items(), key=lambda x: _f._dumps(x[0]))]}


def _space(spec):
    return _Space(spec)   # 正本の dict は変えない (積分は識別で `_INTEGRALS` に共有する)


_INTEGRALS = {}   # 積分 (変わらない記述と、(精度, 段) の完成した上下界) の置き場: 法則・原記録・量の識別ごと


class _Space:
    """1 つの正本の積分の項の置き場。積分は (unit の法則・故障の核・原記録の列・端の時刻・量) の識別で共有する (同じ根から作り
    直した正本・照会と検査の間で、完成した段の上下界を使い直す。値の意味は変えない。箱の列は照会ごと、`_fb_clock._Table`)。"""

    def __init__(self, spec):
        self.spec = spec

    def integral(self, i, selector):
        from ._fb_clock import Integral
        unit = self.spec["units"][i]
        if chained(unit):
            return self._chain(i, selector)
        key = _f._digest({"unit": {k: unit[k] for k in ("law", "failure", "disconnection", "index")},
                          "entries": encode_spec({"units": [], "entries": self.spec["entries"],
                                                  "terminal_ns": self.spec["terminal_ns"]})["entries"],
                          "terminal_ns": self.spec["terminal_ns"], "selector": selector})
        found = _INTEGRALS.get(key)
        if found is None:
            if len(_INTEGRALS) > 256:
                _INTEGRALS.clear()
            found = _INTEGRALS[key] = Integral(unit, self.spec["entries"], self.spec["terminal_ns"], selector)
        return found

    def _chain(self, i, selector):
        from ._fb_chain import Chain, group_of
        tr = self.spec["units"][i]["law"]["transitions"]
        group = [self.spec["units"][j] for j in tr["units"]]
        key = _f._digest({"chain": encode_spec({"units": group, "entries": self.spec["entries"],
                                                "terminal_ns": self.spec["terminal_ns"]}),
                          "unit": i, "selector": selector})
        found = _INTEGRALS.get(key)
        if found is None:
            if len(_INTEGRALS) > 256:
                _INTEGRALS.clear()
            if continuous(self.spec["units"][i]):   # 連続の時計の事前 × 遷移 (K41 決定 8)
                from ._fb_chain import ChainIntegral
                found = _INTEGRALS[key] = ChainIntegral(self.spec, i, selector)
            else:
                need = selector[1] + 1 if selector is not None else 0
                found = _INTEGRALS[key] = Chain(*group_of(self.spec, i, need), selector)
        return found

    def formula(self, i, selector):
        """unit i の積分の版つきの式 (正準な JSON の文字列、K40 決定 12)。遷移のある群の unit は、群の全部の unit (事前つき) と
        群の中の位置を持つ鎖の式 (K41 決定 4)。"""
        unit = self.spec["units"][i]
        if chained(unit):
            tr = unit["law"]["transitions"]
            group = [self.spec["units"][j] for j in tr["units"]]
            encoded = encode_spec({"units": group, "entries": self.spec["entries"], "terminal_ns": self.spec["terminal_ns"]})
            return _f._dumps({**CHAIN_FORMULA, "units": encoded["units"], "entries": encoded["entries"],
                              "terminal_ns": self.spec["terminal_ns"], "unit": i,
                              "selector": None if selector is None else _f._encode(selector)}).decode("utf-8")
        encoded = encode_spec({"units": [{**unit, "prior": _Q(1)}], "entries": self.spec["entries"],
                               "terminal_ns": self.spec["terminal_ns"]})
        u = encoded["units"][0]
        return _f._dumps({**INTEGRAL_FORMULA,
                          "unit": {k: u[k] for k in ("index", "law", "failure", "disconnection")},
                          "entries": encoded["entries"], "terminal_ns": self.spec["terminal_ns"],
                          "selector": None if selector is None else _f._encode(selector)}).decode("utf-8")

    def form(self, i, selector):
        integral = self.integral(i, selector)
        if integral.exact is not None:
            return integral.exact
        return Form(Poly(), {(i, selector): _Q(1)} if integral.positive() else {}, self)


# --- 正本を作る (入口 U が使う) ---

def unit_law(law, state, rate=None, clock=None, transitions=None):
    """法則の状態 state の件数の法則を正本の形 (dict) にする。rate はスイッチを当てた後の率 (K39、None は宣言の率)、clock は
    時計のオンの枝の時計の形 (K40、`f_update2._clock_choices`。オフは None で、欄を持たない)。対応していない法則は None。"""
    i = law.states.index(state)
    if isinstance(law, _fb.PoissonLaw):
        out = {"kind": "poisson", "rate": law.rates[i] if rate is None else rate, "origin_ns": law.origin_ns,
               "time_unit": law.time_unit, "initial_count": law.initial_count,
               **({} if clock is None else {"clock": clock}),
               **({} if transitions is None else {"transitions": transitions})}
    elif isinstance(law, _fb.FiniteCountLaw):
        out = {"kind": "finite", "origin_ns": law.origin_ns, "initial_count": law.initial_count,
               "positions_ns": law.positions_ns, "paths": law.paths, "weights": law.weights_by_state[i]}
    else:
        return None
    return out


def encode_spec(spec):
    def unit(u):
        out = {**{k: v for k, v in u.items() if k not in ("law", "prior", "failure", "disconnection", "family")},
               "prior": _f._encode(u["prior"]), "failure": None if u["failure"] is None else _f._encode(u["failure"]),
               "disconnection": None if u["disconnection"] is None else _f._encode(u["disconnection"]),
               "law": {k: _f._encode(v) for k, v in u["law"].items()}}
        if "family" in u:   # スイッチの族 (K39 決定 5: 部品の辞書・p の共有範囲・a, b。枝は branch。時計の候補と事前、K40)
            out["family"] = {k: _f._encode(v) for k, v in u["family"].items()}
        return out

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
        if "clock" in out:   # 時計の形 (K40): 点の形か、連続の事前の形 (区切りの数 segments を持つ)
            clock = out["clock"]
            if "segments" in clock:
                out["clock"] = {k: v if k == "segments" or v is None else [q(x) for x in v] if isinstance(v[0], list)
                                else q(v) for k, v in clock.items()}
            else:
                out["clock"] = {"period": q(clock["period"]), "starts": [q(x) for x in clock["starts"]],
                                "multipliers": [q(x) for x in clock["multipliers"]]}
        if "transitions" in out:   # 遷移のある群 (K41): 群の状態ごとの率・生成行列の非対角・群の unit の番号
            tr = out["transitions"]
            out["transitions"] = {"rates": [q(x) for x in tr["rates"]], "R": [[q(x) for x in row] for row in tr["R"]],
                                  "units": list(tr["units"])}
        if "weights" in out:
            out["weights"] = tuple(q(x) for x in out["weights"])
            out["paths"] = tuple(tuple(p) for p in out["paths"])
        return out
    def family(raw):
        out = {**raw, "a": q(raw["a"]), "b": q(raw["b"])}
        if "clock" in raw:   # 部品の名前 part・区切りの数 segments はそのまま、周期と事前の重みは有理数
            out["clock"] = {k: v if k in ("part", "segments") else [q(x) for x in v] for k, v in raw["clock"].items()}
        return out
    units = [{**u, "prior": q(u["prior"]), "failure": None if u["failure"] is None else q(u["failure"]),
              "disconnection": None if u["disconnection"] is None else q(u["disconnection"]),
              "law": law(u["law"]), **({"family": family(u["family"])} if "family" in u else {})}
             for u in value["units"]]
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
    """照会する量の (分子, 分母) の Poly。分母は証拠の質量 Z (mass は分母 1)。スイッチと p の照会 (SwitchQuantity) は候補に
    条件づける (`_conditional`、K39 決定 6)。"""
    if isinstance(quantity, (_fb.SwitchQuantity, _fb.ClockQuantity)):
        return _conditional(spec, quantity)
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
        selector = ("ge" if quantity.at_least else "eq", quantity.count)
        n = sum((unit_weight(spec, vs, i, selector) for i in keep), Poly())
        Z = sum((unit_weight(spec, vs, i) for i in range(len(units))), Poly())
        return n, Z
    if kind == "state" and quantity.candidate is not None:
        # state は周辺 P(S | h) (K39-b R3)。候補に条件づけた値は SwitchQuantity、共同の値は candidate の照会と掛けて作る
        raise _fb.TimeBeliefError(kind="invalid", reason="a state query does not name a candidate", field="candidate",
                                  targets=(quantity.candidate,))
    W, Z = weights(spec)
    key = {"state": "state", "candidate": "candidate"}.get(kind)
    target = quantity.state if kind == "state" else quantity.candidate
    if key is None or target not in {u[key] for u in units}:
        raise _fb.TimeBeliefError(kind="invalid", reason="unknown quantity", field=kind)
    return sum((w for w, u in zip(W, units) if u[key] == target), Poly()), Z


def _member(spec, candidate, family):
    """スイッチと p の照会の候補 M の units の番号と、その族 (名前・a・b・部品の辞書)。候補 M の族の名前が family と合うこと
    (ほかの候補の同じ名前の族と 1 つにしない、K39 決定 3)。"""
    units = spec["units"]
    mine = [i for i, u in enumerate(units) if u["candidate"] == candidate]
    if not mine:
        raise _fb.TimeBeliefError(kind="invalid", reason="unknown candidate", field="candidate", targets=(candidate,))
    found = units[mine[0]].get("family")
    if found is None or found["name"] != family:
        raise _fb.TimeBeliefError(kind="invalid", reason="unknown family of the candidate", field="family",
                                  targets=(candidate, family))
    return mine, found


def _evidence(spec, mine, candidate):
    """候補 M の未正規化のかたまり W_i (i ∈ M) と Z_M。Z_M が形で 0 なら条件つきの値を作らずに M を名指す (K37 決定 5。
    並び全体の証拠 0 とは理由で分ける)。"""
    every, _Z = weights(spec)
    W = {i: every[i] for i in mine}
    Z = sum(W.values(), Poly())
    if Z.zero:
        raise _fb.TimeBeliefError(kind="model_falsified", reason="candidate_evidence_zero", targets=(candidate,))
    return W, Z


def _conditional(spec, quantity):
    """候補 M に条件づけた値の (分子, 分母) (K39 決定 6)。分母は Z_M = Σ_{z,S ∈ M} W_{z,S}。on・off は部品の名前で、スイッチの
    列の部分的な条件。p の成分は枝 z ごとに Beta(a + |z|, b + k − |z|) で、取得の回数を足さない (決定 4)。時計の照会
    (`fb.ClockQuantity`、K40 決定 15) も同じ決まりで、on・off は分子の事象だけ。"""
    kind = quantity.kind
    clock = isinstance(quantity, _fb.ClockQuantity)
    # この本が対応していない照会 (名指して断る): p の累積確率・分位点 (K39 (2))、時計の回転・幅・配分の領域の確率と分母を変える
    # 条件 (K40 決定 15。考える側は決定 8 の I(Q; Y | h) を使う)
    if kind in ("p_cdf", "p_quantile") or clock and (kind in ("phase", "width", "fraction")
                                                     or quantity.condition_on or quantity.condition_off):
        raise _fb.TimeBeliefError(kind="unsupported", reason=kind + "_not_supported", field="kind",
                                  targets=(quantity.candidate, quantity.family))
    units = spec["units"]
    mine, family = _member(spec, quantity.candidate, quantity.family)
    names = [x[0] for x in family["parts"]]
    a, b, k = family["a"], family["b"], len(names)
    on, off = quantity.on, quantity.off
    if type(on) is not tuple or type(off) is not tuple or set(on) & set(off) \
            or any(x not in names for x in (*on, *off)) or len(set(on)) != len(on) or len(set(off)) != len(off):
        raise _fb.TimeBeliefError(kind="invalid", reason="on and off must name distinct parts of the family",
                                  field="on", targets=(quantity.candidate, quantity.family))
    if (on or off) and kind not in ("switch", "state", "parameters"):
        raise _fb.TimeBeliefError(kind="invalid", reason="on and off condition only switch, state and parameters",
                                  field="on", targets=(quantity.candidate, quantity.family))
    W, Z = _evidence(spec, mine, quantity.candidate)

    def picked(i):   # 名指したスイッチの値に合う枝か (名指しが無ければ全部)
        z = units[i]["branch"]
        return all(z[names.index(x)] == 1 for x in on) and all(z[names.index(x)] == 0 for x in off)

    def total(factor):
        return sum((W[i].scale(factor(i)) for i in mine), Poly())

    def ones(i):
        return sum(units[i]["branch"])
    if clock:
        return _clock_quantity(spec, quantity, mine, family, W, picked), Z
    if kind == "switch":
        return total(lambda i: int(picked(i))), Z
    if kind == "state":
        if quantity.state not in {units[i]["state"] for i in mine}:
            raise _fb.TimeBeliefError(kind="invalid", reason="unknown state", field="state")
        return total(lambda i: int(picked(i) and units[i]["state"] == quantity.state)), Z
    if kind == "mass":   # P(h | M) = Z_M / (M の起点の事前の重み)
        return Z.scale(1 / sum((units[i]["prior"] for i in mine), _Q(0))), Poly.const(1)
    if kind == "p_mean":
        return total(lambda i: (a + ones(i)) / (a + b + k)), Z
    if kind == "p_moment":
        r = quantity.order
        if type(r) is not int or r < 0:
            raise _fb.TimeBeliefError(kind="invalid", reason="order must be a non-negative int", field="order")
        return total(lambda i: _rising(a + ones(i), r) / _rising(a + b + k, r)), Z
    raise _fb.TimeBeliefError(kind="invalid", reason="unknown quantity", field="kind")


def _clock_quantity(spec, quantity, mine, family, W, picked):
    """時計の照会の分子 (K40 決定 15、分母は候補 M の証拠 Z_M のまま)。parameters = P(T ∈ periods, m ∈ segments, on・off の事象 |
    h, M) (periods・segments は宣言した候補の部分集合、None は全部。時計のオフの枝の T・m は潜在で事前のまま) / allocation =
    E[∫_[lower, upper) c_θ(φ)^{z_時計} dφ | h, M] (端は [0, 1) の有理数、lower > upper は 1 周をまたぐ。時計のオフの枝は区間の長さ)。"""
    from ._fb_clock import share_of
    units, clock = spec["units"], family.get("clock")
    named = (quantity.candidate, quantity.family)
    if clock is None or quantity.part != clock["part"]:
        raise _fb.TimeBeliefError(kind="invalid", reason="part must name the clock part of the family", field="part",
                                  targets=(*named, quantity.part))
    if quantity.kind == "parameters":
        def subset(value, declared, field):
            if value is None:
                return list(declared)
            if type(value) is not tuple or len(set(value)) != len(value) or any(type(x) is bool for x in value)                     or any(x not in declared for x in value):
                raise _fb.TimeBeliefError(kind="invalid", reason=field + " must name declared candidates", field=field,
                                          targets=named)
            return list(value)
        A = subset(quantity.periods, clock["periods"], "periods")
        B = subset(quantity.segments, clock["segments"], "segments")
        latent = sum((w for t, w in zip(clock["periods"], clock["period_weights"]) if t in A), _Q(0))             * sum((w for m, w in zip(clock["segments"], clock["segment_weights"]) if m in B), _Q(0))

        def factor(i):
            shape = units[i]["law"].get("clock")
            if not picked(i):
                return _Q(0)
            if shape is None:
                return latent
            m = shape["segments"] if "segments" in shape else len(shape["starts"])
            return _Q(int(shape["period"] in A and m in B))
        return sum((W[i].scale(factor(i)) for i in mine), Poly())
    if quantity.kind != "allocation":
        raise _fb.TimeBeliefError(kind="invalid", reason="unknown quantity", field="kind", targets=named)
    lo, hi = quantity.lower, quantity.upper
    if quantity.on or quantity.off or not all(type(x) is _Q and 0 <= x < 1 for x in (lo, hi)):
        raise _fb.TimeBeliefError(kind="invalid", reason="allocation ends must be two rationals in [0, 1)",
                                  field="lower", targets=named)
    length = hi - lo if lo <= hi else 1 - lo + hi
    _C, vs = classes(spec)
    out = Poly()
    for i in mine:
        shape = units[i]["law"].get("clock")
        if shape is None:
            out = out + W[i].scale(length)
        elif "segments" in shape:
            out = out + unit_weight(spec, vs, i, ("share", lo, hi))
        else:
            out = out + W[i].scale(share_of(shape, lo, hi))
    return out


def _rising(x, n):
    from .f_update2 import _rising as rising
    return _Q(rising(x, n))


def query(spec, root, quantity, budget):
    """照会の答え (BeliefValue)。分母 Z が形で 0 なら model_falsified (採用された信念には起きない)。精度は 2^−64 から倍に
    していき、幅が budget.tolerance 以下になった所で返す。max_refinements の回数で届かなければ incomplete (モデルの誤り
    ではない)。"""
    n, d = _quantity(spec, quantity)
    if d.zero:
        raise _fb.TimeBeliefError(kind="model_falsified", reason="the evidence mass is structurally zero")
    if isinstance(n, Form) or isinstance(d, Form):
        return _query_forms(n, d, root, quantity, budget)
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


def _as_form(x):
    return x if isinstance(x, Form) else Form(x, {}, None)


def _form_rational(n, d):
    """n / d が有理数なら、その値 (n = r·d が形で成り立つ時だけ)。"""
    n, d = _as_form(n), _as_form(d)
    if n.zero:
        return _Q(0)
    if d.leaves:
        key = next(iter(d.leaves))
        r = n.leaves.get(key, 0) / d.leaves[key]
    else:
        r = _ratio_rational(n.poly, d.poly) if not n.leaves else None
        if r is None:
            return None
    return r if n == d.scale(r) else None


def _integrals(*forms):
    out = {}
    for x in forms:
        x = _as_form(x)
        for key in x.leaves:
            out[key] = x.space.integral(*key)
    return out


def _num(tolerance, rounds):
    """照会の精度 tolerance と精度を上げた回 rounds の数の精度 (`_fb_clock.Num`、紙 F-b K40-i)。"""
    from ._fb_clock import Num, precision_bits
    return Num(precision_bits(tolerance, rounds))


def _enclose_form(x, integrals, num, level):
    """積分を含む x の上下界 (数の精度 num・箱の数 level)。精度が足りず正の量の下界を 0 から分けられなければ (None, None)。"""
    x = _as_form(x)
    lo, hi = x.poly.enclose(num.bits)
    try:
        for key, c in x.leaves.items():
            a, b = integrals[key].table(num).at(level)
            lo, hi = (lo + c * a, hi + c * b) if c > 0 else (lo + c * b, hi + c * a)
    except _f._EnclosureShort:
        return None, None
    return lo, hi


def _ratio_forms(n, d, integrals, level, num):
    """積分を含む n / d の上下界。照会の量はどれも確率か [0, 1] の量の期待値なので [0, 1] に切る。分母が 0 から分けられなければ
    None (精度の不足)。"""
    nl, nh = _enclose_form(n, integrals, num, level)
    dl, dh = _enclose_form(d, integrals, num, level)
    if nl is None or dl is None or dl <= 0:
        return None, None
    values = (nl / dl, nl / dh, nh / dl, nh / dh)
    lo, hi = _outward(min(values), max(values), num.bits + 8)
    return max(lo, _Q(0)), min(hi, _Q(1))


def _first_level():
    from ._fb_clock import FIRST_LEVEL
    return FIRST_LEVEL


def _query_forms(n, d, root, quantity, budget):
    """積分を含む照会 (K40 決定 7): 積分の箱を倍にし、数の精度を上げていき (`_fb_clock.precision_bits`、K40-i)、幅が
    budget.tolerance 以下になった所で返す。max_refinements の回数か max_cells の箱の数で届かなければ incomplete (下界がまだ 0 の
    枝も消さない、P8)。"""
    exact = _form_rational(n, d)
    if exact is not None:
        return _fb.BeliefValue(root=root, quantity=quantity, lower=exact, upper=exact, exact=exact,
                               proof=_f._freeze({"exact": True}))
    integrals = _integrals(n, d)
    regions, rounds = _first_level(), 0
    while True:
        if budget.max_cells is not None and regions * len(integrals) > budget.max_cells:
            raise _fb.TimeBeliefError(kind="incomplete", reason="integration regions exceed the budget")
        num = _num(budget.tolerance, rounds)
        lo, hi = _ratio_forms(n, d, integrals, regions, num)
        if lo is not None and hi - lo <= budget.tolerance:
            return _fb.BeliefValue(root=root, quantity=quantity, lower=lo, upper=hi, exact=None,
                                   proof=_f._freeze({"integration_regions": regions, "precision_bits": num.bits}))
        rounds += 1
        if budget.max_refinements is not None and rounds > budget.max_refinements:
            raise _fb.TimeBeliefError(kind="incomplete", reason="precision not reached within the budget")
        regions *= 2


_CHECK_REGIONS = 1 << 16


def _contains_forms(n, d, lower, upper):
    """[lower, upper] が積分を含む真の値を含むか。箱を倍にしていき、囲みが内側に入れば True・外に出れば False。_CHECK_REGIONS
    の箱で決まらなければ False (確かめられなかった)。"""
    exact = _form_rational(n, d)
    if exact is not None:
        return lower <= exact <= upper
    integrals = _integrals(n, d)
    regions, rounds = _first_level(), 0
    while regions <= _CHECK_REGIONS:
        lo, hi = _ratio_forms(n, d, integrals, regions, _num(None, rounds))
        if lo is not None:
            if lower <= lo and hi <= upper:
                return True
            if hi < lower or upper < lo:
                return False
        regions, rounds = regions * 2, rounds + 1
    return False


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
    if isinstance(n, Form) or isinstance(d, Form):
        return _contains_forms(n, d, lower, upper)
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
    if reading.independent_of_count is not True:   # 名指しは足りない宣言の欄 (K41 決定 6 の「足りない測定の条件を名指す」)
        return "independent_of_count"
    return None if reading.count_shift == 0 else "count_shift"


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


def query_switch(state, belief, quantity, budget):
    return _query_typed(state, belief, quantity, budget, _fb.SwitchQuantity)


def query_clock(state, belief, quantity, budget):
    return _query_typed(state, belief, quantity, budget, _fb.ClockQuantity)


def _query_typed(state, belief, quantity, budget, typ):
    if not isinstance(quantity, typ):
        raise _fb.TimeBeliefError(kind="invalid", reason=typ.__name__ + " required", field="quantity")
    with state.lock:
        spec = _spec(state, belief)
    return query(spec, belief.root, quantity, budget)


def _mixture(spec, candidate, family):
    """p の混合の成分の形 (K39 決定 6): スイッチの列 z (辞書順) ごとに (Beta の a, b, その枝の重みの照会)。M の証拠 0 は名指し。"""
    mine, found = _member(spec, candidate, family)
    _evidence(spec, mine, candidate)
    from itertools import product
    names = [x[0] for x in found["parts"]]
    a, b, k = found["a"], found["b"], len(names)
    out = []
    for z in product((0, 1), repeat=k):
        quantity = _fb.SwitchQuantity(kind="switch", candidate=candidate, family=family,
                                      on=tuple(x for x, bit in zip(names, z) if bit),
                                      off=tuple(x for x, bit in zip(names, z) if not bit))
        out.append((a + sum(z), b + k - sum(z), quantity))
    return found, out


def p_distribution(state, belief, candidate, family, budget):
    """候補 M に条件づけた p の分布の作り直せる混合の表現 (K39 決定 6): 枝 z ごとの成分 Beta(a + |z|, b + k − |z|) と、その重み
    P(z | h, M) の照会の答え (根から作り直した上下界)。"""
    with state.lock:
        spec = _spec(state, belief)
    found, shapes = _mixture(spec, candidate, family)
    return _fb.BetaMixture(
        root=belief.root, candidate=candidate, family=family, parts=tuple(x[0] for x in found["parts"]),
        a=found["a"], b=found["b"], components=tuple(_fb.BetaMixtureComponent(
            a=x, b=y, weight=query(spec, belief.root, q, budget)) for x, y, q in shapes),
        proof=_f._freeze({"components": "bit_strings", "weights": "switch_queries"}))


def verify_p_distribution(state, belief, distribution) -> bool:
    """混合の表現が根から作り直した混合と同じ候補・族・部品の辞書・a, b・成分の形と重みの照会を持ち、各重みの上下界が真の値を
    含むか (保存した重みの自己申告を信じない)。"""
    if not isinstance(distribution, _fb.BetaMixture) or distribution.root != belief.root:
        return False
    with state.lock:
        try:
            spec = _spec(state, belief)
            found, shapes = _mixture(spec, distribution.candidate, distribution.family)
        except _fb.TimeBeliefError:
            return False
    if distribution.parts != tuple(x[0] for x in found["parts"]) or (distribution.a, distribution.b) != (
            found["a"], found["b"]) or len(distribution.components) != len(shapes):
        return False
    for component, (x, y, q) in zip(distribution.components, shapes):
        w = component.weight
        if (component.a, component.b) != (x, y) or not isinstance(w, _fb.BeliefValue) or w.root != belief.root \
                or w.quantity != q or not (isinstance(w.lower, _Q) and isinstance(w.upper, _Q)) \
                or w.exact is not None and not w.lower == w.exact == w.upper or not contains(spec, q, w.lower, w.upper):
            return False
    return True


def resolve_public(reader, declaration):
    """`fb.resolve_belief_candidates` の中身 (K39 決定 8): 起動の宣言か並びの記録から、ホストと入口 U と同じ候補の解決で並びを
    読むだけで解く。読めない候補は名指して断る。"""
    from . import f_update2 as u
    c = _c()
    try:
        record = reader.record(declaration)
    except (KeyError, TypeError):
        raise _fb.TimeBeliefError(kind="unavailable", reason="unresolved_reference", targets=(declaration,)) from None
    try:
        if record.body.contract == c.BOOT_DECLARATION:
            members = [u.initial_candidate(reader, declaration)]
            document = members[0]["document"]
        elif record.body.contract == c.BELIEF_POOL:
            _content, members = u.pool_candidates(reader, declaration)
            document = u.direct_sum(members)
        else:
            raise _fb.TimeBeliefError(kind="invalid", reason="reference_kind", targets=(declaration,))
    except u.Unresolved as exc:   # 候補の解決の名指しの不足 (K39-b R1)
        raise unresolved_error(exc) from None
    except u._Issue as issue:
        raise _fb.TimeBeliefError(kind="unavailable" if issue.code == "unresolved_reference" else "invalid",
                                  reason=issue.code,
                                  targets=tuple(sorted(x for x in issue.evidence if isinstance(x, str)))) from None
    except ValueError as exc:   # 直和のモデルに表せない (`direct_sum`)
        raise _fb.TimeBeliefError(kind="invalid", reason="pool:" + str(exc), targets=(declaration,)) from None
    out = [_resolved(m) for m in members]
    references = frozenset().union(*(x.references for x in out))
    return _fb.ResolvedBeliefPool(document=_f._freeze(document), candidates=tuple(out), references=references)


def unresolved_error(exc):
    """候補の解決の名指しの不足 (`f_update2.Unresolved`) を公開の答えにする (公開の解決の口と候補を足す口が同じこれを使う):
    この本が対応していない宣言は unsupported、対応・モデルの形の誤りは invalid。名指しは候補と部品の名前。"""
    return _fb.TimeBeliefError(kind="unsupported" if exc.code == "missing_contract" else "invalid",
                               reason=exc.reason, targets=exc.named, field=exc.field)


def _resolved(member):
    """候補の記述の公開の形 (`fb.ResolvedCandidate`)。対応は候補の解決が確かめた phi (入口 U と同じ、K39-b R4) で、率を展開した
    状態の順に並べる。観測の見込みを読まない候補 (区間の札の δ) は対応が空。"""
    from .f import _Fraction, _decode
    document = member["document"]
    states = document["states"]
    rates = clocks = None
    if member["computation"] == "poisson":
        law_state = {j: a for a, j in enumerate(member["phi"])}   # 宣言のモデルの状態の番号 → 法則の状態の番号
        size = len(member["base"]["states"])
        rates = tuple(branch["rates"][law_state[j]] for branch in member["branches"] for j in range(size))
        clocks = tuple(None if branch["clock"] is None else (branch["clock"]["period"], () if "segments" in branch["clock"]
                       else tuple(zip(branch["clock"]["starts"], branch["clock"]["multipliers"])))
                       for branch in member["branches"] for _j in range(size))
    pairs = member["pairs"] if member["phi"] is not None else []
    return _fb.ResolvedCandidate(
        id=member["id"], states=tuple(s["id"] for s in states),
        prior=_decode(document["initial"], tuple[_Fraction, ...]), rates=rates,
        correspondence=tuple(tuple(x) for x in pairs), knowledge_targets=tuple(s["target"] for s in states),
        references=frozenset(member["references"]), clocks=clocks)


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
            work = _f._ExpressionWork(budget, precision=precision)
            work.integral_regions = _EVALUATION_REGIONS * 4 ** rounds   # 積分の箱も回ごとに増やす (K40 決定 12)
            bounds = work.enclose(quantity.exact)
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
