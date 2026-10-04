"""S4b-1c v0.24 §6-2 の独立した固定値 (実装の前の試験台本、Claude 2026-10-04)。

sui を import しない。有理数は Fraction で完全一致、実数は閉じた式・digamma・
scipy の積分・総当たりの列挙で、2 通り以上の計算の差を確かめる。仕様書と
Codex `sui-s4b1c` の値とも照合する。帰着 (L2〜L4・Y9) と停止・公開の境界は
sui のコードが要るので試験 (tests/) の側で行い、ここには置かない。

実行: .venv/Scripts/python.exe -B tools/s4b1c_fixed_values.py
"""
from fractions import Fraction as Fr
import math
import sys

import numpy as np
from scipy.integrate import quad, tplquad
from scipy.special import betaln, digamma

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
LOG = math.log
LN2 = LOG(2)
results = []


def check(name, value, expected, tol=0.):
    """有理数は tol = 0 で完全一致。実数は |差| ≤ tol。"""
    ok = value == expected if tol == 0 else abs(float(value) - float(expected)) <= tol
    results.append((name, ok, value, expected))
    if not ok:
        print(f"NG {name}: {value} != {expected}")


def hb(p):
    return 0. if p <= 0 or p >= 1 else -p * LOG(p) - (1 - p) * LOG(1 - p)


def EHb(a, b):
    """E[H_b(p)], p ~ Beta(a, b)。"""
    n = a + b
    return (a / n) * (digamma(n + 1) - digamma(a + 1)) + (b / n) * (digamma(n + 1) - digamma(b + 1))


def kl_beta(a1, b1, a0, b0):
    """KL(Beta(a1, b1) ‖ Beta(a0, b0))。"""
    return (betaln(a0, b0) - betaln(a1, b1) + (a1 - a0) * digamma(a1) + (b1 - b0) * digamma(b1)
            + (a0 - a1 + b0 - b1) * digamma(a1 + b1))


def kl_disc(p, q):
    return sum(x * LOG(x / y) for x, y in zip(p, q) if x > 0)


def softmax_q(J, gamma=1.):
    J = np.asarray(J, float)
    w = np.exp(-gamma * (J - J.min()))
    return w / w.sum()


# --- 情報の対象: 混合の成分のラベルを数えない (§3-7-2) ---------------------
# ½Beta(2,1) + ½Beta(1,2) の密度は x + (1 - x) = 1 = Beta(1,1)
dens = [0.5 * 2 * x + 0.5 * 2 * (1 - x) for x in np.linspace(0, 1, 11)]
check("混合 = Beta(1,1) の密度", max(abs(d - 1) for d in dens), 0., 1e-15)
false_bonus = 0.5 * kl_beta(2, 1, 1, 1) + 0.5 * kl_beta(1, 2, 1, 1)
check("成分ごとの KL の平均 (誤り) = log 2 − ½", false_bonus, LN2 - 0.5, 1e-15)
check("偽の加点 0.1931471806", false_bonus, 0.1931471806, 1e-10)

# --- B_h・d_h の式 (§3-7-3): p ~ U[0,1]、根までに成功 1 回、その後もう 1 回 -----
Bs, Bf = kl_beta(3, 1, 2, 1), kl_beta(2, 2, 2, 1)
check("B_成功 = log(3/2) − 1/3", Bs, LOG(1.5) - 1 / 3, 1e-15)
check("B_失敗 = log 3 − 5/6", Bf, LOG(3) - 5 / 6, 1e-15)
d = 2 / 3 * Bs + 1 / 3 * Bf
check("d = 0.1365141682948128", d, 0.1365141682948128, 1e-15)
# 条件つきの情報で: I(p; Y | h) = H_b(E[p|h]) − E[H_b(p) | h]、h: Beta(2,1)
check("d = I(p; Y | h)", d, hb(2 / 3) - EHb(2, 1), 1e-15)
# §3-7-3 の級数の形: L0 = p、Lη′ = p² (成功) または p(1−p) (失敗)、μ = U[0,1]
def B_series(Leta, L0, M):
    z0 = quad(L0, 0, 1)[0]
    ze = quad(Leta, 0, 1)[0]
    s = sum(quad(lambda x, m=m: Leta(x) * (1 - L0(x)) ** m / m, 0, 1)[0] for m in range(1, M + 1))
    phi = quad(lambda x: -Leta(x) * LOG(Leta(x)) if Leta(x) > 0 else 0., 0, 1)[0]
    return LOG(z0 / ze) + (s - phi) / ze, 1 / ((M + 1) * ze)

for name, Le, ref in (("成功", lambda x: x * x, Bs), ("失敗", lambda x: x * (1 - x), Bf)):
    val, bound = B_series(Le, lambda x: x, 400)
    check(f"級数の B_{name} は区間 [val, val + 上界] に参照を含む", val <= ref + 1e-12 and ref <= val + bound + 1e-12, True)

# --- 橋 A (§3-0-11): 所要を学ぶと中身と選択が変わる 1 歩 -----------------------
def bridgeA(a, b):
    Ep = a / (a + b)
    py = .5 * Ep + .75 * (1 - Ep)          # P(s(1)=1) = 1/2、P(s(2)=1) = 3/4
    cost = -(py * LOG(.8) + (1 - py) * LOG(.2))
    info = (hb(Ep) - EHb(a, b)) + Ep * LN2 + (1 - Ep) * (.75 * -LOG(.75) + .25 * -LOG(.25))
    return py, cost, info, cost - info

Jb_A = -(.5 * LOG(.8) + .5 * LOG(.2)) - LN2
check("橋 A J_b", Jb_A, 0.2231435513, 1e-10)
for (a, b), exp in (((3, 1), (0.5625, 0.8296473343, 0.7644459829, 0.0652013514, 0.5394036712)),
                    ((1, 3), (0.6875, 0.6563605392, 0.6990399649, -0.0426794257, 0.5660671659))):
    py, c, I, J = bridgeA(a, b)
    q = softmax_q([J, Jb_A])[0]
    check(f"橋 A Beta{(a, b)} P(Y_a=1)", Fr(py).limit_denominator(10 ** 6), Fr(exp[0]).limit_denominator(10 ** 6))
    for nm, v, e in (("費用", c, exp[1]), ("総情報", I, exp[2]), ("J_a", J, exp[3]), ("q(a)", q, exp[4])):
        check(f"橋 A Beta{(a, b)} {nm}", v, e, 1e-10)
# 同じ乱数 u = 0.55、候補の順 (a, b): q(a) < u なら b
pick = lambda qa, u=.55: "a" if u < qa else "b"
check("橋 A u=.55 で Beta(3,1) は b", pick(softmax_q([bridgeA(3, 1)[3], Jb_A])[0]), "b")
check("橋 A u=.55 で Beta(1,3) は a", pick(softmax_q([bridgeA(1, 3)[3], Jb_A])[0]), "a")

# --- 橋 B (§3-0-13): Q・名前・所要の学習を同時に先読みへ (H = 2) --------------
# 段 1 の X* = (p, θ0, θ1, s(1), s(2))、初期 0、0→1 率 log 2 (吸収)
HB = 2
ROOT = [((0, 0), (1, 1), {0: (1, 1), 1: (1, 1)}, .25),
        ((0, 1), (1, 1), {0: (1, 1), 1: (1, 1)}, .25),
        ((1, 1), (1, 1), {0: (1, 1), 1: (1, 1)}, .5)]


def st(path, t):
    return 0 if t == 0 else path[t - 1]


def outcomes(comp, act, t):
    path, cp, th, w = comp
    if act == "b":
        tc = t + 1
        return [(("b", tc, st(path, tc)), 1., comp, tc)] if tc <= HB else [(("none",), 1., comp, None)]
    a, b = cp
    Ep = a / (a + b)
    out = []
    for dd, pd, ncp in ((1, Ep, (a + 1, b)), (2, 1 - Ep, (a, b + 1))):
        tc = t + dd
        if tc > HB:
            out.append((("none",), pd, (path, ncp, th, w), None))
            continue
        s = st(path, tc)
        al, be = th[s]
        for y, py in ((1, al / (al + be)), (0, be / (al + be))):
            nth = dict(th)
            nth[s] = (al + 1, be) if y else (al, be + 1)
            out.append((("a", tc, y), pd * py, (path, ncp, nth, w), tc))
    return out


def cond_H(comp, act, t):
    path, (a, b), th, w = comp
    if act == "b":
        return 0.
    Ep = a / (a + b)
    h = EHb(a, b)
    for dd, pd in ((1, Ep), (2, 1 - Ep)):
        if t + dd <= HB:
            h += pd * EHb(*th[st(path, t + dd)])
    return h


def step(belief, act, t):
    groups = {}
    for comp in belief:
        for key, pr, nc, nt in outcomes(comp, act, t):
            g = groups.setdefault(key, [0., [], nt])
            g[0] += comp[3] * pr
            g[1].append((nc[0], nc[1], nc[2], comp[3] * pr))
    tot = sum(g[0] for g in groups.values())
    HE = -sum((g[0] / tot) * LOG(g[0] / tot) for g in groups.values() if g[0] > 0)
    Hc = sum(c[3] * cond_H(c, act, t) for c in belief) / sum(c[3] for c in belief)
    kids = []
    for key, (pk, comps, nt) in groups.items():
        z = sum(c[3] for c in comps)
        kids.append((key, pk / tot, [(c[0], c[1], c[2], c[3] / z) for c in comps], nt))
    return HE - Hc, kids


def V(belief, t):
    if t is None or t >= HB:
        return 0., None
    J = {}
    for act in ("a", "b"):
        info, kids = step(belief, act, t)
        J[act] = -info + sum(pk * V(b, nt)[0] for _, pk, b, nt in kids)
    q = softmax_q([J["a"], J["b"]])
    return float(q[0] * J["a"] + q[1] * J["b"]), (J, q)


vroot, (JB, qB) = V(ROOT, 0)
check("橋 B 根 J_a", JB["a"], -0.6004777099601217, 1e-13)
check("橋 B 根 J_b", JB["b"], -1.0417864504639565, 1e-13)
check("橋 B 根 q(a)", qB[0], 0.3914291668110499, 1e-12)
kid_values = {}
for act in ("a", "b"):
    for key, pk, b, nt in step(ROOT, act, 0)[1]:
        v, r = V(b, nt)
        if r:
            kid_values[(act, key)] = (v, r[1][0])
check("橋 B 根 a・所要 1 の報告の後 V", kid_values[("a", ("a", 1, 1))][0], -0.4283666977, 1e-10)
check("橋 B 根 a・所要 1 の報告の後 q(a)", kid_values[("a", ("a", 1, 1))][1], 0.4211358999, 1e-10)
check("橋 B 根 b・状態 0 の後 V", kid_values[("b", ("b", 1, 0))][0], -0.5315791849, 1e-10)
check("橋 B 根 b・状態 0 の後 q(a)", kid_values[("b", ("b", 1, 0))][1], 0.4004893872, 1e-10)
check("橋 B 根 b・状態 1 の後 V", kid_values[("b", ("b", 1, 1))][0], -0.1656993549, 1e-10)
check("橋 B 根 b・状態 1 の後 q(a)", kid_values[("b", ("b", 1, 1))][1], 0.5719277716, 1e-10)
# 次の a の情報 (根 a・所要 1 の後) = h(2/3) − ½ + (2/3)(h(5/8) − ½)
info_next = step(next(b for k, pk, b, nt in step(ROOT, "a", 0)[1] if k == ("a", 1, 1)), "a", 1)[0]
check("橋 B 次の a の情報 0.2442229937", info_next, hb(2 / 3) - .5 + 2 / 3 * (hb(5 / 8) - .5), 1e-13)


# 全終端からの総量: 再帰の方策 π で終端の記録の列を列挙し、E_π KL(P(X* | y) ‖ P(X*)) を直接
def kl_total(comps):
    """comps: 路ごとに 1 つの成分 (路 → Beta の数え)。KL = Σ_路 P(路|y)[log P(路|y)/P(路) + Σ KL(Beta)]。"""
    prior = {c[0]: w for c in ROOT for w in [c[3]]}
    tot = 0.
    for path, cp, th, w in comps:
        if w <= 0:
            continue
        k = LOG(w / prior[path]) + kl_beta(*cp, 1, 1) + kl_beta(*th[0], 1, 1) + kl_beta(*th[1], 1, 1)
        tot += w * k
    return tot


def path_total(belief, t, first=None):
    if t is None or t >= HB:
        return kl_total(belief)
    if first is None:
        _, (J, q) = V(belief, t)
        probs = {"a": q[0], "b": q[1]}
    else:
        probs = {first: 1.}
    tot = 0.
    for act, pa in probs.items():
        for _, pk, b, nt in step(belief, act, t)[1]:
            tot += pa * pk * path_total(b, nt)
    return tot


for act in ("a", "b"):
    check(f"橋 B 根 J_{act} = −E_π[B_h(η_N)] (全終端の直接の総 KL)", -path_total(ROOT, 0, act), JB[act], 1e-13)

# --- 段 1 の結合の事後: 混合 (Beta の数え) と、直接の 3 重積分の一致 ------------
# 履歴: 根 a が所要 1 で完了、名前 1 (s(1) の θ)。P(路, y) を路ごとに
def mixture_post():
    out = {}
    for path, cp, th, w in ROOT:
        s1 = path[0]
        out[path] = w * Fr(1, 2) * Fr(1, 2)        # E[p] E[θ_{s1}] = 1/2・1/2
    z = sum(out.values())
    return {k: v / z for k, v in out.items()}


def integral_post():
    out = {}
    for path, cp, th, w in ROOT:
        val = tplquad(lambda t1, t0, p: p * (t1 if path[0] else t0), 0, 1, 0, 1, 0, 1)[0]
        out[path] = w * val
    z = sum(out.values())
    return {k: v / z for k, v in out.items()}


mp, ip = mixture_post(), integral_post()
for k in mp:
    check(f"段 1 の結合の事後 路{k} 混合 = 積分", float(mp[k]), ip[k], 1e-10)

# --- progress の核 (§3-7-5) ----------------------------------------------------
q = LN2


def progress_mass(w, c0, c1, H=math.inf):
    """初期 0・0→1 率 q。原子 (R = w/c0、T ≥ t0) と連続の部分 (T < t0) の質量と、密度の積分。"""
    t0 = w / c0
    atom = math.exp(-q * t0)
    if c0 == c1:
        return atom, 1 - atom, None
    slope = 1 - c0 / c1                     # R = w/c1 + slope·T
    dens = lambda r: q * math.exp(-q * (r - w / c1) / slope) / abs(slope)
    lo, hi = sorted((w / c1, w / c1 + slope * t0))
    return atom, quad(dens, lo, hi)[0], (lo, hi)


for name, (c0, c1) in (("速くなる", (1, 2)), ("遅くなる", (2, 1))):
    atom, cont, _ = progress_mass(1, c0, c1)
    check(f"progress {name} 原子 + 連続 = 1", atom + cont, 1., 1e-12)
check("progress 遅くなる 原子 0.7071067812", progress_mass(1, 2, 1)[0], 0.7071067812, 1e-10)
check("progress 遅くなる 連続 0.2928932188", progress_mass(1, 2, 1)[1], 0.2928932188, 1e-10)
# ヤコビアンを落とす誤り (|slope| で割らない) は質量 1 にならない (速くなる例、|slope| = 1/2)
bad_fast = quad(lambda r: q * math.exp(-q * (r - .5) / .5), .5, 1)[0]   # 速くなる例で |slope| = 1/2 を落とす
check("progress 速くなる ヤコビアンを落とす誤りは質量が合わない", abs(bad_fast + .5 - 1) > 1e-3, True)

# 同じ速さ: 完了の時刻は 1 点、状態は 0・1 の両方 (w = 1、c = 1 → R = 1、P(s(1) = 1) = 1/2)
check("progress 同じ速さ 完了の時刻 1 点でも P(s(R)=1) = 1/2", 1 - math.exp(-q * 1), .5, 1e-15)
# 有限の仕事量の永久未着 (2 状態が率 1 で行き来・両方の速さ 0 → P(D = ∞) = 1) は、
# 進みの積分が恒等的に 0 になることの検査で、数値の固定値ではないので試験 (tests/) の側に置く

# --- progress の情報 (定規): 速さ (1,1)・(1,2) 半々、w = 1、H = 1 ---------------
post_R1 = {((1, 1), 0): Fr(1, 2) * Fr(1, 2), ((1, 1), 1): Fr(1, 2) * Fr(1, 2),
           ((1, 2), 0): Fr(1, 2) * Fr(1, 2), ((1, 2), 1): Fr(0)}
z = sum(post_R1.values())
post_R1 = {k: v / z for k, v in post_R1.items()}
check("progress R = 1 の結合の事後 (1,1),0", post_R1[((1, 1), 0)], Fr(1, 3))
check("progress R = 1 の結合の事後 (1,1),1", post_R1[((1, 1), 1)], Fr(1, 3))
check("progress R = 1 の結合の事後 (1,2),0", post_R1[((1, 2), 0)], Fr(1, 3))
check("progress R = 1 の結合の事後 (1,2),1", post_R1[((1, 2), 1)], Fr(0))
indep = (post_R1[((1, 2), 0)] + post_R1[((1, 2), 1)]) * (post_R1[((1, 1), 1)] + post_R1[((1, 2), 1)])
check("progress 独立に混ぜ直す誤りは (1,2),1 に 1/9", indep, Fr(1, 9))
I_rho = LN2 - .75 * hb(1 / 3)
check("progress I(ρ; R) 0.2157615543388357", I_rho, 0.2157615543388357, 1e-15)
g_int = quad(lambda t: q * 2 ** -t * (-LOG(1 - 2 ** (-(1 + t) / 2))), 0, 1, epsabs=1e-14)[0] + .5 * LN2
M = 80
g_ser = .5 * LN2 + sum(2 / (n * (n + 2)) * (2 ** (-n / 2) - 2. ** (-n - 1)) for n in range(1, M + 1))
tail = 2 ** (-(M + 1) / 2) / (2 * (M + 1) * (1 - 2 ** -.5))
check("progress ＊ 級数 80 項の残りの上界 1.3553792864e-14", tail, 1.3553792864e-14, 1e-23)
check("progress ＊ 級数 ≤ 積分 ≤ 級数 + 上界", g_ser - 1e-15 <= g_int <= g_ser + tail + 1e-15, True)
check("progress ＊ 0.8225607462", g_int, 0.8225607461934701, 1e-13)
Ia = I_rho + .5 * g_int
check("progress 𝓘_a 0.6270419274", Ia, 0.6270419274355707, 1e-13)
check("progress q_a 0.6518184260", softmax_q([-Ia, 0.])[0], 0.6518184260214424, 1e-13)

# --- 締め切りの前の未着 (H = .75) と未着による状態の更新 -----------------------
p_bot = .5 + .5 * 2 ** -.5
r = .5 * 2 ** -.5 / p_bot
check("未着 p_⊥ 0.8535533906", p_bot, 0.8535533906, 1e-10)
check("未着 P(ρ=(1,2) | ⊥) = √2 − 1", r, math.sqrt(2) - 1, 1e-15)
B_bot = kl_disc([r, 1 - r], [.5, .5])
check("未着 B_h(⊥) 0.0147917024", B_bot, 0.0147917024, 1e-10)
check("未着 p_⊥ B_h(⊥) 0.0126255077", p_bot * B_bot, 0.0126255077, 1e-10)
check("未着 P(s(.75)=1 | R > .75) = 1 − 2^{-1/4}", (2 ** -.5 - 2 ** -.75) / 2 ** -.5, 1 - 2 ** -.25, 1e-15)
check("未着 名前だけの濾過の誤り 1 − 2^{-3/4}", 1 - 2 ** -.75, 0.4053964425, 1e-10)

# --- 時刻・因果 (§3-2) ----------------------------------------------------------
check("開始の共有 R = .75・D = .1 で読み ⌊.85⌋ = 0", math.floor(.75 + .1), 0)
check("開始を U[.75, 1) に引き直す誤りの読み 1 の確率", Fr(1, 10) / Fr(1, 4), Fr(2, 5))
# 同着: 公平な状態 X を知らせる進行中の報告が自分の無情報な報告と同着、次の行動は X に合う方の好み .8・違う方 .2、γ = 1
q_after = softmax_q([-LOG(.8), -LOG(.2)])[0]                   # X を読んでから選ぶ: 合う方を q で
J_blind = -(.5 * LOG(.8) + .5 * LOG(.2))                        # X を知らずに選ぶ: 両方の期待費用が同じ
q_blind = softmax_q([J_blind, J_blind])[0]
check("同着 全部読んでから選ぶ正解の確率 0.8", q_after, .8, 1e-15)
check("同着 自分の報告だけで選ぶ誤りは 0.5", .5 * q_blind + .5 * (1 - q_blind), .5, 1e-15)
# 締め切り: 根の本当の時刻 U ~ U[0,1]、窓 (U, U + 1]、進行中の報告の到着 1.5
p_in = quad(lambda u: 1. if 1.5 <= u + 1 else 0., 0, 1, points=[.5])[0]
p_bad = quad(lambda u: 1. if 1.5 <= 2 else 0., 0, 1)[0]       # 本当の時刻の上限 2 で窓を切る誤り
check("締め切り 届く確率 0.5", p_in, .5, 1e-12)
check("締め切り 上限で切る誤りは 1", p_bad, 1., 1e-12)
check("縮約の係数 J = (0,2)・γ = 1", sum(softmax_q([0, 2]) * abs(1 - (np.array([0, 2]) - softmax_q([0, 2]) @ np.array([0, 2])))), 1.1815684976, 1e-10)

# --- 不変 (§5) ------------------------------------------------------------------
# λ を見分ける: 仕事量 1・開始 0、λ = exact (読み 1) / 幅 2・位相 0 の tick (読み 0) 半々 → log 2
check("λ を見分けた情報 log 2", hb(.5), LN2, 1e-15)
# 同じ λ の候補の複製: exact を 2 つに割って (1/4, 1/4)、tick 1/2 → λ の名札の上では H が増えるが
# 記録 (読み) の分布は同じ → 記録が教える情報は同じ log 2 (名札を対象にしない)
reads = {"exact_a": 1, "exact_b": 1, "tick": 0}
w = {"exact_a": .25, "exact_b": .25, "tick": .5}
pr = {}
for k, v in reads.items():
    pr[v] = pr.get(v, 0) + w[k]
check("λ の複製で記録の情報は変わらない", -sum(x * LOG(x) for x in pr.values()), LN2, 1e-15)
# 単位の同時の変換 (W, ρ) → (cW, cρ): R の分布は不変 (速くなる例、c = 3)
a1 = progress_mass(1, 1, 2)[0]
a3 = progress_mass(3, 3, 6)[0]
check("尺度の同時の変換で原子の質量は不変", a1, a3, 1e-15)

# --- 根の q の上下界 (§3-7-4 の ⑥) ---------------------------------------------
def q_bounds(Ls, Us, gamma=1.):
    out = []
    for i in range(len(Ls)):
        lo = math.exp(-gamma * Us[i]) / (math.exp(-gamma * Us[i]) + sum(math.exp(-gamma * Ls[j]) for j in range(len(Ls)) if j != i))
        hi = math.exp(-gamma * Ls[i]) / (math.exp(-gamma * Ls[i]) + sum(math.exp(-gamma * Us[j]) for j in range(len(Ls)) if j != i))
        out.append((lo, hi))
    return out

Jt = [bridgeA(3, 1)[3], Jb_A]
qb = q_bounds([j - 1e-9 for j in Jt], [j + 1e-9 for j in Jt])
qt = softmax_q(Jt)
check("q の上下界が真の q を包む", all(lo <= qq <= hi for (lo, hi), qq in zip(qb, qt)), True)
check("同点・誤差 ±5e-13・γ = 1e12 で q は 0.5〜0.7310585786", q_bounds([0 - 5e-13, 0 - 5e-13], [0 + 5e-13, 0 + 5e-13], 1e12)[0][1], 0.7310585786, 1e-9)

ok = sum(1 for r in results if r[1])
print(f"{ok} / {len(results)} 一致")
sys.exit(0 if ok == len(results) else 1)
