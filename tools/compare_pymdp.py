"""S1b §6-4・S1c §6-4: sui と pymdp 1.0.4 の比べっこ (検品用。どちらのコードも書き換えない)。
S1c から sui は観測の回数だけを持ち、信念と帳面を毎回計算する。pymdp の学習は事後 q′ の分を足す (S1 の規則) ので、
4 の学習後の選択は一致しなくなる (差を記録する)。4b は pymdp の更新に事後の代わりに (1, 1) を渡した時に sui の帳面と同じになるか。

pymdp の venv で実行し、sui は src を sys.path に足して import する。
venv の作り方 (sui の依存にはしない): py -3.12 -m venv <どこか> → <venv>/Scripts/python -m pip install --timeout 300 inferactively-pymdp==1.0.4
(jax が大きく、1 回目は通信の時間切れで失敗した。2026-09-28)
"""
import math
import sys
import time

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
import numpy as np

from pymdp import control, inference, learning

sys.path.insert(0, r"C:\Users\you11\Desktop\iku\sui\src")
from sui.inference import belief, efe, expected_A, ledger, log_likelihood, novelty, select  # noqa: E402

WINDOWS = ("look1", "look2", "wait")
TRUE = {
    "look1": np.array([[.9, .5], [.1, .5], [0., 0.]]),
    "look2": np.array([[.5, .1], [.5, .9], [0., 0.]]),
    "wait": np.array([[0., 0.], [0., 0.], [1., 1.]]),
}
worst = {}


def note(key, value):
    worst[key] = max(worst.get(key, 0.0), float(value))


def full_A(A_by_window):
    # A[o, s, window]
    return jnp.stack([jnp.asarray(A_by_window[w]) for w in WINDOWS], axis=-1)


def B_lists():
    B_hidden = jnp.eye(2)[:, :, None]  # (2, 2, 1)
    B_window = jnp.zeros((3, 3, 3))
    for a in range(3):
        B_window = B_window.at[a, :, a].set(1.0)  # 前の窓がどれでも、行動 a の後は窓 a
    return [B_hidden, B_window]


B = B_lists()
A_DEP, B_DEP = [[0, 1]], [[0], [1]]


def pymdp_neg_efe(q, A_by_window, log_C, u, pA_by_window=None):
    A = [full_A(A_by_window)]
    pA = None if pA_by_window is None else [full_A(pA_by_window)]
    qs = [jnp.asarray(q), jnp.ones(3) / 3]
    policy = jnp.array([[0, u]])
    return float(control.compute_neg_efe_policy(
        qs, A, B, [jnp.asarray(log_C)], pA, None, A_DEP, B_DEP, policy,
        use_utility=True, use_states_info_gain=True, use_param_info_gain=pA is not None))


def pymdp_novelty(q, counts_by_window, u):
    A = full_A({w: expected_A(counts_by_window[w]) for w in WINDOWS})
    window = jnp.eye(3)[u]
    qs = [jnp.asarray(q), window]
    qo = control.compute_expected_obs(qs, [A], A_DEP)
    return -float(control.calc_negative_pA_info_gain([full_A(counts_by_window)], qo, qs, A_DEP))


def pymdp_posterior(q, A_u, o):
    obs = [jnp.eye(3)[o][None, :]]
    qs = inference.update_posterior_states([jnp.asarray(A_u)], None, obs, None, prior=[jnp.asarray(q)],
                                           A_dependencies=[[0]], method="exact", distr_obs=True)
    return np.asarray(qs[0]).reshape(-1)[-2:]


# 1. 状態の事後 (選んだ窓の A を切り出して 1 因子で)
for u, w in enumerate(WINDOWS):
    for q0 in (.9, .5, .2, 1e-9):
        q = np.array([q0, 1 - q0])
        for o in range(3):
            try:
                ours = belief(q, [log_likelihood(TRUE[w], np.eye(3, dtype=np.int64)[o], learnable=False)])
            except ValueError:
                continue
            theirs = pymdp_posterior(q, TRUE[w], o)
            note("1 posterior", np.max(np.abs(ours - theirs)))

# 2. novelty なしの G
for log_C in (np.full(3, -math.log(3)), np.log(np.array([.1, .2, .7]))):
    for q0 in (.9, .642857142857, .5, .2):
        q = np.array([q0, 1 - q0])
        for u, w in enumerate(WINDOWS):
            r, a, _ = efe(q, TRUE[w], log_C)
            note("2 G without novelty", abs((r + a) - (-pymdp_neg_efe(q, TRUE, log_C, u))))

# 3. novelty: sui (定義どおりの期待値) と pymdp (周辺の積)
counts = {w: 10 * TRUE[w] for w in WINDOWS}
counts["look2"] = np.array([[1., 1.], [1., 1.], [0., 0.]])
rows = []
for w, c in (("look1", 10 * TRUE["look1"]), ("look2", counts["look2"])):
    for q0 in (1.0, .9, .5, .2):
        q = np.array([q0, 1 - q0])
        byw = dict(counts); byw[w] = c
        ours = novelty(q, c)
        theirs = pymdp_novelty(q, byw, WINDOWS.index(w))
        rows.append((w, q0, ours, theirs))
print("3 novelty (window, q0, sui, pymdp):")
for row in rows:
    print("   %s q0=%-4s sui=%.15f pymdp=%.15f diff=%.3e" % (row[0], row[1], row[2], row[3], row[3] - row[2]))

# 4. 学習後の A -> G -> q_pi -> 同じ u での選択 (L5 の世界: look2 は知らない・学ぶ、事前 (.5,.5)、γ=64、u=.5、台本 o1)
gamma, u_draw, log_C = 64.0, .5, np.full(3, -math.log(3))
D0 = np.array([.5, .5])
ours_q, theirs_q = D0.copy(), jnp.array([.5, .5])
ours_c = {w: c.copy() for w, c in counts.items()}
ours_n = {w: np.zeros(3, dtype=np.int64) for w in WINDOWS}
theirs_pA = full_A(counts)
theirs_pA_b = full_A(counts)
calls = {"sui": [], "pymdp": []}
for step in range(6):
    # sui
    G = []
    for w in WINDOWS:
        r, a, _ = efe(ours_q, expected_A(ours_c[w]), log_C)
        G.append(r + a - (novelty(ours_q, ours_c[w]) if w == "look2" else 0.0))
    G = np.array(G)
    q_pi = np.exp(-gamma * (G - G.min())); q_pi /= q_pi.sum()
    ours_choice = WINDOWS[select(q_pi, u_draw)]
    # pymdp: G は novelty なしの neg_efe から、学ぶ窓 (look2) だけ pymdp の novelty を足す
    A_now = {w: np.asarray(theirs_pA[:, :, i] / theirs_pA[:, :, i].sum(axis=0).clip(1e-300)) for i, w in enumerate(WINDOWS)}
    neg = np.array([pymdp_neg_efe(np.asarray(theirs_q), A_now, log_C, i) for i in range(3)])
    neg[1] += pymdp_novelty(np.asarray(theirs_q), {w: np.asarray(theirs_pA[:, :, i]) for i, w in enumerate(WINDOWS)}, 1)
    p_pi = np.asarray(jax.nn.softmax(gamma * jnp.asarray(neg)))
    theirs_choice = WINDOWS[select(p_pi / p_pi.sum(), u_draw)]
    note("4 q_pi", np.max(np.abs(q_pi - p_pi)))
    calls["sui"].append(ours_choice); calls["pymdp"].append(theirs_choice)
    # 実行 (台本 o1) と更新: 両方とも自分が選んだ窓で
    o = 1
    i = WINDOWS.index(ours_choice)
    # sui: 前の q を持ち回らず、初期の D・初期の数え上げ・全部の窓の回数から毎回計算する (S1c)
    ours_n[ours_choice][o] += 1
    ours_q = belief(D0, [log_likelihood(counts[w], ours_n[w], learnable=(w == "look2")) for w in WINDOWS])
    ours_c["look2"] = ledger(counts["look2"], ours_n["look2"])
    if ours_choice == "look2":
        # 4b: pymdp の更新に、隠れた命題の事後の代わりに (1, 1) を渡す
        theirs_pA_b, _ = learning.update_obs_likelihood_dirichlet_m(
            theirs_pA_b, jnp.eye(3)[o][None, :], [jnp.ones(2)[None, :], jnp.eye(3)[i][None, :]], [0, 1])
    j = WINDOWS.index(theirs_choice)
    A_j = A_now[theirs_choice]
    theirs_new = pymdp_posterior(np.asarray(theirs_q), A_j, o)
    if theirs_choice == "look2":
        theirs_pA, _ = learning.update_obs_likelihood_dirichlet_m(
            theirs_pA, jnp.eye(3)[o][None, :], [jnp.asarray(theirs_new)[None, :], jnp.eye(3)[j][None, :]], [0, 1])
    theirs_q = jnp.asarray(theirs_new)
    note("4 q after step", np.max(np.abs(np.asarray(ours_q) - np.asarray(theirs_q))))
note("4 counts look2 (規則が違うので差が出る)", np.max(np.abs(ours_c["look2"] - np.asarray(theirs_pA[:, :, 1]))))
note("4b counts look2 (pymdp に (1, 1) を渡す)", np.max(np.abs(ours_c["look2"] - np.asarray(theirs_pA_b[:, :, 1]))))
print("4 calls sui  :", calls["sui"])
print("4 calls pymdp:", calls["pymdp"])

# 5. 計算時間 (novelty なしの G 1 回ぶん)
q = np.array([.9, .1])
t0 = time.perf_counter(); pymdp_neg_efe(q, TRUE, log_C, 0); t1 = time.perf_counter()
for _ in range(100):
    pymdp_neg_efe(q, TRUE, log_C, 0)
t2 = time.perf_counter()
for _ in range(100):
    efe(q, TRUE["look1"], log_C)
t3 = time.perf_counter()
print("5 time: pymdp first %.3fs, pymdp after %.2fms/call, sui %.3fms/call" % (t1 - t0, (t2 - t1) * 10, (t3 - t2) * 10))

print("max abs differences:")
for k, v in worst.items():
    print("   %-22s %.3e" % (k, v))
