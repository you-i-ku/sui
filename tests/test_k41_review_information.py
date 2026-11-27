"""K41-f R9. The original target is constant; only the resolved law is learned."""

from dataclasses import replace
from fractions import Fraction as Q
from functools import lru_cache

from k41_world import HALF, adopt, at_entry, worlds
from test_fb_clock_belief import clock_prior, unnormalized_entropy
from test_fb_time_belief import budget, enclose, exp_minus, outward, rat


@lru_cache(maxsize=8192)
def entropy_mass(a, b):
    # g(a,b) = (a+b)H(a/(a+b)). Its partial derivatives are log(1+b/a)
    # and log(1+a/b), so it is increasing in each positive argument.
    return enclose(unnormalized_entropy(rat(a), rat(b)), 16)


@lru_cache(maxsize=4097)
def empty_cells(f):
    # The entire half time-unit lies inside the first segment of the clock.
    # B has two competing hazards. In these units the jump to A has rate
    # d and an arrival has rate 4f. A is silent and absorbing.
    d = Q(1, 16)
    x = d + 4*f
    e_lo, e_hi = exp_minus(x, 24)
    b_lo, b_hi = outward(Q(7, 8)*e_lo, Q(7, 8)*e_hi, 64)
    a_lo, a_hi = outward(Q(1, 8)+Q(7, 8)*d*(1-e_hi)/x,
                         Q(1, 8)+Q(7, 8)*d*(1-e_lo)/x, 64)
    return ((a_lo, a_hi), (b_lo, b_hi),
            (entropy_mass(a_lo, b_lo)[0], entropy_mass(a_hi, b_hi)[1]))


def information_bounds(n):
    # A increases by the integral of the surviving B->A flux. This flux and
    # surviving B both decrease in f, so the right and left sums bound the
    # uniform integral of each cell mass and of the entropy mass.
    rows = [empty_cells(Q(i, n)) for i in range(n+1)]
    on = [(sum(row[k][0] for row in rows[1:])/n,
           sum(row[k][1] for row in rows[:-1])/n) for k in range(3)]
    off = empty_cells(HALF)
    mixed = [tuple((7*on[k][i]+off[k][i])/8 for i in (0, 1)) for k in range(3)]
    a, b, conditional = mixed
    z_lo, z_hi = a[0]+b[0], a[1]+b[1]
    h_lo, h_hi = entropy_mass(a[0], b[0])[0], entropy_mass(a[1], b[1])[1]
    assert h_lo > conditional[1]
    info = ((h_lo-conditional[1])/z_hi, (h_hi-conditional[0])/z_lo)
    # The wrong order first merges all on-clock fractions, but still lets Y reveal
    # the on/off bit. Its conditional entropy uses g(integral A, integral B).
    collapsed_lo = (7*entropy_mass(on[0][0], on[1][0])[0]+off[2][0])/8
    collapsed_hi = max(Q(0), h_hi-collapsed_lo)/z_lo
    return info, collapsed_hi


def test_common_target_integrates_clock_conditional_entropy_before_averaging(worlds):
    tolerance = Q(1, 16)
    (ref_lo, ref_hi), collapsed_hi = information_bounds(256)
    assert ref_hi-ref_lo < tolerance/4
    assert ref_lo-collapsed_hi > tolerance
    clock = clock_prior(fractions={"kind": "conditional_dirichlet", "concentration": Q(2)})
    r = worlds(clock=clock, prior=(Q(1, 8), Q(7, 8)), rates=(0, 4),
               process=((0, 0), (Q(1, 8), -Q(1, 8))), unit=HALF,
               a=Q(7), b=Q(1), targets=("same", "same"),
               thinking=True, measurement=at_entry())
    doc = dict(r.document)
    for field in ("operations", "kernels", "policies"):
        doc[field] = [entry for entry in doc[field] if entry["id"] == "peek"]
    r.replace_model(doc)
    decl = r.boot_input.declaration
    initial = decl.initial
    limits = budget(tolerance)
    r.boot_input = replace(r.boot_input, declaration=replace(decl, initial=replace(initial,
        value=replace(initial.value, prepare_budget=limits, evaluate_budget=limits))))
    r.direct()
    history = adopt(r)
    pick = r.think()
    assert r.expression().root == history.root
    answers = r.selected_value(pick).evaluation
    info = answers.information[answers.candidates.index("peek")].additional.bounds
    assert collapsed_hi < info.lower <= info.upper
    assert info.lower <= ref_hi and ref_lo <= info.upper
    # Even the furthest endpoints of the two enclosures must be within the
    # chosen tolerance. A more precise public enclosure is equally admissible.
    assert max(info.upper, ref_hi) - min(info.lower, ref_lo) <= tolerance
