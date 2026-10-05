"""Independent finite ruler for S4b v0.19 T15; standard library only.

No sui imports. Enumerate all 2**(n+1) state paths and integrate each uniform
Dirichlet column with sequential Polya factors (count+1)/(total+2).
The fixed-value tool instead uses factorial integrals; main checks both.
All observations are AFTER the action, before the next action (spec :288).
"""
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction as F
from itertools import product
import json
import math
from pathlib import Path

ACTIONS = (0, 1, 0, 0, 1, 0)
OUTCOMES = (1, 0, 1, 1, 0, 1)


@dataclass(frozen=True)
class PathMass:
    states: tuple
    counts: tuple  # B a0/a1 then Theta a0/a1; within each: column0, column1
    mass: F


def enumerate_paths(actions, outcomes=None, *, post=True):
    if outcomes is not None:
        assert len(actions) == len(outcomes)
    rows = []
    for states in product((0, 1), repeat=len(actions)+1):
        counts = [[0, 0] for _ in range(8)]
        mass = F(1, 2)
        for step, action in enumerate(actions):
            column = counts[2*action + states[step]]
            result = states[step+1]
            mass *= F(column[result]+1, sum(column)+2)
            column[result] += 1
            if outcomes is not None:
                column = counts[4 + 2*action + states[step+int(post)]]
                result = outcomes[step]
                mass *= F(column[result]+1, sum(column)+2)
                column[result] += 1
        rows.append(PathMass(states, tuple(map(tuple, counts)), mass))
    return tuple(rows)


def evidence(rows):
    return sum((row.mass for row in rows), F())


def beta_product(a, b, n, m=0):
    """E[p**n (1-p)**m] = (a)_n (b)_m / (a+b)_(n+m)."""
    numerator = math.prod((F(a)+i for i in range(n)), start=F(1))
    numerator *= math.prod((F(b)+i for i in range(m)), start=F(1))
    return numerator / math.prod((F(a)+F(b)+i for i in range(n+m)), start=F(1))


def table_moment(rows, parameter, action, powers):
    start = (0 if parameter == "B" else 4) + 2*action
    result = F()
    for row in rows:
        conditional = F(1)
        for column in range(2):
            n0, n1 = row.counts[start+column]
            conditional *= beta_product(n0+1, n1+1,
                                        powers[0][column], powers[1][column])
        result += row.mass * conditional
    return result / evidence(rows)


def state_marginal(rows, positions):
    result = defaultdict(F)
    total = evidence(rows)
    for row in rows:
        result[tuple(str(row.states[p]) for p in positions)] += row.mass / total
    return dict(result)


def harmonic(n):
    return sum((F(1, k) for k in range(1, n+1)), F())


def expected_log_likelihood(rows):
    """For registered post states, likelihood is product Theta[y,s]**n.

    Under each path's posterior Dir(1+n0,1+n1), E[log Theta_y] is
    H(n_y)-H(1+n0+n1). State/B factors cancel against the SAME-control root
    law in joint KL. Path mixture weights are exact integrated mass / Z.
    """
    result = F()
    for row in rows:
        value = F()
        for n0, n1 in row.counts[4:]:
            value += sum((n*(harmonic(n)-harmonic(1+n0+n1))
                          for n in (n0, n1)), F())
        result += row.mass * value
    return result / evidence(rows)


def joint_information(rows):
    return float(expected_log_likelihood(rows)) - math.log(float(evidence(rows)))


def noisy_law_information():
    # Success notice gives posterior density f(p)=2/5+(6/5)p on [0,1].
    # Substitute u=f(p): integral f log f dp = [u² log(u)/2-u²/4]/(6/5).
    def primitive(u):
        return u*u*math.log(u)/2-u*u/4
    return (primitive(8/5)-primitive(2/5))/(6/5)


def main():
    """Executable oracle audit, without importing or executing action code."""
    fixed = json.loads(Path(__file__).with_name("fixed_s4b_action.json").read_bytes())["items"]
    rows = enumerate_paths(ACTIONS, OUTCOMES)
    for row in rows:
        factorial_mass = F(1, 2)
        for n0, n1 in row.counts:
            factorial_mass *= F(math.factorial(n0)*math.factorial(n1),
                                math.factorial(n0+n1+1))
        assert factorial_mass == row.mass
    post = fixed["T15"]["values"]["post"]
    assert evidence(rows) == F(*post["evidence"]) == F(198151, 4665600)
    assert len(rows) == post["paths"] == 128
    assert len({(r.states[-1], r.counts) for r in rows}) == post["components"] == 106
    assert evidence(enumerate_paths(ACTIONS, OUTCOMES, post=False)) == F(12257, 311040)
    assert evidence(enumerate_paths(ACTIONS)) == 1
    assert sum(state_marginal(rows, tuple(range(1, 7))).values()) == 1
    assert F(4, 5)*beta_product(2, 1, 2)+F(1, 5)*beta_product(1, 2, 2) == F(13, 30)
    assert beta_product(F(9, 5), F(6, 5), 2) == F(21, 50)
    assert beta_product(1, 1, 0) == F(1)
    for parameter, action in product(("B", "Theta"), (0, 1)):
        for column in (0, 1):
            powers0 = [[0, 0], [0, 0]]
            powers1 = [[0, 0], [0, 0]]
            powers0[0][column] = powers1[1][column] = 1
            m0 = table_moment(rows, parameter, action, powers0)
            m1 = table_moment(rows, parameter, action, powers1)
            assert isinstance(m0, F) and isinstance(m1, F) and m0+m1 == 1
    # A separate Simpson integral checks the analytic density integral used in
    # T13. f is positive and smooth on the whole interval (no singular endpoint).
    n = 10000
    def integrand(i):
        density = .4+1.2*i/n
        return density*math.log(density)
    integral = (integrand(0)+integrand(n)+math.fsum((4 if i % 2 else 2)*integrand(i)
                                                  for i in range(1, n)))/(3*n)
    assert abs(integral-noisy_law_information()) < 1e-12
    print("PASS: 128 exact path masses, 106 components, post/pre evidence, normalized moments, T13 analytic/integral")
    print(json.dumps({"T15": {"evidence": str(evidence(rows)),
        "expected_log_likelihood": str(expected_log_likelihood(rows)),
        "joint_information_nat": joint_information(rows),
        "next_outcome_1": {str(a): str(evidence(enumerate_paths(ACTIONS+(a,), OUTCOMES+(1,)))/evidence(rows))
                           for a in (0, 1)}}, "T13_law_information_nat": noisy_law_information()}, sort_keys=True))


if __name__ == "__main__":
    main()
