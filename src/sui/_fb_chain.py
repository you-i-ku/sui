"""観測の間にも変わる調子の、件数と調子の共同の推移 (紙 F-b K41 決定 3〜5)。

調子 S は宣言した固定の生成行列 R で実時間に動き、到着はその時の調子 (と時計の位置) の率で件数を 1 増やす。状態を
(S, min(N, C)) にまとめるのは厳密 (C は使う最大のカーソルより大きい、K38 決定 4)。固有値は一般に有理数でないので、
**一様化**で計算する: 出ていく率の最大以上の有理数 ν をとり、B = I + A/ν (非負の有理数の行列、列の和は 1) の累乗に平均 ν·Δ の
Poisson の重みを掛けて足す。全体の時間 T にわたる因子 e^{−νT} を外に出すと、質量は e^{−νT} · S で、S = Σ_n s_n は非負の
有理数の級数 (n は仮の跳びの総数)。各段の質量は 1 以下の核しか掛けないので s_n の質量は M0 · (νT)^n / n! 以下
(M0 は初期の質量)。だから跳びの数 K までの部分和が下界、残りは Poisson の尾で包める (落とした寄与を消さない、P8・P10)。

幅のある取得 (判定の時刻 U は [b, a] の一様、判定は 1 回) は、仮の跳びが n 回の条件で U の順位が n + 1 通り等しいので
(1/(n+1)) Σ_i B^(n−i) O B^i (紙 K41 決定 4、点検係が検算)。区間の中に率の境目 (時計の区切り) や一歩の読む点があれば、
U が入る小区間の長さの割合で足す (O は 1 回だけ)。一歩は入場の時刻 entered に状態ごとの因子を 1 回掛ける (決定 6)。

構造の 0 は数でなく支えで決める (決定 5): 正の初期の質量から、正の長さの区間の正の率の辺と、各観測が許す状態をたどる。
"""
from __future__ import annotations

from fractions import Fraction as _Q
from math import factorial as _factorial

_UNAVAILABLE = "unavailable_called"
_MISSING = "unavailable_missing"
_UNREAD = (_UNAVAILABLE, _MISSING)


class Group:
    """1 つの遷移の群 (候補 × 枝 z × 時計の形) の、作り直せる記述。rates[s] はスイッチを当てた後の状態 s の到着の率、R は
    生成行列の非対角 (R[s][s2] は s → s2 の率)、clock は点の時計の形 (`_fb_clock.point_shape`) か None、priors は初期の状態の
    重み (並びの事前)、factors_of(entry) は一歩の状態ごとの因子の列、source(entry) は取得の状態に依らない因子。"""

    def __init__(self, *, rates, R, clock, origin_ns, time_unit, initial_count, priors, entries, terminal_ns,
                 factors, source, C):
        self.rates, self.R, self.clock = tuple(rates), tuple(tuple(r) for r in R), clock
        self.origin, self.scale, self.n0 = origin_ns, time_unit, initial_count
        self.priors, self.entries, self.terminal_ns = tuple(priors), entries, terminal_ns
        self.factors, self.source, self.C = factors, source, C
        self.S = len(self.rates)
        heights = (1,) if clock is None else tuple(clock["multipliers"])
        out = [sum(r for s2, r in enumerate(row) if s2 != s) for s, row in enumerate(self.R)]
        # ν: どの時刻でも出ていく率 (遷移 + 到着) 以下の有理数 (K41 決定 4)
        self.nu = max((out[s] + self.rates[s] * max(heights) for s in range(self.S)), default=_Q(0))
        self.events = self._events()
        self._bounds, self._runs, self._coefs = {}, {}, {}   # 完成した値の控え (変わらない値だけ、並行に読んでよい)

    # --- 時刻の列 ---
    def _t(self, ns):
        return (ns - self.origin) * self.scale

    def _events(self):
        """観測を時刻の順に: 取得 (区間) と一歩 (入場の点)。一歩の点が取得の区間の中にあれば、その取得の内側の点にする。"""
        acq = sorted((e for e in self.entries if e["kind"] == "acquisition"), key=lambda e: e["before_ns"])
        steps = sorted((e for e in self.entries if e["kind"] == "step"), key=lambda e: e["start_ns"])
        out, used = [], set()
        for e in acq:
            inner = [s for s in steps if e["before_ns"] < s["start_ns"] < e["after_ns"]]
            used.update(id(s) for s in inner)
            out.append(("acquisition", self._t(e["before_ns"]), self._t(e["after_ns"]), e, inner))
        out += [("step", self._t(s["start_ns"]), self._t(s["start_ns"]), s, []) for s in steps if id(s) not in used]
        return sorted(out, key=lambda x: (x[1], 0 if x[0] == "step" else 1))

    def _rate(self, s, t):
        """時刻 t の後の小区間で状態 s の到着の率 (時計があれば区切りの倍率を掛ける)。"""
        if self.clock is None:
            return self.rates[s]
        return self.rates[s] * _height(self.clock, t)

    def _cuts(self, b, a):
        if self.clock is None or a == b:
            return [b, a]
        from ._fb_time import _clock_cuts
        return list(_clock_cuts(self.clock, b, a))

    # --- 1 回の計算は `_Pass` が持つ (丸めの向き・途中の列)。群は変わらない記述と、完成した値の控えだけを持つ ---

    def _coef(self, t):
        """時刻 t から始まる率が一定の小区間の B = I + A/ν の係数 (状態ごとに: 件数 < C の留まり、件数 C の留まり、遷移の行き先と
        係数、到着の係数)。時計の高さごとに 1 回作る (作った値は変わらない)。ν は出ていく率の最大以上なので、留まりの係数は非負。"""
        h = 1 if self.clock is None else _height(self.clock, t)
        found = self._coefs.get(h)
        if found is None:
            nu, rows = self.nu, []
            for s in range(self.S):
                lam = _Q(self.rates[s] * h)
                leave = sum((r for s2, r in enumerate(self.R[s]) if s2 != s), _Q(0))
                moves = [(s2, _Q(r) / nu) for s2, r in enumerate(self.R[s]) if s2 != s and r]
                rows.append((1 - (leave + lam) / nu, 1 - leave / nu, moves, lam / nu))
            found = self._coefs.setdefault(h, rows)
        return found

    def _observe(self, cursor, taken):
        """判定の対角 O: taken ⇔ 件数 > cursor (K38 決定 2)。"""
        C1 = self.C + 1
        return [int((c > cursor) == taken) for s in range(self.S) for c in range(C1)]

    def _step(self, e):
        f = self.factors(e)
        C1 = self.C + 1
        return [f[s] for s in range(self.S) for _ in range(C1)]

    def run(self, K, g, down, end_ns=None):
        """跳びの数 K までの係数 u[0..K] (状態 × 件数の列ベクトル、2^g 倍した整数、down なら下向きの丸め)。"""
        return _Pass(self, down).run(K, g, end_ns)

    # --- 上下界 ---
    def bounds(self, num, select, end_ns=None):
        """select(状態, 件数) → bool の成分の質量の和の上下界 (`_fb_clock.Num` の精度 num.bits)。跳びの数 K は Poisson の尾が
        2^−(bits+4) 以下になるまで増やす。下界 = e^{−νT} の下界 × 下向きの部分和、上界 = e^{−νT} の上界 × (上向きの部分和 +
        M0 × 尾の上界)。"""
        key = (num.bits, select, end_ns)
        if key in self._bounds:
            return self._bounds[key]
        T = self._t(self.terminal_ns if end_ns is None else end_ns)
        x = self.nu * T
        M0 = sum(self.priors, _Q(0))
        eps = _Q(1, 1 << (num.bits + 4))
        K = int(x) + 1
        while tail_bound(x, K) * M0 > eps:
            K += max(1, K // 4)
        # 格子 2^−g: 丸めの幅が精度より十分細かくなる桁 (粗くても上下界は正しく、幅だけが広がる)
        g = num.bits + 16 + (K * self.S * (self.C + 1) * (len(self.events) + 1)).bit_length()
        C1 = self.C + 1
        parts = []
        for down in (True, False):
            k = (K, end_ns, g, down)
            if k not in self._runs:
                self._runs.setdefault(k, self.run(K, g, down, end_ns))
            parts.append(_Q(sum(y for vec in self._runs[k] for i, y in enumerate(vec) if select(i // C1, i % C1)), 1 << g))
        lo_e, hi_e = num.exp(-x)
        out = (lo_e * parts[0], hi_e * (parts[1] + M0 * tail_bound(x, K)))
        self._bounds[key] = out
        return out

    # --- 支え (構造の 0、決定 5) ---
    def support(self, end_ns=None):
        """(状態, 件数) の支えの集合。率の正負と観測が許す状態だけで決まり、数の大きさに依らない。"""
        C1 = self.C + 1
        cur = {(s, min(self.n0, self.C)) for s, p in enumerate(self.priors) if p}

        def flow(sup, t0, t1):
            for left, right in zip(self._cuts(t0, t1), self._cuts(t0, t1)[1:]):
                if right > left:
                    sup = self._closure(sup, left)
            return sup
        t = _Q(0)
        for kind, b, a, e, inner in self.events:
            cur = flow(cur, t, b)
            if kind == "step":
                f = self.factors(e)
                cur = {(s, c) for s, c in cur if f[s]}
                t = b
                continue
            if self.source(e) == 0:
                return set()
            # 件数を読まない取得も、区間の中の一歩は同じ道で読む (R1)
            cur = self._read_support(cur, b, a, inner, None if e["symbol"] in _UNREAD else e["cursor"],
                                     e["symbol"] == "taken")
            t = a
        return flow(cur, t, self._t(self.terminal_ns if end_ns is None else end_ns))

    def _closure(self, sup, t):
        """正の長さの小区間 (始まり t) で到達できる (状態, 件数)。"""
        sup, frontier = set(sup), list(sup)
        while frontier:
            s, c = frontier.pop()
            nxt = [(s2, c) for s2, r in enumerate(self.R[s]) if s2 != s and r]
            if c < self.C and self._rate(s, t):
                nxt.append((s, c + 1))
            for n in nxt:
                if n not in sup:
                    sup.add(n)
                    frontier.append(n)
        return sup

    def _read_support(self, sup, b, a, inner, cursor, taken):
        """区間 [b, a] を通した後の支え (`_Pass.through` と同じ道)。cursor が None なら件数を読まない (区間の中の一歩だけ)。"""
        ok = (lambda c: True) if cursor is None else (lambda c: (c > cursor) == taken)
        if a == b:
            return {(s, c) for s, c in sup if ok(c)}
        points = sorted({*self._cuts(b, a), *(self._t(s["start_ns"]) for s in inner)})
        at = {}
        for s in inner:
            at.setdefault(self._t(s["start_ns"]), []).append(s)
        out = set()
        for p_index in range(len(points) - 1):
            v = set(sup)
            for i, (l, r) in enumerate(zip(points, points[1:])):
                if i > 0:
                    for s in at.get(l, ()):
                        f = self.factors(s)
                        v = {(x, c) for x, c in v if f[x]}
                if i == p_index:
                    # 判定の時刻はこの正の長さの小区間のどこか: 判定の前後で区間の中の到達を許す
                    before = self._closure(v, l)
                    v = self._closure({(x, c) for x, c in before if ok(c)}, l)
                else:
                    v = self._closure(v, l)
            out |= v
        return out



class _Pass:
    """群 (`Group`) の上の 1 回の計算 (丸めの向き 1 つ)。丸めの向きと途中の列はこの呼び出しだけが持ち、群は変わらない記述と完成
    した値の控えだけを持つ (同じ群を並行に照会しても、互いの丸めの向きを変えない。K40-k と同じ形、K41 レビュー R2)。
    列の成分は 2^g 倍した整数。非負の有理数の係数を掛けるたびに、下向きは切り捨て・上向きは切り上げる。どの作用も非負の係数の
    線形なので、下向きの列は真の値以下・上向きは以上のまま (丸めは幅を広げるだけ、K41 決定 4)。"""

    def __init__(self, group, down):
        self.group, self.down = group, down

    def mul(self, x, c):
        n = x * c.numerator
        return n // c.denominator if self.down else -((-n) // c.denominator)

    def B(self, v, coef):
        """B v (列ベクトル、添字 s·(C+1) + c、coef は小区間の係数 `Group._coef`)。遷移は件数を保ち、到着は件数を 1 増やす、
        C 以上は C のまま。"""
        C = self.group.C
        C1, mul = C + 1, self.mul
        out = [0] * len(v)
        for s, (stay, stay_top, moves, arrive) in enumerate(coef):
            base = s * C1
            for c in range(C1):
                x = v[base + c]
                if not x:
                    continue
                out[base + c] += mul(x, stay if c < C else stay_top)
                for s2, r in moves:
                    out[s2 * C1 + c] += mul(x, r)
                if c < C and arrive:
                    out[base + c + 1] += mul(x, arrive)
        return out

    def diag(self, v, w):
        return [self.mul(x, _Q(y)) for x, y in zip(v, w)]

    # --- 跳びの数ごとの係数のベクトル u[n] (n = 0..K) の上の作用 ---
    def piece(self, u, t, L, K, inner=None):
        """率が一定の小区間 (長さ L) の作用。inner = O なら、判定の時刻がこの小区間の一様 (n 跳びで (1/(n+1)) Σ B^(n−i) O B^i)。"""
        g = self.group
        if not L or not g.nu:   # 時間が無い・何も動かない: 発展は恒等で、一様の核は O そのもの
            return u if inner is None else [self.diag(x, inner) for x in u]
        x, mul, coef = g.nu * L, self.mul, g._coef(t)
        w = [x ** k / _factorial(k) for k in range(K + 1)]
        if inner is not None:
            w = [c / (k + 1) for k, c in enumerate(w)]
        out = [[0] * len(u[0]) for _ in range(K + 1)]
        for j, base in enumerate(u):
            if not any(base):
                continue
            p, acc = base, None
            for k in range(K + 1 - j):
                if inner is None:
                    term = p
                else:   # S_k = Σ_{i=0}^{k} B^(k−i) O B^i base = B S_{k−1} + O B^k base
                    seen = self.diag(p, inner)
                    acc = seen if acc is None else [a + b for a, b in zip(self.B(acc, coef), seen)]
                    term = acc
                out[j + k] = [o + mul(y, w[k]) for o, y in zip(out[j + k], term)]
                if k < K - j:
                    p = self.B(p, coef)
        return out

    def through(self, u, b, a, inner_steps, O, K):
        """区間 [b, a] を通す 1 つの道 (K41 決定 3・6、レビュー R1)。区間の中の率の境目と一歩の点で小区間に分け、一歩は区間の中の
        自分の点で 1 回だけ掛ける。O が None なら件数を読まない (自由な発展と一歩だけ)。O があれば判定の時刻 U は区間の一様で判定は
        1 回: U が小区間 p に入る確率 (長さの比) × (前の発展と一歩 → p の中の一様の核 → 後の発展と一歩) を足す。幅 0 は点で O を
        1 回 (区間の中に点は無い)。"""
        g = self.group
        if a == b:
            return u if O is None else [self.diag(x, O) for x in u]
        points = sorted({*g._cuts(b, a), *(g._t(s["start_ns"]) for s in inner_steps)})
        at = {}
        for s in inner_steps:
            at.setdefault(g._t(s["start_ns"]), []).append(s)

        def walk(v, uniform_at):
            for i, (l, r) in enumerate(zip(points, points[1:])):
                if i > 0:
                    for s in at.get(l, ()):
                        v = [self.diag(x, g._step(s)) for x in v]
                v = self.piece(v, l, r - l, K, O if i == uniform_at else None)
            return v
        if O is None:
            return walk(u, None)
        total = [[0] * len(u[0]) for _ in range(K + 1)]
        for p_index, (left, right) in enumerate(zip(points, points[1:])):
            share = (right - left) / (a - b)
            total = [[t + self.mul(y, share) for t, y in zip(tv, vv)] for tv, vv in zip(total, walk(u, p_index))]
        return total

    def run(self, K, g_bits, end_ns):
        g = self.group
        V = g.S * (g.C + 1)
        u0 = [0] * V
        for s, p in enumerate(g.priors):
            u0[s * (g.C + 1) + min(g.n0, g.C)] = self.mul(1 << g_bits, _Q(p))
        u = [u0] + [[0] * V for _ in range(K)]
        t = _Q(0)
        for kind, b, a, e, inner in g.events:
            u = self.through(u, t, b, [], None, K)
            if kind == "step":
                u = [self.diag(x, g._step(e)) for x in u]
                t = b
                continue
            # 件数を読まない取得 (呼んだ後の故障・つながっていない) も、区間の中の一歩は同じ道で 1 回ずつ掛ける (R1)
            O = None if e["symbol"] in _UNREAD else g._observe(e["cursor"], e["symbol"] == "taken")
            u = self.through(u, b, a, inner, O, K)
            f = _Q(g.source(e))
            u = [[self.mul(y, f) for y in x] for x in u]
            t = a
        return self.through(u, t, g._t(g.terminal_ns if end_ns is None else end_ns), [], None, K)

def _height(clock, t):
    """時計の位置 φ(t) の区切りの倍率 (区切りの境目 t ちょうどでは右の区切り)。"""
    period = clock["period"]
    phase = t / period - (t // period)
    starts, rates = clock["starts"], clock["multipliers"]
    j = sum(1 for s in starts if s <= phase) - 1
    return rates[j] if j >= 0 else rates[-1]


def tail_bound(x, K):
    """Σ_{n>K} x^n / n! の上界 (x ≥ 0 の有理数)。K + 2 > x なら x^(K+1)/(K+1)! · (K+2)/(K+2−x)、そうでなければ e^x の粗い上界。"""
    x = _Q(x)
    if not x:
        return _Q(0)
    if K + 2 > x:
        return x ** (K + 1) / _factorial(K + 1) * _Q(K + 2) / (K + 2 - x)
    return _Q(3) ** (int(x) + 1)


# --- 正本の unit から群を作る・Form の葉の口 (`_fb_time._Space.integral` と同じ口: exact・blind・positive・levels・table) ---

def chained(unit) -> bool:
    """遷移のある群の unit か (法則が R ≠ 0 の調子の過程を持つ、K41 決定 1。R = 0 は解決で外してある)。"""
    return "transitions" in unit["law"]


def group_of(spec, i, need=0):
    """unit i の群 (同じ候補・枝の状態の unit を宣言の状態の順に) と、群の中の i の位置。need は照会する件数の類の数 (C を
    need + 1 以上にする、`_fb_time.classes` と同じ)。"""
    from ._fb_time import _source_factor
    unit = spec["units"][i]
    tr = unit["law"]["transitions"]
    members = [spec["units"][j] for j in tr["units"]]
    law = unit["law"]
    entries = spec["entries"]
    C = max([*(e["cursor"] + 1 for e in entries if e["kind"] == "acquisition"), need + 1, 1])
    group = Group(rates=tr["rates"], R=tr["R"], clock=law.get("clock"), origin_ns=law["origin_ns"],
                  time_unit=law["time_unit"], initial_count=law["initial_count"], priors=[u["prior"] for u in members],
                  entries=entries, terminal_ns=spec["terminal_ns"],
                  factors=lambda e: [e["factors"][j] for j in tr["units"]],
                  source=lambda e: _source_factor(unit, e["symbol"]), C=C)
    return group, tr["units"].index(i)


class Chain:
    """遷移のある群の unit 1 つの量 (群の初期の事前を含む質量 Σ_{s0} prior(s0) · L(s0 → この状態)、K41 決定 3・4)。selector は
    `_fb_clock.Integral` と同じ: None = 全件数、("eq", k)・("ge", k) = 件数の類。θ の積分ではないので blind (P(Y | Q, h) は θ に
    依らない)。値は精度 num.bits の上下界 (`Group.bounds`)、形の 0 は支え (決定 5)。"""

    exact = None
    blind = True

    def __init__(self, group, position, selector):
        if selector is not None and selector[0] not in ("eq", "ge"):
            raise ValueError("selector")
        self.group, self.position, self.selector = group, position, selector
        self.levels = {}

    def _select(self, s, c):
        sel = self.selector
        if s != self.position:
            return False
        if sel is None:
            return True
        return c == sel[1] if sel[0] == "eq" else c >= sel[1]

    def positive(self):
        return any(self._select(s, c) for s, c in self.group.support())

    def table(self, num):
        return _ChainTable(self, num)


class _ChainTable:
    """`_fb_clock._Table` と同じ口 (at(level))。上下界は精度 num.bits だけで決まり、箱の段 level には依らない。"""

    def __init__(self, chain, num):
        self.chain, self.num = chain, num

    def at(self, level):
        from ._fb_clock import _down, _up
        chain, bits = self.chain, self.num.bits
        out = chain.levels.get(bits)
        if out is None:
            lo, hi = chain.group.bounds(self.num, chain._select)
            out = chain.levels.setdefault(bits, (_down(lo, bits), _up(hi, bits)))
        return out


# --- 連続の時計の事前 × 遷移 (K41 決定 8): K40 の積分 (`_fb_clock.Integral`) の箱の上で、θ ごとの尤度だけを鎖の上下界に差し替える ---

def _integral_base():
    from ._fb_clock import Integral
    return Integral


class ChainIntegral(_integral_base()):
    """遷移のある群の unit 1 つの ∫ (群の初期の事前を含む質量)(θ) Π(dθ | T, m) の上下界。箱の事前の質量・時計の形の差の上界
    `_distance` は K40 のまま。違うのは 3 つ: ① θ ごとの値は鎖の上下界 (`Group.bounds`、指数多項式に閉じない) ② 箱の中の差は、同じ
    調子の道を共有した 2 つの到着の過程の比べで |L_θ − L_θ0| ≤ M0 (1 − e^{−D*})、D* = ∫ max_s |λ_θ(s, t) − λ_θ0(s, t)| dt ≤
    max_s 率_s · ∫ |c_θ − c_θ0| (点検係が検算、M0 は群の初期の質量) ③ 遷移があると尤度は読む位相の累積だけでは決まらない (定規 ④
    の順) ので、配分 f の座標をまとめず (`_groups`)、回転 ρ も解析的に積分せず箱の座標にする (K40 決定 14 は「してよい」で、
    鎖では使わない)。"""

    analytic_rotation = False

    def __init__(self, spec, i, selector):
        from ._fb_time import _source_factor
        unit = spec["units"][i]
        law, clock = unit["law"], unit["law"]["clock"]
        tr = law["transitions"]
        self.spec, self.i = spec, i
        self.unit, self.entries, self.terminal_ns, self.selector = unit, spec["entries"], spec["terminal_ns"], selector
        self.period, self.m = clock["period"], clock["segments"]
        self.rho0, self.w0, self.f0 = clock["rotation"], clock["widths"], clock["shares"]
        self.kw, self.kf = clock["width_concentration"], clock["share_concentration"]
        self.rate = max(tr["rates"])
        origin, scale = law["origin_ns"], law["time_unit"]
        horizon = max([_Q(0), *((e["after_ns"] - origin) * scale for e in self.entries if e["kind"] == "acquisition")])
        if selector is not None and selector[0] in ("eq", "ge"):
            horizon = (self.terminal_ns - origin) * scale   # 終わりの件数は終わりまでの到着で決まる
        self.horizon = horizon
        self.turns = -((-horizon) // self.period)
        self.F = sum((spec["units"][j]["prior"] for j in tr["units"]), _Q(0))   # 群の初期の質量 (核はどれも 1 以下)
        # 尤度が θ に依らないと構造から言えるのは、到着が無い (率 0) か、件数を読む観測も終わりの件数の照会も無い時だけ。K40 の
        # 「読む位相が 1 周の終わりだけなら形は見えない」(`_reads`) は、遷移があると成り立たない (定規 ④、決定 8)
        reads = any(e["kind"] == "acquisition" and e["symbol"] not in _UNREAD for e in self.entries)
        self.constant = not self.rate or not (reads or selector is not None and selector[0] in ("eq", "ge"))
        self.groups = tuple((j,) for j in range(self.m))
        self.dims = (([("rho",)] if self.rho0 is None else [])
                     + ([("w", j) for j in range(self.m - 1)] if self.w0 is None else [])
                     + ([("f", j) for j in range(self.m - 1)] if self.f0 is None else []))
        self.levels = {}
        self.blind = self.constant and not (selector is not None and selector[0] == "share")
        self.exact = None
        self._need = selector[1] + 1 if selector is not None and selector[0] in ("eq", "ge") else 0
        self._by_theta = {}
        self._source = lambda e: _source_factor(unit, e["symbol"])

    def _groups(self):
        return self.groups

    def _group(self, theta):
        """θ 1 点の時計の形 (`_fb_clock.point_shape`) の群と、群の中のこの unit の位置。"""
        from ._fb_clock import point_shape
        key = (theta[0], tuple(theta[1]), tuple(theta[2]))
        tr = self.unit["law"]["transitions"]
        group = self._by_theta.get(key)
        if group is None:
            law, entries, units = self.unit["law"], self.spec["entries"], self.spec["units"]
            C = max([*(e["cursor"] + 1 for e in entries if e["kind"] == "acquisition"), self._need + 1, 1])
            group = Group(rates=tr["rates"], R=tr["R"], clock=point_shape(self.period, *theta),
                          origin_ns=law["origin_ns"], time_unit=law["time_unit"], initial_count=law["initial_count"],
                          priors=[units[j]["prior"] for j in tr["units"]], entries=entries,
                          terminal_ns=self.spec["terminal_ns"], factors=lambda e: [e["factors"][j] for j in tr["units"]],
                          source=self._source, C=C)
            if len(self._by_theta) > 4096:
                self._by_theta.clear()
            self._by_theta[key] = group
        return group, tr["units"].index(self.i)

    def _select(self, position):
        sel = self.selector

        def pick(s, c):
            if s != position:
                return False
            if sel is None or sel[0] == "share":
                return True
            return c == sel[1] if sel[0] == "eq" else c >= sel[1]
        return pick

    def _point_bounds(self, theta, num):
        from ._fb_clock import point_shape, share_of
        group, position = self._group(theta)
        lo, hi = group.bounds(num, self._select(position))
        s = self.selector
        if s is not None and s[0] == "share":
            r = share_of(point_shape(self.period, *theta), s[1], s[2])
            lo, hi = lo * r, hi * r
        return lo, hi

    def positive(self):
        s = self.selector
        if s is not None and s[0] == "share" and s[1] == s[2]:
            return False
        group, position = self._group(self._interior_point())
        pick = self._select(position)
        return any(pick(x, c) for x, c in group.support())

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
        if any(x <= 0 for x in (*theta[1], *theta[2])):   # 代表点が単体の外: 値は [0, F]
            return m_lo, m_hi, _Q(0), self.F
        A = self._distance(rho, w, f, theta)
        delta = 0 if self.constant else min(_Q(1), self.rate * self.period * self.turns * A)
        s = self.selector
        if s is not None and s[0] == "share":   # |L g − L0 g0| ≤ F (δ + A)、K40 と同じ
            delta = delta + A
        V = self._point_bounds(theta, self._num_for(num, self.F * delta))
        return m_lo, m_hi, max(_Q(0), V[0] - self.F * delta), min(self.F, V[1] + self.F * delta)

    def _num_for(self, num, slack):
        """箱の中の差の包み slack (> 0) より十分細かい精度だけで θ 1 点の値を計算する (上下界は精度によらず正しく、幅が slack に
        比べて小さければ足りる)。slack が 0 なら呼ぶ側の精度のまま。"""
        if not slack:
            return num
        from ._fb_clock import Num
        bits = min(num.bits, max(24, (1 / slack).numerator.bit_length() - (1 / slack).denominator.bit_length() + 8))
        if bits == num.bits:
            return num
        # 粗い精度の数の口は、呼ぶ側の照会の数の口 num が持つ (照会ごとの作業で、ほかの照会と共有しない、レビュー R2)
        derived = num.__dict__.setdefault("derived", {})
        if bits not in derived:
            derived[bits] = Num(bits)
        return derived[bits]

    def _splittable(self, box):
        """w が単体の境目に触れる箱は f の座標を分けない (K40 の `Integral._splittable` と同じ理由。ρ の座標の分だけずらす)。"""
        if self.w0 is None and self.f0 is None and any(l <= 0 for l, _h in self._intervals(box)[1]):
            return [i for i, d in enumerate(self.dims) if d[0] != "f"]
        return range(len(box))
