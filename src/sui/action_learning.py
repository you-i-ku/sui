"""Column-wise Dirichlet products and certified finite mixture integrals.

Counts belong to latent paths. They are integers, never expected counts.
The polynomial densities sum paths before taking a logarithm, so component
identity and unregistered states are integrated out of the information target.
"""
from fractions import Fraction as F
from functools import lru_cache
from collections import defaultdict
import math

from .action_model import load_canonical, rational
from .action_types import ActionIncomplete, ActionNumericalRange, Bounds, rational_bounds
from .quantity import SimplexPolynomial


class DirichletProduct:
    def __init__(self, model):
        d=load_canonical(model.declaration)
        beta=[]; keys=[]; indexes={}; tables={}; offset=0
        for parameter in ("B","Theta"):
            for action in model.actions:
                table=d["effects"][action]["B"]["values"] if parameter=="B" else d["a"][action]
                tables[parameter,action]=tuple(tuple(rational(x,"parameter") for x in row) for row in table)
                learned=(d["effects"][action]["B"]["kind"]=="dirichlet" if parameter=="B" else action in d["learnable"])
                if not learned: continue
                for column in range(len(model.states)):
                    active=[row for row in range(len(table)) if rational(table[row][column],"parameter")]
                    values=tuple(rational(table[row][column],"parameter") for row in active)
                    keys.append((parameter,action,column)); beta.append(values)
                    for coordinate,row in enumerate(active): indexes[parameter,action,column,row]=offset+coordinate
                    offset+=len(values)
        self.beta=tuple(beta); self.keys=tuple(keys); self.indexes=indexes; self.tables=tables
        self.sizes=tuple(map(len,beta)); self.offsets=tuple(sum(self.sizes[:i]) for i in range(len(beta)))
        self.zero=(0,)*offset; self._moments={}
        self.groups={key:i for i,key in enumerate(keys)}

    def moment(self, counts):
        counts=tuple(counts)
        if counts not in self._moments:
            result=F(1)
            for beta,offset,size in zip(self.beta,self.offsets,self.sizes):
                group=counts[offset:offset+size]
                for b,n in zip(beta,group):
                    for k in range(n): result*=b+k
                for k in range(sum(group)): result/=sum(beta)+k
            self._moments[counts]=result
        return self._moments[counts]

    def expectation(self, polynomial):
        return sum((c*self.moment(k) for k,c in polynomial.coefficients.items()),F(0))

    def observe(self, parameter, action, column, row, counts):
        group=self.groups.get((parameter,action,column))
        if group is None: return self.tables[parameter,action][row][column],counts
        coordinate=self.indexes.get((parameter,action,column,row))
        if coordinate is None: return F(0),counts
        offset=self.offsets[group]; size=self.sizes[group]
        probability=(self.beta[group][coordinate-offset]+counts[coordinate])/(sum(self.beta[group])+sum(counts[offset:offset+size]))
        updated=list(counts); updated[coordinate]+=1
        return probability,tuple(updated)

    def tilted(self, counts):
        other=object.__new__(DirichletProduct)
        other.__dict__.update(self.__dict__)
        other.beta=tuple(tuple(b+n for b,n in zip(beta,counts[offset:offset+size]))
                         for beta,offset,size in zip(self.beta,self.offsets,self.sizes))
        other._moments={}
        return other

    def log_coordinates(self, counts):
        from scipy.special import digamma
        result=[]
        for beta,offset,size in zip(self.beta,self.offsets,self.sizes):
            column=tuple(b+n for b,n in zip(beta,counts[offset:offset+size])); total=sum(column)
            for b in column:
                if b==total: result.append(0.); continue
                if total.denominator==b.denominator==1 and total-b<10000:
                    result.append(-math.fsum(1/k for k in range(int(b),int(total))))
                else:
                    try: value=float(digamma(float(b))-digamma(float(total)))
                    except (OverflowError,FloatingPointError) as exc:
                        raise ActionNumericalRange(reason="overflow",detail="Dirichlet log moment exceeds range") from exc
                    if not math.isfinite(value) or value>=0:
                        raise ActionNumericalRange(reason="positive_underflow",detail="Dirichlet log moment disappeared")
                    result.append(value)
        return tuple(result)


@lru_cache(maxsize=64)
def measure(model):
    return DirichletProduct(model)


def _degrees(sizes, counts):
    offset=0; result=[]
    for size in sizes:
        result.append(sum(counts[offset:offset+size])); offset+=size
    return tuple(result)


def _elevation_work(poly, degrees):
    return sum(math.prod(math.comb(new-old+size-1,size-1) for size,new,old in
        zip(poly.sizes,degrees,_degrees(poly.sizes,k))) for k in poly.coefficients)


def _guard(work, budget):
    if work>budget.node_budget:
        raise ActionIncomplete(reason="budget",detail="Dirichlet polynomial work exceeds node budget")


def _multiply(left, right, budget):
    _guard(len(left.coefficients)*len(right.coefficients),budget)
    return left.multiply(right)


def _ratio(left, right, budget):
    degrees=tuple(max(a,b) for a,b in zip(left.degrees,right.degrees))
    _guard(_elevation_work(left,degrees)+_elevation_work(right,degrees),budget)
    return left.ratio_to(right)


def polynomial(product, coefficients, budget):
    if not coefficients: return SimplexPolynomial.constant(product.sizes,0)
    degrees=tuple(max(_degrees(product.sizes,k)[i] for k in coefficients) for i in range(len(product.sizes)))
    work=sum(math.prod(math.comb(d-old+size-1,size-1) for size,d,old in
        zip(product.sizes,degrees,_degrees(product.sizes,k))) for k in coefficients)
    _guard(work,budget)
    result=defaultdict(F)
    for k,c in coefficients.items():
        term=SimplexPolynomial(product.sizes,_degrees(product.sizes,k),{k:c}).elevate(degrees)
        for key,value in term.coefficients.items(): result[key]+=value
    return SimplexPolynomial(product.sizes,degrees,result).reduced()


def density_cells(data, targets, budget):
    if getattr(data,'finite',False):
        from .action_finite import queried
        product=measure(data.model); cells={}
        for path,states in queried(data,targets,budget):
            coefficients=cells.setdefault((path.hypotheses,states),defaultdict(F))
            coefficients[path.counts]+=path.probability*data.evidence/product.moment(path.counts)
        return {row:polynomial(product,coefficients,budget) for row,coefficients in cells.items()}
    from .action_joint import _resolve,_state_at
    product=measure(data.model); labels=tuple(_resolve(data,t) for t in targets)
    cells={}
    for path in data.paths:
        row=tuple(data.model.states[_state_at(path,data.events,label)] for label in labels)
        coefficients=cells.setdefault(row,defaultdict(F))
        coefficients[path.counts]+=path.probability*data.evidence/product.moment(path.counts)
    return {row:polynomial(product,coefficients,budget) for row,coefficients in cells.items()}


def _minimum(poly):
    return tuple(min(k[i] for k in poly.coefficients) for i in range(sum(poly.sizes)))


def _remove(poly, powers, scale=F(1)):
    return SimplexPolynomial(poly.sizes,tuple(a-b for a,b in zip(poly.degrees,_degrees(poly.sizes,powers))),
        {tuple(a-b for a,b in zip(k,powers)):c/scale for k,c in poly.coefficients.items()}).reduced()


def _scale_bound(poly, powers):
    # Upper Bernstein control after removing a common monomial.
    from .quantity import _multinomial,_simplex_groups
    return max(c/math.prod(_multinomial(g) for g in _simplex_groups(poly.sizes,
        tuple(a-b for a,b in zip(k,powers)))) for k,c in poly.coefficients.items())


def _closed_ratio(product, numerator, denominator, budget):
    left,right=_minimum(numerator),_minimum(denominator)
    scale=max(F(1),_scale_bound(numerator,left),_scale_bound(denominator,right))
    ratio=_ratio(_remove(numerator,left,scale),_remove(denominator,right,scale),budget)
    if ratio is None or not ratio: return None
    delta=tuple(a-b for a,b in zip(left,right)); log_ratio=math.log(ratio.numerator)-math.log(ratio.denominator)
    terms=[]
    for counts,coefficient in numerator.coefficients.items():
        term=log_ratio+math.fsum(n*v for n,v in zip(delta,product.log_coordinates(counts)) if n)
        weight=rational_bounds(coefficient*product.moment(counts)).lower
        terms.append(weight*term)
    return math.fsum(terms)


def _cross(product, numerator, denominator, goal, budget):
    if len(denominator.coefficients)==1:
        powers,c=next(iter(denominator.coefficients.items()))
        value=math.fsum(rational_bounds(w*product.moment(k)).lower *
            (-(math.log(c.numerator)-math.log(c.denominator))-math.fsum(n*v for n,v in
                zip(powers,product.log_coordinates(k)) if n)) for k,w in numerator.coefficients.items())
        return value,value
    # The caller proves numerator <= denominator. The remainder is bounded by
    # E[(1-denominator)^(m+1)]/(m+1), without ignoring boundary mass.
    complement=denominator.complement(); power=SimplexPolynomial.constant(product.sizes,1); values=[]
    for m in range(1,budget.series_budget+1):
        power=_multiply(power,complement,budget)
        values.append(rational_bounds(product.expectation(_multiply(numerator,power,budget))).lower/m)
        following=_multiply(power,complement,budget)
        tail=rational_bounds(product.expectation(following)).lower/(m+1)
        if tail<=goal:
            value=math.fsum(values); return value,value+tail
    raise ActionIncomplete(reason="accuracy",detail="Dirichlet cross-log series did not reach its bound")


def joint_information(root, current, reference, targets, budget):
    product=measure(root._data.model)
    b=density_cells(current._data,targets,budget); r=density_cells(reference._data,targets,budget)
    zb,zr=current._data.evidence,reference._data.evidence
    if set(b)==set(r) and all(_ratio(b[row],r[row],budget)==zb/zr for row in b):
        return rational_bounds(F(0))
    log_z=math.log((zr/zb).numerator)-math.log((zr/zb).denominator)
    goal=budget.tolerance*rational_bounds(zb).lower/(8*max(1,len(b)))
    if not goal: raise ActionNumericalRange(reason="positive_underflow",detail="information error allocation disappeared")
    lows=[]; highs=[]
    for row,numerator in b.items():
        denominator=r.get(row)
        if denominator is None: raise ActionNumericalRange(reason="invalid_interval",detail="posterior outside reference support")
        closed=_closed_ratio(product,numerator,denominator,budget)
        if closed is not None:
            lows.append(closed); highs.append(closed); continue
        degrees=tuple(max(a,c) for a,c in zip(numerator.degrees,denominator.degrees))
        _guard(_elevation_work(numerator,degrees)+_elevation_work(denominator,degrees),budget)
        left,right=numerator.elevate(degrees),denominator.elevate(degrees)
        if any(c>right.coefficients.get(k,F(0)) for k,c in left.coefficients.items()):
            raise ActionIncomplete(reason="accuracy",detail="observation-density domination is not certified")
        common=tuple(min(a,c) for a,c in zip(_minimum(numerator),_minimum(denominator)))
        scale=max(F(1),_scale_bound(numerator,common),_scale_bound(denominator,common))
        n,d=_remove(numerator,common,scale),_remove(denominator,common,scale)
        factor=product.moment(common)*scale; tilted=product.tilted(common)
        allocated=goal/rational_bounds(factor).lower
        cross=_cross(tilted,n,d,allocated,budget); phi=_cross(tilted,n,n,allocated,budget)
        value=rational_bounds(factor).lower
        lows.append(value*(cross[0]-phi[1])); highs.append(value*(cross[1]-phi[0]))
    z=rational_bounds(zb).lower
    lower=log_z+math.fsum(lows)/z; upper=log_z+math.fsum(highs)/z
    if not math.isfinite(lower) or not math.isfinite(upper):
        raise ActionNumericalRange(reason="overflow",detail="joint mixture KL exceeds range")
    if upper-lower>budget.tolerance:
        raise ActionIncomplete(reason="accuracy",detail="joint mixture KL interval exceeds requested width")
    return Bounds(lower,upper,None)
