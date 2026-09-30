"""S4d 仕様書 §6-5 の固定値を、sui のコードを使わずに総当たりで作る。

世界 WS (状態は変わらない、Q なし): 状態 s0・s1、D = (.5, .5)。
look は A の列 s0 = (.9, .1, 0)・s1 = (.2, .8, 0)、所要 {1: .5, 3: .5}。
peek は完全に見える、所要 {2: 1}。wait は none だけ、所要 {None: 1}。
どれも "report"。now = 0、進行中なし、締め切り T = H。
再帰 (§3-2-4) と、全路の列挙 E[ℓ] − I(X; O, A) の両方で計算し、一致を確かめる。
"""

import itertools
import math

STATES = (0, 1)
PRIOR = (0.5, 0.5)
OUT = ("o0", "o1", "none")
A = {
    "look": ((0.9, 0.1, 0.0), (0.2, 0.8, 0.0)),
    "peek": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "wait": ((0.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
}
DUR = {"look": ((1, 0.5), (3, 0.5)), "peek": ((2, 1.0),), "wait": ((None, 1.0),)}
U = ("look", "peek", "wait")


def normalize(v):
    total = math.fsum(v)
    return tuple(x / total for x in v)


def kl(p, q):
    return math.fsum(a * math.log(a / b) for a, b in zip(p, q) if a > 0)


def branches(post, t, a, T):
    """(E, q, 子の事後) を E の値ごとに合算して返す。E = ('arr', 時刻, 観測) か ('none',)。"""
    rows = {}
    for d, w in DUR[a]:
        if d is None or t + d > T:
            key = ("none",)
            like = tuple(w for _ in STATES)
            rows[key] = tuple(x + y for x, y in zip(rows.get(key, (0.0, 0.0)), like))
            continue
        for k, o in enumerate(OUT):
            key = ("arr", t + d, o)
            like = tuple(w * A[a][s][k] for s in STATES)
            rows[key] = tuple(x + y for x, y in zip(rows.get(key, (0.0, 0.0)), like))
    out = []
    for key, like in sorted(rows.items(), key=lambda kv: str(kv[0])):
        joint = tuple(p * l for p, l in zip(post, like))
        q = math.fsum(joint)
        if q > 0:
            out.append((key, q, normalize(joint)))
    return out


def softmax_finite(J, gamma):
    finite = [j for j in J if j != math.inf]
    if not finite:
        return None
    m = min(finite)
    z = [math.exp(-gamma * (j - m)) if j != math.inf else 0.0 for j in J]
    s = math.fsum(z)
    return [x / s for x in z]


def J_node(post, t, a, T, gamma, ell, obs, acts):
    """J_h(η, a) = −I(X; E ∣ η, a) + Σ_e q(e) V_h(η ⊕ (a, e))。"""
    acts = acts + ((t, len(acts), a),)
    rows = branches(post, t, a, T)
    info = math.fsum(q * kl(child, post) for _, q, child in rows)
    total = -info
    for key, q, child in rows:
        if key[0] == "none":
            V = ell(obs, acts)
        else:
            obs2 = obs + ((key[1], len(acts) - 1, a, key[2]),)
            Js = [J_node(child, key[1], b, T, gamma, ell, obs2, acts) for b in U]
            rho = softmax_finite(Js, gamma)
            V = math.inf if rho is None else math.fsum(r * j for r, j in zip(rho, Js) if r > 0)
        total += q * V if q > 0 else 0.0
    return total


def enumerate_paths(a0, T, gamma, ell):
    """全路を (状態, 路) の同時分布として並べ、E[ℓ] − I(X; (O, A)) を直接計算する。"""
    joint = {}

    def walk(s, w, post, t, a, obs, acts):
        acts = acts + ((t, len(acts), a),)
        for d, pd in DUR[a]:
            if d is None or t + d > T:
                path = (obs, acts)
                joint[(s, path)] = joint.get((s, path), 0.0) + w * pd
                continue
            for k, o in enumerate(OUT):
                pw = w * pd * A[a][s][k]
                if pw == 0:
                    continue
                key = ("arr", t + d, o)
                child = dict((kk, c) for kk, _, c in branches(post, t, a, T))[key]
                obs2 = obs + ((t + d, len(acts) - 1, a, o),)
                Js = [J_node(child, t + d, b, T, gamma, ell, obs2, acts) for b in U]
                rho = softmax_finite(Js, gamma)
                for b, r in zip(U, rho):
                    if r > 0:
                        walk(s, pw * r, child, t + d, b, obs2, acts)

    for s in STATES:
        walk(s, PRIOR[s], PRIOR, 0, a0, (), ())
    paths = sorted({p for _, p in joint}, key=str)
    px = [math.fsum(v for (s, _), v in joint.items() if s == x) for x in STATES]
    pp = {p: math.fsum(joint.get((s, p), 0.0) for s in STATES) for p in paths}
    mi = math.fsum(v * math.log(v / (px[s] * pp[p])) for (s, p), v in joint.items() if v > 0)
    cost = math.fsum(v * ell(*p) for p, v in pp.items())
    return cost - mi


def blank(obs, acts):
    return 0.0


def o1_count(obs, acts):
    """試験の中だけの決まり: min(o1 の数, 2) に P* = (.2, .3, .5)。"""
    n = min(sum(1 for *_, o in obs if o == "o1"), 2)
    return -math.log((0.2, 0.3, 0.5)[n])


def report(name, T, gamma, ell):
    Js = [J_node(PRIOR, 0, a, T, gamma, ell, (), ()) for a in U]
    q = softmax_finite(Js, gamma)
    print(f"{name}: T = {T}, γ = {gamma}")
    for a, j, qq in zip(U, Js, q):
        e = enumerate_paths(a, T, gamma, ell)
        print(f"  {a}: J = {j!r}  q_pi = {qq!r}  |J − 列挙| = {abs(j - e):.2e}")


if __name__ == "__main__":
    report("L1 (付箋なし、先読み)", 4, 1.0, blank)
    report("L2 (試験の決まり o1_count)", 4, 1.0, o1_count)
    report("L3 (付箋なし、H = 1)", 1, 1.0, blank)
