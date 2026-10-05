"""Known-Q response-wait/1 mathematical ruler, separate from public branches.

The auxiliary wait/done flag is never an information target. Rates and B are
read from the declaration; the response uses the column of the state at that
instant, after any background changes while waiting.
"""
import numpy as np
from .action_types import ActionInputError,ActionIncomplete,ActionNumericalRange,rational_bounds
from .action_model import load_canonical,rational
from .inference import transition


def reconstruction_support(model):
    """Certify the known augmented generator, separately from branch support."""
    from .action_types import ActionSupport
    from .action_finite import scope
    d=load_canonical(model.declaration)
    for action,e in d['effects'].items():
        if e['family']['name']!='response-wait': continue
        if (e['B']['kind']!='known' or e['marks'] is not None or e['notice'] is not None
                or e['progress_start']!='dispatch'):
            raise ActionIncomplete(reason='algorithm_unavailable',detail='response reconstruction needs known B, no marks and dispatch-started work')
        ai=model.actions.index(action)
        if any(len(set(map(tuple,c[ai])))!=1 for c in d['completion']['candidates']):
            raise ActionIncomplete(reason='continuous_timing',detail='response-driven progress needs a continuous first-passage ruler')
    if d['arrivals']:
        raise ActionIncomplete(reason='arrival_scope',detail='response reconstruction has no arrival ruler')
    support=scope(model)
    if support.status!='certified': return support
    return ActionSupport(status='certified',stage='2',reason=None,method='known_response_wait_generator',
        conditions=support.conditions+('known_response_B','state_independent_work_speed'))


def _generator(model,action,mode):
    d=load_canonical(model.declaration)
    if action not in d['actions'] or mode not in d['activity']['modes']:
        raise ActionInputError(reason='shape',detail='unknown response action or mode')
    e=d['effects'][action]
    if e['family']['name']!='response-wait':
        raise ActionInputError(reason='shape',detail='response-wait/1 action required')
    if e['B']['kind']!='known':
        raise ActionIncomplete(reason='algorithm_unavailable',detail='unknown B in a response generator requires certified sufficient statistics')
    q=np.asarray(d['activity']['Q_by_mode'][mode],dtype=float); r=np.asarray(e['response_rate_s'],dtype=float)
    b=np.asarray([[rational_bounds(rational(x,'B')).lower for x in row] for row in e['B']['values']]); n=len(q)
    result=np.zeros((2*n,2*n))
    result[:n,:n]=q-np.diag(r)
    result[n:,:n]=b*r[None,:]
    result[n:,n:]=q
    return result


def _transition(model,action,mode,elapsed_s):
    generator=_generator(model,action,mode)
    try: return transition(generator,float(elapsed_s))
    except (ValueError,FloatingPointError,OverflowError) as exc:
        raise ActionNumericalRange(reason='invalid_interval',detail='response-wait exponential failed') from exc
