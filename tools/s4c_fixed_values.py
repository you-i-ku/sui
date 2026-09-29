# S4c Part I 固定値: sui のコードを使わない総当たり (状態の道を全部並べる)
import itertools, math
import numpy as np
from scipy.linalg import expm

def B(Q, dt):
    return np.eye(len(Q)) if dt == 0 else expm(Q * dt)

def joint_paths(D, Q, times, lik):
    """times: 昇順の時刻 (0 を含む)。lik[t] = 尤度ベクトル (無ければ 1)。道ごとの重み (正規化)"""
    S = len(D); out = {}
    for path in itertools.product(range(S), repeat=len(times)):
        w = 1.0; prev_t = 0.0; prev_s = None
        for t, s in zip(times, path):
            if prev_s is None:
                w *= (B(Q, t) @ D)[s]
            else:
                w *= B(Q, t - prev_t)[s, prev_s]
            w *= lik.get(t, np.ones(S))[s]
            prev_t, prev_s = t, s
        out[path] = w
    Z = sum(out.values())
    return {k: v / Z for k, v in out.items()}

def G_branch(D, Q, hist, pend_times, pend_A, cand_time, cand_A, logC):
    """hist: {t: 尤度}。pend_times: 進行中の測る時刻。cand: 候補の測る時刻。
    戻り値 (risk, ambiguity, q_o) = 枝の中の E_{o_P}[KL(p(o_pi|o_P)||C)] と E[H(A|s_pi)]"""
    times = sorted(set([0.0] + list(hist) + list(pend_times) + [cand_time]))
    P = joint_paths(D, Q, times, hist)
    idx = {t: i for i, t in enumerate(times)}
    nO = cand_A.shape[0]
    # p(o_P vector, s_pi)
    joint = {}
    for path, w in P.items():
        s_pi = path[idx[cand_time]]
        pstates = [path[idx[t]] for t in pend_times]
        for oP in itertools.product(range(nO), repeat=len(pend_times)):
            pw = w
            for A, s, o in zip(pend_A, pstates, oP):
                pw *= A[o, s]
            if pw > 0:
                joint[(oP, s_pi)] = joint.get((oP, s_pi), 0) + pw
    risk = 0.0; amb = 0.0; q_o = np.zeros(nO)
    oPs = {k[0] for k in joint}
    for oP in oPs:
        ps = np.zeros(len(D))
        for (o2, s), w in joint.items():
            if o2 == oP: ps[s] += w
        mass = ps.sum()
        qo = cand_A @ (ps / mass)
        q_o += mass * qo
        pos = qo > 0
        risk += mass * np.sum(qo[pos] * (np.log(qo[pos]) - logC[pos]))
    ps_all = np.zeros(len(D))
    for (o2, s), w in joint.items(): ps_all[s] += w
    H = np.array([-sum(a * math.log(a) for a in cand_A[:, s] if a > 0) for s in range(len(D))])
    amb = float(ps_all @ H)
    return risk, amb, q_o

def G(D, Q, hist, pend, cand, logC):
    """pend: [(A, [(t_meas, w), ...])]、cand: (A, [(t_meas, w), ...])。枝の直積で平均"""
    cA, cbr = cand
    total_r = total_a = 0.0; q_o = np.zeros(cA.shape[0])
    for combo in itertools.product(*[br for _, br in pend], cbr):
        w = np.prod([c[1] for c in combo])
        pt = [c[0] for c in combo[:-1]]
        r, a, qo = G_branch(D, Q, hist, pt, [A for A, _ in pend], combo[-1][0], cA, logC)
        total_r += w * r; total_a += w * a; q_o += w * qo
    return total_r, total_a, total_r + total_a, q_o

def qpi(Gs, gamma):
    x = -gamma * np.array(Gs); x -= x.max(); e = np.exp(x); return e / e.sum()

def filt(D, Q, hist, t_end):
    times = sorted(set([0.0] + list(hist) + [t_end]))
    P = joint_paths(D, Q, times, hist)
    q = np.zeros(len(D))
    for path, w in P.items(): q[path[-1]] += w
    return q

k = 0.5
Q2 = np.array([[-k, k], [k, -k]])
logC = np.log(np.full(3, 1/3))
look = np.array([[.9, .2], [.1, .8], [0, 0]])
wait = np.array([[0, 0], [0, 0], [1, 1]])
perfect = np.array([[1, 0], [0, 1], [0, 0]])
D = np.array([.5, .5])
gamma = 4.0
np.set_printoptions(precision=17)
def show(name, D, Q, hist, pend, cand, extra=""):
    r, a, g, qo = G(D, Q, hist, pend, cand, logC)
    gw = G(D, Q, hist, pend, (wait, [(cand[1][0][0], 1.0)]), logC)[2]
    p = qpi([g, gw], gamma)
    print(f"{name}: risk={r!r} amb={a!r} G(look)={g!r} G(wait)={gw!r} q_pi(look)={p[0]!r} q_o={qo.tolist()} {extra}")

# A: Codex の例。完全に見える look、進行中は 10 秒後を測る、候補は今 (0) を測る
show("A  pending@10 cand@0 (perfect)", D, Q2, {}, [(perfect, [(10.0, 1.0)])], (perfect, [(0.0, 1.0)]))
show("A' pending@0 cand@0 (S4a近似)", D, Q2, {}, [(perfect, [(0.0, 1.0)])], (perfect, [(0.0, 1.0)]))
show("A0 no pending", D, Q2, {}, [], (perfect, [(0.0, 1.0)]))
# P5: S4a 表6 (o0@0, look 進行中, now=1, 全部 now を測る)
h = {0.0: look[0]}
show("P5 S4a表6", D, Q2, h, [(look, [(1.0, 1.0)])], (look, [(1.0, 1.0)]))
# B: 測る時刻 = 始めた時刻。o0 は 0 を測る (受け取り 0.5)、進行中 A2 は 1 を測る、o1 は 2 を測る (受け取り 2.5)、now=3
hB = {0.0: look[0], 2.0: look[1]}
print("B q@anchor(2.0) start-measured:", filt(D, Q2, hB, 2.0).tolist())
print("B q@now(3.0):", filt(D, Q2, hB, 3.0).tolist())
show("B  start-measured", D, Q2, hB, [(look, [(1.0, 1.0)])], (look, [(3.0, 1.0)]))
hB2 = {0.5: look[0], 2.5: look[1]}
print("B' q@anchor(2.5) receipt-measured:", filt(D, Q2, hB2, 2.5).tolist())
show("B' S4a-style (受け取りで測る・進行中は今)", D, Q2, hB2, [(look, [(3.0, 1.0)])], (look, [(3.0, 1.0)]))
# C: 受け取りで測る、所要時間 {1: .5, 4: .5}。o0 受け取り 1、進行中 A2 は 1.5 に開始、now=3 (経過 1.5 → d=4 だけ → 5.5 を測る)
hC = {1.0: look[0]}
show("C  now=3 pending@5.5 cand@{4,7}", D, Q2, hC, [(look, [(5.5, 1.0)])], (look, [(4.0, .5), (7.0, .5)]))
show("C2 now=2 pending@{2.5,5.5} cand@{3,6}", D, Q2, hC, [(look, [(2.5, .5), (5.5, .5)])], (look, [(3.0, .5), (6.0, .5)]))
# D: 届かない重み。所要時間 {2: .5, None: .5}、経過 3 → None だけ → 進行中は何も測らない
show("D  never", D, Q2, hC, [], (look, [(4.0, .5), (7.0, .5)]))

print("---- 基準つき (rest = none、1 回の出来事は G + ln C(none)、届かない枝は 0) ----")
ref = logC[2]
def Gref(D, Q, hist, pend, cand_branches, A):
    """cand_branches: [(t or None, w)]。None = 届かない (0)"""
    tot = 0.0; parts = []
    for t, w in cand_branches:
        if t is None:
            parts.append((w, 0.0)); continue
        r, a, g, qo = G(D, Q, hist, pend, (A, [(t, 1.0)]), logC)
        parts.append((w, g + ref)); tot += w * (g + ref)
    return tot
def show2(name, hist, pend, cand_branches, now):
    gl = Gref(D, Q2, hist, pend, cand_branches, look)
    gw = 0.0
    p = qpi([gl, gw], gamma)
    print(f"{name}: G(look)={gl!r} G(wait)={gw!r} q_pi(look)={p[0]!r}")
show2("P5 表6 (基準つき)", h, [(look, [(1.0, 1.0)])], [(1.0, 1.0)], 1.0)
show2("B  start-measured", hB, [(look, [(1.0, 1.0)])], [(3.0, 1.0)], 3.0)
hB3 = {0.5: look[0], 2.1: look[1]}
print("B'' q@anchor(2.1) receipt:", filt(D, Q2, hB3, 2.1).tolist(), " q@now(3):", filt(D, Q2, hB3, 3.0).tolist())
show2("B'' S4a-style 受け取り 0.5・2.1、進行中は今", hB3, [(look, [(3.0, 1.0)])], [(3.0, 1.0)], 3.0)
show2("C  now=3", hC, [(look, [(5.5, 1.0)])], [(4.0, .5), (7.0, .5)], 3.0)
show2("C2 now=2", hC, [(look, [(2.5, .5), (5.5, .5)])], [(3.0, .5), (6.0, .5)], 2.0)
show2("D  never {1:.5, None:.5}, now=3", hC, [], [(4.0, .5), (None, .5)], 3.0)
show2("A  Codex例", {}, [(perfect, [(10.0, 1.0)])], [(0.0, 1.0)], 0.0) if False else None
gA = G(D, Q2, {}, [(perfect, [(10.0, 1.0)])], (perfect, [(0.0, 1.0)]), logC)[2] + ref
print("A  基準つき G(look)=", repr(gA), " q_pi(look)=", repr(qpi([gA, 0.0], gamma)[0]), " I=", repr(-gA))

print("---- v0.2 (基準なし、届かない枝なし) ----")
show("B'' receipt 0.5/2.1, 進行中は今", D, Q2, hB3, [(look, [(3.0, 1.0)])], (look, [(3.0, 1.0)]))

print("---- v0.4 E6 (片づけ前の結果): o0 を 1 に測る、進行中 J (look) は 1.5 を測る、候補 peek (完全) は 2 を測る ----")
for tJ in (1.5, 2.5):
    r, a, g, qo = G(D, Q2, {1.0: look[0]}, [(look, [(tJ, 1.0)])], (perfect, [(2.0, 1.0)]), logC)
    print(f"J@{tJ}: G(peek)={g!r} q_pi(peek)={qpi([g, math.log(3)], gamma)[0]!r}")
