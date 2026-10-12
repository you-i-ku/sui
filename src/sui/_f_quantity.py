"""Quantity issuance and cheap predicate checks; no numerical refinement here."""
from dataclasses import replace
from types import MappingProxyType
from . import f

_ISSUED = {}
_FACTS_ISSUED = {}


def _consistent(q):
    if type(q) is not f.FQuantity:
        raise f.FInputError('quantity_inconsistent')
    if q.status not in ('finite','positive_infinity','uncertified'):
        raise f.FInputError('quantity_inconsistent')
    if q.exact is not None:
        try:
            f._decode(f._encode(q.exact),f.ExactReal)
        except f.FInputError as exc:
            raise f.FInputError('quantity_inconsistent',exc.detail) from exc
    if q.bounds is not None:
        if type(q.bounds) is not f.RationalInterval or type(q.bounds.lower) is not f._Fraction or type(q.bounds.upper) is not f._Fraction:
            raise f.FInputError('quantity_inconsistent')
        if q.bounds.lower > q.bounds.upper or q.status != 'finite':
            raise f.FInputError('quantity_inconsistent')
        if q.exact is not None and q.exact.op == 'rational' and not q.bounds.lower <= q.exact.value <= q.bounds.upper:
            raise f.FInputError('quantity_inconsistent', 'rational exact is outside bounds')
    if q.status == 'finite' and (q.reason is not None or q.bounds is None):
        raise f.FInputError('quantity_inconsistent')
    if q.status != 'finite' and q.exact is not None:
        raise f.FInputError('quantity_inconsistent')
    if q.status == 'uncertified' and q.reason is None or q.status == 'positive_infinity' and q.reason is not None:
        raise f.FInputError('quantity_inconsistent')


def _declared_binding(ref,q):
    if q.proof is None or q.proof.name != 'sui.f.quantity':
        return
    try:
        if q.proof.version == '2':
            f._keys(q.proof.args,('binding',))
            binding=f._decode(q.proof.args['binding'],f.FQuantityFactsBinding)
            key=f._digest({'domain':'sui.f.quantity_point/1','declaration':binding.declaration,
                'record_digest':binding.record_digest})
            definition=binding.definition
            unit=definition.unit if definition.kind=='rational_constant' else ('dimensionless' if definition.field in ('q_star','Z') else 'nat')
            if ref.key!=key or unit!=binding.unit:
                raise f.FInputError('quantity_binding_conflict')
            if definition.kind=='rational_constant' and (q.exact!=f._r(definition.value) or q.bounds!=f.RationalInterval(definition.value,definition.value)):
                raise f.FInputError('quantity_binding_conflict')
            return
        if q.proof.version != '1':
            raise f.FInputError('quantity_binding_conflict')
        f._keys(q.proof.args,('definition','unit'))
        definition = f._decode(q.proof.args['definition'],f.FQuantityDefinition)
        unit = definition.unit if definition.kind == 'rational_constant' else ('dimensionless' if definition.field in ('q_star','Z') else 'nat')
        if ref.key != f._digest(definition) or unit != q.proof.args['unit']:
            raise f.FInputError('quantity_binding_conflict')
        if definition.kind == 'rational_constant' and (q.exact != f._r(definition.value) or q.bounds != f.RationalInterval(definition.value,definition.value)):
            raise f.FInputError('quantity_binding_conflict')
    except f.FInputError as exc:
        raise f.FInputError('quantity_binding_conflict',exc.detail) from exc


def certify(*, definition, evaluation, resources):
    f._require(resources,f.FResources)
    definition = f._decode(f._encode(definition),f.FQuantityDefinition)
    ref = f.QuantityRef(key=f._digest(definition))
    if definition.kind == 'rational_constant':
        if evaluation is not None:
            raise f.FInputError('quantity_binding_conflict')
        available = {r.id for r in resources.records}
        if not set(definition.provenance) <= available:
            raise f.FReplayUnavailable('missing_input')
        from ._f_identity import resource_bindings
        resource_bindings(resources,definition.provenance)
        q = f.FQuantity(status='finite',exact=f._r(definition.value),
            bounds=f.RationalInterval(definition.value,definition.value),proof=None,reason=None)
        unit, root = definition.unit, None
    else:
        from ._f_eval import _validate_evaluation
        if evaluation is None:
            raise f.FInputError('quantity_binding_conflict')
        _validate_evaluation(evaluation)
        root = evaluation.root
        if root.root_key != definition.root_key:
            raise f.FInputError('quantity_binding_conflict','different root')
        unit = 'dimensionless' if definition.field in ('q_star','Z') else 'nat'
        if definition.field == 'Z':
            if definition.candidate is not None:
                raise f.FInputError('quantity_binding_conflict','Z has no candidate')
            z = evaluation.normalization.Z
            q = f.FQuantity(status='finite',exact=None,bounds=z,proof=None,reason=None)
        else:
            if definition.candidate not in evaluation.candidates:
                raise f.FInputError('quantity_binding_conflict','canonical candidate required')
            i = evaluation.candidates.index(definition.candidate)
            if definition.field in ('already_received','additional','total_information'):
                q = getattr(evaluation.information[i],definition.field)
            else:
                q = getattr(evaluation,definition.field)[i]
    _consistent(q)
    q = replace(q,proof=f.ProofRef(name='sui.f.quantity',version='1',args={
        'definition':f._encode(definition),'unit':unit}))
    _ISSUED[id(q)] = (q,f._digest(q),ref,definition,unit,root)
    return ref,q


def certify_facts(*,binding,evaluation,resources,snapshot):
    """Reuse the quantity mathematics, bind its guarantee to primary CID bytes."""
    _,q=certify(definition=binding.definition,evaluation=evaluation,resources=resources)
    ref=f.QuantityRef(key=f._digest({'domain':'sui.f.quantity_point/1','declaration':binding.declaration,
        'record_digest':binding.record_digest}))
    q=replace(q,proof=f.ProofRef(name='sui.f.quantity',version='2',args={'binding':f._encode(binding)}))
    root=None if evaluation is None else evaluation.root
    _ISSUED[id(q)]=(q,f._digest(q),ref,binding.definition,binding.unit,root)
    _FACTS_ISSUED[id(q)]=(snapshot.model_ref,snapshot.E,snapshot.K,f._digest(resources.records))
    return ref,q


def checked_resources(snapshot,resources):
    """Cached checks cannot transfer an issued quantity to a foreign fact closure."""
    for q in snapshot.quantities.values():
        expected=_FACTS_ISSUED.get(id(q))
        if expected is not None and expected!=(snapshot.model_ref,snapshot.E,snapshot.K,f._digest(resources.records)):
            raise f.FInputError('quantity_binding_conflict','different cached facts')


def checked_snapshot(snapshot):
    if type(snapshot) is not f.PredicateSnapshot:
        raise f.FInputError('shape', 'PredicateSnapshot required', '/snapshot')
    if not isinstance(snapshot.quantities, f._Mapping):
        raise f.FInputError('shape', 'Mapping required', '/quantities')
    for ref,q in snapshot.quantities.items():
        _consistent(q)
        _declared_binding(ref,q)
        old = _ISSUED.get(id(q))
        if old is not None and (old[0] is not q or old[1] != f._digest(q) or old[2] != ref):
            raise f.FInputError('quantity_binding_conflict')
    normalized = f._decode(f._encode(snapshot),f.PredicateSnapshot)
    # Preserve only live authentication across DTO normalization.
    quantities = {ref:(q if id(q) in _ISSUED else normalized.quantities[ref]) for ref,q in snapshot.quantities.items()}
    return replace(normalized,quantities=MappingProxyType(quantities))


def readable_quantity(ref,snapshot):
    q = snapshot.quantities.get(ref)
    if q is None:
        return None
    _consistent(q)
    old = _ISSUED.get(id(q))
    if old is None:
        return None
    _,digest,expected,definition,unit,root = old
    if expected != ref or digest != f._digest(q):
        raise f.FInputError('quantity_binding_conflict')
    facts=_FACTS_ISSUED.get(id(q))
    if facts is not None and facts[:3]!=(snapshot.model_ref,snapshot.E,snapshot.K):
        raise f.FInputError('quantity_binding_conflict','different cached histories')
    if root is not None:
        from ._f_handles import world_state
        world_state(root)
        if snapshot.model_ref != root.model_ref or snapshot.E != root.E or snapshot.K != root.K:
            raise f.FInputError('quantity_binding_conflict','quantity is for different E/K')
    return q,unit
