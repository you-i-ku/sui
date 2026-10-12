"""関所 F v0.8 §3-9・§3-10-10 の独立した固定値 (区切り 0 の前、Claude 2026-10-08)。

sui を import しない。確率は Fraction で完全一致。情報量 (nat) は素数の対数の
有理係数の和 Σ c_p ln p として厳密に持ち、照合用の区間を 60 桁の Decimal から
外向きに丸めて出す。softmax の確率など対数の形で閉じない量は、式と区間を出す。
C1 の 2 窓 (FA20) と全列挙と再帰 (FA04) は、2 通りの別の計算の一致を確かめる。

数の出どころ: 仕様書 §3-9・§3-B-2・§3-B-3・§3-10-10 (Codex `sui-gate-f-core2`
2・3 通目、Claude の検算) と §3-10-12 (空打ちの後、Codex `sui-gate-f-draft` 2 通目)。FA04・FA03・FA16 の具体の世界はこの台本で置いた
例 (仕様書は識別の条件だけを書く)。試験の係は形が合えばそのまま使ってよい。
FA01・FA06・FA17・FA19・FA21 は構造の試験で、数の正本は仕様書と旧の golden。

実行: python -B tools/gate_f_fixed_values.py            (JSON を表示)
      python -B tools/gate_f_fixed_values.py PATH       (新しいファイルに保存)
      python -B tools/gate_f_fixed_values.py --check PATH
"""
from __future__ import annotations

import argparse
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR, getcontext
from fractions import Fraction as F
import json
from math import comb, factorial
from pathlib import Path

getcontext().prec = 60
DIGITS = D("1e-40")


# --- 厳密な対数の量 Σ c_p ln p --------------------------------------------------
def factor(n):
    out, p = {}, 2
    while n > 1:
        while n % p == 0:
            out[p] = out.get(p, 0) + 1
            n //= p
        p += 1
    return out


class L:
    """Σ c_p ln p (c_p は Fraction、p は素数)。"""

    def __init__(self, coeffs=None):
        self.c = {p: F(v) for p, v in (coeffs or {}).items() if v}

    @staticmethod
    def ln(x):
        x = F(x)
        assert x > 0
        out = {p: F(k) for p, k in factor(x.numerator).items()}
        for p, k in factor(x.denominator).items():
            out[p] = out.get(p, F(0)) - k
        return L(out)

    def __add__(self, other):
        keys = self.c.keys() | other.c.keys()
        return L({p: self.c.get(p, F(0)) + other.c.get(p, F(0)) for p in keys})

    def __sub__(self, other):
        return self + other * -1

    def __mul__(self, k):
        return L({p: v * F(k) for p, v in self.c.items()})

    __rmul__ = __mul__

    def __eq__(self, other):
        return self.c == other.c

    def dec(self):
        return sum((D(v.numerator) / D(v.denominator) * D(p).ln() for p, v in self.c.items()), D(0))

    def expr(self):
        if not self.c:
            return "0"
        terms = []
        for p in sorted(self.c):
            v = self.c[p]
            k = "" if v == 1 else "-" if v == -1 else f"{v}*"
            terms.append(f"{k}ln{p}")
        return " + ".join(terms).replace("+ -", "- ")

    def json(self):
        return {"expr": self.expr(), "coeffs": {str(p): serial(v) for p, v in sorted(self.c.items())},
                "interval": interval(self.dec())}


ZERO = L()
LN2 = L.ln(2)


def h(p):
    """2 値のエントロピー (nat)。"""
    p = F(p)
    out = ZERO
    for x in (p, 1 - p):
        if x:
            out = out - L.ln(x) * x
    return out


def H(dist):
    out = ZERO
    for x in dist:
        if x:
            out = out - L.ln(x) * x
    return out


MARGIN = D("1e-50")


def interval(x):
    """照合用の外向きの区間。60 桁の Decimal の各演算 (ln・exp・四則) は正しく丸められ
    (誤差は 1 回 0.5 ulp 以下、相対 5e-60)、この台本の 1 つの値までの演算は千回未満・途中の
    値の大きさは 10 未満なので、計算値と真の値の差は 1e-55 未満。MARGIN = 1e-50 だけ外へ
    広げてから 40 桁で床と天井に切るので、真の値を含む (Decimal.ln の丸めの向きを変えて
    上下界を作ったのではない。外部のレビューの指摘、2026-10-08)。
    この台本で Decimal がちょうど 0 になるのは D(0) から作った厳密な 0 (費用 0 の終端) だけ
    なので、それは一点の区間のまま返す (厳密な値を余白で広げない)。"""
    if x.is_zero():
        return [format(D(0).quantize(DIGITS), "f")] * 2
    return [format((x - MARGIN).quantize(DIGITS, ROUND_FLOOR), "f"),
            format((x + MARGIN).quantize(DIGITS, ROUND_CEILING), "f")]


def dexp(x):
    return x.exp()


def softmax(J, gamma=1):
    """J: Decimal の列。exp(−γJ) の正規化 (有限の候補・counting の測度)。"""
    m = min(J)
    w = [dexp(-D(gamma) * (j - m)) for j in J]
    z = sum(w)
    return [x / z for x in w]


def serial(v):
    if isinstance(v, F):
        return [v.numerator, v.denominator]
    if isinstance(v, L):
        return v.json()
    if isinstance(v, D):
        return {"interval": interval(v)}
    if isinstance(v, dict):
        return {str(k): serial(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [serial(x) for x in v]
    return v


def close(a, b, tol=D("1e-45")):
    return abs(D(a) - D(b)) <= tol


# --- 各 fixture ------------------------------------------------------------------
def fa02():
    prior, like = (F(1, 2), F(1, 2)), (F(1, 2), F(1, 8))
    z = sum(p * l for p, l in zip(prior, like))
    post = prior[0] * like[0] / z
    assert (z, post) == (F(5, 16), F(4, 5))
    return {"prior": prior, "no_arrival_likelihood": like, "evidence": z, "posterior_state0": post,
            "wrong_ignore_no_arrival": prior[0],
            "derivation": "Σ prior·like = 1/4 + 1/16。閉じた区間ではこの尤度を掛けない (事後は 1/2 のまま)"}


def fa03():
    """例: 状態 1 つ、法則 a・b を 1/2 ずつ、1 窓の無到着の尤度 a 1/2・b 1/8、2 窓とも無到着。"""
    pa, la, lb = F(1, 2), F(1, 2), F(1, 8)
    shared = pa * la ** 2 + (1 - pa) * lb ** 2
    redraw = (pa * la + (1 - pa) * lb) ** 2
    post = pa * la ** 2 / shared
    assert (shared, redraw, post) == (F(17, 128), F(25, 256), F(16, 17))
    return {"world": "1 状態、法則 {a,b} 事前 1/2、窓ごとの無到着 a 1/2・b 1/8、2 窓とも無到着",
            "evidence_shared_law": shared, "posterior_law_a": post,
            "wrong_redraw_or_average_per_window": {"evidence": redraw, "posterior_law_a": pa},
            "derivation": "法則を全区間で共有: Σ_θ P(θ) l_θ²。区間ごとに引き直す・平均する誤り: (Σ P(θ) l_θ)²"}


def info_meas(p, acc):
    """静的なビット (P(X=1)=p) を正答率 acc で 1 回測る情報と、y ごとの (P(y), 事後)。"""
    p1 = p * acc + (1 - p) * (1 - acc)
    branches = {1: (p1, p * acc / p1), 0: (1 - p1, p * (1 - acc) / (1 - p1))}
    return h(p1) - h(acc), branches


def dfrac(x):
    return D(x.numerator) / D(x.denominator)


def two_stage_tree(cost, soft_min=False):
    """FA04 の木: 公平な静的ビット X、候補 M (正答率 3/4 で 1 回測る)・Q (何もしない)、
    選択の節 2 段 (根と 1 手の後) で終わり、γ = 1、soft_choice/1。
    cost(path) は終端で路全体に 1 回だけ掛ける費用 (Decimal、path は "MM" など)。"""
    acc = F(3, 4)

    def J(p, path):
        if len(path) == 2:
            return {}
        im, br = info_meas(p, acc)
        return {"M": -im.dec() + sum(dfrac(py) * V(q, path + "M") for py, q in br.values()),
                "Q": V(p, path + "Q")}

    def V(p, path):
        j = J(p, path)
        if not j:
            return cost(path)
        vals = [j["M"], j["Q"]]
        if soft_min:
            m = min(vals)
            return m - sum(dexp(-(x - m)) for x in vals).ln()
        return sum(q * x for q, x in zip(softmax(vals), vals))

    def kl(p, prior=F(1, 2)):
        return sum(dfrac(x) * (dfrac(x) / dfrac(y)).ln() for x, y in ((p, prior), (1 - p, 1 - prior)) if x)

    def enumerate_paths(p, path, first=None):
        """方策 π で終端まで全列挙し、E_π[C(路) − KL(終端の事後 ‖ 事前)] を直接 (総量方式)。"""
        if len(path) == 2:
            return cost(path) - kl(p)
        if first is None:
            j = J(p, path)
            q = softmax([j["M"], j["Q"]])
            probs = {"M": q[0], "Q": q[1]}
        else:
            probs = {first: D(1)}
        tot = D(0)
        for op, pa in probs.items():
            if op == "Q":
                tot += pa * enumerate_paths(p, path + "Q")
            else:
                for py, q in info_meas(p, acc)[1].values():
                    tot += pa * dfrac(py) * enumerate_paths(q, path + "M")
        return tot

    def node(p, path):
        j = J(p, path)
        return {"J_M": j["M"], "J_Q": j["Q"], "q_M": softmax([j["M"], j["Q"]])[0], "V": V(p, path)}
    return J, V, enumerate_paths, node


def fa04():
    """白紙 (費用 0)。"""
    J, V, enumerate_paths, node = two_stage_tree(lambda path: D(0))
    root = J(F(1, 2), "")
    for op in ("M", "Q"):
        assert close(root[op], enumerate_paths(F(1, 2), "", op)), op
    assert close(V(F(1, 2), ""), enumerate_paths(F(1, 2), ""))
    wrong = two_stage_tree(lambda path: D(0), soft_min=True)[3](F(1, 2), "")
    assert not close(wrong["q_M"], node(F(1, 2), "")["q_M"], D("1e-6"))
    i_root_M, _ = info_meas(F(1, 2), F(3, 4))
    i_after_M1, _ = info_meas(F(3, 4), F(3, 4))
    return {"world": "公平な静的ビット、M = 正答率 3/4 の 1 回の測定、Q = 何もしない、選択 2 段で終わり、白紙",
            "information": {"M_at_root": i_root_M, "M_after_first_y1": i_after_M1, "Q": ZERO},
            "root": node(F(1, 2), ""), "after_first_M_y1": node(F(3, 4), "M"),
            "after_first_Q": node(F(1, 2), "Q"), "path_cost": F(0),
            "wrong_soft_minimum": wrong,
            "derivation": "再帰 J = −I + Σ P(y) V、V = Σ softmax(−J)·J。全列挙 −E_π[KL(事後‖事前)] と "
                          "1e-45 以内で一致 (根の M・Q とも)。誤り: V を −ln Σ exp(−J) にする"}


def fa04_nonzero_path_cost():
    """FA04 と同じ世界に、S4d の item (table・started_actions) の路全体の好みを置く (Codex
    `sui-gate-f-draft` 2 通目 §12)。費用 = −ln C(路)、終端で 1 回だけ。"""
    probs = {"MM": F(1, 2), "MQ": F(1, 8), "QM": F(1, 8), "QQ": F(1, 4)}
    assert sum(probs.values()) == 1
    costs = {k: L.ln(v) * -1 for k, v in probs.items()}
    assert costs == {"MM": LN2, "MQ": LN2 * 3, "QM": LN2 * 3, "QQ": LN2 * 2}
    assert costs["MM"] + costs["QQ"] != costs["MQ"] + costs["QM"]  # 手ごとの和に分解できない

    def cost(path):
        return costs[path].dec()
    J, V, enumerate_paths, node = two_stage_tree(cost)
    root = J(F(1, 2), "")
    for op in ("M", "Q"):
        assert close(root[op], enumerate_paths(F(1, 2), "", op)), op
    # Codex の閉じた式 (I0・Ic・r_M・r_Q) と照合
    I0, Ic, l2 = (LN2 - h(F(1, 4))).dec(), (h(F(5, 8)) - h(F(1, 4))).dec(), LN2.dec()
    r_M = softmax([l2 - Ic, 3 * l2])[0]
    r_Q = softmax([3 * l2 - I0, 2 * l2])[0]
    C_M, C_Q = r_M * l2 + (1 - r_M) * 3 * l2, r_Q * 3 * l2 + (1 - r_Q) * 2 * l2
    I_M, I_Q = I0 + r_M * Ic, r_Q * I0
    assert close(root["M"], C_M - I_M) and close(root["Q"], C_Q - I_Q)
    first = {"M": probs["MM"] + probs["MQ"], "Q": probs["QM"] + probs["QQ"]}
    wrongs = {"wrong_all_costs_zero": two_stage_tree(lambda path: D(0))[3](F(1, 2), ""),
              "wrong_cost_counted_at_each_stage": two_stage_tree(lambda path: 2 * cost(path))[3](F(1, 2), ""),
              "wrong_first_action_only": two_stage_tree(lambda path: -dfrac(first[path[0]]).ln())[3](F(1, 2), ""),
              "wrong_soft_minimum": two_stage_tree(cost, soft_min=True)[3](F(1, 2), "")}
    right = node(F(1, 2), "")
    for name, w in wrongs.items():
        assert not close(w["q_M"], right["q_M"], D("1e-6")), name
    return {"preference_item": {"kind": "item", "rule": {"name": "table", "version": "1"},
                                "args": {"feature": {"name": "started_actions", "version": "1"},
                                         "probs": [[list(k), float(v)] for k, v in probs.items()]}},
            "path_costs": costs, "root": right, "root_cost": {"M": C_M, "Q": C_Q},
            "root_information": {"M": I_M, "Q": I_Q},
            "after_first_M_y1": node(F(3, 4), "M"), "after_first_Q": node(F(1, 2), "Q"),
            **wrongs,
            "derivation": "終端で −ln C(路) を 1 回。MM+QQ = 3 ln2 ≠ MQ+QM = 6 ln2 で手ごとの和に分解できない。"
                          "再帰・全列挙・Codex の閉じた式 (I0・Ic・r) の 3 通りが 1e-45 以内で一致。"
                          "誤り: 費用 0 / 各段で 2 回 / 初手の周辺 −ln(5/8)・−ln(3/8) だけ / soft minimum"}


def fa05():
    acc, p = F(3, 4), F(1, 2)
    one = p * acc / (p * acc + p * (1 - acc))
    two = p * acc ** 2 / (p * acc ** 2 + p * (1 - acc) ** 2)
    assert (one, two) == (F(3, 4), F(9, 10))
    i1, _ = info_meas(p, acc)
    joint = [F(5, 16), F(3, 16), F(3, 16), F(5, 16)]
    i2 = H(joint) - h(acc) * 2
    assert i1 == L({2: -1, 3: F(3, 4)})
    return {"posterior_one_measurement_redelivered_twice": one, "posterior_two_independent_same_value": two,
            "information_one": i1, "information_two_independent": i2,
            "wrong_double_count_redelivery": two, "wrong_dedupe_by_body": one,
            "derivation": "同じ測定の配送は 1 回と数える (3/4)。別の機会の同じ値は 2 回 (9/10)"}


def fa07():
    already = h(F(1, 2))
    assert already == LN2
    return {"already_received": already, "additional": ZERO, "total_information": already,
            "old_G": already * -1, "wrong_reflect_twice_G": already * -2, "wrong_drop_common_term_G": ZERO,
            "derivation": "H = 0、受信済み未読の O₀ が公平なビットの完全測定。旧 G = −(I₀ + 0)"}


def fa07_first_action_cost():
    """FA07 の世界 (H = 0、O₀ = 進行中の完全測定 P) に、初手の好み M 3/4・Q 1/4 (S4d の item、
    started_actions) を置く。今始める手の結果は H = 0 に入らない (Codex `sui-gate-f-draft` 2 通目 §11)。"""
    C = {"M": F(3, 4), "Q": F(1, 4)}
    cost = {k: L.ln(v) * -1 for k, v in C.items()}
    common = h(F(1, 2))
    J = {k: cost[k] - common for k in C}
    assert J == {"M": L.ln(F(2, 3)), "Q": LN2}
    q = softmax([J["M"].dec(), J["Q"].dec()])
    assert close(q[0], D(3) / D(4))
    return {"order": ["M", "Q"], "cost": cost, "already_received": common, "additional": ZERO,
            "J": J, "q": [F(3, 4), F(1, 4)], "u": F(1, 2), "selected": "M",
            "wrong_drop_common_term_J": cost, "wrong_count_P_as_new_start": "P を初手として数えない",
            "derivation": "J = −ln C(初手) − I₀。q ∝ exp(−J) = (3/2, 1/2)。共通項 I₀ は q を変えないが J の値は変える"}


def fa21_minimal_bridge():
    """静的な公平な 2 状態、M = 完全測定・Q = 情報のない一定の報告、所要 1 秒、白紙、1 歩 (H_ns = null)。"""
    J = {"M": h(F(1, 2)) * -1, "Q": ZERO}
    q = softmax([J["M"].dec(), J["Q"].dec()])
    assert close(q[0], D(2) / D(3))
    return {"order": ["M", "Q"], "J": J, "q": [F(2, 3), F(1, 3)], "u": F(1, 2), "selected": "M",
            "scope": "one_step", "derivation": "旧 plan と F の one_step が同じ J・q・選択になる最小の橋"}


def fa08():
    return {"two_operations": [F(1, 2), F(1, 2)], "with_display_alias": [F(1, 2), F(1, 2)],
            "wrong_alias_counted": [F(2, 3), F(1, 3)],
            "derivation": "counting/1 は意味の異なる操作に質量 1。別名は質量を足さない"}


def fa09():
    now = F(1) / (1 + 1)
    return {"now": now, "two_cells_each_half": now, "wrong_cells_as_points": F(1, 3),
            "derivation": "原子 1 + [0,2] 上の総質量 1、全 J = 0 → 1/(1+1)。2 セルを各質量 1 の点にする誤り 1/3"}


def fa10():
    J = [D(0), -LN2.dec()]
    q = softmax(J)
    assert close(q[1], D(2) / D(3))
    return {"I_now": ZERO, "I_later": LN2, "q_later": F(2, 3), "wrong_time_tie": F(1, 2),
            "derivation": "q = e^{ln2}/(1+e^{ln2}) = 2/3"}


def scope_world(arrive):
    """FA11〜FA13: A = 今 1/2 で完全測定、W = arrive でいつか完全測定、P(D=k|届く) = 2^-k。"""
    I_A = LN2 * F(1, 2)
    I_W = LN2 * arrive

    def I_W_by(n):
        return LN2 * (arrive * (1 - F(1, 2 ** n)))

    def q_W(iw):
        return softmax([-iw.dec(), -I_A.dec()])[0]
    return I_A, I_W, I_W_by, q_W


def fa11():
    I_A, I_W, I_W_by, q_W = scope_world(F(3, 4))
    u = D(1) / D(2)
    q_unb, q_h1 = q_W(I_W), q_W(I_W_by(1))
    assert close(q_unb, D(1) / (1 + D(2) ** (D(-1) / 4)))
    assert close(q_h1, D(1) / (1 + D(2) ** (D(1) / 8)))
    assert u < q_unb and not u < q_h1
    return {"order": ["W", "A"], "u": F(1, 2),
            "unbounded": {"I_W": I_W, "I_A": I_A, "q_W": q_unb, "q_W_expr": "1/(1+2^(-1/4))", "selected": "W"},
            "finite_H_1": {"I_W": I_W_by(1), "I_A": I_A, "q_W": q_h1, "q_W_expr": "1/(1+2^(1/8))", "selected": "A"},
            "derivation": "W: 3/4 で届く (D ≤ 1 は 1/2)、1/4 永久未着。手 k は F_{k-1} ≤ u < F_k"}


def fa12():
    I_A, I_W, _, q_W = scope_world(F(1, 4))
    q = q_W(I_W)
    assert not D(1) / D(2) < q
    return {"I_W": I_W, "I_A": I_A, "q_W": q, "q_W_expr": "1/(1+2^(1/4))", "selected": "A",
            "derivation": "届く確率 1/4 なら I_W = ln2/4 < I_A。永久未着を含めば待つ、の誤りを落とす"}


def fa13():
    I_A, I_W, I_W_by, q_W = scope_world(F(3, 4))
    out = {}
    for n in (1, 2):
        lo, tail = I_W_by(n), I_W - I_W_by(n)
        q_lo, q_hi = q_W(lo), q_W(I_W)
        out[f"n{n}"] = {"I_W_lower": lo, "I_W_upper": I_W, "tail_R": tail,
                        "q_W_interval": [q_lo, q_hi], "certified_at_u_half": D(1) / D(2) < q_lo}
    assert out["n2"]["I_W_lower"] == LN2 * F(9, 16) and out["n2"]["tail_R"] == LN2 * F(3, 16)
    assert not out["n1"]["certified_at_u_half"] and out["n2"]["certified_at_u_half"]
    assert close(out["n2"]["q_W_interval"][0], D(1) / (1 + D(2) ** (D(-1) / 16)))
    out["derivation"] = ("I_n = (3/4)(1−2^-n) ln2 ≤ I∞ ≤ I_n + R_n、R_n = (3/4)2^-n ln2 (捨てない)。"
                         "n = 1 は区間が u = 1/2 をまたぐ、n = 2 の下界 2^(1/16)/(1+2^(1/16)) > 1/2 で W が確定")
    return out


def fa14():
    q = softmax([D(0), -LN2.dec()])
    assert close(q[0], D(1) / D(3))
    return {"order": ["Q", "M"], "G_Q": ZERO, "G_M": LN2 * -1, "q": [F(1, 3), F(2, 3)],
            "u_selecting_Q": [F(0), F(1, 3)], "u_example": F(1, 6), "selected": "Q",
            "derivation": "静かな Q (将来の測定なし) は G = 0 の候補として選ばれる。NoDecision と別"}


def fa15():
    once = h(F(1, 2))
    return {"one_perfect_measurement": once, "hundred_of_same_bit": once,
            "wrong_sum_hundred": once * 100, "new_bit_each_time_I_n": "n*ln2 (発散、型の外)",
            "derivation": "同じビットの完全測定は 1 回で H(X) を使い切る。毎回新しいビットは I_n = n ln2"}


def fa16():
    """例: 公平なビット、完全測定が確実に時刻 d で届く。H = 1。"""
    out = {}
    for d in (1, 2):
        out[f"arrive_at_{d}"] = {"unbounded": LN2, "finite_H_1": LN2 if d <= 1 else ZERO,
                                 "equal": d <= 1}
    out["packaging"] = {"one_composite_wait_then_measure": LN2, "two_operations_wait_and_measure": LN2,
                        "one_step_composite": LN2, "one_step_two_operations_first": ZERO}
    out["derivation"] = ("尾が厳密に 0 (d ≤ H) なら有限 H と一致、H+1 で初めて届くと不一致。"
                         "包装を変えても unbounded は同じ、1 歩は包装で変わる (§3-B-3)")
    return out


def fa18():
    T, Fa, U = "true", "false", "unknown"

    def AND(a, b):
        return Fa if Fa in (a, b) else T if a == b == T else U

    def OR(a, b):
        return T if T in (a, b) else Fa if a == b == Fa else U
    vals = (T, Fa, U)
    return {"and": {f"{a},{b}": AND(a, b) for a in vals for b in vals},
            "or": {f"{a},{b}": OR(a, b) for a in vals for b in vals},
            "not": {T: Fa, Fa: T, U: U},
            "redelivery_100_draw_ids": 1,
            "derivation": "§3-10-3: AND は False があれば False、全て True なら True、他は Unknown (OR は双対)"}


def c1_kernel(n, delta):
    """C1: 0→1 の率 r、到着率 (r, 2r)。幅 delta で n 到着の核を r の多項式 × e^{−2r·delta} で。
    戻り値 K[to][from] = {r の次数: 係数}。遷移の時刻 s で積分して作る (閉じた式を使わない)。"""
    stay0 = {n: F(delta) ** n / factorial(n)}
    stay1 = {n: (2 * F(delta)) ** n / factorial(n)}
    # ∫_0^Δ r e^{-rs} e^{-r(2Δ-s)} (r(2Δ-s))^n / n! ds = e^{-2rΔ} r^{n+1}/n! ∫_0^Δ (2Δ-s)^n ds
    integral = sum(comb(n, k) * (2 * F(delta)) ** (n - k) * (-1) ** k * F(delta) ** (k + 1) / (k + 1)
                   for k in range(n + 1))
    jump = {n + 1: integral / factorial(n)}
    return [[stay0, {}], [jump, stay1]]


def poly_mul(a, b):
    out = {}
    for i, x in a.items():
        for j, y in b.items():
            out[i + j] = out.get(i + j, F(0)) + x * y
    return out


def poly_add(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, F(0)) + v
    return out


def c1_direct(reports, delta=1):
    """核の積を r の多項式で持ち、事前 Gamma(2,2) = 4 r e^{-2r} で r を積分する。"""
    f = [{0: F(1)}, {}]  # 初期は状態 0
    for n in reports:
        K = c1_kernel(n, delta)
        f = [poly_add(poly_mul(K[to][0], f[0]), poly_mul(K[to][1], f[1])) for to in (0, 1)]
    beta = 2 + 2 * delta * len(reports)
    mass = [sum(c * 4 * F(factorial(k + 1), beta ** (k + 2)) for k, c in s.items()) for s in f]
    return mass[0] / sum(mass)


def c1_closure(reports, delta=1):
    """Codex の閉包 (N, T, A₀, A₁)。"""
    N, T, A0, A1 = 0, 0, F(4), F(0)
    for n in reports:
        d0 = F(delta) ** n / factorial(n)
        d1 = 2 ** n * d0
        v = F(delta) ** (n + 1) * (2 ** (n + 1) - 1) / factorial(n + 1)
        A0, A1, N, T = d0 * A0, v * A0 + d1 * A1, N + n, T + delta
    beta = 2 + 2 * T
    w0, w1 = A0 * factorial(N + 1) / F(beta) ** (N + 2), A1 * factorial(N + 2) / F(beta) ** (N + 3)
    return w0 / (w0 + w1), (N, T)


def fa20():
    out = {}
    for reports, expected in (((1, 0), F(4, 9)), ((0, 1), F(4, 11))):
        direct = c1_direct(reports)
        closed, nt = c1_closure(reports)
        assert direct == closed == expected, (reports, direct, closed)
        out[f"{reports[0]}{reports[1]}"] = {"P_S2_state0": direct, "N_T": list(nt)}
    out["wrong_keep_only_N_T"] = "(1,0) と (0,1) は (N,T) = (1,2) で同じ → 区別できない"
    out["derivation"] = ("C1: 0→1 率 r、到着 (r, 2r)、初期 0、r ~ Gamma(2,2)、幅 1 秒の連続 2 窓。"
                         "核の積を r の多項式で直接積分と、閉包 (N,T,A₀,A₁) の 2 通りで一致")
    return out


def fb03():
    old, new = {"A": F(9, 10), "B": F(1, 10)}, {"A": F(1, 10), "B": F(9, 10)}
    agree_A = min(old["A"], new["A"])
    agree_B = min(old["B"], new["B"])
    return {"old": old, "new": new, "wrong_execute_only_if_same_u": {"A": agree_A, "B": agree_B,
                                                                       "cancel": 1 - agree_A - agree_B},
            "correct": "元の根の結果 (旧の確率で選んだ手) を残す",
            "derivation": "u < .9 で旧 A、u < .1 で新 A。一致は u < .1 (A) と u ≥ .9 (B) だけ"}


def review_f09_unobservable_branches():
    """§3-10-14-6 (レビュー F09): 公平な静的 2 状態、H = 内部の 2 枝 diag(1,0)・diag(0,1) で
    どちらも証拠なし (evidence = null・reveal = [])、Q = 単位行列。観測の側から集計する:
    証拠の射影が同じ枝は核を足してから条件づける (T_e = Σ T_o)。"""
    prior = (F(1, 2), F(1, 2))
    branches = [((F(1), F(0)), "o1"), ((F(0), F(1)), "o2")]  # 対角の成分 = 状態ごとの質量
    # 証拠が同じ (null) なので 1 つのセルに合算
    T_e = tuple(sum(b[0][i] for b in branches) for i in range(2))
    p_e = sum(t * q for t, q in zip(T_e, prior))
    post = tuple(t * q / p_e for t, q in zip(T_e, prior))
    assert p_e == 1 and post == prior          # 証拠のセルは 1 つ、事後 = 事前
    info = H(prior) - H(post)                  # = 0
    assert info == ZERO
    # 誤り: 内部の枝ごとに条件づけて情報を数える
    wrong = H(prior) - sum((H(b[0]) * F(1, 2) for b in branches), ZERO)
    assert wrong == LN2
    q = softmax([D(0), D(0)])
    u = F(3, 5)
    selected = "H" if u < F(1, 2) else "Q"
    q_wrong = softmax([-wrong.dec(), D(0)])
    assert close(q_wrong[0], D(2) / D(3))
    return {"order": ["H", "Q"], "information_H": info, "q": [F(1, 2), F(1, 2)], "u": u, "selected": selected,
            "wrong_split_by_latent_outcome": {"information_H": wrong, "q": [F(2, 3), F(1, 3)], "selected": "H"},
            "derivation": "証拠の射影が同じ内部の枝は核を合算 (T_e = Σ T_o) してから条件づけるので情報 0、"
                          "J = (0, 0) で q = (1/2, 1/2)、u = 3/5 は F_1 = 1/2 ≤ u なので Q。"
                          "枝ごとに条件づける誤りは ln2・q(H) = 2/3・H"}


def z_shift_property():
    """§3-10-14-11 C の 9: 全部の J に c を足すと q は不変、Z は e^{−γc} 倍 (レビュー F04 の再発を独立に落とす)。
    例: J = (−ln2, −ln2) と (0, 0)、γ = 1。"""
    Z_shifted = 2 * LN2.dec().exp()   # Σ exp(ln2) = 4
    Z_base = D(2)
    assert close(Z_shifted, D(4)) and close(Z_shifted / Z_base, LN2.dec().exp())
    return {"J_base": [ZERO, ZERO], "J_shifted": [LN2 * -1, LN2 * -1], "q": [F(1, 2), F(1, 2)],
            "Z_base": F(2), "Z_shifted": F(4), "wrong_drop_common_factor_Z": F(2),
            "derivation": "Z = Σ exp(−γJ)。共通の c は q で相殺するが Z には e^{−γc} が残る"}


def references():
    items = {"FA02": fa02(), "FA03": fa03(), "FA04": fa04(),
             "FA04_nonzero_path_cost": fa04_nonzero_path_cost(), "FA05": fa05(),
             "FA07": fa07(), "FA07_first_action_cost": fa07_first_action_cost(),
             "FA08": fa08(), "FA09": fa09(), "FA10": fa10(), "FA11": fa11(), "FA12": fa12(),
             "FA13": fa13(), "FA14": fa14(), "FA15": fa15(), "FA16": fa16(), "FA18": fa18(),
             "FA20": fa20(), "FA21_minimal_bridge": fa21_minimal_bridge(), "FB03": fb03(),
             "review_F09_unobservable_branches": review_f09_unobservable_branches(),
             "z_shift_property": z_shift_property()}
    structural = {"FA01": "符号化の拒否と往復 (数なし)", "FA06": "E/K の数の不変 (数なし)",
                  "FA17": "発散の証明と未完了の区別 (負の fixture)", "FA19": "抽選の独立と同じ u (数なし)",
                  "FA21": "旧への橋 (最小の直接の橋は FA21_minimal_bridge、それ以外は旧の golden と既存の 1a L2〜L4・1b Y9・1c・S4b-2 R01〜R07 が正本)"}
    return serial({"spec": "関所F v0.11", "information_unit": "nat", "items": items,
                   "structural_without_numbers": structural})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.path and args.check:
        parser.error("capture and --check are mutually exclusive")
    data = canonical(references()) + b"\n"
    n = len(json.loads(data)["items"])
    if args.check:
        if args.check.read_bytes() != data:
            raise SystemExit("FAIL: independent references differ")
        print(f"PASS: {n} items, exact canonical match")
    elif args.path:
        with args.path.open("xb") as stream:
            stream.write(data)
        print(f"CREATED: {args.path} ({n} items)")
    else:
        print(json.dumps(json.loads(data), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
