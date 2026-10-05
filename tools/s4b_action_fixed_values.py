"""Independent S4b action v0.19 references (spec §3-6, §6-2).

No sui imports. Fractions are serialized as reduced [numerator, denominator].
Natural logarithms give nats; mathematical times are seconds. Capture creates a
new file exclusively; --check recomputes and compares without writing anything.
R1/R5 byte identities are obligations checked by the separate baseline golden,
not numeric values invented by this oracle. See each item's derivation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction as F
from itertools import product
import json
import math
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def serial(value):
    if isinstance(value, F):
        return [value.numerator, value.denominator]
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    return value


def kl(p, q):
    return math.fsum(float(x) * math.log(float(x / y)) for x, y in zip(p, q) if x)


def entropy(p):
    return -math.fsum(float(x) * math.log(float(x)) for x in p if x)


def mv(matrix, vector):
    return tuple(sum((F(a) * b for a, b in zip(row, vector)), F()) for row in matrix)


def beta_moment(a, b, power):
    result = F(1)
    for k in range(power):
        result *= (F(a) + k) / (F(a) + F(b) + k)
    return result


def t15_enumeration(side="post"):
    """Integrate each independent uniform Beta column, then sum 2**7 paths."""
    actions, observations = (0, 1, 0, 0, 1, 0), (1, 0, 1, 1, 0, 1)
    evidence, components = F(), set()
    for states in product(range(2), repeat=7):
        counts = {(kind, a, s): [0, 0]
                  for kind in ("B", "Theta") for a in range(2) for s in range(2)}
        for i, (a, y) in enumerate(zip(actions, observations)):
            counts["B", a, states[i]][states[i + 1]] += 1
            measured = states[i + (side == "post")]
            counts["Theta", a, measured][y] += 1
        mass = F(1, 2)
        for n0, n1 in counts.values():
            mass *= F(math.factorial(n0) * math.factorial(n1),
                      math.factorial(n0 + n1 + 1))
        evidence += mass
        components.add((states[-1], tuple(tuple(v) for v in counts.values())))
    return {"evidence": evidence, "paths": 128, "components": len(components)}


def finite_tree():
    """Two reports; read=identity, random=fair reset, reset=constant 0.

    Carry the full registered state vector. Enumerate B-conditioned root law
    separately from observation-conditioned paths at every leaf. Backwards
    recursion and a second forward summation over all terminal histories agree.
    """
    kernels = {"read": ((1, 0), (0, 1)),
               "random": ((F(1, 2), F(1, 2)),) * 2,
               "reset": ((1, 1), (0, 0))}
    names = tuple(sorted(kernels))

    def law(controls):
        paths = {(s, ()): F(1, 2) for s in range(2)}
        for action in controls:
            nxt = defaultdict(F)
            for (before, registered), mass in paths.items():
                for after in range(2):
                    nxt[after, registered + (after,)] += mass * kernels[action][after][before]
            paths = {key: mass for key, mass in nxt.items() if mass}
        result = defaultdict(F)
        for (_, registered), mass in paths.items():
            result[registered] += mass
        return dict(result)

    policies, scores = {}, {}

    def backward(controls=(), observed=()):
        root_law = law(controls)
        potential = -math.log(float(root_law[observed])) if observed else 0.
        if len(controls) == 2:
            return 0.
        values = []
        for action in names:
            full = law(controls + (action,))
            mass = sum(p for path, p in full.items() if path[:-1] == observed)
            branches = [(path, p / mass) for path, p in full.items()
                        if path[:-1] == observed and p]
            expected_b = math.fsum(float(p) * -math.log(float(full[path]))
                                  for path, p in branches)
            future = math.fsum(float(p) * backward(controls + (action,), path)
                               for path, p in branches)
            values.append(-(expected_b - potential) + future)
        weights = [math.exp(-j) for j in values]
        policy = [w / sum(weights) for w in weights]
        policies[controls, observed] = policy
        scores[controls, observed] = values
        return math.fsum(p * j for p, j in zip(policy, values))

    value = backward()

    def forward(controls=(), observed=(), path_mass=1.):
        if len(controls) == 2:
            return path_mass * -math.log(float(law(controls)[observed]))
        total = 0.
        for action, choice_mass in zip(names, policies[controls, observed]):
            full = law(controls + (action,))
            denominator = sum(p for path, p in full.items() if path[:-1] == observed)
            for path, p in full.items():
                if path[:-1] == observed and p:
                    total += forward(controls + (action,), path,
                                     path_mass * choice_mass * float(p / denominator))
        return total

    information = forward()
    assert abs(value + information) < 1e-14
    return {"candidates": names, "H_s": F(2), "J": scores[(), ()],
            "q": policies[(), ()], "terminal_information": information,
            "recursive_value": value}


def references():
    L = math.log(2)
    half = (F(1, 2), F(1, 2))
    I, C, flip = ((1, 0), (0, 1)), ((1, 1), (0, 0)), ((0, 1), (1, 0))
    P = ((F(1, 2), 0), (F(1, 2), 1))
    result = {}

    def add(key, values, derivation):
        result[key] = {"values": values, "derivation": derivation}

    add("T1", {"information": kl((1, 0), (1, 0)), "wrong_uncontrolled": L},
        "For each forced A=a the reference and posterior of X are delta_a; "
        "the fair mixture over selected controls is not the reference.")
    add("T2", {"information": entropy(half), "wrong_condition_on_actions": 0.},
        "Enumerate X=0,1 with weight 1/2; O1=X and A2=O1. Identity keeps the "
        "original fair reference; both fully observed paths have KL=ln2.")
    add("T3", {"flip_information": entropy(mv(flip, half)), "reset_information": 0.},
        "Flip preserves fair prior; full report gives entropy ln2. C maps both "
        "states to 0, so posterior and controlled reference are delta_0.")
    add("T4", {"once": entropy(half), "twice": entropy((F(1, 4),) * 4)},
        "Independent resets give two/four equiprobable registered state vectors.")
    law_information = L - F(1, 2)
    add("T5", {"law_information": law_information, "joint_information": L,
               "wrong_marginal_sum": law_information + L},
        "Integrate uniform p: integral_0^1 2*p*ln(2*p) dp=ln2-1/2. "
        "Y=S' is deterministic given (p,S'), so joint information=H(Y)=ln2.")
    add("T6", {"theta_information": law_information, "constant_B_information": 0.},
        "Known constant state with uniform Theta uses the same integral as T5. "
        "A constant likelihood in B leaves its density unchanged, KL=0.")
    add("T7", {"start_pre": L, "start_post": 0., "completion_state": [F(1), F(0)]},
        "Measure the fair state before C, or deterministic 0 after C. Completion "
        "is after the impulse, before the next choice; it adds no extra uncertainty.")
    add("T8", {"C_then_F": mv(flip, mv(C, (F(1), F(0)))),
               "F_then_C": mv(C, mv(flip, (F(1), F(0))))},
        "Multiply column-stochastic kernels in causal order, from initial state 0.")
    add("T9", {"P_C_b": mv(P, mv(C, (F(0), F(1)))),
               "C_P_b": mv(C, mv(P, (F(0), F(1))))},
        "P=exp(Q*1s), Q[1,0]=ln2, Q[0,0]=-ln2. Apply C and P in both "
        "orders from state 1; column is departure. This includes nonzero Q.")
    add("T10", {"one_second": F(1, 2), "half_second": -math.expm1(-L / 2),
                "switch_at_one": F(1, 2), "wrong_both_intervals": F(3, 4)},
        "Absorbing 0->1 law is 1-exp(-ln2*t); switch at 1 integrates only the "
        "second of two one-second intervals.")
    add("T11", {"completion_s": F(1, 2) + (2 - F(1, 2)) / 2,
                "wrong_fixed_speed_s": F(2)},
        "One shared W=2: accumulate 1/2, then remaining 3/2 at speed 2.")
    posterior = F(4, 5) * F(1, 2) / (F(4, 5) * F(1, 2) + F(1, 5) * F(1, 2))
    add("T12", {"success_posterior": posterior, "uninformative_abort": F(1, 2)},
        "Bayes: (.5*.8)/(.5*.8+.5*.2); constant abort likelihood cancels.")
    mean = posterior * beta_moment(2, 1, 1) + (1-posterior) * beta_moment(1, 2, 1)
    second = posterior * beta_moment(2, 1, 2) + (1-posterior) * beta_moment(1, 2, 2)
    wrong = beta_moment(F(9, 5), F(6, 5), 2)
    add("T13", {"weights": [posterior, 1-posterior], "mean": mean, "second": second,
                "wrong_second": wrong, "difference": second-wrong},
        "Use E[p^k]=prod_i(a+i)/(a+b+i) in .8 Beta(2,1)+.2 Beta(1,2); "
        "compare Beta(9/5,6/5), not an expected-count update.")
    add("T14", {"information": 0., "next_two_successes": beta_moment(1, 1, 2),
                "wrong_mean_product": beta_moment(1, 1, 1) ** 2},
        "Unobserved Bernoulli trial has likelihood p+(1-p)=1; uniform prior "
        "remains, integral p^2 dp=1/3.")
    add("T15", {"post": t15_enumeration(), "pre": t15_enumeration("pre")},
        "Enumerate 128 initial/state paths. Each path mass is 1/2 times the "
        "product over B and Theta columns of n0!*n1!/(n0+n1+1)!.")
    add("T16", {"J": [-L, 0.], "q": [F(2, 3), F(1, 3)], "tree": finite_tree()},
        "H=1s read/reset: terminal KL is ln2/0, cost=0, gamma=1. exp(-J) "
        "is 2:1. Additional H=2 tree independently enumerates all terminal "
        "registered vectors, then checks forward total against backward recursion.")

    def dispatch_table(correlated=False):
        cells = defaultdict(F)
        for u in (0, 1):
            delays = [(F(1, 4) if u == 0 else F(3, 4), F(1))] if correlated else [
                (F(1, 4), F(1, 2)), (F(3, 4), F(1, 2))]
            for delay, weight in delays:
                # exp[-4 ln2 (12-(11+delay))] = 2**[-4(1-delay)].
                survival = F(1, 2 ** int(4 * (1-delay))) if u == 0 else F(0)
                cells[f"{u}0"] += F(1, 2) * weight * survival
                cells[f"{u}1"] += F(1, 2) * weight * (1-survival)
        return {key: mass for key, mass in cells.items() if mass}

    independent, correlated = dispatch_table(), dispatch_table(True)
    add("T17", {"joint_U_Z": independent, "information": 0.},
        "U fair; R=.25/.75; T_in=R+10<11. tau=11+Delta. For U=0, "
        "survival at 12 is (1/8+1/2)/2=5/16. All observed clock readings "
        "and report names are constant, so posterior equals same-kernel reference.")
    z0 = F(5, 16)
    add("T18", {"constant_parent": 0., "constant_child": 0.,
                "read_increment": entropy((z0, 1-z0)),
                "wrong_reference_early": F(7, 32), "wrong_reference_late": F(13, 32),
                "wrong_early_KL": kl((z0, 1-z0), (F(7, 32), F(25, 32))),
                "wrong_late_KL": kl((z0, 1-z0), (F(13, 32), F(19, 32)))},
        "U is auxiliary, state initially 0. R=.25+U, think=10/10.5; "
        "all T_in<12. Shared waiting gives Z0=(1/8+1/2)/2=5/16 at 13. "
        "Fixing only the U=0 half to early/late gives (1/8+5/16)/2=7/32 "
        "or (1/2+5/16)/2=13/32.")
    add("T19", {"send_reference": [F(0), F(1)], "send_increment": 0.,
                "wrong_drop_reference": list(half), "wrong_drop_increment": L},
        "Enumerate U=0,1: max(1,.25+2U) is 1 or 9/4, both before 3. "
        "Both send and reset to 1. Dropping late U=1 changes half the reference.")
    add("T20", {"information": L, "drop_all_informative_clocks": 0.,
                "condition_reference_on_clock": 0., "drop_only_later_clock": L},
        "Exact R=1+U and tau=R+1/4. Observed R=2 already identifies U=1. "
        "Controlled reference stays fair; dropping both likelihoods or "
        "conditioning the reference makes posterior and reference identical.")
    add("T21", {"joint_U_Z": correlated, "information": 0.,
                "wrong_independent_KL": kl(tuple(correlated.values()), tuple(independent.values()))},
        "Keep Delta=.25 for U=0, .75 for U=1. Survival mass is .5/8=1/16; "
        "compare to the independent T17 table: (1/16)ln(2/5)+(7/16)ln(14/11).")
    add("T22", {"reference_X_Z": {"01": F(1, 2), "11": F(1, 2)},
                "parent": L, "child": L, "increment": 0.,
                "wrong_endogenous_increment": -L, "wrong_response_increment": math.log(F(2, 3))},
        "not_before=9/4 is after fixed X=S(2), preserving fair X and forcing Z=1. "
        "Removing reservation makes early U=0 reset before 2, so reference "
        "X=1 becomes certain (or 3/4 with exponential response).")
    add("T23", {"reference_V_Z": {k: F(1, 4) for k in ("00", "01", "10", "11")},
                "parent": L, "read_child": 2*L, "read_increment": L,
                "constant_child": L, "constant_increment": 0.,
                "wrong_kappa_share_increment": math.log(4)-math.log(3)/2},
        "At 2, V is fair: exp[-(4/3)ln2*(2-5/4)]=1/2. Waiting until 9/4 "
        "then independent reset makes four joint cells 1/4. V=0 gives ln2; "
        "reading Z gives ln4. Constant report retains ln2.")
    add("T24", {"exact_information": L, "same_tick_information": 0.},
        "Chi is a shared law, not an individual delay draw. Two deterministic "
        "candidate laws with equal priors are identified by exact, but have "
        "identical integer readings when both lie in one tick.")
    add("T25", {"events": ["reservation", "receipt", "dispatch", "report", "redelivery"],
                "B_trial_counts": [0, 0, 1, 1, 1], "never_dispatched": 0},
        "Count unique physical applications of B, not observations: "
        "start-impulse/2 applies once at dispatch, including self transitions.")
    add("R1", {"immediate_probability": F(1)-F(1, 2)**2,
               "wait_probability": F(1)-F(1, 2)**3, "new_informative_notice": L,
               "equality_obligation": "all generating laws equal, immediate-start/1"},
        "Absorbing rate ln2 from state0 gives 3/4 at t=2 and 7/8 at t=3. "
        "Waiting changes the experiment. Equal B/Q alone is insufficient.")
    known = ((F(3, 4), F(1, 4)), (F(1, 4), F(3, 4)))
    add("R2", {"B": known, "one_step": mv(known, (F(1), F(0))),
               "two_steps": mv(known, mv(known, (F(1), F(0)))), "B00_squared": F(3, 4)**2},
        "Known law is a point mass. Multiply its exact rational table; "
        "its second moment is (3/4)^2, not the moment of any finite Dirichlet.")
    add("R3", {"second_moments": {str(k): beta_moment(F(k, 2), F(k, 2), 2)
                                   for k in (1, 2, 10, 100, 1000)},
               "limit": F(1, 4), "finite_forbidden_cost": "+inf", "point_zero_cost": 0.},
        "Symmetric Beta gives (k+2)/(4(k+1)); Beta(1,k+1) has positive "
        "forbidden mass at every finite k, so infinite cost does not converge to zero.")
    add("R4", {"evidence": t15_enumeration()["evidence"]},
        "Set every Q_m=0; T15's independent integrated discrete path sum remains. "
        "This full reduction uses unknown B/Theta and requires stage1b.")
    add("R5", {"two_candidates_gamma_zero": list(half),
               "wrong_extra_wait": [F(1, 3)]*3,
               "byte_obligation": "tests/golden_s4b_action.json pre_implementation"},
        "Softmax at gamma0 is uniform on the declared candidate set; adding wait "
        "changes 1/2 to 1/3. Actual old model bytes come from baseline, not this oracle.")
    assert set(result) == {f"T{i}" for i in range(1, 26)} | {f"R{i}" for i in range(1, 6)}
    return serial({"spec": "S4b action v0.19", "information_unit": "nat",
                   "time_unit": "second", "items": result})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.path and args.check:
        parser.error("capture and --check are mutually exclusive")
    data = canonical(references()) + b"\n"
    if args.check:
        if args.check.read_bytes() != data:
            raise SystemExit("FAIL: independent references differ")
        print("PASS: T1-T25 / R1-R5 (30 items), exact canonical match")
    elif args.path:
        with args.path.open("xb") as stream:
            stream.write(data)
        print(f"CREATED: {args.path} (30 items)")
    else:
        print(data.decode("utf-8"), end="")


if __name__ == "__main__":
    main()
