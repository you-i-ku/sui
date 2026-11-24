"""時計の部品の連続の事前の積分 (紙 F-b K40 決定 7・13・14 の計算法)。法則・正本の意味は変えない (同じ積分の解き方)。

1 つの unit (候補・スイッチの列 z・状態 S・周期 T・区切りの数 m) の尤度の積分 I = ∫ L(h | θ) Π(dθ | T, m) を求める。回転 ρ が
連続の事前 ([0, 1) の一様) なら、ρ は w・f を固定して解析的に積分する (決定 14、`rotation_integral`: 指数多項式で厳密)。被積分の
量が依らないと構造から言える座標は箱で割らない (決定 14 の「先に計算」): 尤度が θ によらなければ積分は尤度 × 事前の期待値
(`Integral._reads`)、ρ・w が点なら f は読む位相で係数が同じ区切りの和だけ (Dirichlet の集約、`Integral._groups`)。残る w・f の
連続の座標は箱に分けて有理数の上下界で包む (決定 7)。箱ごとに、事前の質量の上下界 × 箱の中の尤度の上下界を足す (代表点に
質量を移さない)。箱の中の尤度は、代表点 θ0 の尤度 (`_fb_time._poisson` の指数多項式で厳密) と、到着の率の差の積分の上界
D ≥ ∫_0^H |λ_θ − λ_θ0| dt から |L(θ) − L(θ0)| ≤ F·min(1, D) で包む (F は状態と件数に依らない因子の積、L ∈ [0, F]。2 つの
Poisson 源の共通の到着を共有する組み立て、Codex sui-open-world 10 通目)。単体の境目に触れる箱は、尤度を [0, F]、事前の質量を
周辺の Beta の下側の確率の上界で包む (決定 13、外した質量の寄与は [0, F·ε])。Dirichlet の正規化定数は Γ を使わず、Beta の積分の
積で包む (決定 13)。数は全部、外向きに丸めた有理数 (P10) で、log・exp・和の丸めは F-a の保証つきの数の仕組み (`Num`、
紙 F-b K40-i)。精度は呼ぶ側が照会の精度と予算から決めて渡す (`Integral.at`)。

構造の 0 (決定 7・K38 決定 6): 内部の θ では区切りの倍率が全部正なので、正の長さの区間の到着の件数の支持は θ によらない。
よって尤度の正負は内部の θ で一定で、内部の 1 点 θ* の指数多項式が形で 0 なら積分は 0、そうでなければ正 (`positive`)。
"""

import heapq
from fractions import Fraction as _Q

_HALF = _Q(1, 2)
FIRST_LEVEL = 32   # 積分の箱の数の段の最初 (段は倍にしていく、`Integral.at`)


# --- 数の上下界 (F-a の保証つきの数の仕組みに乗せる、紙 F-b K40-i) ---

def _down(x, bits):
    s = 1 << bits
    return _Q((x.numerator * s) // x.denominator, s)


def _up(x, bits):
    s = 1 << bits
    return _Q(-((-x.numerator * s) // x.denominator), s)


def _significant(x, bits, up):
    """正の有理数 x を有効桁 bits の 2 進の有理数に外向きに丸める (下は x 以下・上は x 以上、どちらも正)。"""
    shift = bits - (x.numerator.bit_length() - x.denominator.bit_length())
    scaled = x * _Q(2) ** shift
    whole = -((-scaled.numerator) // scaled.denominator) if up else scaled.numerator // scaled.denominator
    return _Q(whole) / _Q(2) ** shift


def precision_bits(tolerance, rounds=0):
    """数の格子の桁 (紙 F-b K40-i: 固定の 64 bit にしない)。照会の精度 tolerance (幅、None は精度の指定なし) の 2^−16 倍の
    格子から始め、精度を上げた回 rounds ごとに 32 桁ずつ細かくする (回の上限は呼ぶ側の予算 max_refinements)。"""
    start = 64 if tolerance is None else max(64, tolerance.denominator.bit_length() - tolerance.numerator.bit_length() + 17)
    return start + 32 * rounds


def _short(detail):
    from .f import _EnclosureShort
    return _EnclosureShort("certificate_incomplete", detail)


class Num:
    """時計の数の上下界の口 (紙 F-b K40-i)。log・exp は F-a の `rate._RateInformationWork` (級数の各項・和・剰余を厳密な有理数で
    持ち、最後に格子 2^−bits の外向きに丸める)、和の丸めも同じ仕組みの格子。精度 bits は呼ぶ側が照会の精度と予算から決め
    (`precision_bits`)、足りなければ上げる。正の量で割るのは正の下界が証明できてから (`inverse`)。できなければ F-a の
    `_EnclosureShort` (精度の不足、入力の不正ではない)。上下界は (引数, bits) だけで決まる。"""

    def __init__(self, bits):
        from .rate import RateBudget, _RateInformationWork
        self.bits = bits
        self.work = _RateInformationWork(RateBudget(_Q(1), None, None, None))   # 項の数は精度で決まる (予算は精度の回数)
        self.work.epsilon = self.work.number(1, 1 << bits)
        self.fraction = self.work.arithmetic.to_fraction
        self.pows, self.betas = {}, {}

    def log(self, lo, hi=None):
        """ln を [lo, hi] (有理数) の上で包む (ln は増える)。引数は有効桁 bits + 8 に外向きに丸めてから F-a の log へ。"""
        hi = lo if hi is None else hi
        if lo <= 0:
            raise _short("log argument not separated from zero")
        w, b = self.work, self.bits + 8
        return (self.fraction(w.log(_significant(_Q(lo), b, False)).lower),
                self.fraction(w.log(_significant(_Q(hi), b, True)).upper))

    def exp(self, lo, hi=None):
        """exp を [lo, hi] (有理数) の上で包む (exp は増える)。引数は格子 2^−(bits+8) に外向きに丸めてから F-a の exp へ。"""
        hi = lo if hi is None else hi
        w, b = self.work, self.bits + 8
        return self.fraction(w.exp(_down(_Q(lo), b)).lower), self.fraction(w.exp(_up(_Q(hi), b)).upper)

    def inverse(self, lo, hi):
        """正の量 x ∈ [lo, hi] の 1/x の上下界。正の下界が証明できなければ精度の不足 (0 で割らない、P8・P10)。"""
        if lo <= 0:
            raise _short("denominator not separated from zero")
        return 1 / _Q(hi), 1 / _Q(lo)

    def pow(self, x, e):
        """x^e (x > 0、e は有理数) の上下界。整数の e は厳密、ほかは exp(e ln x)。"""
        key = (x, e)
        if key not in self.pows:
            if e.denominator == 1 or x == 1:
                v = _Q(1) if x == 1 else _Q(x) ** int(e)
                self.pows[key] = (v, v)
            else:
                a, b = self.log(x)
                self.pows[key] = self.exp(*sorted((e * a, e * b)))
        return self.pows[key]

    def pow_box(self, lo, hi, e):
        """x ∈ [lo, hi] (lo > 0) の x^e の上下界 (x^e は x について単調)。"""
        if e == 0:
            return _Q(1), _Q(1)
        a, b = self.pow(lo, e), self.pow(hi, e)
        return (a[0], b[1]) if e > 0 else (b[0], a[1])

    def pow_corners(self, x_lo, x_hi, e_lo, e_hi):
        """x ∈ [x_lo, x_hi] ⊂ (0, 1]、e ∈ [e_lo, e_hi] の x^e の上下界。x^e は e について減る (x ≤ 1) ので、上は e_lo、下は e_hi で
        x の端をとる (どの e でも x について単調なので、x の端で最大・最小)。"""
        up = max(self.pow(x_lo, e_lo)[1], self.pow(x_hi, e_lo)[1])
        down = min(self.pow(x_lo, e_hi)[0], self.pow(x_hi, e_hi)[0])
        return down, up

    def _beta_half(self, a, b):
        """∫_0^{1/2} x^{a−1}(1−x)^{b−1} dx = 2^{−a} Σ_k C(b−1, k)(−1)^k 2^{−k} / (a+k)。項は厳密な有理数で、和は F-a の格子で
        外向きに丸めて足す。k > b−1 では項の符号がそろい絶対値が毎回半分以下になるので、そこで止めた残りは止めた項の絶対値の
        2 倍以下。b が正の整数なら有限の和。"""
        w = self.work
        eps = _Q(1, 1 << (self.bits + 6))
        total = w.interval(0, 0)
        g, k = _Q(1), 0
        while True:
            c = g * (-1) ** k / ((1 << k) * (a + k))
            if k > b - 1 and abs(c) * 2 < eps:
                total = w.add(total, w.interval(-2 * abs(c), 2 * abs(c)))
                break
            total = w.add(total, w.interval(c, c))
            g = g * (b - 1 - k) / (k + 1)
            k += 1
            if not g:
                break
        lo, hi = max(self.fraction(total.lower), _Q(0)), self.fraction(total.upper)   # 非負の関数の積分なので下は 0 以上
        p = self.pow(_HALF, a)
        return lo * p[0], hi * p[1]   # 非負どうしの厳密な積 (格子で丸めると小さい正の値が 0 に落ちる)

    def beta(self, a, b):
        """B(a, b) (a, b > 0 の有理数) の上下界 = [0, 1/2] と [1/2, 1] の 2 つの級数の和 (Γ の評価器を作らない、決定 13)。"""
        key = (a, b)
        if key not in self.betas:
            x, y = self._beta_half(a, b), self._beta_half(b, a)
            self.betas[key] = (x[0] + y[0], x[1] + y[1])
        return self.betas[key]

    def dirichlet_norm(self, alpha_lo, alpha_hi):
        """Dirichlet の正規化定数 Γ(Σα)/ΠΓ(α_j) = Π_{j=1}^{m−1} 1/B(α_j, Σ_{l>j} α_l) (決定 13) の上下界。α_j は区間
        [alpha_lo_j, alpha_hi_j]。B は両方の引数について減るので、下は全部の下端、上は全部の上端で包める。上は 1/B の正の下界が
        証明できてから (`inverse`)。"""
        m = len(alpha_lo)
        lo = hi = _Q(1)
        for j in range(m - 1):
            hi = hi * self.inverse(*self.beta(alpha_hi[j], sum(alpha_hi[j + 1:])))[1]   # 小さい B → 大きい 1/B
            if alpha_lo[j] > 0 and sum(alpha_lo[j + 1:]) > 0:
                lo = lo / self.beta(alpha_lo[j], sum(alpha_lo[j + 1:]))[1]   # B の上界は正 (真の値以上)
            else:   # 引数が 0 に触れる: B は発散し 1/B の下界は 0
                lo = _Q(0)
        return _down(lo, self.bits), _up(hi, self.bits)

    def lower_tail(self, x, a, b):
        """Beta(a, b) の P(X ≤ x) の上界: x^a / (a B(a, b)) · max(1, (1 − x)^{b−1}) (x < 1)。x ≥ 1 なら 1。"""
        if x >= 1:
            return _Q(1)
        if x <= 0:
            return _Q(0)
        p = self.pow(x, a)[1]
        q = max(_Q(1), self.pow(1 - x, b - 1)[1]) if b != 1 else _Q(1)
        B = self.beta(a, b)
        return min(_Q(1), _up(p * q * self.inverse(a * B[0], a * B[1])[1], self.bits))


def _volume(box):
    """単体の座標の箱の体積 (最後の成分は残りの和で決まるので、最初の m − 1 個の辺の積)。"""
    out = _Q(1)
    for l, h in box[:-1]:
        out *= h - l
    return out


# --- 時計の形 (点の θ) ---

def point_shape(period, rotation, widths, shares):
    """点の θ = (ρ, w, f) の時計の形 {"period", "starts" (区切りの始まり、昇順、[0, 1)), "multipliers" (f_j / w_j)}。区切り j は
    ρ + w_1 + … + w_{j−1} (mod 1) から幅 w_j (K40 決定 2)。`f_update2._clock_choices` (点の事前) と積分の代表点が同じこれを使う。"""
    edge, segments = rotation, []
    for w, f in zip(widths, shares):
        segments.append((edge % 1, f / w))
        edge += w
    segments.sort()
    return {"period": period, "starts": [s for s, _r in segments], "multipliers": [r for _s, r in segments]}


def share_of(shape, lo, hi):
    """∫_{[lo, hi)} c(φ) dφ (lo > hi は [lo, 1) ∪ [0, hi)、決定 15 ②) の厳密な値。"""
    if lo > hi:
        return share_of(shape, lo, _Q(1)) + share_of(shape, _Q(0), hi)
    starts, rates = shape["starts"], shape["multipliers"]
    edges = [_Q(0), *starts, _Q(1)]
    heights = [rates[-1], *rates]
    return sum((h * (min(hi, r) - max(lo, l)) for l, r, h in zip(edges, edges[1:], heights) if min(hi, r) > max(lo, l)),
               _Q(0))


# --- 回転 ρ の解析的な積分 (決定 14) ---

class _RPoly:
    """Σ c · ρ^k · exp(−(q0 + q1 ρ)) (c, q0, q1 は有理数、k は非負の整数)。terms は {(q0, q1): {k: c}}。"""
    __slots__ = ("terms",)

    def __init__(self, terms=None):
        self.terms = {key: {k: c for k, c in poly.items() if c} for key, poly in (terms or {}).items()}
        self.terms = {key: poly for key, poly in self.terms.items() if poly}

    @staticmethod
    def const(c):
        return _RPoly({(_Q(0), _Q(0)): {0: _Q(c)}})

    @property
    def zero(self):
        return not self.terms

    def __add__(self, other):
        out = {key: dict(poly) for key, poly in self.terms.items()}
        for key, poly in other.terms.items():
            target = out.setdefault(key, {})
            for k, c in poly.items():
                target[k] = target.get(k, 0) + c
        return _RPoly(out)

    def __sub__(self, other):
        return self + other.scale(-1)

    def scale(self, r):
        return _RPoly({key: {k: c * r for k, c in poly.items()} for key, poly in self.terms.items()}) if r else _RPoly()

    def __mul__(self, other):
        out = {}
        for (a0, a1), p in self.terms.items():
            for (b0, b1), q in other.terms.items():
                target = out.setdefault((a0 + b0, a1 + b1), {})
                for i, c in p.items():
                    for j, d in q.items():
                        target[i + j] = target.get(i + j, 0) + c * d
        return _RPoly(out)

    def integrate(self, lo, hi):
        """∫_lo^hi … dρ を指数多項式 (`_fb_time.Poly`) で厳密に。"""
        from math import factorial
        from ._fb_time import Poly
        out = {}

        def put(q, c):
            out[q] = out.get(q, 0) + c
        for (q0, q1), poly in self.terms.items():
            for k, c in poly.items():
                if not q1:
                    put(q0, c * (hi ** (k + 1) - lo ** (k + 1)) / (k + 1))
                    continue
                for j in range(k + 1):   # 原始関数 −e^{−q0−q1ρ} Σ_j k!/(k−j)! ρ^{k−j} / q1^{j+1}
                    coef = c * factorial(k) / factorial(k - j) / q1 ** (j + 1)
                    put(q0 + q1 * hi, -coef * hi ** (k - j))
                    put(q0 + q1 * lo, coef * lo ** (k - j))
        return Poly(out)

    def derivative(self):
        """d/dρ (c ρ^k e^{−q0−q1ρ} の和) = c (k ρ^{k−1} − q1 ρ^k) e^{−q0−q1ρ} の和。"""
        out = {}
        for key, poly in self.terms.items():
            target = out.setdefault(key, {})
            for k, c in poly.items():
                if k:
                    target[k - 1] = target.get(k - 1, 0) + c * k
                target[k] = target.get(k, 0) - c * key[1]
        return _RPoly(out)

    def value(self, rho, bits):
        """ρ (有理数) での値の上下界。"""
        from ._fb_time import _exp_neg
        lo = hi = _Q(0)
        for (q0, q1), poly in self.terms.items():
            p = sum((c * rho ** k for k, c in poly.items()), _Q(0))
            a, b = _exp_neg(q0 + q1 * rho, bits)
            lo, hi = (lo + p * a, hi + p * b) if p > 0 else (lo + p * b, hi + p * a)
        return _down(lo, bits), _up(hi, bits)

    def range(self, a, b, bits):
        """0 ≤ a ≤ ρ ≤ b での値の上下界 (項ごとに ρ^k と e^{−q0−q1ρ} の端で包む)。"""
        from ._fb_time import _exp_neg
        lo = hi = _Q(0)
        for (q0, q1), poly in self.terms.items():
            ea, eb = _exp_neg(q0 + q1 * a, bits), _exp_neg(q0 + q1 * b, bits)
            e = (min(ea[0], eb[0]), max(ea[1], eb[1]))
            for k, c in poly.items():
                r = (a ** k, b ** k)
                t = (c * r[0] * e[0], c * r[1] * e[1]) if c > 0 else (c * r[1] * e[1], c * r[0] * e[0])
                lo, hi = lo + t[0], hi + t[1]
        return _down(lo, bits), _up(hi, bits)


def _affine(a, b):
    """a + b ρ の _RPoly。"""
    return _RPoly({(_Q(0), _Q(0)): {0: a, 1: b}})


def _poisson_power(x0, x1, n):
    """e^{−x} x^n / n! (x = x0 + x1 ρ) の _RPoly。"""
    from math import comb, factorial
    poly = {k: comb(n, k) * x0 ** (n - k) * x1 ** k / factorial(n) for k in range(n + 1)}
    return _RPoly({(x0, x1): poly})


def _rmatrix(x, C, kernel=None, weight=None, height=None, span=None):
    """`_fb_time._poisson_matrix` の ρ の関数の版。x = (x0, x1) は累積の率の差 x0 + x1 ρ。kernel のある時は、判定の時刻が小区間に
    ある確率 weight = (w0, w1) (小区間の長さ / 取得区間の長さ) を先に掛ける: s1 = (1 − Σ_{i≤n0} p(i)) / x の 1/x は、
    weight · (1/x) = 1 / (height · span) (height = 小区間の上の率、span = 取得区間の長さ) で消える (height = 0 は x = 0)。"""
    one = _RPoly.const(1)
    m = [[_RPoly() for _ in range(C + 1)] for _ in range(C + 1)]
    p = [_poisson_power(x[0], x[1], n) for n in range(C + 2)]
    w = one if weight is None else _affine(*weight)

    def survive(n0):
        out = one
        for n in range(n0):
            out = out - p[n]
        return out

    def s1(n0):   # weight × Σ_{n≥n0} e^{−x} x^n / (n+1)!
        if not height:
            return _RPoly()
        out = one
        for i in range(n0 + 1):
            out = out - p[i]
        return out.scale(1 / (height * span))

    for k in range(C):
        for j in range(k, C):
            n = j - k
            if kernel is None:
                m[j][k] = p[n]
            else:
                c, taken = kernel
                count = max(0, j - max(k, c + 1) + 1) if taken else max(0, min(j, c) - k + 1)
                m[j][k] = (p[n] * w).scale(_Q(count, n + 1))
        n0 = C - k
        if kernel is None:
            m[C][k] = survive(n0)
        else:
            c, taken = kernel
            m[C][k] = survive(n0) * w - s1(n0).scale(max(0, c + 1 - k)) if taken else s1(n0).scale(max(0, c - k + 1))
    m[C][C] = (one if kernel is None else w) if kernel is None or kernel[1] else _RPoly()
    return m


def _rapply(m, v):
    out = []
    for j in range(len(m)):
        total = _RPoly()
        for k in range(len(v)):
            if not v[k].zero and not m[j][k].zero:
                total = total + m[j][k] * v[k]
        out.append(total)
    return out


def rotation_integral(unit, entries, terminal_ns, C, selector, period, widths, shares):
    """∫_0^1 g(h, ρ, w, f) dρ (w・f は点、ρ は [0, 1) の一様、決定 14) を指数多項式で厳密に。ρ の [0, 1) を、区切りの境目が時刻 0・
    取得の端・(件数の照会なら) 終わりの時刻・(割合の照会なら) 区間の端を通る所で分けると、各小区間の中で累積の率・区切りの
    境目の時刻・判定の小区間の長さは ρ の一次式で、尤度は「ρ の多項式 × ρ の一次式の指数」の有限和になり、解析的に積分できる。
    一次式は小区間の中の 2 点の有理数の値から作る (構造が同じ間は一次式なので厳密)。"""
    total = None
    for lo, hi in _pieces(unit, entries, terminal_ns, selector, period, widths):
        r1, r2 = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
        piece = _rotation_piece(unit, entries, terminal_ns, C, selector, period, widths, shares, r1, r2)
        part = piece.integrate(lo, hi)
        total = part if total is None else total + part
    return total


def _pieces(unit, entries, terminal_ns, selector, period, widths):
    """ρ の [0, 1) を、構造が同じ (被積分の量が _RPoly 1 つで書ける) 小区間に分けた端の組の列 (`rotation_integral`)。"""
    law = unit["law"]
    origin, scale = law["origin_ns"], law["time_unit"]
    times = [_Q(0)]
    for e in entries:
        if e["kind"] != "step":
            times += [(e["before_ns"] - origin) * scale, (e["after_ns"] - origin) * scale]
    if selector is not None and selector[0] in ("eq", "ge"):
        times.append((terminal_ns - origin) * scale)
    starts, edge = [], _Q(0)
    for w in widths:
        starts.append(edge)
        edge += w
    phases = [t / period for t in times]
    if selector is not None and selector[0] == "share":
        phases += [selector[1], selector[2]]
    cuts = sorted({_Q(0), _Q(1), *(((x - s) % 1) for x in phases for s in starts)})
    return list(zip(cuts, cuts[1:]))


def _rotation_piece(unit, entries, terminal_ns, C, selector, period, widths, shares, r1, r2):
    """ρ の小区間 (構造が同じ間) の被積分の量を _RPoly で。時刻は (r1 での値, r2 での値) の組で持ち (取得の端は固定、区切りの境目は
    ρ と一緒に動く)、累積の率・長さを 2 点の値から一次式にする。"""
    from ._fb_time import _UNREAD, _clock_cuts, _clock_integral, _source_factor
    law = unit["law"]
    rate, origin, scale = law["rate"], law["origin_ns"], law["time_unit"]
    s1, s2 = point_shape(period, r1, widths, shares), point_shape(period, r2, widths, shares)

    def lin(a, b):   # 2 点の値から一次式 (x0, x1)
        slope = (b - a) / (r2 - r1)
        return a - slope * r1, slope

    def X(p):   # 時刻の組 p での累積の率の一次式
        return lin(rate * _clock_integral(s1, p[0]), rate * _clock_integral(s2, p[1]))

    def diff(x, y):
        return x[0] - y[0], x[1] - y[1]

    def evolve(v, x):
        return _rapply(_rmatrix(x, C), v) if x[0] or x[1] else v
    v = [_RPoly() for _ in range(C + 1)]
    v[min(law["initial_count"], C)] = _RPoly.const(1)
    t = (_Q(0), _Q(0))
    for e in entries:
        if e["kind"] == "step":
            v = [y.scale(e["factors"][unit["index"]]) for y in v]
            continue
        b, a = (e["before_ns"] - origin) * scale, (e["after_ns"] - origin) * scale
        B, A = (b, b), (a, a)
        v = evolve(v, diff(X(B), X(t)))
        if e["symbol"] in _UNREAD:
            v = evolve(v, diff(X(A), X(B)))
        else:
            kernel = (e["cursor"], e["symbol"] == "taken")
            if a == b:
                v = _rapply(_rmatrix((_Q(0), _Q(0)), C, kernel), v)
            else:
                pts = list(zip(_clock_cuts(s1, b, a), _clock_cuts(s2, b, a)))
                out = [_RPoly() for _ in v]
                for left, right in zip(pts, pts[1:]):
                    span1 = right[0] - left[0]
                    height = (rate * _clock_integral(s1, right[0]) - rate * _clock_integral(s1, left[0])) / span1
                    length = lin(span1, right[1] - left[1])
                    weight = (length[0] / (a - b), length[1] / (a - b))
                    inside = _rapply(_rmatrix(diff(X(right), X(left)), C, kernel, weight, height, a - b),
                                     evolve(v, diff(X(left), X(B))))
                    out = [o + y for o, y in zip(out, evolve(inside, diff(X(A), X(right))))]
                v = out
        v = [y.scale(_source_factor(unit, e["symbol"])) for y in v]
        t = A
    s = selector
    if s is not None and s[0] in ("eq", "ge"):
        end = (terminal_ns - origin) * scale
        v = evolve(v, diff(X((end, end)), X(t)))
        picked = [v[s[1]]] if s[0] == "eq" else v[s[1]:]
    else:
        picked = v
    out = _RPoly()
    for y in picked:
        out = out + y
    if s is not None and s[0] == "share":
        out = out * _affine(*lin(share_of(s1, s[1], s[2]), share_of(s2, s[1], s[2])))
    return out


# --- 1 つの unit の積分 ---

class Integral:
    """unit 1 つの ∫ g(h, θ) Π(dθ | T, m) の上下界 (決定 7)。selector は積分する量: None = 尤度 (全件数)、("eq", k)・("ge", k) =
    件数の類 N = k・N ≥ k と原記録の同時の確率、("share", lo, hi) = 尤度 × 区間 [lo, hi) に配る 1 周の割合 ∫ c_θ (決定 15 ②)。
    積分は変わらない記述で、照会の間で共有する (`_fb_time._Space.integral`)。精度で変わる計算表 (箱の列) は照会ごとの別々の値
    (`table`)。共有するのは、計算表が通った段の完成した上下界だけ (`levels`、(精度, 段) を名前にした変わらない値、紙 F-b K40-k)。"""

    def __init__(self, unit, entries, terminal_ns, selector):
        from . import _fb_time as ft
        law = unit["law"]
        clock = law["clock"]
        self.unit, self.entries, self.terminal_ns, self.selector = unit, entries, terminal_ns, selector
        self.period, self.m = clock["period"], clock["segments"]
        self.rho0, self.w0, self.f0 = clock["rotation"], clock["widths"], clock["shares"]
        self.kw, self.kf = clock["width_concentration"], clock["share_concentration"]
        self.rate = law["rate"]
        origin, scale = law["origin_ns"], law["time_unit"]
        F = _Q(1)
        cursors, horizon = [], _Q(0)
        for e in entries:
            if e["kind"] == "step":
                F *= e["factors"][unit["index"]]
            else:
                F *= ft._source_factor(unit, e["symbol"])
                cursors.append(e["cursor"])
                horizon = max(horizon, (e["after_ns"] - origin) * scale)
        need = selector[1] + 1 if selector is not None and selector[0] in ("eq", "ge") else 0
        self.C = max([*(c + 1 for c in cursors), need + 1, 1])
        if selector is not None and selector[0] in ("eq", "ge"):
            horizon = (terminal_ns - origin) * scale   # 終わりの件数は終わりまでの到着で決まる
        self.F, self.horizon = F, horizon
        self.turns = -((-horizon) // self.period)   # ⌈H / T⌉
        self.constant = not self.rate or not any(self._reads())   # 尤度が θ によらないと構造から証明した
        self.groups = self._groups()
        self.dims = (([("w", j) for j in range(self.m - 1)] if self.w0 is None else [])
                     + ([("f", j) for j in range(len(self.groups) - 1)] if self.f0 is None else []))
        self.levels = {}   # (数の精度の bits, 段) → 完成した上下界 (`_Table.at`)
        share = selector is not None and selector[0] == "share"
        self.blind = self.constant and not share   # 被積分の量が θ によらない (考える側の判定、`_fb_time._flat`)
        self.exact = None
        if self.constant and (not share or self.rho0 is None or self.f0 is None):
            # 尤度が θ によらなければ、積分は尤度 × 事前の期待値。割合の事前の期待値は、ρ が一様 (回すと c の平均は 1) か f が
            # 連続 (E[f_j | w] = w_j) なら、どの w・f でも区間の長さ
            self.exact = self._point_value(self._interior_point())
            if share:
                lo, hi = selector[1], selector[2]
                self.exact = self.exact.scale(hi - lo if lo <= hi else 1 - lo + hi)
        elif not self.dims:   # 残る座標が無い (ρ だけ連続なら解析的な積分): 厳密
            self.exact = self._value(self._interior_point())

    def table(self, num):
        """数の精度 num (`Num`) の計算表 (`_Table`)。呼ぶ側の照会が作って自分だけで使う。"""
        return _Table(self, num)

    def _steps(self, level):
        """計算表が通る段: FIRST_LEVEL から倍にして level まで。"""
        step = FIRST_LEVEL
        yield step
        while step * 2 <= level:
            step *= 2
            yield step

    def _bound(self, step, table):
        """段 step の上下界: 計算表の箱を step 個まで分けた上下界。"""
        table.refine(step)
        return table.bounds()

    # 点の w・f の量 (ρ が連続なら ρ を解析的に積分した値。割合の照会は割合を掛けた値)
    def _value(self, theta):
        if self.rho0 is None:
            return rotation_integral(self.unit, self.entries, self.terminal_ns, self.C, self.selector, self.period,
                                     theta[1], theta[2])
        value = self._point_value(theta)
        s = self.selector
        if s is not None and s[0] == "share":
            value = value.scale(share_of(point_shape(self.period, *theta), s[1], s[2]))
        return value

    # 点の θ の尤度 (割合を掛けない)
    def _point_value(self, theta):
        from . import _fb_time as ft
        rho, w, f = theta
        unit = {**self.unit, "law": {**self.unit["law"], "clock": point_shape(self.period, rho, w, f)}}
        v = ft._poisson(unit, self.entries, self.terminal_ns, self.C)
        s = self.selector
        if s is None or s[0] == "share":
            return sum(v, ft.Poly())
        return v[s[1]] if s[0] == "eq" else sum(v[s[1]:], ft.Poly())

    def _interior_point(self):
        m = self.m
        w = self.w0 if self.w0 is not None else tuple(_Q(1, m) for _ in range(m))
        f = self.f0 if self.f0 is not None else w
        return (self.rho0 if self.rho0 is not None else _Q(0), w, f)

    def positive(self):
        """積分が正か (形で 0 なら False)。内部の 1 点の指数多項式で決まる (モジュールの説明)。区間の長さ 0 の割合は 0。"""
        s = self.selector
        if s is not None and s[0] == "share" and s[1] == s[2]:
            return False
        return not self._point_value(self._interior_point()).zero

    def _reads(self):
        """尤度が時計の形に依る所 (決定 6・14): 読む位相 (取得の端と、件数の照会の終わりの時刻の 1 周の中の位置。0 は除く) の集合と、
        中を読む取得 (判定の時刻が区間の中の一様) の位相の区間 (始まり, 長さ) の列。尤度は、累積 C(x) = ∫_0^x c (n 周の分は形に
        よらない) を読む位相で読んだ値と、中を読む区間の上の形にだけ依る。どちらも無ければ尤度は θ によらない。"""
        from ._fb_time import _UNREAD
        law = self.unit["law"]
        origin, scale, T = law["origin_ns"], law["time_unit"], self.period

        def phase(t):
            x = t / T
            return x - x.numerator // x.denominator
        s = self.selector
        times = [(self.terminal_ns - origin) * scale] if s is not None and s[0] in ("eq", "ge") else []
        spans = []
        for e in self.entries:
            if e["kind"] == "step":
                continue
            b, a = (e["before_ns"] - origin) * scale, (e["after_ns"] - origin) * scale
            times += [b, a]
            if e["symbol"] not in _UNREAD and a != b:
                spans.append((phase(b), (a - b) / T))
        return {phase(t) for t in times} - {_Q(0)}, spans

    def _groups(self):
        """配分 f の座標のまとめ (決定 14: 解析的に先に計算できる所は先に)。ρ・w が点なら区切りの位置は決まり、C(x) は f の一次式
        (区切り j の係数は、j のうち [0, x) に入る割合)。全部の読む位相 (割合の照会は区間の端も) で係数が同じで、中を読む区間に
        触れない区切りどうしは、和だけが被積分の量に効く。f | w ~ Dirichlet(κ_f w) の和の組は Dirichlet(κ_f Σw) (集約の性質、事前は
        そのまま) なので、箱はまとめた和の座標だけで割る。まとめは区切りの番号の組の列 (ρ か w が連続・f が点なら 1 つずつ)。"""
        if self.f0 is not None or self.w0 is None or self.rho0 is None:
            return tuple((j,) for j in range(self.m))
        phases, spans = self._reads()   # 率によらない (同じ θ の空間の unit は同じまとめ、`Information`)
        s = self.selector
        if s is not None and s[0] == "share":
            phases |= {s[1], s[2]} - {_Q(0)}

        def overlap(lo, hi, start, width):   # [lo, hi) と区切り (位相 start から幅 width、1 周ごとにくり返す) の重なりの長さ
            return sum((max(_Q(0), min(hi, start + k + width) - max(lo, start + k)) for k in range(-1, int(hi) + 2)), _Q(0))
        out, edge = {}, self.rho0
        for j, width in enumerate(self.w0):
            start, edge = edge % 1, edge + width
            if any(overlap(p, p + length, start, width) for p, length in spans):
                key = ("inside", j)
            else:
                key = tuple(overlap(_Q(0), x, start, width) / width for x in sorted(phases))
            out.setdefault(key, []).append(j)
        return tuple(tuple(g) for g in out.values())

    # 箱
    def _intervals(self, box):
        """箱の座標の区間から ρ・w (m 個)・f の和の組 g (まとめごと、`_groups`)・f (m 個) の区間と代表点。最後の成分は 1 − 残りの和。
        まとめた区切りの f は、まとめの和を w の比で分けた値 (被積分の量は和だけに依るので、どう分けても同じ)。"""
        it = iter(box)
        rho = (_Q(0), _Q(0)) if self.rho0 is None else (self.rho0, self.rho0)   # ρ は箱にしない (解析的、または点)

        def simplex(point, n):
            if point is not None:
                return [(x, x) for x in point], list(point)
            coords = [next(it) for _ in range(n - 1)]
            last = (1 - sum(h for _l, h in coords), 1 - sum(l for l, _h in coords))
            mid = [(l + h) / 2 for l, h in coords]
            return [*coords, last], [*mid, 1 - sum(mid)]
        w, wc = simplex(self.w0, self.m)
        g, gc = simplex(self.f0, len(self.groups))
        f, fc = [None] * self.m, [None] * self.m
        for group, (l, h), c in zip(self.groups, g, gc):
            total = sum(wc[j] for j in group)
            for j in group:
                r = 1 if len(group) == 1 else wc[j] / total
                f[j], fc[j] = (l * r, h * r), c * r
        return rho, w, g, f, ((rho[0] + rho[1]) / 2, tuple(wc), tuple(fc))

    def _distance(self, rho, w, f, theta):
        """箱の中の θ と代表点 θ0 の時計の形の差の L1 (1 周) の上界 A ≤ 2 (決定 7 の D の材料)。同じ区切りの中は高さの差 × 幅の上端、
        境目の動く帯 (境目の位置の区間の長さ) では高さの上端。"""
        m = self.m
        if any(l <= 0 for l, _h in w):
            return _Q(2)
        h0 = [theta[2][j] / theta[1][j] for j in range(m)]
        hi = [f[j][1] / w[j][0] for j in range(m)]
        lo = [f[j][0] / w[j][1] for j in range(m)]
        core = sum((w[j][1] * max(hi[j] - h0[j], h0[j] - lo[j]) for j in range(m)), _Q(0))
        top = max(hi)
        zones = rho[1] - rho[0]
        a_lo = a_hi = _Q(0)
        for j in range(m - 1):
            a_lo, a_hi = a_lo + w[j][0], a_hi + w[j][1]
            zones += (rho[1] + a_hi) - (rho[0] + a_lo)
        return min(_Q(2), core + zones * top)

    def _mass(self, w, f, num):
        """箱の事前の質量の上下界 P(w ∈ 箱) · [inf, sup]_{w ∈ 箱} P(f ∈ 箱 | w) (f は和の組 g、`_groups`: g | w ~ Dirichlet(κ_f Σw))。
        単体の境目に触れる座標は、下界 0・上界は周辺の Beta の下側の確率 (決定 13)。内部は密度の上下界 × 体積。"""
        bits, m = num.bits, self.m
        if self.w0 is None and w[-1][1] <= 0 or self.f0 is None and f[-1][1] <= 0:
            return _Q(0), _Q(0)   # 単体の外
        w_lo = w_hi = f_lo = f_hi = _Q(1)
        if self.w0 is None:
            if any(l <= 0 for l, _h in w):
                w_lo, w_hi = _Q(0), min(num.lower_tail(h, self.kw, (m - 1) * self.kw) for l, h in w if l <= 0)
            else:
                c = num.dirichlet_norm([self.kw] * m, [self.kw] * m)
                w_lo, w_hi = c[0] * _volume(w), c[1] * _volume(w)
                for l, h in w:
                    p = num.pow_box(l, h, self.kw - 1)
                    w_lo, w_hi = _down(w_lo * p[0], bits), _up(w_hi * p[1], bits)
        if self.f0 is None and w_lo == 0 and self.w0 is None:
            f_hi = _Q(1)   # w が境目に触れる箱は f を分けない (`refine`): f の質量は 1 以下
        elif self.f0 is None:
            alpha_lo = [self.kf * sum(max(w[j][0], _Q(0)) for j in group) for group in self.groups]
            alpha_hi = [self.kf * sum(w[j][1] for j in group) for group in self.groups]
            if any(l <= 0 for l, _h in f):   # f_j | w ~ Beta(κ_f w_j, κ_f (1 − w_j)): 箱の中の w の上限 (`_tail_sup`)
                f_lo = _Q(0)
                f_hi = min(self._tail_sup(h, a_lo, a_hi, num) for (l, h), a_lo, a_hi in zip(f, alpha_lo, alpha_hi)
                           if l <= 0)
            else:
                c = num.dirichlet_norm(alpha_lo, alpha_hi)
                f_lo, f_hi = c[0] * _volume(f), c[1] * _volume(f)
                for (l, h), a_lo, a_hi in zip(f, alpha_lo, alpha_hi):
                    p = num.pow_corners(l, h, a_lo - 1, a_hi - 1)
                    f_lo, f_hi = _down(f_lo * p[0], bits), _up(f_hi * p[1], bits)
        return _down(w_lo * f_lo, bits), _up(w_hi * min(_Q(1), f_hi), bits)

    def _tail_sup(self, x, a_lo, a_hi, num):
        """箱の中の w について、P(f_j ≤ x | w) の上界の上限: x^a / a は a について減る (上は a_lo)、1/B(a, b) は増える (上は
        a_hi・b_hi)、(1 − x)^{b−1} は b について減る (上は b_lo)。b = κ_f − a。"""
        if x >= 1:
            return _Q(1)
        kf = self.kf
        b_lo, b_hi = kf - a_hi, kf - a_lo
        if a_lo <= 0 or b_lo <= 0:
            return _Q(1)
        p = num.pow(x, a_lo)[1] / a_lo
        q = max(_Q(1), num.pow(1 - x, b_lo - 1)[1])
        return min(_Q(1), _up(p * q * num.inverse(*num.beta(a_hi, b_hi))[1], num.bits))

    def _evaluate(self, box, num):
        """箱の事前の質量の上下界 (μ_lo, μ_hi) と、箱の中の被積分の量の上下界 (V_lo, V_hi)。"""
        rho, w, g, f, theta = self._intervals(box)
        m_lo, m_hi = self._mass(w, g, num)
        if not m_hi:
            return None
        if any(x <= 0 for x in (*theta[1], *theta[2])):   # 代表点が単体の外 (箱が単体の境目で切れる): 尤度は [0, F]
            return m_lo, m_hi, _Q(0), self.F
        A = self._distance(rho, w, f, theta)   # 同じ ρ どうしの差 (ρ の帯は 0)
        delta = 0 if self.constant else min(_Q(1), self.rate * self.period * self.turns * A)
        s = self.selector
        if s is not None and s[0] == "share":   # |L g − L0 g0| ≤ |L − L0| g + L0 |g − g0| ≤ F (δ + A)
            delta = delta + A
        V = self._value(theta).enclose(num.bits)
        return m_lo, m_hi, max(_Q(0), V[0] - self.F * delta), min(self.F, V[1] + self.F * delta)

    def _splittable(self, box):
        """分ける座標。w が単体の境目に触れる箱は f の座標を分けない (その箱の質量の上界は w の周辺の下側の確率だけで決まり、f で
        分けても縮まない。f の密度は w → 0 で κ_f w_j → 0 の端に寄り、箱ごとの上界が足し合わさって 1 を超える)。"""
        if self.w0 is None and self.f0 is None and any(l <= 0 for l, _h in self._intervals(box)[1]):
            return [i for i, d in enumerate(self.dims) if not (isinstance(d, tuple) and d[0] == "f")]
        return range(len(box))


class _Table:
    """1 つの積分の、1 つの数の精度 num での計算表 (紙 F-b K40-k)。照会が作って自分だけで使う作業で、ほかの照会と共有しない:
    ある精度の照会が別の精度の表を消さず、途中で例外で止まった表は作った照会と一緒に捨てられる。照会の間で共有するのは、通った段の
    完成した上下界だけ (`Integral.levels`、(精度, 段) を名前にした変わらない値)。箱は加えるたびに一番幅の広い箱を座標の一番長い辺で
    2 つに分ける。"""

    def __init__(self, integral, num):
        self.integral, self.num = integral, num
        self.heap, self.boxes, self.serial, self.ends = None, {}, 0, {}   # heap は最初に分ける時に根の箱から

    def at(self, level):
        """箱の数 level (FIRST_LEVEL から倍にした段) での上下界。段は下から順に通り、通った段の上下界を控えるので、上下界は
        (式, 段, 精度) だけで決まる (前に細かく分けた呼び方の歴史・どの照会が先に控えたかに依らない。F-a の評価の作り直しで同じ数
        になる)。正の量の下界が 0 から分けられなければ `_EnclosureShort` (呼ぶ側が予算の中で精度を上げるか incomplete)。"""
        it, bits = self.integral, self.num.bits
        if it.exact is not None:
            return it.exact.enclose(bits)
        for step in it._steps(level):
            out = it.levels.get((bits, step))
            if out is None:
                out = it.levels.setdefault((bits, step), it._bound(step, self))
        return out

    def _push(self, box):
        value = self.integral._evaluate(box, self.num)
        if value is None:
            return
        self.serial += 1
        m_lo, m_hi, v_lo, v_hi = value
        self.boxes[self.serial] = value
        width = m_hi * v_hi - m_lo * v_lo
        if width > 0:
            heapq.heappush(self.heap, (-width, self.serial, box))

    def refine(self, regions):
        """箱の数が regions に届くまで (または全部の箱の幅が 0 になるまで) 分ける。"""
        if self.heap is None:
            self.heap = []
            self._push(tuple((_Q(0), _Q(1)) for _ in self.integral.dims))
        while len(self.boxes) < regions and self.heap:
            _width, n, box = heapq.heappop(self.heap)
            del self.boxes[n]
            k = max(self.integral._splittable(box), key=lambda i: box[i][1] - box[i][0])
            l, h = box[k]
            mid = (l + h) / 2
            for part in ((l, mid), (mid, h)):
                self._push(box[:k] + (part,) + box[k + 1:])

    def bounds(self):
        """積分の上下界。箱の質量の和はちょうど 1 なので、∫ = Σ μ_k V_k を「μ_lo ≤ μ ≤ μ_hi・Σ μ = 1」の上で最大・最小にした値で
        包む (下界の質量の残りを、上界は V_hi の大きい箱から、下界は V_lo の小さい箱から配る)。"""
        boxes = list(self.boxes.values())

        def extreme(index, reverse):
            rest = 1 - sum(b[0] for b in boxes)
            total = sum((b[0] * b[index] for b in boxes), _Q(0))
            for b in sorted(boxes, key=lambda b: b[index], reverse=reverse):
                if rest <= 0:
                    break
                give = min(rest, b[1] - b[0])
                total, rest = total + give * b[index], rest - give
            return total
        return _down(extreme(2, False), self.num.bits), _up(extreme(3, True), self.num.bits)


# --- 考える側の情報量の積分 (紙 F-b K40 決定 8・K40-g) ---

def _phi(cells, num, upper):
    """φ(c) = Σ_y c_y ln(Σc / c_y) (正規化しない条件つきのエントロピー) の、非負の有理数のベクトル c での下界 (upper=False)・
    上界。φ は各 c_y について増える (∂φ/∂c_y = ln(Σc / c_y) ≥ 0) ので、c の箱の下端・上端での値が、箱の上の φ の下界・上界。"""
    s = sum(cells, _Q(0))
    out = _Q(0)
    for c in cells:
        if c > 0:
            lo, hi = num.log(s / c)
            out += c * (hi if upper else lo)
    return _up(out, num.bits) if upper else _down(out, num.bits)


class Information(Integral):
    """考える側の情報量の積分 ∫ φ(c(θ)) Π(dθ | T, m) (紙 F-b K40 決定 8・K40-g)。c_y(θ) = Σ_k a_yk L_k(h | θ) は、同じ θ の空間の
    unit k の尤度 (selector なし) に、一歩の結果の類 y ごとの非負の係数を掛けて足したもの (同じ知る対象の状態を θ ごとにまとめた
    P(Y | Q, h) の、正規化しない形)。φ は 0 ≤ φ(c) ≤ (Σc) log|Y| に収まり、各 c_y について増え、凹で 1 次の斉次。
    回転だけが連続 (w・f は点) なら、ρ の構造が同じ小区間ごとに c が _RPoly で書ける (決定 14)。小区間を 1/level の格子で切った
    各区間 [a, b] で、上界は凹と斉次から ∫φ(c) ≤ φ(∫c) (Jensen、∫c は厳密)、下界は台形の値から (b − a)³/12 × sup g'' を引く
    (g = φ∘c、g'' = Σ_y c_y'' ln(Σc / c_y) + ((Σc')²/Σc − Σ c_y'²/c_y) ≤ Σ_y c_y'' ln(Σc / c_y))。c が 0 から離れず g'' を包めない
    区間は (b − a) × φ(c の下端)。w・f が連続なら (ρ が一様なら ρ も) 座標の箱に分け、箱ごとに事前の質量の上下界 ×
    [φ(c の下端), φ(c の上端)] (c の上下界は `Integral._evaluate` と同じ、代表点の尤度と率の差の積分の上界)。どちらも箱・区間を
    倍にしていく段の上下界で、届かない幅は呼ぶ側の精度の確かめが incomplete にする (P10: 包んだ幅を信念にしない)。"""

    def __init__(self, parts, cells):
        first = parts[0]
        for name in ("period", "m", "rho0", "w0", "f0", "kw", "kf", "groups"):
            setattr(self, name, getattr(first, name))
        self.parts, self.cells = parts, [tuple(row) for row in cells]
        self.selector, self.exact, self.levels = None, None, {}
        self.dims = ([("rho",)] if self.rho0 is None else []) + list(first.dims)
        self.rotation = self.rho0 is None and not first.dims
        if not self.rotation:
            return
        self.pieces = []
        cuts = sorted({x for p in parts for piece in _pieces(p.unit, p.entries, p.terminal_ns, None, p.period, p.w0)
                       for x in piece})
        for lo, hi in zip(cuts, cuts[1:]):
            r1, r2 = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
            polys = [_rotation_piece(p.unit, p.entries, p.terminal_ns, p.C, None, p.period, p.w0, p.f0, r1, r2)
                     for p in parts]
            cells = [c for c in (sum((q.scale(a) for q, a in zip(polys, row)), _RPoly()) for row in self.cells)
                     if not c.zero]
            self.pieces.append((lo, hi, cells, [c.derivative().derivative() for c in cells]))

    def positive(self):
        """積分が正か: 内部の θ では尤度の支持が θ によらない (モジュールの説明) ので、内部の 1 点で正の類が 2 つ以上なら φ は
        内部の全体で正、そうでなければ 0。"""
        from ._fb_time import Poly
        theta = self.parts[0]._interior_point()
        values = [p._point_value(theta) for p in self.parts]
        return sum(1 for row in self.cells if not sum((v.scale(a) for v, a in zip(values, row)), Poly()).zero) >= 2

    def _steps(self, level):
        return (level,) if self.rotation else super()._steps(level)

    def _bound(self, step, table):
        return self._rotation_bounds(step, table) if self.rotation else super()._bound(step, table)

    def _rotation_bounds(self, n, table):
        from math import ceil, floor
        num, bits, low, high = table.num, table.num.bits, _Q(0), _Q(0)
        for index, (lo, hi, cells, second) in enumerate(self.pieces):
            points = [lo, *(_Q(j, n) for j in range(floor(lo * n) + 1, ceil(hi * n))), hi]
            for a, b in zip(points, points[1:]):
                d = b - a
                high += _phi([c.integrate(a, b).enclose(bits)[1] for c in cells], num, True)
                box = [c.range(a, b, bits) for c in cells]
                lower = d * _phi([max(_Q(0), r[0]) for r in box], num, False)
                K = _curvature(box, [s.range(a, b, bits) for s in second], num)
                if K is not None:
                    lower = max(lower, d * (self._end(index, a, table) + self._end(index, b, table)) / 2 - d ** 3 * K / 12)
                low += lower
        return _down(low, bits), _up(high, bits)

    def _end(self, index, rho, table):
        """小区間 index の端 ρ での g = φ(c(ρ)) の下界 (同じ計算表の中で、格子の段をまたいで控える)。"""
        key = (index, rho)
        if key not in table.ends:
            cells = self.pieces[index][2]
            table.ends[key] = _phi([max(_Q(0), c.value(rho, table.num.bits)[0]) for c in cells], table.num, False)
        return table.ends[key]

    def _intervals(self, box):
        if self.rho0 is not None:
            return super()._intervals(box)
        _rho, w, g, f, theta = super()._intervals(box[1:])
        return box[0], w, g, f, ((box[0][0] + box[0][1]) / 2, theta[1], theta[2])

    def _evaluate(self, box, num):
        rho, w, g, f, theta = self._intervals(box)
        m_lo, m_hi = self._mass(w, g, num)
        if self.rho0 is None:
            m_lo, m_hi = m_lo * (rho[1] - rho[0]), m_hi * (rho[1] - rho[0])
        if not m_hi:
            return None
        outside = any(x <= 0 for x in (*theta[1], *theta[2]))
        A = None if outside else self._distance(rho, w, f, theta)
        bounds = []
        for p in self.parts:
            if outside:   # 代表点が単体の外 (箱が単体の境目で切れる): 尤度は [0, F]
                bounds.append((_Q(0), p.F))
                continue
            V = (p.exact if p.blind else p._point_value(theta)).enclose(num.bits)
            delta = 0 if p.blind else min(_Q(1), p.rate * p.period * p.turns * A)
            bounds.append((max(_Q(0), V[0] - p.F * delta), min(p.F, V[1] + p.F * delta)))
        c_lo = [sum((a * v[0] for a, v in zip(row, bounds)), _Q(0)) for row in self.cells]
        c_hi = [sum((a * v[1] for a, v in zip(row, bounds)), _Q(0)) for row in self.cells]
        return m_lo, m_hi, _phi(c_lo, num, False), _phi(c_hi, num, True)


def _curvature(box, second, num):
    """区間の上の sup Σ_y c_y'' ln(Σc / c_y) の上界 (c_y ∈ box_y、c_y'' ∈ second_y)。どれかの c_y が 0 から離れなければ None。"""
    if any(lo <= 0 for lo, _hi in box):
        return None
    total_lo, total_hi = sum(lo for lo, _hi in box), sum(hi for _lo, hi in box)
    K = _Q(0)
    for (lo, hi), (_s_lo, s_hi) in zip(box, second):
        if s_hi > 0:
            K += s_hi * num.log((total_hi - hi + lo) / lo)[1]   # Σc / c_y ≤ 1 + Σ_{y'≠y} hi_y' / lo_y
        else:
            K += s_hi * num.log((total_lo - lo + hi) / hi)[0]   # Σc / c_y ≥ 1 + Σ_{y'≠y} lo_y' / hi_y
    return _up(K, num.bits)
