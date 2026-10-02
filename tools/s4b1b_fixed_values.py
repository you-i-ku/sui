"""S4b-1b v0.11 §6-5 の独立した固定値 (実装と並行の試験台本、Claude)。

sui を import しない。有理数は Fraction の総当たり・分割の和・閉じた式で完全一致、
実数は閉じた式か scipy の積分で 1e-12 以内。仕様書・Codex の値と全部照合する。
最後に §3-4 の重い尾の多変数の積分 (誤差を包む方法) を、mpmath 40 桁の参照値で確かめる。

実行: .venv/Scripts/python.exe -B tools/s4b1b_fixed_values.py
"""
from fractions import Fraction as Fr
from itertools import product
import math
import sys

import numpy as np
from scipy.integrate import quad

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
LOG = math.log
results = []


def check(name, value, expected, tol=0.):
    """有理数は tol = 0 で完全一致。実数は |差| ≤ tol。"""
    ok = value == expected if tol == 0 else abs(float(value) - float(expected)) <= tol
    results.append((name, ok, value, expected))
    if not ok:
        print(f"NG {name}: {value} != {expected}")


def h(ps):
    return -sum(float(p) * LOG(float(p)) for p in ps if p)


def hb(x):
    x = float(x)
    return -(x * LOG(x) if x else 0.) - ((1 - x) * math.log1p(-x) if x < 1 else 0.)


def integral(f, a=0., b=1., points=None):
    value, err = quad(f, a, b, epsabs=1e-15, epsrel=1e-15, limit=200, points=points)
    return value


# ---------------------------------------------------------------- D 系 (exact)
def rising(x, n):
    out = Fr(1)
    for i in range(n):
        out *= x + i
    return out


def dirichlet_joint(prior, latent):
    """有限の原子の DP = Dirichlet。潜在の値の列の確率 = Π(a_k)_{N_k} / (α)_n。"""
    counts = [latent.count(k) for k in range(len(prior))]
    return math.prod(rising(a, n) for a, n in zip(prior, counts)) / rising(sum(prior), len(latent))


def brute(prior, allowed):
    """allowed[i] = 試み i が許す原子の集合。(N ごとの重み, 証拠, 潜在の列ごとの重み)。"""
    by_n, by_path = {}, {}
    for latent in product(*allowed):
        w = dirichlet_joint(prior, list(latent))
        n = tuple(latent.count(k) for k in range(len(prior)))
        by_n[n] = by_n.get(n, 0) + w
        by_path[latent] = w
    z = sum(by_n.values())
    return {n: w / z for n, w in by_n.items()}, z, {p: w / z for p, w in by_path.items()}


def predictive(prior, by_n):
    total = sum(prior)
    return tuple(sum(w * (prior[k] + n[k]) / (total + sum(n)) for n, w in by_n.items())
                 for k in range(len(prior)))


ONE, TWO, INF = 0, 1, 2           # 値 {1, 2, ∞}
DIR111 = (Fr(1), Fr(1), Fr(1))

# D1: D₁ = 1・D₂ > 1・D₃ > 0 (Codex sui-s4b1b 1 通目)
d1_n, d1_z, d1_paths = brute(DIR111, [(ONE,), (TWO, INF), (ONE, TWO, INF)])
check("D1 証拠", d1_z, Fr(1, 6))
check("D1 N の種類と重み", sorted(d1_n.values()), [Fr(1, 5)] * 5)
check("D1 予測", predictive(DIR111, d1_n), (Fr(2, 5), Fr(3, 10), Fr(3, 10)))
# D6: 進行中の 2 つ (D₂・D₃) がともに ∞ は 1/5、新しい 2 つなら 2/15
check("D6 進行中の 2 つがともに ∞", sum(w for p, w in d1_paths.items() if p[1] == p[2] == INF), Fr(1, 5))
new_two = sum(w * (DIR111[INF] + n[INF]) * (DIR111[INF] + n[INF] + 1) / ((3 + 3) * (3 + 4))
              for n, w in d1_n.items())
check("D6 新しい 2 つがともに ∞", new_two, Fr(2, 15))
# D2: Dir(1,1,1)・D > 1 一件で E[F({2,∞})] = 3/4 (積の式と総当たり)
d2_n, _, _ = brute(DIR111, [(TWO, INF)])
check("D2 総当たり", sum(predictive(DIR111, d2_n)[1:]), Fr(3, 4))
check("D2 右の打ち切りの積の式", Fr(2 + 1, 3 + 1) * Fr(2, 3) / Fr(2, 3), Fr(3, 4))
# D3: → D = 2 で (1/5, 8/15, 4/15)
d3_n, _, _ = brute(DIR111, [(TWO, INF), (TWO,)])
check("D3 完了の後の見直し", predictive(DIR111, d3_n), (Fr(1, 5), Fr(8, 15), Fr(4, 15)))
# D4: {1, 2, None}・同じ試みを 2 回 {2, None} と確かめても 1 標本 → (1/4, 3/8, 3/8)
d4_n, _, _ = brute(DIR111, [(TWO, INF)])
check("D4 確かめ直しは 1 標本", predictive(DIR111, d4_n), (Fr(1, 4), Fr(3, 8), Fr(3, 8)))
d4_wrong, _, _ = brute(DIR111, [(TWO, INF), (TWO, INF)])
check("D4 2 標本と数える誤り", predictive(DIR111, d4_wrong), (Fr(1, 5), Fr(2, 5), Fr(2, 5)))
# D5: Beta(1,1) に情報の無い観測 10 件 → 事後は不変 (2 つ新しく左 1/3)、5 件ずつ配る誤り 7/26
d5_n, _, _ = brute((Fr(1), Fr(1)), [(0, 1)] * 10)
both_left = sum(w * (1 + n[0]) * (2 + n[0]) / ((2 + 10) * (3 + 10)) for n, w in d5_n.items())
check("D5 情報の無い観測で不変", both_left, Fr(1, 3))
check("D5 5 件ずつ配る誤り", Fr(6, 12) * Fr(7, 13), Fr(7, 26))

# D10・D18: 幅 4・位相 0・潜在 1 か 3 (事前 1/2)、確かめの実時刻は [0,4] で一様
for checks, post in ((1, Fr(3, 4)), (2, Fr(9, 10))):
    lik = [Fr(d, 4) ** checks for d in (1, 3)]
    check(f"D10 未着 {checks} 回の後の長い方", lik[1] / sum(lik), post)
# D11: 共有の受け取り (始まり 0・所要 1/2 が 2 つ・T ~ U[0,1])
#   共有: P(T < d₁ かつ T < d₂) = min(d₁, d₂)、誤り: 試みごとの周辺の積 d₁ d₂
check("D11 共有の受け取りで両方未着", min(Fr(1, 2), Fr(1, 2)), Fr(1, 2))
check("D11 周辺の積の誤り", Fr(1, 2) * Fr(1, 2), Fr(1, 4))
check("D11 幅 4・所要 2・T ~ U[0,4]", (min(Fr(2), Fr(2)) / 4, Fr(2, 4) ** 2), (Fr(1, 2), Fr(1, 4)))
# D12: 幅 1・同じ刻みで始まりの後に確かめ 1 回
d = .5
check("D12 一様の順序統計 2d - d^2", 1 - integral(lambda s: (1 - s - d) if s < 1 - d else 0., 0, 1) * 2, .75, 1e-14)
check("D12 別の法則 d(1 - log d)", integral(lambda s: min(1., d / (1 - s))), d * (1 - LOG(d)), 1e-13)
check("D12 別の法則の値", d * (1 - LOG(d)), 0.84657359027997265, 1e-15)
# D16: 始まり S ~ U[0,1]、所要 1/4、R = S + 1/4 の完了の記録は正規化される
dd = Fr(1, 4)
check("D16 記録 0 と 1 (S + d < 1 か否か)", (1 - dd, dd, 1 - dd + dd), (Fr(3, 4), Fr(1, 4), Fr(1)))
check("D16 一様に置く誤りの和 (差の密度 2(1-d) + d)", 2 * (1 - dd) + dd, Fr(7, 4))
# D17: 所要が両方 1・共通の確かめが λ ごとに U[0,2] か U[0,4]・事前半々・両方未着
lik = [Fr(1, 2), Fr(1, 4)]
check("D17 λ の事後", tuple(x / sum(lik) for x in lik), (Fr(2, 3), Fr(1, 3)))
wrong = [x * x for x in lik]
check("D17 行動ごとに積分して掛ける誤り", tuple(x / sum(wrong) for x in wrong), (Fr(4, 5), Fr(1, 5)))
# D19: 幅 8・始まり 0・A は 1 か 3・B は 2 か 4・両方記録 0・A が先
pairs = {(a, b): Fr(1, 4) for a in (1, 3) for b in (2, 4)}
kernel = {(a, b): 1 if a < b else 0 for a, b in pairs}
z = sum(pairs[p] * kernel[p] for p in pairs)
post = {p: pairs[p] * kernel[p] / z for p in pairs}
check("D19 記録の確率", z, Fr(3, 4))
check("D19 P(A = 3)", sum(w for (a, _), w in post.items() if a == 3), Fr(1, 3))
check("D19 P(B = 4)", sum(w for (_, b), w in post.items() if b == 4), Fr(2, 3))
# 次の試みが長い方: DP α = 2・基底半々で 1 件見た後の Polya (1 + 1{長})/(2 + 1)
nxt = lambda long: Fr(1 + long, 3)
check("D19 次の A が長い", sum(w * nxt(a == 3) for (a, _), w in post.items()), Fr(4, 9))
check("D19 次の B が長い", sum(w * nxt(b == 4) for (_, b), w in post.items()), Fr(5, 9))
# D22: 幅 4・B は 1 か 3 (短い方 p ~ U)・A は 2・S_B < S_A は同じ刻みの一様の順序統計
#   P(h | d) = P(S_A - S_B > d) = (4 - d)^2 / 16、P(h, E_A = 0 | d) = P(S_A - S_B > d, S_A < 2)
#   三角形 0 < S_B < S_A < 4 (密度 1/8) の上で {S_A - S_B > d, S_A < top} の面積 = ∫_d^top (a - d) da
tri = lambda dd, top: max(Fr(0), top - dd) ** 2 / 2 / 8
check("D22 P(h | B = 1)", tri(1, 4), Fr(9, 16))
check("D22 P(h | B = 3)", tri(3, 4), Fr(1, 16))
check("D22 P(h, E_A = 0 | B = 1)", tri(1, 2), Fr(1, 16))
check("D22 P(h, E_A = 0 | B = 3)", tri(3, 2), Fr(0))
ph = lambda p: (1 + 8 * p) / 16            # = p · 9/16 + (1 - p) / 16
ph0 = lambda p: p / 16
R = integral(ph)
check("D22 E[p | h]", integral(lambda p: p * ph(p)) / R, 19 / 30, 1e-14)
check("D22 E[p | h, E_A = 0]", integral(lambda p: p * ph0(p)) / integral(ph0), 2 / 3, 1e-14)
check("D22 E[p | h, E_A = 4]", integral(lambda p: p * (ph(p) - ph0(p))) / integral(lambda p: ph(p) - ph0(p)),
      17 / 27, 1e-14)
q0 = integral(ph0) / R
check("D22 P(E_A = 0 | h)", q0, .1, 1e-15)
d22 = hb(q0) - integral(lambda p: ph(p) * hb(ph0(p) / ph(p))) / R
check("D22 I(F_B; E_A | h)", d22, 0.0015967840886618202613, 1e-15)
# D23: 幅 4・始まりの位相 2 (点)・所要 1・同じ刻みで始まりの後の確かめ 1 回
#   始まり 2 (点)・確かめ C ~ U[2, 4]: P(C < 2 + 1) = 1/2。誤り: 始まりと確かめを [0,4] の順序統計に
check("D23 位相が点", Fr(1, 4 - 2), Fr(1, 2))
check("D23 始まりまで一様にする誤り", 1 - (1 - Fr(1, 4)) ** 2, Fr(7, 16))

# ---------------------------------------------------------------- O 系 (tick と λ)
P0 = lambda p: .25 + p / 2                 # 幅 1・位相一様・潜在 {1/4 (p), 3/4}、記録 0 の確率
for n, value in ((1, Fr(1, 2)), (2, Fr(13, 48)), (3, Fr(5, 32))):
    # E[(1/4 + p/2)^n] = 2((3/4)^{n+1} - (1/4)^{n+1}) / (n + 1)
    check(f"O1 E[P0^{n}]", 2 * (Fr(3, 4) ** (n + 1) - Fr(1, 4) ** (n + 1)) / (n + 1), value)
# O1 後半: G₀ = U[0,1]・α = 1・2 件とも記録 0 (k₀(d) = 1 - d)
m1, m2, m3 = Fr(1, 2), Fr(1, 3), Fr(1, 4)  # ∫k₀, ∫k₀², ∫k₀³
z2 = (m1 * m1 + m2) / rising(Fr(1), 2)
z3 = (m1 ** 3 + 3 * m2 * m1 + 2 * m3) / rising(Fr(1), 3)
check("O1 証拠", z2, Fr(7, 24))
check("O1 まとまり 1 つ", m2 / (m1 * m1 + m2), Fr(4, 7))
check("O1 まとまり 2 つ", m1 * m1 / (m1 * m1 + m2), Fr(3, 7))
check("O1 次も記録 0", z3 / z2, Fr(9, 14))
# O2: 時計 ⌊t⌋・始まり 0・確かめ T ~ U[0,1]
check("O2 未着の尤度 P(T < d)", tuple(min(Fr(1), dd) for dd in (Fr(1, 4), Fr(3, 4))), (Fr(1, 4), Fr(3, 4)))
check("O2 下限への所属だけの誤り (記録 ≥ 0)", (Fr(1), Fr(1)), (Fr(1), Fr(1)))
# O3: α = 2・G₀{∞} = 1/2
check("O3 P(D1 = D2 = ∞)", Fr(1, 2) * (1 + 1) / (2 + 1), Fr(1, 3))
check("O3 同じまとまりだけの誤り", 2 * 1 * Fr(1, 2) / rising(Fr(2), 2), Fr(1, 6))
# O4: λ₀ = 記録は必ず 0、λ₁ = 位相一様 (記録 0 の確率 1/4 + p/2)、λ を共有・事前半々・p ~ U


def moment(k0, k1):
    """E[P0^k0 (1 - P0)^k1] (p ~ U[0,1]) を Fraction で。"""
    poly = np.polynomial.Polynomial
    p0 = [Fr(1, 4), Fr(1, 2)]
    out = [Fr(1)]
    for factor, times in ((p0, k0), ([Fr(3, 4), Fr(-1, 2)], k1)):
        for _ in range(times):
            new = [Fr(0)] * (len(out) + 1)
            for i, c in enumerate(out):
                new[i] += c * factor[0]
                new[i + 1] += c * factor[1]
            out = new
    return sum(c / (i + 1) for i, c in enumerate(out))


def lam_table(records):
    """記録の列 → (記録の確率, 事後の重み, 次の記録 0 の予測)。"""
    k0, k1 = records.count(0), records.count(1)
    lik = [Fr(1) if k1 == 0 else Fr(0), moment(k0, k1)]
    z = sum(Fr(1, 2) * x for x in lik)
    w = tuple(Fr(1, 2) * x / z for x in lik)
    nxt = w[0] * (1 if lik[0] else 0) + w[1] * moment(k0 + 1, k1) / lik[1]
    return z, w, nxt


for records, z, w, nxt in (((), 1, (Fr(1, 2), Fr(1, 2)), Fr(3, 4)),
                           ((0,), Fr(3, 4), (Fr(2, 3), Fr(1, 3)), Fr(61, 72)),
                           ((1,), Fr(1, 4), (Fr(0), Fr(1)), Fr(11, 24)),
                           ((0, 0), Fr(61, 96), (Fr(48, 61), Fr(13, 61)), Fr(111, 122))):
    check(f"O4 {records}", lam_table(list(records)), (z, w, nxt))
# 周辺を別々に混ぜ直す誤り (記録 0 の後): λ の周辺 (2/3, 1/3) と p の周辺の混ぜ合わせを独立に
#   p の周辺の事後 = 2/3·1 + 1/3·(1/2 + p) で E[p] = 19/36、λ の周辺 (2/3, 1/3) と独立に混ぜる
e_p = Fr(2, 3) * Fr(1, 2) + Fr(1, 3) * (Fr(1, 2) * Fr(1, 2) + Fr(1, 3))
check("O4 周辺を混ぜ直す誤り", Fr(2, 3) + Fr(1, 3) * (Fr(1, 4) + e_p / 2), Fr(181, 216))
lik2 = [Fr(1), Fr(1, 2) * Fr(1, 2)]
check("O4 独立な 2 行動が 1 回ずつ 0", tuple(x / sum(lik2) for x in lik2), (Fr(4, 5), Fr(1, 5)))
# O7: L = κ = h = w = 1・位相一様で記録 2 の確率 = log(4/3)
check("O7 記録 2", integral(lambda x: max(0., 1 - abs(x - 2)) / x ** 2, 1, 3, points=[2]), LOG(4 / 3), 1e-14)
check("O7 log(4/3) の値", LOG(4 / 3), 0.287682072451780927, 1e-16)


# O9: 多重度の漸化式 (Codex review 2 通目)
def recurrence_Z(kernels, counts, prior, alpha):
    """kernels: 原子ごとの核の値の表 (種類 × 原子)、counts: 種類ごとの個数、prior: G₀ (原子)。"""
    memo = {}

    def mu(b):
        return sum(g * math.prod(k[x] ** e for k, e in zip(kernels, b)) for x, g in enumerate(prior))

    def C(n):
        if not any(n):
            return Fr(1)
        if n in memo:
            return memo[n]
        i = next(j for j, v in enumerate(n) if v)
        total = Fr(0)
        for b in product(*(range(v + 1) for v in n)):
            if b[i] < 1:
                continue
            ways = math.comb(n[i] - 1, b[i] - 1) * math.prod(math.comb(n[j], b[j]) for j in range(len(n)) if j != i)
            total += ways * math.factorial(sum(b) - 1) * mu(b) * C(tuple(x - y for x, y in zip(n, b)))
        memo[n] = alpha * total
        return memo[n]

    return C(tuple(counts)) / rising(alpha, sum(counts))


def labelled_Z(kernel_list, prior, alpha):
    """名札つきの分割の直接の列挙 (Antoniak の和)。"""
    n = len(kernel_list)

    def partitions(items):
        if not items:
            yield []
            return
        first, rest = items[0], items[1:]
        for part in partitions(rest):
            yield [[first]] + part
            for i in range(len(part)):
                yield part[:i] + [[first] + part[i]] + part[i + 1:]

    total = Fr(0)
    for part in partitions(list(range(n))):
        term = alpha ** len(part)
        for block in part:
            term *= math.factorial(len(block) - 1) * sum(
                g * math.prod(kernel_list[i][x] for i in block) for x, g in enumerate(prior))
        total += term
    return total / rising(alpha, n)


hist, k, one_minus = (Fr(1), Fr(0)), (Fr(3, 4), Fr(1, 4)), (Fr(1, 4), Fr(3, 4))
prior, alpha = (Fr(1, 2), Fr(1, 2)), Fr(2)
base = recurrence_Z([hist], [2], prior, alpha)
for m, value in ((0, Fr(5, 8)), (1, Fr(9, 40)), (2, Fr(11, 128))):
    ratio = recurrence_Z([hist, k, one_minus], [2, 1, m], prior, alpha) / base
    direct = labelled_Z([hist, hist, k] + [one_minus] * m, prior, alpha) / labelled_Z([hist, hist], prior, alpha)
    check(f"O9 E[P(1 - P)^{m}] 漸化式", ratio, value)
    check(f"O9 E[P(1 - P)^{m}] 名札つきの列挙", direct, value)
# 上昇階乗の比を落とす誤り (C の比だけ) は値が変わる
check("O9 C の比だけの誤りは違う値", recurrence_Z([hist, k], [2, 1], prior, alpha) / base * (alpha + 2) != Fr(5, 8), True)

# ---------------------------------------------------------------- U 系 (知る価値)
EH = integral(lambda p: hb(P0(p)))
u2 = math.log(2) - EH
check("U2 I(F; E) 閉じた式", u2, LOG(2) - (.5 - 9 / 8 * LOG(3) + LOG(4)), 1e-15)
check("U2 I(F; E)", u2, 0.0427916441916780934, 1e-15)


def series_tail(M, weight=Fr(1)):
    """ε_M = Σ_r E[(1 - P_r)^{M+1}] / (M + 1)、P₀ = 1/4 + p/2・P₁ = 3/4 - p/2 (同じ値)。"""
    e = 2 * (Fr(3, 4) ** (M + 2) - Fr(1, 4) ** (M + 2)) / (M + 2)   # E[(3/4 - p/2)^{M+1}] = E[(1/4+p/2)^{M+1}]
    return float(weight * 2 * e / (M + 1))


check("U2 64 項の残りの上界", series_tail(64), 5.29231984256609e-12, 1e-25)
check("U2 70 項の残りの上界", series_tail(70), 7.90460386504392e-13, 1e-26)
# 進行中の記録 E_p を条件に: I(F; E_a | E_p) = H(E_a | E_p) - E H(P)
pe = [(lambda p, a=a, b=b: (P0(p) if a == 0 else 1 - P0(p)) * (P0(p) if b == 0 else 1 - P0(p)))
      for a in (0, 1) for b in (0, 1)]
joint = [integral(f) for f in pe]
h_cond = h(joint) - h((joint[0] + joint[1], joint[2] + joint[3]))
check("U2 I(F; E_a | E_p)", h_cond - EH, 0.0393153919887595056, 1e-15)
# U3: λ を入れた所要の項
check("U3 I(F, λ; E)", hb(.75) - EH / 2, 0.2371573764346747423, 1e-15)
check("U3 I(λ; E)", hb(.75) - LOG(2) / 2, 0.2157615543388356956, 1e-15)
check("U3 I(F; E | λ)", u2 / 2, 0.0213958220958390467, 1e-15)
lam_joint = [.5 * float(a == 0 and b == 0) + .5 * j for (a, b), j in zip(product((0, 1), repeat=2), joint)]
check("U3 I(F, λ; E_a | E_p)", h(lam_joint) - hb(lam_joint[0] + lam_joint[1]) - EH / 2,
      0.1678629519655597415, 1e-15)
check("U3 F 既知で I(λ; E)", hb(7 / 8) - hb(3 / 4) / 2, 0.0956025889470326111, 1e-15)
# U4: F と λ が相関する例 (記録 0 の後、λ₀ は今 0・λ₁ は今 1 を必ず出す)
f1 = lambda p: .5 + p
check("U4 E[p | h]", 2 / 3 * .5 + 1 / 3 * integral(lambda p: p * f1(p)), 19 / 36, 1e-15)
mix = lambda p: 2 / 3 + f1(p) / 3
check("U4 I(F; E | h)", hb(2 / 3) - integral(lambda p: mix(p) * hb(2 / 3 / mix(p))), 0.0096212884228709242, 1e-15)
# U5: U・λ・M が公平な 2 値、Y = U・E = λ、Z = (U, λ) か (⊥, ⊥)
cells = [(u, l, m) for u in (0, 1) for l in (0, 1) for m in (0, 1)]
zf = lambda u, l, m: (u, l) if m else None


def cond_mi(target, obs):
    """I(target; obs | Z) を 8 枝の総当たりで (公平な重み)。"""
    out = 0.
    for zv in {zf(*c) for c in cells}:
        sub = [c for c in cells if zf(*c) == zv]
        pz = len(sub) / 8
        jt = {}
        for c in sub:
            jt[(target(*c), obs(*c))] = jt.get((target(*c), obs(*c)), 0) + 1 / len(sub)
        mt, mo = {}, {}
        for (t, o), p in jt.items():
            mt[t] = mt.get(t, 0) + p
            mo[o] = mo.get(o, 0) + p
        out += pz * (h(mt.values()) + h(mo.values()) - h(jt.values()))
    return out


check("U5 I(U, λ; Y, E | Z)", cond_mi(lambda u, l, m: (u, l), lambda u, l, m: (u, l)), LOG(2) * 1, 1e-15)
check("U5 I(U; Y | Z)", cond_mi(lambda u, l, m: u, lambda u, l, m: u), LOG(2) / 2, 1e-15)
check("U5 I(λ; E | Z)", cond_mi(lambda u, l, m: l, lambda u, l, m: l), LOG(2) / 2, 1e-15)
# U6: 決まった記録の候補 (λ₀) のエントロピーは厳密に 0 (64 項、2 候補の例)
check("U6 正しい上界", series_tail(64, Fr(1, 2)), 2.64616e-12, 1e-17)
check("U6 一般の上界を当てる誤り", .5 / 65 + series_tail(64, Fr(1, 2)), 0.007692307694953852, 1e-17)
# U10: F・λ 既知・所要 1/2・始まりの位相だけ一様 → 記録 0・1 が半々でも知る価値 0
check("U10 T を先に条件にする誤り", hb(.5) - 0, LOG(2), 1e-16)
# U11・U12: 共有の確かめ (始まり 0・所要 1/4 (p)・3/4、T ~ U[0,1])、p ~ U、h = 一件目未着
first = lambda p: .75 - p / 2               # P(一件目未着 | p)
both = lambda p: .25 + (1 - p) ** 2 / 2     # P(両方未着 | p)
P2 = lambda p: both(p) / first(p)
check("U11 P(二件目も未着 | h)", integral(both) / integral(first), 5 / 6, 1e-15)
check("U11 別々に積分する誤り", integral(lambda p: first(p) ** 2) / integral(first), 13 / 24, 1e-15)
u12 = integral(lambda p: P2(p) * (1 - P2(p)) * first(p)) / integral(first)
check("U12 E[P(1 - P) | h]", u12, .75 - 9 / 16 * LOG(3), 1e-15)
check("U12 値", u12, 0.13203058762418829859, 1e-15)
# U13 (1): 同じ例で p = 1/4・3/4 の 2 点を半々、E = 二件目の未着
post = [first(p) for p in (.25, .75)]
cond = [P2(p) for p in (.25, .75)]
w = [x / sum(post) for x in post]
u13 = hb(sum(a * b for a, b in zip(w, cond))) - sum(a * hb(b) for a, b in zip(w, cond))
check("U13 恒等式の例 (1) 直接", u13, 0.007508706066214646434704861, 1e-15)
# U13 (2): η 2 値・Z 2 値 (Codex review 6 通目)。直接の式と恒等式
B = {0: {(0, 0): Fr(1, 8), (0, 1): Fr(1, 8), (1, 0): Fr(1, 8), (1, 1): Fr(1, 8)},
     1: {(0, 0): Fr(1, 8), (0, 1): Fr(3, 8), (1, 0): Fr(1, 16), (1, 1): Fr(1, 16)}}
Rh = sum(Fr(1, 2) * sum(t.values()) for t in B.values())
check("U13 (2) P(h)", Rh, Fr(9, 16))
direct = 0.
for zz in (0, 1):
    pz = sum(Fr(1, 2) * (B[e][(zz, 0)] + B[e][(zz, 1)]) for e in (0, 1)) / Rh
    a_e = {eta: Fr(1, 2) * (B[eta][(zz, 0)] + B[eta][(zz, 1)]) for eta in (0, 1)}
    pe_z = [sum(Fr(1, 2) * B[eta][(zz, e)] for eta in (0, 1)) / (pz * Rh) for e in (0, 1)]
    cond_h = sum(a_e[eta] / (pz * Rh) * hb(B[eta][(zz, 0)] / (B[eta][(zz, 0)] + B[eta][(zz, 1)])) for eta in (0, 1))
    direct += float(pz) * (h(pe_z) - cond_h)
phi = lambda x: -float(x) * LOG(float(x)) if x else 0.
ident = 0.
for zz in (0, 1):
    a = sum(Fr(1, 2) * (B[eta][(zz, 0)] + B[eta][(zz, 1)]) for eta in (0, 1))
    b = [sum(Fr(1, 2) * B[eta][(zz, e)] for eta in (0, 1)) for e in (0, 1)]
    ident += float(a) * h([x / a for x in b]) - sum(
        .5 * (phi(B[eta][(zz, 0)]) + phi(B[eta][(zz, 1)]) - phi(B[eta][(zz, 0)] + B[eta][(zz, 1)])) for eta in (0, 1))
ident /= float(Rh)
check("U13 (2) 直接", direct, 0.0203833411304169878573, 1e-15)
check("U13 (2) 恒等式", ident, 0.0203833411304169878573, 1e-15)
check("U13 (2) 等分に平均する誤りは違う値", abs(.5 * sum(
    hb(float((B[0][(zz, 0)] + B[1][(zz, 0)]) / (sum(B[0][(zz, e)] + B[1][(zz, e)] for e in (0, 1))))) for zz in (0, 1)) - direct) > 1e-6, True)

# ---------------------------------------------------------------- v0.16 (同着の順・未来の記録の順)
# D27: 同着の順はどの順も同じ確率。2 つなら各 1/2 (和 1)、3 つなら各 1/6
check("D27 2 つの同着の各順", Fr(1, math.factorial(2)), Fr(1, 2))
check("D27 3 つの同着の各順の和", 6 * Fr(1, math.factorial(3)), Fr(1))
# U15: 幅 8・位相 0・始まりは両方 0、候補 A は既知の 3、進行中 B は {2 (p), 4}、p ~ U。
#   読みはどちらも 0。候補の挿入の位置 (E) は B = 2 なら B→A、B = 4 なら A→B → E が B を明かす
#   I(F_B; E) = H(E) − E[H(E | p)] = h(1/2) − E[h_b(p)] = log 2 − 1/2
u15 = hb(.5) - integral(lambda p: hb(p))
check("U15 未来の記録の順 (挿入の位置は E)", u15, LOG(2) - .5, 1e-15)
check("U15 値", u15, 0.1931471805599453, 1e-15)
# U15 (2): 進行中 C = 4 (既知) も加える。Z = 進行中どうしの順 (B = 2 なら B→C、B = 4 なら C と同着で各 1/2)。
#   E の挿入の位置が D_B を明かすので I(p; E | Z) = H(D_B | Z) − E_p[H(D_B | Z, p)]
pz_bc = integral(lambda p: p + (1 - p) / 2)
h_dz = pz_bc * hb(integral(lambda p: p) / pz_bc)
u15b = h_dz - integral(lambda p: (p + (1 - p) / 2) * hb(p / (p + (1 - p) / 2)))
check("U15 (2) 進行中どうしの順は Z", u15b, .75 * LOG(3) - LOG(2), 1e-14)
check("U15 (2) 値", u15b, 0.1308120359411369591292, 1e-14)

# ---------------------------------------------------------------- そのほかの仕様書の値
check("§3-7 e^{QD} D = 1/4", (1 + math.exp(-.5)) / 2, 0.8032653298563167, 1e-16)
check("§3-7 e^{QD} D = 3/4", (1 + math.exp(-1.5)) / 2, 0.611565080074215, 1e-15)
d7 = brute(DIR111, [(TWO, INF), (ONE,)])[0]
check("§3-8 粗い対象 D_new = 1", sum(predictive(DIR111, d7)[:2]), Fr(7, 10))
d8 = brute(DIR111, [(TWO, INF), (TWO,)])[0]
check("§3-8 粗い対象 D_new = 2", sum(predictive(DIR111, d8)[:2]), Fr(11, 15))
check("§4-5 確率 1e-15 の 2 値エントロピー", hb(1e-15), 3.55388e-14, 1e-19)
check("§4-5 γ = 1e12 の増幅", 1 / (1 + math.exp(-1)), 0.7310585786, 1e-10)


# ---------------------------------------------------------------- O10: 誤差を包む多変数の積分
def ma_add(*terms):
    out = {}
    for coef, X in terms:
        for m, v in X.items():
            out[m] = out.get(m, 0.) + coef * v
    return {m: v for m, v in out.items() if v != 0.}


def ma_eval(X, s):
    return sum(v * math.prod(s[i] for i in m) for m, v in X.items())


class Piece:
    """外から内への変数の上下限 (外の x の一次式 {index: 係数, None: 定数}) と、
    因子 (x の一次式, 冪)。x_k = lo_k + (hi_k - lo_k) s_k で s ∈ [0,1]^n に写す (多重一次)。"""

    def __init__(self, limits, factors, const=1.):
        self.n, self.const, xs, forms = len(limits), const, [], []
        lin = lambda f: ma_add((f.get(None, 0.), {frozenset(): 1.}), *((c, xs[i]) for i, c in f.items() if i is not None))
        for k, (lo, hi) in enumerate(limits):
            LO, HI = lin(lo), lin(hi)
            width = ma_add((1., HI), (-1., LO))
            xs.append(ma_add((1., LO), (1., {m | {k}: v for m, v in width.items()})))
            forms.append((width, 1))
        self.forms = [(lin(f), p) for f, p in factors] + forms

    def value(self, s):
        return self.const * math.prod(ma_eval(X, s) ** p for X, p in self.forms)

    def bound(self, k, rho):
        """sup{|f| : s_k ∈ 写した Bernstein 楕円 E_ρ, ほかは [0,1] の実数} の上界。"""
        A = (rho + 1 / rho) / 2
        lo_re, hi_re, mod = .5 - A / 2, .5 + A / 2, .5 + A / 2
        others = [i for i in range(self.n) if i != k]
        M = abs(self.const)
        for X, p in self.forms:
            alpha = {m: v for m, v in X.items() if k not in m}
            beta = {m - {k}: v for m, v in X.items() if k in m}
            vals = []
            for corner in product((0., 1.), repeat=len(others)):
                s = [0.] * self.n
                for i, v in zip(others, corner):
                    s[i] = v
                vals.append((ma_eval(alpha, s), ma_eval(beta, s)))
            if p >= 0 and p == int(p):
                M *= max(abs(a) + abs(b) * mod for a, b in vals) ** p
                continue
            re_min = min(min(a + b * lo_re, a + b * hi_re) for a, b in vals)
            if re_min <= 0:
                return math.inf
            M *= (re_min ** p if p < 0 else max(abs(a) + abs(b) * mod for a, b in vals) ** p)
        return M

    def integrate(self, N):
        nodes, weights = np.polynomial.legendre.leggauss(N)
        nodes, weights = (nodes + 1) / 2, weights / 2
        total = sum(math.prod(weights[i] for i in idx) * self.value([nodes[i] for i in idx])
                    for idx in product(range(N), repeat=self.n))
        return total, self.error(N)

    def error(self, N):
        """軸ごとの上界。1 次元: |E| ≤ 2M(2 + 2/(4N²-1)) ρ^{-2N} / (1 - ρ^{-2})、[0,1] で 1/2 倍。
        ρ の候補に上限を置かない (上界が下がる間は 2 倍にしていく。整関数なら ρ → ∞ で 0 へ)。"""
        per = []
        for k in range(self.n):
            best, rho = math.inf, 1.05
            while True:
                e = self.bound(k, rho) * (2 + 2 / (4 * N * N - 1)) * rho ** (-2 * N) / (1 - rho ** -2)
                if not e < best:
                    if rho > 2:
                        break
                else:
                    best = e
                rho = rho + .05 if rho < 1.2 else rho * 2
            per.append(best)
        return per


def adaptive(make, n, target, N0=4):
    """箱ごとに次数を 2 倍に増やし (N0, 2N0, 4N0)、それでも 目標 × 箱の体積 に届かなければ、
    寄与が最大の軸で二分する (次数の適応と空間の適応の併用、Johansson 2018 §2 の考え)。
    回数の上限は置かない。二分の中点が端と同じになったら数値の失敗として止まる。"""
    stack, total, err, pieces = [[(0., 1.)] * n], 0., 0., 0
    while stack:
        box = stack.pop()
        vol = math.prod(b - a for a, b in box)
        piece = make(box)
        for N in (N0, 2 * N0, 4 * N0):
            per = piece.error(N)
            if sum(per) <= target * vol:
                break
        else:
            k = max(range(n), key=lambda i: per[i])
            a, b = box[k]
            mid = (a + b) / 2
            if not a < mid < b:
                raise ArithmeticError("bisection cannot split the box")
            stack += [box[:k] + [(a, mid)] + box[k + 1:], box[:k] + [(mid, b)] + box[k + 1:]]
            continue
        value, e = piece.integrate(N)
        total, err, pieces = total + value, err + sum(e), pieces + 1
    return total, err, pieces


def sub(lo, hi, a, b):
    """[lo, hi] (一次式) の s の箱 [a, b] の部分 = lo + (hi - lo) a 〜 lo + (hi - lo) b。"""
    keys = set(lo) | set(hi)
    at = lambda t: {key: lo.get(key, 0.) + (hi.get(key, 0.) - lo.get(key, 0.)) * t for key in keys}
    return at(a), at(b)


KAPPA = 2 / 3
# 参照値は mpmath 1.4.1 の 40 桁 (Claude、scratchpad の別の venv、2026-10-01。台本 integ_ref.py・ref4.py)。
# REF_FOUR は Codex (sui-s4b1b-review 7 通目、別の消去の順) とも全部の桁で一致。
REF_BETA = 0.430963660567163360273514772492
REF_CHAIN = 4.6983167877960075985086234716e-05
REF_LONG = 0.450183201730608990526716286318
REF_FOUR = 7.4028953660967428951458956525992e-07


def tail_density(L, w):
    return w * KAPPA * L ** KAPPA


def beta_piece(box):
    return Piece([sub({None: 2.}, {None: 3.}, *box[0])], [({0: 1.}, -KAPPA), ({0: 1., None: -1.}, -KAPPA)])


def chain_piece(c_lo, c_hi, L=3.5, m=.5, w=.5):
    """5 ≤ a < b+1 < c+2 < 6 (h = 1・位相は点 0・始まり 0, 1, 2・報告は全部読み 5 で a, b, c の順)。
    G₀ = 一様 [0, L) の質量 m + パレート (L, κ) の質量 w。変数の順 c, b, a。
    a も c も b だけに依るので解析的には 1 変数まで減る (3 次元の求積器の検査として使う)。"""
    tail, c_tail = tail_density(L, w), c_lo >= L
    def make(box):
        return Piece([sub({None: c_lo}, {None: c_hi}, *box[0]), sub({None: 4.}, {0: 1., None: 1.}, *box[1]),
                      sub({None: 5.}, {1: 1., None: 1.}, *box[2])],
                     ([({0: 1.}, -KAPPA - 1)] if c_tail else []) + [({1: 1.}, -KAPPA - 1), ({2: 1.}, -KAPPA - 1)],
                     const=(tail if c_tail else m / L) * tail * tail)
    return make


def four_pieces(L=2.5, m=.5, w=.5):
    """5 ≤ a < b+1 < c+2 < d+3 < 6 (始まり 0・1・2・3、報告は全部読み 5 で a, b, c, d の順、Codex の例)。
    a・d を消しても b < c + 1 で結ばれた b・c が残り、初等的に消えない (自由な変数が 2 つ)。
    変数の順 c, b, a, d。d ∈ (c-1, 3) は L = 2.5 の面をまたぐ → c を 3.5 で分け、3 片。"""
    tail = tail_density(L, w)
    def make(c_lo, c_hi, d_lo, d_hi, d_tail):
        def build(box):
            lim = [sub({None: c_lo}, {None: c_hi}, *box[0]), sub({None: 4.}, {0: 1., None: 1.}, *box[1]),
                   sub({None: 5.}, {1: 1., None: 1.}, *box[2]), sub(d_lo, d_hi, *box[3])]
            factors = [({0: 1.}, -KAPPA - 1), ({1: 1.}, -KAPPA - 1), ({2: 1.}, -KAPPA - 1)]
            if d_tail:
                factors.append(({3: 1.}, -KAPPA - 1))
            return Piece(lim, factors, const=tail ** 3 * (tail if d_tail else m / L))
        return build
    return [make(3., 3.5, {0: 1., None: -1.}, {None: L}, False), make(3., 3.5, {None: L}, {None: 3.}, True),
            make(3.5, 4., {0: 1., None: -1.}, {None: 3.}, True)]


def long_piece(box, H=1e4):
    x_lo, x_hi = sub({None: 1.}, {None: H}, *box[0])
    y_lo, y_hi = sub({None: 1.}, {0: 1.}, *box[1])
    return Piece([(x_lo, x_hi), (y_lo, y_hi)],
                 [({0: 1.}, -KAPPA - 1), ({1: 1.}, -KAPPA - 1), ({0: 1., 1: -1., None: 1.}, -KAPPA)])


# 浮動小数点の丸めは区間に含めない (§4-6)。包むことの検査は、離散化の誤差が丸めより十分大きい N で行う。
for N in (3, 4, 6):
    value, per = beta_piece([(0., 1.)]).integrate(N)
    check(f"O10 1 変数 N={N} を包む", abs(value - REF_BETA) <= sum(per), True)
value, bound, _ = adaptive(beta_piece, 1, 1e-12)
ROUND = 4 * sys.float_info.epsilon   # 丸めの余裕 (相対)。保証の外なので検査の側だけで足す
check("O10 1 変数 目標 1e-12", abs(value - REF_BETA) <= bound + ROUND * REF_BETA and bound <= 1e-12, True)
for N in (2, 3, 4):
    parts = [chain_piece(3., 3.5)([(0., 1.)] * 3).integrate(N), chain_piece(3.5, 4.)([(0., 1.)] * 3).integrate(N)]
    value, bound = sum(p[0] for p in parts), sum(sum(p[1]) for p in parts)
    check(f"O10 3 変数の鎖 N={N} を包む (誤差 {abs(value - REF_CHAIN):.1e} ≤ {bound:.1e})",
          abs(value - REF_CHAIN) <= bound and abs(value - REF_CHAIN) > 1e-18, True)
for N in (2, 3, 4):
    parts = [make([(0., 1.)] * 4).integrate(N) for make in four_pieces()]
    value, bound = sum(p[0] for p in parts), sum(sum(p[1]) for p in parts)
    check(f"O10 4 変数 (消去の後も 2 変数) N={N} を包む (誤差 {abs(value - REF_FOUR):.1e} ≤ {bound:.1e})",
          abs(value - REF_FOUR) <= bound and abs(value - REF_FOUR) > 1e-20, True)
value, bound = 0., 0.
for make in four_pieces():
    v, e, _ = adaptive(make, 4, 1e-14)
    value, bound = value + v, bound + e
check("O10 4 変数 目標 1e-14 (全片の和)", abs(value - REF_FOUR) <= bound + ROUND * REF_FOUR and bound <= 3e-14, True)
value, bound, pieces = adaptive(long_piece, 2, 1e-12)
check(f"O10 長い範囲を二分で 1e-12 ({pieces} 片)", abs(value - REF_LONG) <= bound + ROUND * REF_LONG and bound <= 1e-12, True)
# 識別力: 上界を 0 とみなす (誤差を包みに足さない) と外れる
value, _ = beta_piece([(0., 1.)]).integrate(4)
check("O10 誤差を足さない誤りは外れる", abs(value - REF_BETA) > 1e-12, True)
# Codex review 7 通目の BLOCKER: f = 1・N = 4 固定・ρ ≤ 32 だと上界は箱の体積に比例したまま
# 1.8497e-12 × 体積 で、目標 1e-12 × 体積 に二分では届かない。次数を増やす道があれば終わる。
const = lambda box: Piece([sub({None: 0.}, {None: 1.}, *box[0])], [])
fixed = lambda N, rho, vol: vol * (2 + 2 / (4 * N * N - 1)) * rho ** (-2 * N) / (1 - rho ** -2)
check("O10 N 固定・二分だけは届かない (どの体積でも)", all(fixed(4, 32., 2. ** -j) > 1e-12 * 2. ** -j for j in range(60)), True)
value, bound, pieces = adaptive(const, 1, 1e-12)
check("O10 次数の適応で終わる", (abs(value - 1) <= 1e-15, bound <= 1e-12, pieces), (True, True, 1))

failed = [r for r in results if not r[1]]
print(f"{len(results) - len(failed)} / {len(results)} matched")
sys.exit(1 if failed else 0)
