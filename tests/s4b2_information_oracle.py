"""Independent C1 information integrals from spec v0.10, not sui algorithms.

All endpoints are rationals. Integer endpoints use the fixed denominator
2**256; every multiplication/division rounds outward on that rational grid.
log/exp carry explicit series tails. Order-8 interval Taylor quadrature uses
f^(8)([a,b])/8! to bound the integral remainder, not differences of estimates.
The omitted [0,2**-20] and [16,infinity) use L(h|r)*H(C|r,S,h) <= log(4).
No scipy, binary-float quadrature or production import supplies an endpoint.
"""
from fractions import Fraction as F
from functools import lru_cache
import heapq
from math import comb, factorial


BITS = 256
SCALE = 1 << BITS
ORDER = 8


class Box:
    __slots__ = ("lo", "hi")

    def __init__(self, lo=0, hi=None):
        lo, hi = F(lo), F(lo if hi is None else hi)
        self.lo = lo.numerator*SCALE//lo.denominator
        self.hi = -((-hi.numerator*SCALE)//hi.denominator)
        assert self.lo <= self.hi

    @classmethod
    def raw(cls, lo, hi):
        result = object.__new__(cls)
        result.lo, result.hi = lo, hi
        assert lo <= hi
        return result

    def fractions(self):
        return F(self.lo, SCALE), F(self.hi, SCALE)

    def __add__(self, other):
        other = as_box(other)
        return Box.raw(self.lo+other.lo, self.hi+other.hi)

    __radd__ = __add__

    def __neg__(self):
        return Box.raw(-self.hi, -self.lo)

    def __sub__(self, other):
        return self+-as_box(other)

    def __rsub__(self, other):
        return as_box(other)+-self

    def __mul__(self, other):
        other = as_box(other)
        values = (self.lo*other.lo, self.lo*other.hi, self.hi*other.lo, self.hi*other.hi)
        return Box.raw(min(values)//SCALE, -((-max(values))//SCALE))

    __rmul__ = __mul__

    def reciprocal(self):
        if self.lo <= 0 <= self.hi:
            raise ZeroDivisionError("interval contains zero")
        return Box.raw(SCALE*SCALE//self.hi, -((-SCALE*SCALE)//self.lo))

    def __truediv__(self, other):
        return self*as_box(other).reciprocal()

    def __pow__(self, exponent):
        assert type(exponent) is int and exponent >= 0
        result, base = Box(1), self
        while exponent:
            if exponent % 2:
                result = result*base
            base = base*base
            exponent //= 2
        return result


def as_box(value):
    return value if isinstance(value, Box) else Box(value)


def exp_point(value):
    """32 Taylor terms on [0,1/8], geometric tail, then squaring."""
    value = F(value)
    if value < 0:
        return exp_point(-value).reciprocal()
    squarings = 0
    while value > F(1, 8):
        value /= 2
        squarings += 1
    x = Box(value)
    term = result = Box(1)
    for k in range(1, 33):
        term = term*x/k
        result = result+term
    tail = term*x/33/(1-x/34)
    result = Box.raw(result.lo, result.hi+tail.hi)
    for _ in range(squarings):
        result = result*result
    return result


def exp_box(value):
    lo, hi = value.fractions()
    return Box.raw(exp_point(lo).lo, exp_point(hi).hi)


def log_series(value):
    z = (value-1)/(value+1)
    assert 0 <= z.lo <= z.hi <= SCALE//3+1
    power, squared, total = z, z*z, Box(0)
    for k in range(40):
        total = total+power*F(2, 2*k+1)
        power = power*squared
    tail = 2*power/81/(1-squared)
    return Box.raw(total.lo, total.hi+tail.hi)


LOG_TWO = log_series(Box(2))


def log_point(raw):
    assert raw > 0
    exponent = raw.bit_length()-1-BITS
    mantissa = Box(F(raw, SCALE)/F(2)**exponent)
    return log_series(mantissa)+exponent*LOG_TWO


def log_box(value):
    if value.lo <= 0:
        raise ZeroDivisionError("log argument is not proved positive")
    return Box.raw(log_point(value.lo).lo, log_point(value.hi).hi)


def constant(value):
    return (as_box(value),)+(Box(0),)*ORDER


def add(a, b):
    return tuple(x+y for x, y in zip(a, b))


def scale(a, value):
    return tuple(x*value for x in a)


def subtract(a, b):
    return add(a, scale(b, -1))


def multiply(a, b):
    return tuple(sum((a[j]*b[k-j] for j in range(k+1)), Box(0)) for k in range(ORDER+1))


def reciprocal(a):
    result = [a[0].reciprocal()]
    for k in range(1, ORDER+1):
        result.append(-sum((a[j]*result[k-j] for j in range(1, k+1)), Box(0))/a[0])
    return tuple(result)


def exp_jet(a):
    result = [exp_box(a[0])]
    for k in range(1, ORDER+1):
        result.append(sum((j*a[j]*result[k-j] for j in range(1, k+1)), Box(0))/k)
    return tuple(result)


def log_jet(a):
    inverse = reciprocal(a)
    return (log_box(a[0]),)+tuple(
        sum((j*a[j]*inverse[k-j] for j in range(1, k+1)), Box(0))/k
        for k in range(1, ORDER+1))


def phi(a):
    return multiply(a, log_jet(a))


def powers(a, count):
    result = [constant(1)]
    for _ in range(count):
        result.append(multiply(result[-1], a))
    return result


def a_coefficient(k):
    return F(2**(k+1)-1, k+1)


def positive_tail_series(x, weighted=False):
    """sum r^j/(j+3)! or sum a_(j+3)*r^j/(j+3)!, plus all derivative tails.

    The weighted coefficient is <= 16*2**j/(j+4)!. The ratio of consecutive
    derivative terms decreases after truncation; hence a geometric majorant.
    x must be linear in the integration variable (r or 2r).
    """
    assert all(v.lo == v.hi == 0 for v in x[2:])
    degree = 40
    radius = F(x[0].hi, SCALE)
    p = [Box(1)]
    for _ in range(degree):
        p.append(p[-1]*x[0])
    result = []
    first = degree+1
    for d in range(ORDER+1):
        value = sum((p[k-d]*comb(k, d)*(a_coefficient(k+3) if weighted else 1)/factorial(k+3)
                     for k in range(d, degree+1)), Box(0))
        if weighted:
            start = F(16*2**first*comb(first, d), factorial(first+4))*radius**(first-d)
            ratio = 2*radius*F(first+1, (first+1-d)*(first+5))
        else:
            start = F(comb(first, d), factorial(first+3))*radius**(first-d)
            ratio = radius*F(first+1, (first+1-d)*(first+4))
        assert 0 <= ratio < 1
        remainder = Box(0, start/(1-ratio))
        result.append((value+remainder)*(x[1]**d))
    return tuple(result)


def poisson_tail_factor(x, *, weighted=False):
    """Positive factorizations avoid subtracting nearly equal masses near r=0."""
    if x[0].hi <= 2*SCALE:
        return positive_tail_series(x, weighted)
    xp = powers(x, 3)
    inverse = reciprocal(x)
    if weighted:
        whole = multiply(subtract(exp_jet(scale(x, 2)), exp_jet(x)), inverse)
        removed = add(constant(1), add(scale(x, F(3, 2)), scale(xp[2], F(7, 6))))
    else:
        whole = exp_jet(x)
        removed = add(constant(1), add(x, scale(xp[2], F(1, 2))))
    return multiply(subtract(whole, removed), reciprocal(xp[3]))


def entropy_integrands(left, right):
    """Jets of prior(r)*sum_s likelihood(h,S2=s|r)*H(C|r,S2=s,h).

    w0,w1 are the first-window state likelihoods. The second-window joint
    cells are exp(-2r)*(w0*r^k, w1*(2r)^k+w0*r^(k+1)*a_k)/k!.
    The fourth cell is the full positive series k>=3, never a discarded tail.
    """
    x = (Box(left, right), Box(1))+(Box(0),)*(ORDER-1)
    xp = powers(x, 4)
    em = exp_jet(scale(x, -1))
    em2 = exp_jet(scale(x, -2))
    t = poisson_tail_factor(x)
    t2 = poisson_tail_factor(scale(x, 2))
    ta = poisson_tail_factor(x, weighted=True)
    roots = [(scale(multiply(em2, xp[n]), F(1, factorial(n))),
              scale(multiply(em2, xp[n+1]), a_coefficient(n)/factorial(n))) for n in range(3)]
    roots.append((multiply(multiply(em2, xp[3]), t), multiply(multiply(em2, xp[4]), ta)))
    prior = scale(multiply(x, em2), 4)
    result = []
    for w0, w1 in roots:
        state = (multiply(w0, em), add(w1, multiply(w0, subtract(constant(1), em))))
        cells = []
        for k in range(3):
            zero = multiply(w0, xp[k])
            one = add(scale(multiply(w1, xp[k]), 2**k),
                      scale(multiply(w0, xp[k+1]), a_coefficient(k)))
            cells.extend(scale(multiply(em2, g), F(1, factorial(k))) for g in (zero, one))
        cells.append(multiply(multiply(multiply(w0, em2), xp[3]), t))
        cells.append(multiply(em2, add(scale(multiply(multiply(w1, xp[3]), t2), 8),
                                       multiply(multiply(w0, xp[4]), ta))))
        # Independent normalization identities, including every derivative:
        # the eight joint cells must sum to the two terminal state masses.
        for s in range(2):
            total = constant(0)
            for k in range(4):
                total = add(total, cells[2*k+s])
            assert all(v.lo <= 0 <= v.hi for v in subtract(total, state[s]))
        entropy = add(phi(state[0]), phi(state[1]))
        for cell in cells:
            entropy = subtract(entropy, phi(cell))
        result.append(multiply(prior, entropy))
    return tuple(result)


def taylor_cell(left, right):
    midpoint, half = (left+right)/2, (right-left)/2
    point = entropy_integrands(midpoint, midpoint)
    ranged = entropy_integrands(left, right)
    return tuple(sum((point[n][j]*F(2, j+1)*half**(j+1)
                      for j in range(0, ORDER, 2)), Box(0))
                 + ranged[n][ORDER]*F(2, ORDER+1)*half**(ORDER+1)
                 for n in range(4))


def joint_masses(n):
    """Spec §6-4, plus complement of n=0,1,2 for the saturated root."""
    z = (F(3, 8), F(17, 64), F(5, 32), F(13, 64))[n]
    if n == 3:
        integral = lambda p, decay: F(4*factorial(p+1), decay**(p+2))
        whole = [(integral(k, 5)/factorial(k),
                  (2**k*(integral(k, 4)-integral(k, 5))
                   + a_coefficient(k)*integral(k+1, 5))/factorial(k)) for k in range(3)]
        whole.append(tuple(total-sum(row[s] for row in whole)
                           for s, total in enumerate((F(1, 4), F(3, 4)))))
        return z, tuple(tuple(whole[k][s]-sum(joint_masses(j)[1][k][s] for j in range(3))
                              for s in range(2)) for k in range(4))
    cells = [(F(4*factorial(n+k+1), factorial(n)*factorial(k)*6**(n+k+2)),
              F(4*factorial(n+k+2), factorial(n)*factorial(k)*6**(n+k+3))
              *(2**k*a_coefficient(n)+a_coefficient(k))) for k in range(3)]
    t0 = F(4*factorial(n+1), factorial(n)*5**(n+2))
    cells.append(tuple(total-sum(row[s] for row in cells) for s, total in enumerate((t0, z-t0))))
    return z, tuple(cells)


@lru_cache(maxsize=1)
def certified_information():
    """Return (four (I_read,q_read) rational intervals, residual diagnostics)."""
    epsilon, cutoff = F(1, 2**20), F(16)
    edges = [epsilon]
    while edges[-1] < 1:
        edges.append(2*edges[-1])
    edges.extend(F(k, 2) for k in range(3, 33))
    heap, serial = [], 0
    lower, upper = [0]*4, [0]*4

    def insert(left, right):
        nonlocal serial
        try:
            values = taylor_cell(left, right)
        except ZeroDivisionError:
            middle = (left+right)/2
            insert(left, middle)
            insert(middle, right)
            return
        for n, value in enumerate(values):
            lower[n] += value.lo
            upper[n] += value.hi
        heapq.heappush(heap, (-max(v.hi-v.lo for v in values), serial, left, right, values))
        serial += 1

    for left, right in zip(edges, edges[1:]):
        insert(left, right)
    while max(F(hi-lo, SCALE) for lo, hi in zip(lower, upper)) > F(1, 10**10):
        assert len(heap) < 4000, "independent quadrature exhausted its explicit cell limit"
        _, _, left, right, old = heapq.heappop(heap)
        for n, value in enumerate(old):
            lower[n] -= value.lo
            upper[n] -= value.hi
        middle = (left+right)/2
        insert(left, middle)
        insert(middle, right)
    # Prior mass near zero <= integral 4r dr. Tail is the exact Gamma(2,2) tail.
    log_four = 2*LOG_TWO
    head = 2*epsilon**2*log_four
    tail = exp_point(-2*cutoff)*(1+2*cutoff)*log_four
    omitted = Box.raw(0, head.hi+tail.hi)
    result = []
    for n in range(4):
        z, cells = joint_masses(n)
        probabilities = [sum(cell)/z for cell in cells]
        hc = sum((-Box(p)*log_box(Box(p)) for p in probabilities), Box(0))
        conditional = Box.raw(lower[n], upper[n])+omitted
        information = LOG_TWO-F(1, 2)+hc-conditional/z
        q = (1+exp_box(-information)).reciprocal()
        result.append((information.fractions(), q.fractions()))
    diagnostics = {"cells": len(heap), "evaluated_cells": serial,
        "head_upper": F(head.hi, SCALE), "tail_upper": F(tail.hi, SCALE),
        "quadrature_widths": tuple(F(hi-lo, SCALE) for lo, hi in zip(lower, upper)),
        "order": ORDER, "grid_bits": BITS, "epsilon": epsilon, "cutoff": cutoff}
    return tuple(result), diagnostics
