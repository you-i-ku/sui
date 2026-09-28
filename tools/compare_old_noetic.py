# 旧 Noetic の core/active_inference と sui の S1 を、同じ 1 modality のモデルで比べる (検品用、どちらのコードも書き換えない)
# 実行: 旧 Noetic の venv (scipy あり) で。2026-09-28 は "Noetic_seed/profiles/_template - features-v2-smoke/.venv" を使った。差の最大 2.22e-16
# S1c: sui の posterior はなくなったので、1 回の観測の事後は belief(q, [log_likelihood(A, 回数, learnable=False)]) で比べる (efe は変わらない)
import sys, math, numpy as np
OLD = r"C:\Users\you11\Desktop\iku\Noetic_seed\profiles\_template"
SUI = r"C:\Users\you11\Desktop\iku\sui\src"
sys.path.insert(0, OLD)
from core.active_inference.model import DiscreteModel, StateFactor, Policy, PolicyStep
from core.active_inference.inference import expected_free_energy, infer_states
sys.path.insert(0, SUI)
from sui.inference import belief, efe, log_likelihood
A = {"look1": np.array([[.9,.5],[.1,.5],[0.,0.]]), "look2": np.array([[.5,.1],[.5,.9],[0.,0.]]), "wait": np.array([[0.,0.],[0.,0.],[1.,1.]])}
worst = 0.0
for logC in (np.full(3, -math.log(3)), np.log(np.array([.1,.2,.7]))):
    old = DiscreteModel(version="cmp", factors=(StateFactor("h", ("s0","s1")),), modalities={"m": ("o0","o1","none")},
                        actions=tuple(A), A={u: {"m": A[u]} for u in A}, Q={u: np.zeros((2,2)) for u in A},
                        D=np.array([.9,.1]), C={"m": logC})
    for q0 in (.9, .642857142857, .3, .1, .5, 1e-9):
        q = np.array([q0, 1-q0])
        for u in A:
            r = expected_free_energy(Policy(u, (PolicyStep(u, 0.0),)), q, old)
            nr, na, _ = efe(q, A[u], logC)
            worst = max(worst, abs(r.risk - nr), abs(r.ambiguity - na))
            for o in range(3):
                onehot = np.eye(3)[o]
                try: po = infer_states(q, A[u], onehot)
                except ValueError: po = None
                try: pn = belief(q, [log_likelihood(A[u], np.eye(3, dtype=np.int64)[o], learnable=False)])
                except ValueError: pn = None
                assert (po is None) == (pn is None), (u, q0, o)
                if po is not None: worst = max(worst, float(np.max(np.abs(po - pn))))
print("max |old - new| over G parts and posteriors:", worst)
