"""Issued-world gate shared by mathematics and factories. No input resolution."""

from .f import FCertifiedWorld, FProblem, FRoot, FInputError, FReplayMismatch, _require, _digest
from contextlib import contextmanager
from contextvars import ContextVar

_ISSUED = {}

# Mathematical provenance is held by the issuer, never recovered from a DTO.
_MATH = {}
_VERIFY_WORK = ContextVar('sui_f_verification_work', default=None)


class VerificationBudgetExceeded(Exception):
    """Separate from mathematical FIncomplete, so it cannot become a claim."""


@contextmanager
def verification_budget(budget):
    token=_VERIFY_WORK.set({'budget':budget,'cells':0,'terms':0,'refinements':0})
    try:
        yield
    finally:
        _VERIFY_WORK.reset(token)


def charge_verification(kind='cells',count=1):
    work=_VERIFY_WORK.get()
    if work is not None:
        work[kind]+=count
        if work[kind]>getattr(work['budget'],'max_'+kind):
            raise VerificationBudgetExceeded(kind)


def has_math(value):
    old=_MATH.get(id(value))
    return old is not None and old[0] is value


def _issued_digest(value):
    from .f import FMathArtifact, _digest
    if type(value) is FMathArtifact:
        return _digest({'value':value.value,'bytes':value.canonical_bytes,
            'reader':value.reader.view_key})
    return _digest(value)


def seed_math(value, source):
    _MATH[id(value)] = (value, _digest(value), source)
    return value


def math_source(value):
    old = _MATH.get(id(value))
    if old is None or old[0] is not value:
        raise FInputError('shape', 'issued mathematical provenance required')
    if old[1] != _digest(value):
        raise FReplayMismatch('result_mismatch',fields=('/claim',))
    return old[2]


def trace_math(value, op, *, inputs, args):
    """Keep the call graph only for outputs descended from a facts factory."""
    if all(id(v) in _MATH and _MATH[id(v)][0] is v for v in inputs.values()):
        sources = {name:math_source(v) for name,v in inputs.items()}
        node={'op':op,'args':args,'inputs':sources,'value':value}
        seed_math(value,node)
        if getattr(value,'resume',None) is not None:
            seed_math(value.resume,node)
    return value


def issue(value):
    _ISSUED[id(value)] = (value, _issued_digest(value), _require(value, type(value)))
    return value


def require_issued(value, cls):
    authority = _require(value, cls)
    old = _ISSUED.get(id(value))
    if old is None or old[0] is not value or old[1] != _issued_digest(value) or old[2] is not authority:
        raise FReplayMismatch("result_mismatch", "issued content changed", fields=("/world",))
    return authority


def attached_world(value):
    if type(value) not in (FProblem, FRoot):
        raise FInputError("shape", "FProblem or FRoot required")
    world = require_issued(value, type(value))
    require_issued(world, FCertifiedWorld)
    if value.world_key != world.world_key or value.world_manifest != world.manifest:
        raise FReplayMismatch("result_mismatch", fields=("/world_key",))
    return world


def world_state(root):
    return require_issued(attached_world(root), FCertifiedWorld)
