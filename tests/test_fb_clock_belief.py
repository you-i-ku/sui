"""K40 v7, requests125-133; public entries only, no source bodies.

Chosen public spelling (proposed under the explicit naming permission):
  SwitchPart(..., clock=None), kind='clock', multipliers=() for a clock part.
  ClockPrior(periods, max_segments, segments, phase, widths, fractions,
             couplings=()). periods/segments are (value, prior-weight) tuples.
  phase: {'kind':'uniform'} or {'kind':'point','value':Fraction}.
  widths: {'kind':'symmetric_dirichlet','concentration':Fraction} or point.
  fractions: {'kind':'conditional_dirichlet','concentration':Fraction} or point.
  A simplex point uses {'kind':'point','values':((m,(q1,...,qm)),...)}.
  couplings explicitly requests additional dependencies outside decision4.
  ClockQuantity(kind,candidate,family,part,periods=None,segments=None,index=None,
                lower=None,upper=None,on=(),off=(),condition_on=(),condition_off=()).
    'parameters': period/m subsets and bit events, divided ONLY by Z_M.
    'allocation': E[integral_[lo,hi) c(phi)**clock_bit dphi | h,M]; lo>hi wraps.
    None means all declared candidates; an empty tuple is the empty event.
    index/region kinds and condition_on/off only express unsupported requests.
  FThreadHost.query_clock_belief(*,belief,quantity,budget)->BeliefValue.
  Region probabilities (phase/width/fraction) and denominator conditions are
  unsupported. Mathematical ratios below are computed by the TEST from existing
  joint SwitchQuantity results, never requested as a conditional clock query.
  f.compare_exact(left,right,*,reader,registry,budget)->f.ExactComparison:
    kind='structural'/'identity'/'separated'/'unproved', order=-1/0/1/None,
    proof=None only for unproved. Integral ExactReal nodes carry name/version
    and saved-record references; public math JSON must replay without callbacks.
    reader/registry are the chosen call spelling, not a requirement that each
    comparison read them. A self-contained, already-resolved expression can be
    compared by value; the fixed-reader replay requirement is tested separately.

No new Poisson law type or switch per T/m/shape. Point phase denotes the first
segment's left boundary on the circle. Unknown shapes are named refusals.
All integration rulers use rational bounds; no scipy/float answer is an oracle.
"""
from collections import defaultdict
from dataclasses import fields, replace
from fractions import Fraction as Q
from functools import lru_cache
from itertools import product
import json

import pytest

from sui import f, f_contracts as fc, f_entry as fe, f_facts as ff, fb, fb_contracts as c, f_update2 as u2
from sui.rate import RateBudget
from test_fb_belief import BeliefSnapshotReader
from test_fb_cycle import T, E, U, NativeEntryObserver, wire
from test_fb_switch_belief import (SwitchRig, OracleJoint, bit_prior, rising, joint_oracle,
    marginal_state, selection_oracle)
from test_fb_time_belief import (TimeRig, TimeSource, script, budget, rat, plus, minus, times,
    divide, total, expneg, logarithm, enclose, exp_minus, assert_contains,
    information_and_choice, finite_ce1, time_fact_at)


def clock_api():
    missing=[n for n in ('ClockPrior','ClockQuantity') if not hasattr(fb,n)]
    if 'clock' not in {x.name for x in fields(fb.SwitchPart)}:
        missing.append('SwitchPart.clock')
    if not hasattr(fb.FThreadHost,'query_clock_belief'):
        missing.append('FThreadHost.query_clock_belief')
    assert not missing, 'K40 public shape missing: '+', '.join(missing)


def point(values):
    return {'kind':'point','values':tuple((m,tuple(v)) for m,v in values)}


def clock_prior(*, periods=((Q(1),Q(1)),), m=2, phase=Q(0),
                widths=(Q(1,2),Q(1,2)), fractions=(Q(3,4),Q(1,4)),
                segments=None, max_segments=None, couplings=()):
    clock_api()
    return fb.ClockPrior(periods=tuple(periods),max_segments=max_segments or m,
        segments=tuple(segments or ((m,Q(1)),)),
        phase={'kind':'uniform'} if phase is None else {'kind':'point','value':phase},
        widths=widths if isinstance(widths,dict) else point(((m,widths),)),
        fractions=fractions if isinstance(fractions,dict) else point(((m,fractions),)),
        couplings=tuple(couplings))


class ReleasedClockSource(TimeSource):
    """TEST source: computation duration must not become an acquisition fault.

    The test explicitly releases each read. CycleRig.close releases every gate
    and joins the threads, including on assertion failure. Wall-clock deadlines
    remain on observing transitions/teardown, not on a deliberately pending read.
    """
    def read(self,cursor):
        i=len(self.calls);self.calls.append(cursor)
        gate=self.gates[i];gate.entered.set()
        if i+1==len(self.rig.plan):self.rig.running.stop()
        gate.release.wait()
        if self.rig.closing:raise SystemExit('test teardown')
        self.rig.clock.set(self.rig.plan[i].after)
        symbol=self.symbols[i]
        if symbol==U:raise OSError('independent source failure')
        return fb.SourceItem(media_type='application/octet-stream',data=self.payload,claims={}) if symbol==T else None


class ClockRig(SwitchRig):
    def __init__(self,plan,*,clock=None,mood=False,clock_name='clock',
                 mood_factor=(Q(1),Q(2)),**kwargs):
        clock_api()
        self.clock_prior=clock if clock is not None else clock_prior()
        self.clock_name=clock_name
        self.has_mood=mood
        self.mood_factor=mood_factor
        super().__init__(plan,factors=(mood_factor,) if mood else (),**kwargs)
        self.passive=ReleasedClockSource(self)
        # K39's p helpers use factors only to count bits; a clock is one bit.
        self.part_names=(('mood',) if mood else ())+ (clock_name,)
        self.factors=(mood_factor,) if mood else ()
        declaration=self.boot_input.declaration
        if declaration.initial is not None:
            initial=declaration.initial
            self.boot_input=replace(self.boot_input,declaration=replace(declaration,
                initial=replace(initial,value=replace(initial.value,
                    prepare_budget=budget(Q(1,1024)),evaluate_budget=budget(Q(1,1024))))))

    def law(self,*,rates=None,prior=None):
        parts=(fb.SwitchPart(id='mood',kind='mood',multipliers=self.mood_factor),) if self.has_mood else ()
        parts+=(fb.SwitchPart(id=self.clock_name,kind='clock',multipliers=(),clock=self.clock_prior),)
        return fb.PoissonLaw(run=self.clock.run,states=('A','B'),
            prior=self.time_prior if prior is None else prior,
            rates=self.base if rates is None else tuple(rates),origin_ns=self.origin,
            initial_count=self.initial_count,time_unit=self.unit,family=self.family,
            parts=parts,a=self.a,b=self.b,state_role=self.state_role)

    def candidate(self):
        return self.pool().members[0].id

    def cq(self,kind,*,candidate=None,expression=None,tolerance=Q(1,4096),**event):
        expression=expression or self.expression()
        quantity=fb.ClockQuantity(kind=kind,candidate=candidate or self.candidate(),family=self.family,
            part=self.clock_name,**event)
        result=self.host.query_clock_belief(belief=expression,quantity=quantity,
            budget=budget(tolerance))
        assert result.root==expression.root and result.quantity==quantity
        assert result.upper-result.lower<=tolerance
        assert self.host.verify_belief_value(belief=expression,value=result)
        return result


@pytest.fixture
def clocks():
    made=[]
    def make(*args,**kwargs):
        clock_api()
        r=ClockRig(*args,**kwargs);made.append(r);return r
    yield make
    for r in reversed(made):r.close()


# Independent finite piecewise-rate ruler. A full period integrates to T.
def boundaries(T,phase,widths,before,after):
    cuts={Q(before),Q(after)}
    starts=[phase+sum(widths[:j],Q(0)) for j in range(len(widths))]
    for turn in range(int(before//T)-2,int(after//T)+3):
        for start in starts:
            t=(turn+start)*T
            if before<t<after:cuts.add(t)
    return sorted(cuts)


def multiplier(t,T,phase,widths,fractions):
    position=(t/T-phase)%1
    left=Q(0)
    for width,fraction in zip(widths,fractions,strict=True):
        if position<left+width:return fraction/width
        left+=width
    raise AssertionError('rational circle partition is incomplete')


def hazard(t,T,phase,widths,fractions):
    assert t>=0
    cuts=boundaries(T,phase,widths,Q(0),t)
    return sum(((b-a)*multiplier((a+b)/2,T,phase,widths,fractions)
                for a,b in zip(cuts,cuts[1:])),Q(0))


def piece_empty(R,before,after,*,T=Q(1),phase=Q(0),
                widths=(Q(1,2),Q(1,2)),fractions=(Q(3,4),Q(1,4))):
    if not R:return rat(1)
    if before==after:return expneg(R*hazard(after,T,phase,widths,fractions))
    pieces=[]
    cuts=boundaries(T,phase,widths,before,after)
    for a,b in zip(cuts,cuts[1:]):
        rate=R*multiplier((a+b)/2,T,phase,widths,fractions)
        h=R*hazard(a,T,phase,widths,fractions)
        pieces.append(times(expneg(h),divide(minus(rat(1),expneg(rate*(b-a))),rat(rate))))
    return divide(total(pieces),rat(after-before))


def point_joint(*,base=(Q(1),Q(1)),mood=False,a=Q(1),b=Q(1),
                prior=(Q(1,2),Q(1,2)),before=Q(1,4),after=Q(1,4),
                T=Q(1),phase=Q(0),widths=(Q(1,2),Q(1,2)),
                fractions=(Q(3,4),Q(1,4)),symbol=E,sensor=(Q(1),Q(1)),
                likelihood=None):
    k=2 if mood else 1
    weights={};keys={};likelihoods={}
    for bits in product((0,1),repeat=k):
        for s in range(2):
            R=base[s]*(Q(2) if mood and bits[0] and s else Q(1))
            enabled=bool(bits[-1])
            shape=dict(T=T,phase=phase,widths=widths,
                fractions=fractions if enabled else widths)
            L=piece_empty(R,before,after,**shape)
            if symbol==T_SYMBOL:L=minus(rat(1),L)
            if likelihood is not None:L=likelihood(R,enabled,shape)
            likelihoods[bits,s]=L
            weights[bits,s]=times(rat(bit_prior(bits,a,b)*prior[s]*sensor[s]),L)
        # Caller may supply an equivalent representation; aliases use the
        # independent canonical piecewise function, not period/segment names.
        keys[bits]=tuple(base[s]*(Q(2) if mood and bits[0] and s else Q(1)) for s in range(2)), enabled
    Z=total(weights.values())
    if len(set(likelihoods.values()))==1:
        norm=sum(prior[s]*sensor[s] for s in range(2))
        values={(bits,s):rat(bit_prior(bits,a,b)*prior[s]*sensor[s]/norm) for bits,s in weights}
    else:values={key:divide(w,Z) for key,w in weights.items()}
    norm=sum(prior[s]*sensor[s] for s in range(2))
    exact_state=tuple(prior[s]*sensor[s]/norm for s in range(2)) if not mood and base[0]==base[1] else None
    return OracleJoint(values,exact_state=exact_state),Z,keys


T_SYMBOL=T


def sum_joint(joint,*,on=(),off=(),state=None):
    return total(w for (bits,s),w in joint.items()
        if all(bits[i] for i in on) and all(not bits[i] for i in off)
        and (state is None or state==s))


def check_point(r,joint,Z,*,tol=Q(1,2**40)):
    assert_contains(r.query('mass',tolerance=tol),Z)
    expected=rat(joint.exact_state[0]) if joint.exact_state is not None else sum_joint(joint,state=0)
    assert_contains(r.query('state',state='A',tolerance=tol),expected)
    for i,name in enumerate(r.part_names):
        assert_contains(r.sq('switch',on=(name,),tolerance=tol),sum_joint(joint,on=(i,)))
    for order in (1,2):
        k=len(r.part_names)
        value=total(times(w,rat(rising(r.a+sum(bits),order)/rising(r.a+r.b+k,order)))
            for (bits,s),w in joint.items())
        assert_contains(r.sq('p_moment',order=order,tolerance=tol),value)
    mixture=r.mixture()
    assert all(v.a+v.b==r.a+r.b+len(r.part_names) for v in mixture.components)


def information(joint,keys,targets=('A','B')):
    groups=defaultdict(list)
    rows=((Q(1),Q(1,2)),(Q(0),Q(1,2)))
    for (bits,s),w in joint.items():groups[keys[bits],targets[s]].append((s,w))
    py=[total(times(w,rat(row[s])) for (bits,s),w in joint.items()) for row in rows]
    terms=[]
    for members in groups.values():
        pk=total(w for s,w in members)
        for y,row in enumerate(rows):
            cells=[times(w,rat(row[s])) for s,w in members if row[s]]
            if not cells:continue
            pyk=total(cells)
            terms.append(times(pyk,logarithm(divide(pyk,times(pk,py[y])))))
    I=total(terms)
    return I,divide(('exp',I),plus(rat(1),('exp',I)))


def check_selected(r,selected,joint,keys,expression=None):
    values=r.host.query_selection(selection=selected.cid,budget=budget(Q(1,2**32)))
    I,p=information(joint,keys,r.targets)
    assert values.belief_root==(expression or r.expression()).root
    assert set(values.candidates)=={'peek','wait'}
    for i,name in enumerate(values.candidates):
        assert_contains(values.information[i],I if name=='peek' else rat(0))
        assert_contains(values.G[i],minus(rat(0),I) if name=='peek' else rat(0))
        assert_contains(values.probabilities[i],p if name=='peek' else minus(rat(1),p))
    return values


def conditional_on(r,kind,*,on=(),off=(),state=None,tolerance=Q(1,4096)):
    """TEST arithmetic on existing joint values, not a ClockQuantity condition."""
    event=r.sq('switch',on=on,off=off,tolerance=tolerance)
    if kind=='mass':
        k=len(r.part_names);indices={n:i for i,n in enumerate(r.part_names)}
        prior=sum(bit_prior(bits,r.a,r.b) for bits in product((0,1),repeat=k)
            if all(bits[indices[n]] for n in on) and all(not bits[indices[n]] for n in off))
        mass=r.query('mass',tolerance=tolerance)
        return times_bounds(mass,event,divide_by=prior)
    joint=r.sq('state',on=on,off=off,state=state,tolerance=tolerance)
    assert event.lower>0
    return Bounds(joint.lower/event.upper,joint.upper/event.lower)


class Bounds:
    def __init__(self,lower,upper):self.lower,self.upper=lower,upper


def times_bounds(a,b,*,divide_by=Q(1)):
    return Bounds(a.lower*b.lower/divide_by,a.upper*b.upper/divide_by)


def incomplete_query_budget(tolerance=Q(1,256)):
    """Small TEST budget; only the incomplete contract may accept exhaustion."""
    return RateBudget(tolerance=tolerance,max_cells=16,max_terms=512,max_refinements=2)


def budget_contract_call(r,call):
    expression=r.expression()
    try:result=call()
    except fb.TimeBeliefError as error:
        assert error.kind=='incomplete' and error.reason
        assert r.expression().root==expression.root
        assert not any('model_falsified' in row.reasons for row in r.host.window.status().updates)
        return None
    assert r.expression().root==expression.root
    assert result is not None, 'a missing value is not an incomplete exception'
    return result


def continuous_ruler_budget(tolerance):
    """TEST resources, not a production starting level or an acceptance limit.

    One record and coarse precision keep this a small calculation. Exhaustion
    is a failed numerical comparison, not permission to pass without a ruler.
    """
    return RateBudget(tolerance=tolerance,max_cells=16384,max_terms=4096,max_refinements=16)


def certified_clock_call(r,call,limits):
    expression=r.expression()
    try:result=call()
    except fb.TimeBeliefError as error:
        if error.kind!='incomplete':raise
        pytest.fail(f'numerical ruler NOT reached: reason={error.reason!r}, '
            f'field={error.field!r}, targets={error.targets!r}, budget={limits!r}')
    assert r.expression().root==expression.root
    return result


def certified_belief_query(r,kind,*,switch=False,tolerance=Q(1,64),**event):
    expression=r.expression()
    limits=continuous_ruler_budget(tolerance)
    if switch:
        quantity=fb.SwitchQuantity(kind=kind,candidate=r.candidate(),family=r.family,**event)
        invoke=lambda:r.host.query_switch_belief(belief=expression,quantity=quantity,
            budget=limits)
    else:
        quantity=fb.BeliefQuantity(kind=kind,**event)
        invoke=lambda:r.host.query_belief(belief=expression,quantity=quantity,
            budget=limits)
    value=certified_clock_call(r,invoke,limits)
    assert value.root==expression.root and value.quantity==quantity
    assert value.upper-value.lower<=tolerance
    assert r.host.verify_belief_value(belief=expression,value=value)
    return value


def clock_mixture_reference(on_reference,R,t):
    # One clock bit has prior 1/2. Compare the directly exposed evidence mass
    # instead of demanding two finer queries and multiplying their intervals.
    lo,hi=enclose(expneg(R*t),48)
    return Bounds((on_reference.lower+lo)/2,(on_reference.upper+hi)/2)


def assert_bounds_include(value,reference):
    assert isinstance(value.lower,Q) and isinstance(value.upper,Q)
    assert value.lower<=reference.lower<=reference.upper<=value.upper


@lru_cache(maxsize=128)
def width_integral(R,n=32):
    """Composite Simpson + a proved 4th-derivative bound, on [1/2,1].

    g(u)=exp(-R/(4u))+exp(-R+R/(4u)); each exponential <=1.
    |g''''| <= 384R+288R^2+48R^3+2R^4. Error <= L*h^4*M/180.
    Endpoint exponential errors use exact rational Taylor bounds as in K38.
    """
    if not R:return Bounds(Q(1),Q(1))
    assert n%2==0 and R>=0
    h=Q(1,2*n);lo=hi=Q(0)
    for j in range(n+1):
        u=Q(1,2)+j*h
        l1,h1=exp_minus(R/(4*u),24)
        l2,h2=exp_minus(R-R/(4*u),24)
        weight=1 if j in (0,n) else 4 if j%2 else 2
        lo+=weight*(l1+l2);hi+=weight*(h1+h2)
    derivative=384*R+288*R**2+48*R**3+2*R**4
    remainder=Q(1,2)*h**4*derivative/180
    return Bounds(lo*h/3-remainder,hi*h/3+remainder)


def assert_width_ruler(value,R,*,mixture=False):
    for n in (8,16,32,64,128,256):
        ref=width_integral(R,n)
        if mixture:ref=clock_mixture_reference(ref,R,Q(1,2))
        assert not (ref.upper<value.lower or value.upper<ref.lower)
        if value.lower<=ref.lower<=ref.upper<=value.upper:return
    pytest.fail('width integral reference did not resolve certificate endpoints')


def test_clock1_ruler_controls_are_exact_and_bound_the_width_integral():
    assert hazard(Q(1,4),Q(1),Q(0),(Q(1,2),)*2,(Q(3,4),Q(1,4)))==Q(3,8)
    for phase in (Q(0),Q(1,5),Q(7,8)):
        assert hazard(Q(3),Q(1),phase,(Q(1,3),Q(2,3)),(Q(4,5),Q(1,5)))==3
    assert_contains(Bounds(*enclose(expneg(Q(3,8)),64)),piece_empty(Q(1),Q(1,4),Q(1,4)))
    a,b=width_integral(Q(1),16),width_integral(Q(1),64)
    assert a.lower<b.lower<b.upper<a.upper
    assert b.upper-b.lower<Q(1,2**22)
    assert b.lower>enclose(expneg(Q(1,2)),32)[1]  # equal-width approximation differs.
    assert width_integral(Q(0)).lower==width_integral(Q(0)).upper==1
    # For a neutral second bit, the first bit marginal is still 1/2.
    assert sum(bit_prior(bits,Q(1),Q(1)) for bits in product((0,1),repeat=2) if bits[0])==Q(1,2)
    for t in (Q(1,7),Q(1,2),Q(5,6),Q(8,3)):
        h=hazard(t,Q(1),Q(0),(Q(1,2),)*2,(Q(3,4),Q(1,4)))
        assert hazard(t,Q(2),Q(0),(Q(1,4),)*4,(Q(3,8),Q(1,8))*2)==h
        assert hazard(t,Q(1),Q(1,2),(Q(1,2),)*2,(Q(1,4),Q(3,4)))==h
        assert hazard(t,Q(1),Q(0),(Q(1,4),Q(1,4),Q(1,2)),(Q(3,8),Q(3,8),Q(1,4)))==h
    # The information ruler distinguishes the target quotient from full S,
    # and demonstrates that adding I(clock;Y) really would overcount here.
    independent={(bits,s):rat(Q(1,4)) for bits in [(0,),(1,)] for s in (0,1)}
    I,_=information(independent,{(0,):'one-law',(1,):'one-law'},('same','same'))
    lo,hi=enclose(I,32);assert lo<=0<=hi and hi-lo<Q(1,2**60)
    full,_=information_and_choice(rat(Q(1,2)));assert enclose(full,32)[0]>0
    j,_,keys=point_joint(mood=True)
    extra,_=information(j,{bits:bits[-1] for bits in keys},('same','same'))
    assert enclose(extra,32)[0]>0


def test_clock1_existing_native_footing_and_CE1_control():
    r=TimeRig(script((20,20,E),(30,30,E)),unit=Q(1,10),finite=True,thinking=True)
    r.passive=ReleasedClockSource(r)
    r.direct()
    try:
        r.think()  # Finish the prior activity before the first new evidence.
        r.observe(0);first=r.update();p,z=finite_ce1(2);r.check(rat(p),rat(z))
        r.check_selection(r.think(),rat(p),first)
        r.observe(1);second=r.update();p,z=finite_ce1(3);r.check(rat(p),rat(z))
        r.check_selection(r.think(),rat(p),second)
    finally:r.close()


@pytest.mark.parametrize('ticks',[1,4])
def test_clock1_point_clock_on_matches_piecewise_rate_not_a_constant_rate(clocks,ticks):
    r=clocks(script((ticks,ticks,E)),unit=Q(1,4)).start()
    r.observe(0);r.update()
    conditional=conditional_on(r,'mass',on=('clock',))
    expected=expneg(Q(3,8) if ticks==1 else Q(1))
    assert_contains(conditional,expected)
    j,z,_=point_joint(before=Q(ticks,4),after=Q(ticks,4))
    check_point(r,j,z)


@pytest.mark.parametrize('phase,widths,fractions',[
    (Q(1,4),(Q(1,3),Q(2,3)),(Q(4,5),Q(1,5))),
    (Q(3,4),(Q(2,3),Q(1,3)),(Q(1,5),Q(4,5))),
])
def test_clock1_boundary_crossing_integrates_one_decision_and_keeps_unequal_widths(clocks,phase,widths,fractions):
    prior=clock_prior(phase=phase,widths=widths,fractions=fractions)
    r=clocks(script((1,5,E)),clock=prior,unit=Q(1,6),base=(Q(1),Q(2))).direct()
    r.observe(0);r.update()
    j,z,_=point_joint(base=r.base,before=Q(1,6),after=Q(5,6),phase=phase,widths=widths,fractions=fractions)
    check_point(r,j,z)
    one=piece_empty(Q(1),Q(1,6),Q(5,6),phase=phase,widths=widths,fractions=fractions)
    cut=boundaries(Q(1),phase,widths,Q(1,6),Q(5,6))[1]
    wrong=times(piece_empty(Q(1),Q(1,6),cut,phase=phase,widths=widths,fractions=fractions),
        piece_empty(Q(1),cut,Q(5,6),phase=phase,widths=widths,fractions=fractions))
    assert enclose(one,64)[0]>enclose(wrong,64)[1]


@pytest.mark.parametrize('R',[Q(0),Q(1),Q(3,2)])
def test_clock1_rotation_is_integrated_with_a_separate_zero_rate_branch(clocks,R):
    r=clocks(script((1,1,E)),clock=clock_prior(phase=None),unit=Q(1,2),base=(R,R)).start()
    r.observe(0);r.update()
    expected=rat(1) if not R else times(expneg(R/4),divide(times(rat(2),minus(rat(1),expneg(R/2))),rat(R)))
    assert_contains(conditional_on(r,'mass',on=('clock',)),expected)
    if R:assert enclose(expected,64)[0]>enclose(expneg(3*R/4),64)[1]


def test_clock1_rotation_posterior_keeps_one_theta_for_the_whole_history(clocks):
    r=clocks(script((1,1,E),(2,2,E)),clock=clock_prior(phase=None),unit=Q(1,4)).direct()
    r.observe(0);first=r.update()
    r.observe(1);last=r.update()
    Z_on=times(expneg(Q(1,4)),times(rat(2),minus(rat(1),expneg(Q(1,2)))))
    assert_contains(conditional_on(r,'mass',on=('clock',)),Z_on)
    assert_contains(r.query('mass',tolerance=Q(1,4096)),
        times(rat(Q(1,2)),plus(expneg(Q(1,2)),Z_on)))
    assert first.root!=last.root and len(last.observations)==2
    root=last.root;r.host.rebuild_window();assert r.expression().root==root
    assert_contains(conditional_on(r,'mass',on=('clock',)),Z_on)


def test_clock1_continuous_clock_model_average_reaches_native_G_and_policy_probability(clocks):
    r=clocks(script((1,1,E)),clock=clock_prior(phase=None),unit=Q(1,2),
        base=(Q(1),Q(2)),thinking=True).start()
    r.observe(0);expression=r.update()
    weights=[]
    for R in r.base:
        rotation=times(expneg(R/4),divide(times(rat(2),minus(rat(1),expneg(R/2))),rat(R)))
        weights.append(times(rat(Q(1,4)),plus(expneg(R/2),rotation)))
    Z=total(weights);p=divide(weights[0],Z)
    assert_contains(r.query('state',state='A',tolerance=Q(1,4096)),p)
    assert_contains(r.query('mass',tolerance=Q(1,4096)),Z)
    I,choice=information_and_choice(p)
    values=r.host.query_selection(selection=r.think().cid,budget=budget(Q(1,4096)))
    assert values.belief_root==expression.root
    for i,name in enumerate(values.candidates):
        assert_contains(values.information[i],I if name=='peek' else rat(0))
        assert_contains(values.G[i],minus(rat(0),I) if name=='peek' else rat(0))
        assert_contains(values.probabilities[i],choice if name=='peek' else minus(rat(1),choice))


@pytest.mark.parametrize('prior',['width','fraction-boundary','all-continuous'])
def test_clock1_continuous_small_budget_preserves_root_and_classifies_incomplete(clocks,prior,record_property):
    if prior=='width':
        cp=clock_prior(widths={'kind':'symmetric_dirichlet','concentration':Q(1)},fractions=(Q(1,2),)*2)
    elif prior=='fraction-boundary':
        cp=clock_prior(widths=(Q(1,2),)*2,
            fractions={'kind':'conditional_dirichlet','concentration':Q(1)})
    else:
        cp=clock_prior(phase=None,widths={'kind':'symmetric_dirichlet','concentration':Q(2,3)},
            fractions={'kind':'conditional_dirichlet','concentration':Q(3,2)})
    r=clocks(script((1,1,E)),clock=cp,unit=Q(1,2)).start();r.observe(0);expression=r.update()
    quantity=fb.BeliefQuantity(kind='mass');limits=incomplete_query_budget()
    value=budget_contract_call(r,lambda:r.host.query_belief(belief=expression,
        quantity=quantity,budget=limits))
    if value is None:
        record_property('budget_outcome','incomplete')
    else:
        # No algorithm-independent minimum work is specified. A completed
        # certificate is legitimate, but is NOT counted as a ruler comparison.
        record_property('budget_outcome','certified')
        assert value.root==expression.root and value.quantity==quantity
        assert value.upper-value.lower<=limits.tolerance
        assert r.host.verify_belief_value(belief=expression,value=value)
    assert r.expression().root==expression.root
    assert not any('model_falsified' in row.reasons for row in r.host.window.status().updates)


def test_clock1_width_prior_integrates_the_whole_simplex_with_certified_reference(clocks,record_property):
    cp=clock_prior(widths={'kind':'symmetric_dirichlet','concentration':Q(1)},fractions=(Q(1,2),)*2)
    r=clocks(script((1,1,E)),clock=cp,unit=Q(1,2),base=(Q(4),Q(4))).start()
    r.observe(0);expression=r.update()
    results=[]
    for tolerance in (Q(1,16),Q(1,32)):
        result=certified_belief_query(r,'mass',tolerance=tolerance)
        results.append(result)
        assert_width_ruler(result,Q(4),mixture=True)
    assert results[1].upper-results[1].lower<=results[0].upper-results[0].lower
    assert r.expression().root==expression.root
    record_property('numerical_ruler_comparisons',2)


def test_clock1_fraction_prior_is_dirichlet_conditioned_on_the_widths(clocks):
    cp=clock_prior(widths=(Q(1,3),Q(2,3)),
        fractions={'kind':'conditional_dirichlet','concentration':Q(3)})
    r=clocks(script((1,1,E)),clock=cp,unit=Q(1,3)).start()
    r.observe(0);r.update()
    # f1~Beta(1,2), H(1/3)=f1, integral 2*(R-1+exp(-R))/R^2.
    expected=times(rat(2),expneg(1))
    assert_contains(conditional_on(r,'mass',on=('clock',)),expected)
    assert enclose(expected,64)[0]>enclose(minus(rat(1),expneg(1)),64)[1]


@pytest.mark.parametrize('continuous',[False,True])
def test_clock1_whole_period_cannot_learn_shape_or_create_extra_switches(clocks,continuous):
    cp=clock_prior(phase=None if continuous else Q(2,7),
        widths={'kind':'symmetric_dirichlet','concentration':Q(2,3)} if continuous else (Q(1,5),Q(4,5)),
        fractions={'kind':'conditional_dirichlet','concentration':Q(3,2)} if continuous else (Q(3,4),Q(1,4)))
    r=clocks(script((1,1,E),(2,2,E)),clock=cp).direct()
    for i in range(2):
        r.observe(i);r.update()
        if continuous:
            mass=certified_belief_query(r,'mass')
            assert_contains(mass,expneg(i+1))
            for kind in ('switch','p_mean'):
                event={'on':('clock',)} if kind=='switch' else {}
                value=certified_belief_query(r,kind,switch=True,**event)
                assert_contains(value,rat(Q(1,2)))
            expression=r.expression()
            limits=continuous_ruler_budget(Q(1,64))
            mix=certified_clock_call(r,lambda:r.host.p_distribution(belief=expression,
                candidate=r.candidate(),family=r.family,budget=limits),limits)
            assert mix.root==expression.root and mix.candidate==r.candidate()
            assert mix.family==r.family and mix.a==r.a and mix.b==r.b
            assert all(x.a+x.b==3 for x in mix.components)
            assert tuple(mix.parts)==('clock',)
            assert r.host.verify_p_distribution(belief=expression,distribution=mix)
            continue
        assert_contains(r.query('mass'),expneg(i+1))
        assert r.sq('switch',on=('clock',)).exact==Q(1,2)
        assert r.sq('p_mean').exact==Q(1,2)
        mix=r.mixture()
        assert all(x.a+x.b==3 for x in mix.components)
        assert tuple(mix.parts)==('clock',)
    if continuous:
        for lo,hi in [(Q(1,17),Q(2,17)),(Q(101,1009),Q(102,1009))]:
            # Whole-period evidence has not changed the rotation prior. This is
            # effective allocation, NOT probability of rho falling in the box.
            expression=r.expression()
            quantity=fb.ClockQuantity(kind='allocation',candidate=r.candidate(),family=r.family,
                part=r.clock_name,lower=lo,upper=hi)
            limits=continuous_ruler_budget(Q(1,64))
            value=certified_clock_call(r,lambda:r.host.query_clock_belief(belief=expression,
                quantity=quantity,budget=limits),limits)
            assert value.root==expression.root and value.quantity==quantity
            assert value.upper-value.lower<=limits.tolerance
            assert r.host.verify_belief_value(belief=expression,value=value)
            assert_contains(value,rat(hi-lo))


def test_clock1_continuous_boundary_mass_is_kept_without_region_queries(clocks,record_property):
    cp=clock_prior(widths={'kind':'symmetric_dirichlet','concentration':Q(1)},
        fractions=(Q(1,2),Q(1,2)))
    r=clocks(script((1,1,E)),clock=cp,unit=Q(1,2)).start();r.observe(0);r.update()
    # This whole-domain likelihood includes arbitrarily narrow w. No public
    # probability of a width box is requested by v6.
    result=certified_belief_query(r,'mass',tolerance=Q(1,16))
    assert_width_ruler(result,Q(1),mixture=True)
    record_property('numerical_ruler_comparisons',1)


def test_clock1_clock_off_conditions_shared_p_to_Beta_a_b_plus_one(clocks):
    r=clocks(script((1,1,E)),mood=True).start();r.observe(0);r.update()
    x=expneg(1)
    z=divide(plus(times(rat(5),x),times(x,x)),rat(6))
    p=divide(rat(3),plus(rat(5),x))
    assert_contains(conditional_on(r,'mass',off=('clock',)),z)
    assert_contains(conditional_on(r,'state',off=('clock',),state='A'),p)
    # Joint evidence differs from conditional evidence by P(clock off)=1/2.
    assert_contains(times_bounds(r.query('mass'),r.sq('switch',off=('clock',))),times(rat(Q(1,2)),z))
    j,Z,_=point_joint(mood=True,before=Q(1),after=Q(1));check_point(r,j,Z)
    control=SwitchRig(script((1,1,E)),a=Q(1),b=Q(2),thinking=True).start()
    try:
        control.observe(0);control.update();control.check(p,z)
        joint,_,rates=joint_oracle(control.base,control.factors,Q(1),Q(2))
        control.check_selection_joint(control.think(),joint,rates)
        # Compare every (mood,S) cell under clock-off, not only the S marginal.
        denominator=r.sq('switch',off=('clock',))
        for bit in (0,1):
            for s in (0,1):
                value=r.sq('state',state=('A','B')[s],
                    on=('mood',) if bit else (),off=('clock',) if bit else ('clock','mood'))
                assert_contains(Bounds(value.lower/denominator.upper,value.upper/denominator.lower),joint[(bit,),s])
        assert enclose(p,64)[1]<enclose(divide(rat(2),plus(rat(3),x)),64)[0]
    finally:control.close()


@pytest.mark.parametrize('same_targets',[False,True])
def test_clock1_ineffective_clock_returns_same_K39_information_probability_and_p(clocks,same_targets):
    cp=clock_prior(widths=(Q(1,3),Q(2,3)),fractions=(Q(1,3),Q(2,3)))
    r=clocks(script((1,1,E)),clock=cp,mood=True,thinking=True,same_targets=same_targets).start()
    r.observe(0);r.update()
    joint,Z,rates=joint_oracle(r.base,((Q(1),Q(2)),),r.a,r.b)
    assert_contains(r.query('mass'),Z)
    assert_contains(r.query('state',state='A'),marginal_state(joint,0))
    I,p=selection_oracle(joint,rates,r.targets)
    values=r.host.query_selection(selection=r.think().cid,budget=budget())
    for i,name in enumerate(values.candidates):
        assert_contains(values.information[i],I if name=='peek' else rat(0))
        assert_contains(values.G[i],minus(rat(0),I) if name=='peek' else rat(0))
        assert_contains(values.probabilities[i],p if name=='peek' else minus(rat(1),p))
    expected=sum_joint({(bits,s):w for (bits,s),w in joint.items()},on=(0,))
    assert_contains(r.sq('p_mean'),divide(plus(rat(1),expected),rat(3)))


@pytest.mark.parametrize('symbol',[T,E])
def test_clock1_second_switch_moves_both_ways_through_p_not_extra_observation_counts(clocks,symbol):
    # The nonconstant clock is invisible at full-period endpoints. The record
    # therefore informs mood, with clock moving only through the shared p.
    cp=clock_prior()
    r=clocks(script((1,1,symbol),(2,2,E)),clock=cp,mood=True).direct()
    r.observe(0);r.update()
    j,Z,_=point_joint(mood=True,before=Q(1),after=Q(1),symbol=symbol)
    check_point(r,j,Z)
    mood=r.sq('switch',on=('mood',));clock=r.sq('switch',on=('clock',))
    assert (clock.lower>Q(1,2) and mood.lower>Q(1,2)) if symbol==T else (clock.upper<Q(1,2) and mood.upper<Q(1,2))
    mix=r.mixture();assert all(v.a+v.b==4 for v in mix.components)
    # Continue the SAME z. A taken then empty sees exactly one arrival before t1.
    r.observe(1);r.update()
    def likelihood(R,enabled,shape):
        return times(rat(R),expneg(2*R)) if symbol==T else expneg(2*R)
    j,Z,_=point_joint(mood=True,likelihood=likelihood)
    check_point(r,j,Z)


def test_clock1_clock_evidence_moves_neutral_mood_switch_in_both_directions(clocks):
    # Mood really reads S: factors (2,1). On this declared prior's support S=B,
    # it cannot explain the record, isolating the influence through shared p.
    for symbol,direction in [(T,'up'),(E,'down')]:
        fresh=clocks(script((1,1,symbol)),unit=Q(1,4),mood=True,
            mood_factor=(Q(2),Q(1)),prior=(Q(0),Q(1)))
        fresh.start();fresh.observe(0);fresh.update()
        neutral_value=fresh.sq('switch',on=('mood',))
        clock_value=fresh.sq('switch',on=('clock',))
        L0,L1=expneg(Q(1,4)),expneg(Q(3,8))
        if symbol==T:L0,L1=minus(rat(1),L0),minus(rat(1),L1)
        w=divide(L1,plus(L0,L1))
        assert_contains(clock_value,w)
        assert_contains(neutral_value,divide(plus(rat(1),w),rat(3)))
        assert fresh.query('state',state='B').exact==1
        if direction=='up':assert neutral_value.lower>Q(1,2) and clock_value.lower>Q(1,2)
        else:assert neutral_value.upper<Q(1,2) and clock_value.upper<Q(1,2)


def test_clock1_native_cycle_uses_one_adopted_clock_belief_for_evaluation_step_and_next_update(clocks):
    r=clocks(script((1,1,E),(1,3,E)),unit=Q(1,4),mood=True,thinking=True).start()
    r.observe(0);first=r.update()
    j,z,keys=point_joint(mood=True);check_point(r,j,z)
    selected=r.think();check_selected(r,selected,j,keys,first)
    r.enter_step(selection=selected.cid);r.finish_step(0,T);after_step=r.update()
    j,z,keys=point_joint(mood=True,sensor=(Q(1),Q(1,2)))
    check_point(r,j,z);check_selected(r,r.think(),j,keys,after_step)
    r.observe(1);last=r.update()
    j,z,keys=point_joint(mood=True,before=Q(1,4),after=Q(3,4),sensor=(Q(1),Q(1,2)))
    check_point(r,j,z);check_selected(r,r.think(),j,keys,last)
    assert len(r.actor.calls)==1 and last.root!=after_step.root!=first.root
    original,_,original_keys=point_joint(mood=True)
    check_selected(r,selected,original,original_keys,expression=first)


def test_clock1_declared_target_quotient_is_not_full_latent_state_information(clocks):
    cp=clock_prior(fractions=(Q(1,2),)*2)
    r=clocks(script((1,1,E)),clock=cp,base=(Q(1),Q(2)),same_targets=True,thinking=True).start()
    r.observe(0);r.update()
    values=r.host.query_selection(selection=r.think().cid,budget=budget())
    # All z resolve to the same rate TABLE; target(A)=target(B). Q is one atom.
    for i,name in enumerate(values.candidates):
        assert_contains(values.information[i],rat(0))
        assert_contains(values.G[i],rat(0))
        assert_contains(values.probabilities[i],rat(Q(1,2)))
        assert all(v.upper-v.lower<=budget().tolerance for v in
            (values.information[i],values.G[i],values.probabilities[i]))


@pytest.mark.parametrize('variant',['rename','rotate-labels','split-equal','double-period'])
def test_clock1_equivalent_rate_functions_do_not_inflate_knowledge_or_G(clocks,variant):
    r=clocks(script((1,1,E)),unit=Q(1,4),base=(Q(1),Q(2)),same_targets=True,thinking=True).start()
    r.observe(0);r.update();j,z,keys=point_joint(base=r.base)
    selected=r.think();check_selected(r,selected,j,keys)
    if variant=='rename':cp=clock_prior()
    elif variant=='rotate-labels':cp=clock_prior(phase=Q(1,2),fractions=(Q(1,4),Q(3,4)))
    elif variant=='split-equal':cp=clock_prior(m=3,widths=(Q(1,4),Q(1,4),Q(1,2)),fractions=(Q(3,8),Q(3,8),Q(1,4)))
    else:cp=clock_prior(periods=((Q(2),Q(1)),),m=4,widths=(Q(1,4),)*4,fractions=(Q(3,8),Q(1,8))*2)
    law=r.law();part=replace(law.parts[-1],id='alias',clock=cp)
    r.add_time_candidate(law=replace(law,parts=(part,)));r.update()
    assert len(r.pool().members)==2
    check_point(r,j,z);check_selected(r,r.think(),j,keys)
    # The original fixed selection remains rereadable under its original root.
    assert r.host.query_selection(selection=selected.cid,budget=budget()).belief_root


def test_clock1_period_and_segment_discrete_priors_are_not_additional_switch_bits(clocks):
    cp=clock_prior(periods=((Q(1),Q(1,3)),(Q(2),Q(2,3))),m=3,max_segments=3,
        segments=((2,Q(1,4)),(3,Q(3,4))),
        widths=point(((2,(Q(1,2),)*2),(3,(Q(1,3),)*3))),
        fractions=point(((2,(Q(3,4),Q(1,4))),(3,(Q(1,2),Q(1,3),Q(1,6))))))
    r=clocks(script((2,2,E),(2,4,E)),clock=cp,unit=Q(1,4)).direct()
    r.observe(0);r.update()
    # Explicit product of T/m priors, with a single persistent clock bit.
    weights={}
    for T0,pT in cp.periods:
        for m,pm in cp.segments:
            w=dict(cp.widths['values'])[m];f0=dict(cp.fractions['values'])[m]
            for bit in (0,1):
                weights[T0,m,bit]=times(rat(pT*pm/2),piece_empty(Q(1),Q(1,2),Q(1,2),T=T0,widths=w,fractions=f0 if bit else w))
    Z=total(weights.values());assert_contains(r.query('mass'),Z)
    for T0,pT in cp.periods:
        expected=divide(total(v for (tv,m,b),v in weights.items() if tv==T0),Z)
        assert_contains(r.cq('parameters',periods=(T0,)),expected)
    for m,pm in cp.segments:
        assert_contains(r.cq('parameters',segments=(m,)),divide(total(v for (tv,mv,b),v in weights.items() if mv==m),Z))
    assert all(v.a+v.b==3 for v in r.mixture().components)


def test_clock1_integer_period_endpoints_keep_period_and_effective_allocation_prior(clocks):
    cp=clock_prior(periods=((Q(1),Q(1,3)),(Q(2),Q(2,3))),phase=None)
    # These are point observations at common period endpoints, not a uniform
    # observation over [2,4]. Direct's test port sets the real acquire clock.
    r=clocks(script((2,2,E),(4,4,E)),clock=cp).direct()
    for i in range(2):
        r.observe(i);r.update()
        assert_contains(r.query('mass'),expneg(2*(i+1)))
        for period,p in cp.periods:assert_contains(r.cq('parameters',periods=(period,)),rat(p))
        assert_contains(r.cq('allocation',lower=Q(1,7),upper=Q(2,7)),rat(Q(1,7)))


def test_clock1_same_history_rebuild_U_and_pool_addition_keep_the_clock_root_and_likelihood(clocks):
    r=clocks(script((1,1,T),(3,3,E)),unit=Q(1,4),thinking=False)
    observer=NativeEntryObserver(fb.TimedBeliefUpdater(registry=r.registry))
    r.direct(worker_overrides={'belief_update':observer})
    r.observe(0);r.update();r.observe(1);expression=r.update()
    def L(R,enabled,shape):
        return times(rat(R*hazard(Q(1,4),shape['T'],shape['phase'],shape['widths'],shape['fractions'])),
            expneg(R*hazard(Q(3,4),shape['T'],shape['phase'],shape['widths'],shape['fractions'])))
    j,Z,_=point_joint(likelihood=L);check_point(r,j,Z)
    assert r.query('count',count=1).exact==1 and r.query('count',count=2,at_least=True).exact==0
    for added in (False,True):
        if added:r.add_time_candidate(law=r.law());expression=r.update()
        result=time_fact_at(r,expression.result);q=time_fact_at(r,result.value['request'])
        wid=q.value['desc']['work_id']
        issued=u2.compute_timed_update(q.cid,reader=observer.contexts[wid].reader(),registry=r.registry,evidence=None)
        assert isinstance(issued,u2.IssuedUpdate)
        assert json.dumps(wire(issued.result),sort_keys=True)==json.dumps(result.value['result'],sort_keys=True)
        before=r.expression();r.host.rebuild_window();after=r.expression()
        assert r.host.same_belief(left=before,right=after) and before.root==after.root
        check_point(r,j,Z)
    # Same record is not a new observation; distinct acquisitions keep their IDs.
    assert len(set(r.expression().observations))==len(r.expression().observations)
    before=r.expression();r.host.rebuild_window();assert r.expression().observations==before.observations


def test_clock1_non_counting_acquisition_advances_piecewise_count_law_to_after(clocks):
    r=clocks(script((0,0,E),(0,3,U)),unit=Q(1,4),
        disconnection=Q(1,3),failure=Q(1,4)).start()
    r.observe(0);r.update();r.observe(1);r.update()
    # First empty at t=0: 1/2. Called failure: (1-c)*p=1/6.
    assert r.query('mass').exact==Q(1,12)
    assert r.query('state',state='A').exact==Q(1,2)
    expected=times(rat(Q(1,2)),plus(expneg(Q(3,4)),expneg(Q(7,8))))
    assert_contains(r.query('count',count=0),expected)


def test_clock1_small_positive_period_event_is_not_deleted_by_coarse_bounds(clocks):
    tiny=Q(1,2**100)
    cp=clock_prior(periods=((Q(1),tiny),(Q(2),1-tiny)))
    r=clocks(script((2,2,E)),clock=cp).start();r.observe(0);r.update()
    coarse=r.cq('parameters',periods=(Q(1),),tolerance=Q(1,8))
    assert_contains(coarse,rat(tiny))
    fine=r.cq('parameters',periods=(Q(1),),tolerance=Q(1,2**120))
    assert fine.lower>0
    assert_contains(fine,rat(tiny))


def test_clock1_saved_clock_belief_certificates_are_rechecked_from_the_root(clocks):
    r=clocks(script((1,1,E)),base=(Q(1),Q(2)),unit=Q(1,4)).start()
    r.observe(0);expression=r.update()
    certificate=r.query('state',state='A')
    altered=replace(certificate,lower=Q(0),upper=Q(0),exact=Q(0))
    try:assert r.host.verify_belief_value(belief=expression,value=altered) is False
    except fb.TimeBeliefError as error:assert error.kind in ('invalid','unavailable') and error.reason
    assert r.host.verify_belief_value(belief=expression,value=certificate)
    r.host.rebuild_window();replayed=r.expression()
    assert r.host.same_belief(left=expression,right=replayed)
    assert r.host.verify_belief_value(belief=replayed,value=certificate)


@pytest.mark.parametrize('R,initial,symbol',[(Q(0),0,T),(Q(0),1,T),(Q(1,2**160),0,T)])
def test_clock1_structural_zero_and_tiny_positive_are_not_coarse_interval_zero(clocks,R,initial,symbol):
    r=clocks(script((1,1,symbol)),base=(R,R),initial_count=initial).start();r.observe(0)
    if not R and not initial:
        r.exercise_available_updates()
        assert any(row.outcome=='rejected' and 'model_falsified' in row.reasons for row in r.host.window.status().updates)
        return
    r.update()
    if initial:assert r.query('mass').exact==1
    else:
        fine=r.query('mass',tolerance=Q(1,2**200));assert fine.lower>0
        j,z,_=point_joint(base=(R,R),before=Q(1),after=Q(1),symbol=T);check_point(r,j,z)
    assert r.sq('switch',on=('clock',)).lower>0


def test_clock1_incomplete_query_keeps_root_and_more_budget_refines_the_same_belief(clocks):
    r=clocks(script((1,1,E)),clock=clock_prior(phase=None),unit=Q(1,2)).start();r.observe(0);expression=r.update()
    quantity=fb.BeliefQuantity(kind='mass')
    small=RateBudget(tolerance=Q(1,2**80),max_cells=1,max_terms=None,max_refinements=1)
    try:
        value=r.host.query_belief(belief=expression,quantity=quantity,budget=small)
    except fb.TimeBeliefError as error:
        assert error.kind=='incomplete' and error.reason
    else:
        # No algorithm-independent lower work bound is specified by the paper.
        assert value.upper-value.lower<=small.tolerance
        assert r.host.verify_belief_value(belief=expression,value=value)
    coarse=r.query('mass',tolerance=Q(1,128));fine=r.query('mass',tolerance=Q(1,8192))
    assert fine.upper-fine.lower<=coarse.upper-coarse.lower
    assert r.expression().root==expression.root
    expected=plus(times(rat(Q(1,2)),expneg(Q(1,2))),
        times(rat(Q(1,2)),times(expneg(Q(1,4)),times(rat(2),minus(rat(1),expneg(Q(1,2)))))))
    assert_contains(fine,expected)
    assert not any('model_falsified' in row.reasons for row in r.host.window.status().updates)


@pytest.mark.parametrize('bad',[
    'm-one','T-zero','T-negative','T-weights','m-weights','phase-outside',
    'width-zero','width-sum','fraction-zero','fraction-sum','kappa-width-zero','kappa-fraction-negative',
    'two-clocks','clock-reads-S','couple-T-m','couple-phase-width','couple-z-clock',
])
def test_clock1_invalid_or_unsupported_clock_declarations_are_named_before_use(clocks,bad,record_property):
    clock_api();cp=clock_prior()
    kind='unsupported' if bad.startswith('couple-') or bad in ('two-clocks','clock-reads-S') else 'invalid'
    with pytest.raises(fb.TimeBeliefError) as error:
        if bad=='m-one':
            # Only m=1 is illegal: keep the maximum legal and supply matching
            # one-component simplexes, not the default two-component shape.
            cp=replace(cp,max_segments=2,segments=((1,Q(1)),),
                widths=point(((1,(Q(1),)),)),fractions=point(((1,(Q(1),)),)))
        elif bad=='T-zero':cp=replace(cp,periods=((Q(0),Q(1)),))
        elif bad=='T-negative':cp=replace(cp,periods=((Q(-1),Q(1)),))
        elif bad=='T-weights':cp=replace(cp,periods=((Q(1),Q(2)),))
        elif bad=='m-weights':cp=replace(cp,segments=((2,Q(1,2)),))
        elif bad=='phase-outside':cp=replace(cp,phase={'kind':'point','value':Q(1)})
        elif bad=='width-zero':cp=replace(cp,widths=point(((2,(Q(0),Q(1))),)))
        elif bad=='width-sum':cp=replace(cp,widths=point(((2,(Q(1,2),Q(1,3))),)))
        elif bad=='fraction-zero':cp=replace(cp,fractions=point(((2,(Q(1),Q(0))),)))
        elif bad=='fraction-sum':cp=replace(cp,fractions=point(((2,(Q(1,4),Q(1,4))),)))
        elif bad=='kappa-width-zero':cp=replace(cp,widths={'kind':'symmetric_dirichlet','concentration':Q(0)})
        elif bad=='kappa-fraction-negative':cp=replace(cp,fractions={'kind':'conditional_dirichlet','concentration':Q(-1)})
        elif bad.startswith('couple-'):
            pair={'couple-T-m':('period','segments'),'couple-phase-width':('phase','widths'),'couple-z-clock':('switch','phase')}[bad]
            cp=replace(cp,couplings=(pair,))
        r=clocks(script((1,1,E)),clock=cp)
        declaration=r.boot_input.declaration;obs=declaration.observation_models[0]
        if bad=='two-clocks':law=replace(obs.value.law,parts=(*obs.value.law.parts,replace(obs.value.law.parts[0],id='clock-2')))
        elif bad=='clock-reads-S':law=replace(obs.value.law,parts=(replace(obs.value.law.parts[0],multipliers=(Q(1),Q(2))),))
        else:law=obs.value.law
        r.boot_input=replace(r.boot_input,declaration=replace(declaration,observation_models=(replace(obs,value=replace(obs.value,law=law)),)))
        r.start()
        reader=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in r.snapshot()})
        fb.resolve_belief_candidates(r.boot(),reader=reader,registry=r.registry)
    assert error.value.kind==kind and error.value.reason and error.value.targets
    assert {'clock','clock-2', 'family'} & set(error.value.targets)
    if bad=='m-one':
        record_property('named_refusal_reason',error.value.reason)
        record_property('named_refusal_targets',json.dumps(list(error.value.targets)))


def test_clock1_two_segments_with_neutral_shape_is_a_valid_control_for_m_one(clocks):
    # A constant point shape is allowed with two segments (the no-effect
    # reduction); it must not mask the specific lower bound on segment count.
    cp=clock_prior(m=2,max_segments=2,widths=(Q(1,2),)*2,fractions=(Q(1,2),)*2)
    r=clocks(script((1,1,E)),clock=cp).start()
    reader=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in r.snapshot()})
    resolved=fb.resolve_belief_candidates(r.boot(),reader=reader,registry=r.registry)
    assert isinstance(resolved,fb.ResolvedBeliefPool)


def phase_allocation(lo,hi,phase=Q(0),widths=(Q(1,2),Q(1,2)),fractions=(Q(3,4),Q(1,4))):
    a=hazard(lo,Q(1),phase,widths,fractions)
    b=hazard(hi,Q(1),phase,widths,fractions)
    return b-a if lo<=hi else Q(1)-a+b


def beta_laplace(alpha,beta,R,terms=32):
    """E[exp(-R X)], X~Beta(alpha,beta), 0<=R<=1.

    Exact beta moments and the alternating exponential series. Consecutive
    partial sums enclose the integral; no Gamma/Beta implementation is called.
    """
    assert alpha>0 and beta>0 and 0<=R<=1
    term=Q(1);s=Q(1)
    for j in range(1,terms+1):
        term*=-R*(alpha+j-1)/(j*(alpha+beta+j-1));s+=term
    next_term=term*(-R)*(alpha+terms)/((terms+1)*(alpha+beta+terms))
    return Bounds(min(s,s+next_term),max(s,s+next_term))


def unnormalized_entropy(A,B):
    """Entropy mass of the two outcome cells A,B; both are strictly positive."""
    W=plus(A,B)
    return minus(minus(times(W,logarithm(W)),times(A,logarithm(A))),times(B,logarithm(B)))


def rotation_weights():
    # S=A/B with rates 1/2; clock prior 1/2; all original targets identical.
    weights={}
    for s,R in enumerate((Q(1),Q(2))):
        weights[(0,),s]=times(rat(Q(1,4)),expneg(R/2))
        integrated=times(expneg(R/4),divide(times(rat(2),minus(rat(1),expneg(R/2))),rat(R)))
        weights[(1,),s]=times(rat(Q(1,4)),integrated)
    Z=total(weights.values())
    return weights,Z


@lru_cache(maxsize=32)
def continuous_information_reference(n=64):
    """Independent 1-D certified integral for I(Q;Y), NOT I(z;Y).

    For uniform rotation, x=integrated clock intensity over the half-period is
    uniform on [1/4,3/4]. On this branch A(x)=1/2 exp(-x)+1/4 exp(-2x),
    B(x)=1/4 exp(-2x), including prior density. Integrate
    g=(A+B)log(A+B)-Alog(A)-Blog(B). The other branch is a single Q atom.
    On this interval W,A>=1/4 and B>=1/32; |log|<4. Their derivative bounds
    (orders1..4) are W:(3/2,5/2,9/2,17/2), A:(1,3/2,5/2,9/2), B:(1/2,1,2,4).
    Differentiating x log x four times bounds |g''''| by 7634 < 16384.
    Composite Simpson remainder <= (1/2)*h^4*16384/180.
    """
    assert n%2==0
    h=Q(1,2*n);low=high=Q(0)
    for j in range(n+1):
        x=Q(1,4)+j*h
        A=plus(times(rat(Q(1,2)),expneg(x)),times(rat(Q(1,4)),expneg(2*x)))
        B=times(rat(Q(1,4)),expneg(2*x))
        lo,hi=enclose(unnormalized_entropy(A,B),32)
        k=1 if j in (0,n) else 4 if j%2 else 2
        low+=k*lo;high+=k*hi
    rem=Q(1,2)*h**4*16384/180
    integral=Bounds(low*h/3-rem,high*h/3+rem)
    weights,Z=rotation_weights()
    YA=total(weights[bits,0] for bits in ((0,),(1,)))
    YB=total(weights[bits,1] for bits in ((0,),(1,)))
    HT=divide(unnormalized_entropy(plus(YA,times(rat(Q(1,2)),YB)),times(rat(Q(1,2)),YB)),Z)
    offA=plus(weights[(0,),0],times(rat(Q(1,2)),weights[(0,),1]))
    offB=times(rat(Q(1,2)),weights[(0,),1])
    h0,h1=enclose(HT,32);o0,o1=enclose(unnormalized_entropy(offA,offB),32);z0,z1=enclose(Z,32)
    return Bounds(h0-(o1+integral.upper)/z0,h1-(o0+integral.lower)/z1)


def assert_continuous_information(value):
    # Stored mathematical bounds may be tighter than a requested projection.
    # Refine the independent Simpson ruler instead of accepting mere overlap.
    for n in (32,64,128,256,512,1024):
        reference=continuous_information_reference(n)
        assert not (reference.upper<value.lower or value.upper<reference.lower)
        if value.lower<=reference.lower<=reference.upper<=value.upper:return
    pytest.fail('certified information reference could not separate interval endpoints')


def test_clock1_v6_independent_integral_and_beta_product_rulers():
    # Dirichlet(1/2,1/2,1/2) gives a Beta(1/2,1) marginal.
    ref=beta_laplace(Q(1,2),Q(1),Q(1))
    expected=sum(((-Q(1))**j)/(rising(Q(1),j)*(2*j+1)) for j in range(34))
    assert ref.lower<=expected<=ref.upper and ref.upper-ref.lower<Q(1,2**100)
    # The last Beta factor is at j=m-1, never B(alpha_m,0).
    alpha=(Q(1,2),Q(1,2),Q(1,2))
    assert len([(alpha[j],sum(alpha[j+1:])) for j in range(len(alpha)-1)])==2
    exact=continuous_information_reference(64)
    weights,Z=rotation_weights();joint={key:divide(w,Z) for key,w in weights.items()}
    collapsed,_=information(joint,{(0,):0,(1,):1},('same','same'))
    assert exact.lower>enclose(collapsed,32)[1]
    assert continuous_information_reference(128).upper-continuous_information_reference(128).lower<exact.upper-exact.lower
    # A partition label is not extra evidence or extra knowledge.
    for lo,hi,answer in [(Q(0),Q(1,4),Q(3,8)),(Q(3,4),Q(1,4),Q(1,2)),(Q(1,3),Q(1,3),Q(0))]:
        assert phase_allocation(lo,hi)==answer


@pytest.mark.parametrize('m,kappa,widths',[
    (2,Q(1),(Q(1,2),Q(1,2))),
    (3,Q(3,2),(Q(1,3),Q(1,3),Q(1,3))),
    (3,Q(3,2),(Q(1,6),Q(1,3),Q(1,2))),
    # Smooth Dirichlet(1,1,1): two Beta factors, with a small polynomial
    # density. The fractional boundary examples above remain strict too.
    pytest.param(3,Q(3),(Q(1,3),)*3,id='smooth-m3'),
])
def test_clock1_v6_Dirichlet_normalization_has_m_minus_one_Beta_factors_and_keeps_boundary_mass(clocks,m,kappa,widths,record_property):
    cp=clock_prior(m=m,widths=widths,
        fractions={'kind':'conditional_dirichlet','concentration':kappa})
    r=clocks(script((1,1,E)),clock=cp,unit=widths[0]).start();r.observe(0);r.update()
    observed=certified_belief_query(r,'mass',tolerance=Q(1,16))
    # By the first segment endpoint H=f1. The fractional alpha<1 makes
    # endpoint mass material; deleting an uncomputed boundary loses evidence.
    ref=beta_laplace(kappa*widths[0],kappa*(1-widths[0]),Q(1),48)
    assert_bounds_include(observed,clock_mixture_reference(ref,Q(1),widths[0]))
    record_property('numerical_ruler_comparisons',1)


@pytest.mark.parametrize('alpha',[Q(1,3),Q(5,2)],ids=['one-third','five-halves'])
def test_clock1_noninteger_Dirichlet_remainder_is_enclosed_by_independent_moment_ruler(clocks,alpha,record_property):
    # w=(1/2,1/2), kappa_f=2*alpha gives f1~Beta(alpha,alpha).
    # At the first segment endpoint H=f1, while clock-off has H=1/2.
    cp=clock_prior(widths=(Q(1,2),)*2,
        fractions={'kind':'conditional_dirichlet','concentration':2*alpha})
    r=clocks(script((1,1,E)),clock=cp,unit=Q(1,2),base=(Q(1),)*2).start()
    r.observe(0);expression=r.update()
    # Independent alternating exponential series in exact Beta moments. This
    # does not call the production Beta integral or borrow its error estimate.
    L=beta_laplace(alpha,alpha,Q(1),64)
    Z=clock_mixture_reference(L,Q(1),Q(1,2))
    assert Z.lower>0 and Z.upper-Z.lower<Q(1,2**160)
    limits=RateBudget(tolerance=Q(1,2**8),max_cells=16384,max_terms=256,max_refinements=20)
    quantity=fb.BeliefQuantity(kind='mass')
    value=certified_clock_call(r,lambda:r.host.query_belief(
        belief=expression,quantity=quantity,budget=limits),limits)
    assert value.root==expression.root and value.quantity==quantity
    assert value.upper-value.lower<=limits.tolerance
    assert r.host.verify_belief_value(belief=expression,value=value)
    assert_bounds_include(value,Z)
    record_property('numerical_ruler_comparisons',1)


@pytest.mark.parametrize('on,off',[((),()),(('clock',),()),((),('clock',))])
def test_clock1_v6_parameter_events_keep_Z_M_denominator_even_when_clock_is_off(clocks,on,off):
    cp=clock_prior(periods=((Q(1),Q(1,3)),(Q(2),Q(2,3))),m=3,max_segments=3,
        segments=((2,Q(1,4)),(3,Q(3,4))),
        widths=point(((2,(Q(1,2),)*2),(3,(Q(1,3),)*3))),
        fractions=point(((2,(Q(3,4),Q(1,4))),(3,(Q(1,2),Q(1,3),Q(1,6))))))
    r=clocks(script((1,1,E)),clock=cp,unit=Q(1,2)).start();r.observe(0);r.update()
    weights={}
    for period,pT in cp.periods:
        for m,pm in cp.segments:
            w=dict(cp.widths['values'])[m];f0=dict(cp.fractions['values'])[m]
            for bit in (0,1):
                weights[period,m,bit]=times(rat(pT*pm/2),piece_empty(Q(1),Q(1,2),Q(1,2),T=period,widths=w,fractions=f0 if bit else w))
    Z=total(weights.values());actual=[]
    for period,pT in cp.periods:
        for m,pm in cp.segments:
            num=total(v for (tv,mv,bit),v in weights.items()
                if tv==period and mv==m and (not on or bit) and (not off or not bit))
            result=r.cq('parameters',periods=(period,),segments=(m,),on=on,off=off,tolerance=Q(1,2**24))
            assert_contains(result,divide(num,Z));actual.append(result)
    bit=r.sq('switch',on=on,off=off)
    assert sum(v.lower for v in actual)<=bit.upper and sum(v.upper for v in actual)>=bit.lower
    if off:
        # Clock-off's T and m are real latent events, with their declared prior.
        value=r.cq('parameters',periods=(Q(1),),segments=(2,),off=('clock',))
        assert_contains(value,times(rat(Q(1,12)),divide(total(v for (tv,mv,b),v in weights.items() if not b),Z)))


@pytest.mark.parametrize('ticks',[0,1])
@pytest.mark.parametrize('lo,hi',[(Q(0),Q(1,4)),(Q(1,2),Q(3,4)),
    (Q(3,4),Q(1,4)),(Q(1,3),Q(1,3)),(Q(1,2),Q(0))])
def test_clock1_v6_effective_allocation_includes_off_branch_and_wraps_left_closed_interval(clocks,ticks,lo,hi):
    r=clocks(script((ticks,ticks,E)),unit=Q(1,4)).start();r.observe(0);r.update()
    length=(hi-lo)%1;enabled=phase_allocation(lo,hi)
    L0,L1=expneg(Q(ticks,4)),expneg(Q(3*ticks,8))
    expected=rat(length) if enabled==length else divide(plus(times(rat(length),L0),times(rat(enabled),L1)),plus(L0,L1))
    value=r.cq('allocation',lower=lo,upper=hi,tolerance=Q(1,2**24))
    assert_contains(value,expected)
    assert 0<=value.lower<=value.upper<=1


@pytest.mark.parametrize('ticks',[0,1])
def test_clock1_wrapped_allocation_uses_complement_length_with_positive_off_mass(clocks,ticks):
    lo,hi=Q(5,6),Q(1,6)
    cp=clock_prior(phase=Q(0),widths=(Q(1,2),)*2,fractions=(Q(3,4),Q(1,4)))
    r=clocks(script((ticks,ticks,E)),clock=cp,unit=Q(1,4)).start()
    r.observe(0);r.update()
    assert r.sq('switch',off=('clock',),tolerance=Q(1,4096)).lower>0
    # Off: 1/3. On: (1/6)*(1/2)+(1/6)*(3/2)=1/3 too.
    # A wrong off length lo-hi=2/3 therefore changes the mixture.
    assert 1-lo+hi==Q(1,3) and lo-hi==Q(2,3)
    value=r.cq('allocation',lower=lo,upper=hi,tolerance=Q(1,2**24))
    assert_contains(value,rat(Q(1,3)))
    L0,L1=expneg(Q(ticks,4)),expneg(Q(3*ticks,8))
    wrong=divide(plus(times(rat(Q(2,3)),L0),times(rat(Q(1,3)),L1)),plus(L0,L1))
    assert value.upper<enclose(wrong,64)[0]


def test_clock1_v6_query_conditions_on_candidate_not_pool_or_clock_on(clocks):
    cp=clock_prior(periods=((Q(1),Q(1,3)),(Q(2),Q(2,3))))
    r=clocks(script((2,2,E)),clock=cp).start();r.observe(0);r.update()
    r.add_time_candidate(law=r.law(),alpha=Q(1,4));r.update()
    assert r.query('candidate',candidate='later').exact==Q(1,4)
    assert_contains(r.cq('parameters',candidate='later',periods=(Q(1),),on=('clock',)),rat(Q(1,6)))
    assert_contains(r.cq('allocation',candidate='later',lower=Q(0),upper=Q(1,4)),rat(Q(5,16)))


@pytest.mark.parametrize('kind',['parameters','allocation'])
def test_clock1_v6_zero_candidate_evidence_is_named_not_given_a_conditional_clock_value(clocks,kind):
    r=clocks(script((1,1,T))).start();r.observe(0);r.update()
    r.add_time_candidate(law=r.law(rates=(Q(0),Q(0))));r.update()
    assert r.query('candidate',candidate='later').exact==0
    event={} if kind=='parameters' else {'lower':Q(0),'upper':Q(1,2)}
    with pytest.raises(fb.TimeBeliefError) as error:r.cq(kind,candidate='later',**event)
    assert error.value.reason and 'later' in error.value.targets


@pytest.mark.parametrize('event',[
    {'kind':'phase','lower':Q(0),'upper':Q(1,2)},
    {'kind':'width','index':0,'lower':Q(0),'upper':Q(1,2)},
    {'kind':'fraction','index':0,'lower':Q(0),'upper':Q(1,2)},
    {'kind':'allocation','lower':Q(0),'upper':Q(1,2),'condition_on':('clock',)},
    {'kind':'parameters','condition_on':('clock',)},
    {'kind':'parameters','condition_off':('clock',)},
])
def test_clock1_v6_regions_and_denominator_switch_conditions_are_unsupported(clocks,event):
    r=clocks(script((0,0,E))).start();r.observe(0);r.update()
    with pytest.raises(fb.TimeBeliefError) as error:r.cq(**event)
    assert error.value.kind=='unsupported' and error.value.reason and error.value.targets


@pytest.mark.parametrize('event',[
    {'kind':'parameters','periods':(Q(3),)},
    {'kind':'parameters','segments':(3,)},
    {'kind':'allocation','lower':Q(-1,4),'upper':Q(1,2)},
    {'kind':'allocation','lower':Q(0),'upper':Q(1)},
])
def test_clock1_v6_unknown_period_m_or_invalid_phase_endpoints_are_invalid_queries(clocks,event):
    r=clocks(script((0,0,E))).start();r.observe(0);r.update()
    with pytest.raises(fb.TimeBeliefError) as error:r.cq(**event)
    assert error.value.kind=='invalid' and error.value.reason
    assert error.value.targets or error.value.field


@pytest.mark.parametrize('event',[{'periods':()},{'segments':()},{'periods':(),'segments':()}])
def test_clock1_v6_empty_parameter_subset_is_zero_not_all_candidates(clocks,event):
    r=clocks(script((0,0,E))).start();r.observe(0);r.update()
    assert r.cq('parameters',**event).exact==0


def test_clock1_v6_continuous_information_keeps_theta_and_does_not_count_integration_boxes_as_states(clocks):
    r=clocks(script((1,1,E)),clock=clock_prior(phase=None),base=(Q(1),Q(2)),
        unit=Q(1,2),same_targets=True,thinking=True).start()
    r.observe(0);expression=r.update();selection=r.think()
    widths=[]
    for tol in (Q(1,2**14),Q(1,2**18)):
        values=r.host.query_selection(selection=selection.cid,budget=budget(tol))
        assert values.belief_root==expression.root
        for i,name in enumerate(values.candidates):
            if name=='peek':
                assert_continuous_information(values.information[i]);widths.append(values.information[i].upper-values.information[i].lower)
                negative=Bounds(-values.G[i].upper,-values.G[i].lower)
                assert_continuous_information(negative)
            else:assert_contains(values.information[i],rat(0))
        assert all(v.upper-v.lower<=tol for v in values.information)
    assert widths[-1]<=widths[0]
    assert r.expression().root==expression.root


class ClockMathSnapshotReader(f.FReader):
    """Freeze all five public reader ports, including authenticated content."""
    def __init__(self,rig):
        points=tuple(rig.snapshot())
        self.fixed_entries=tuple(rig.ledger.entries())
        self.by_point={p:rig.ledger.entry(p) for p in points}
        self.records={p:rig.read_stored(p)[2] for p in points}
        self.contents={p:rig.contents.get(self.by_point[p].seal) for p in points}
        self.closures={p:rig.ledger.ancestors((p,)) for p in points}
    def entry(self,point):return self.by_point[point]
    def entries(self):return self.fixed_entries
    def record(self,point):return self.records[point]
    def sealed_content(self,point):return self.contents[point]
    def ancestors(self,frontier):
        return frozenset().union(*(self.closures[p] for p in frontier))


def integral_math(r):
    selection=r.think();evaluation=r.selected_value(selection).evaluation
    i=evaluation.candidates.index('peek')
    exact=evaluation.information[i].additional.exact
    assert isinstance(exact,f.ExactReal)
    return evaluation,exact,ClockMathSnapshotReader(r)


def test_clock1_v6_integral_exact_expression_is_versioned_json_and_replays_from_a_fixed_reader(clocks):
    r=clocks(script((1,1,E)),clock=clock_prior(phase=None),base=(Q(1),Q(2)),
        unit=Q(1,2),same_targets=True,thinking=True).start()
    r.observe(0);expression=r.update();evaluation,exact,reader=integral_math(r)
    data=fe.f_json(exact);decoded=fe.f_from_json(data,contract=fc.VALUE_FACTS)
    assert isinstance(decoded,f.ExactReal) and fe.f_json(decoded)==data
    tree=json.loads(data);new_nodes=[]
    def walk(value):
        if isinstance(value,dict):
            if 'op' in value and value['op'] not in ('rational','log','exp','add','mul','neg','div'):new_nodes.append(value)
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(tree);assert new_nodes, 'continuous integral cannot be replaced by finite numeric weights'
    text=json.dumps(new_nodes,sort_keys=True)
    assert 'version' in text and 'name' in text
    assert any(str(p) in text for p in (expression.result,expression.model,*expression.observations))
    # selected_value above decodes a DTO; E-05 does not grant it issuance.
    # Replay the native worker's complete saved artifact through the public
    # factory, then serialize that issued handle (not the decoded evaluation).
    evaluated,=r.facts(c.EVALUATED)
    saved=next(x for x in r.facts(fc.MATH_ARTIFACT_V2) if x.cid==evaluated.value['artifact'])
    math=json.dumps(saved.value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    restored=ff.restore_f_math_result(math,reader=reader,registry=r.registry,budget=budget(Q(1,2**18)))
    assert isinstance(restored,f.FMathArtifact) and restored.canonical_bytes==math
    assert ff.f_math_json(restored)==math
    assert isinstance(restored.value,f.Selected)
    replayed=restored.value.evaluation
    index=replayed.candidates.index('peek')
    assert fe.f_json(replayed.information[index].additional.exact)==data
    assert_continuous_information(replayed.information[index].additional.bounds)


@pytest.mark.parametrize('case',['structural-zero','structural-positive','identity','separated','limited-unproved'])
def test_clock1_v6_integral_comparison_distinguishes_proofs_from_budgeted_unproved(clocks,case):
    r=clocks(script((1,1,E)),clock=clock_prior(phase=None),base=(Q(1),Q(2)),
        unit=Q(1,2),same_targets=True,thinking=True).start()
    r.observe(0);r.update();_evaluation,I,reader=integral_math(r)
    missing=[name for name in ('compare_exact','ExactComparison') if not hasattr(f,name)]
    assert not missing,'K40 public shape missing: '+', '.join('f.'+x for x in missing)
    zero=f.ExactReal(op='rational',value=Q(0));left=I;right=zero;expected=1
    limits=budget(Q(1,2**18))
    if case=='structural-zero':left=f.ExactReal(op='mul',args=(zero,I));expected=0
    elif case=='structural-positive':left=f.ExactReal(op='exp',arg=I)
    elif case=='identity':right=fe.f_from_json(fe.f_json(I),contract=fc.VALUE_FACTS);expected=0
    else:
        # A known strict inequality, without giving the implementation our proof.
        reference=continuous_information_reference(128)
        right=f.ExactReal(op='rational',value=reference.lower/2)
        if case=='limited-unproved':limits=RateBudget(tolerance=Q(1,2**160),max_cells=1,max_terms=1,max_refinements=1)
    # Supplying these public dependencies does not require their consumption
    # for an expression already resolved by value. Replay is tested separately.
    answer=f.compare_exact(left,right,reader=reader,registry=r.registry,budget=limits)
    assert isinstance(answer,f.ExactComparison)
    assert answer.kind in ('structural','identity','separated','unproved')
    if answer.kind=='unproved':
        assert case=='limited-unproved' and answer.order is None and answer.proof is None
    else:
        assert answer.order==expected and answer.proof is not None
        if case.startswith('structural'):assert answer.kind=='structural'
        if case=='identity':assert answer.kind=='identity'

