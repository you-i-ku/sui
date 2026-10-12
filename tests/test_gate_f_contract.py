"""Gate F mathematical/legacy contracts; F-b receipt/storage tests live in tests_fb.

Read gate_f_cases.py for the input assumptions and explicit construction gaps.
Assembly success means only constructors/raw records work, never certification.
Numerical expectations are fixed_gate_f.json or the specification. Decimal below
interprets a RETURNED ExactReal expression; it never generates expected values
from sui and is never supplied back to selection as a mathematical certificate.
Independent outward rational bounds check containment, not numerical proximity.
A separate width ceiling rejects vacuous bounds; it is not an information-tail cutoff.
"""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING
from fractions import Fraction as F
from itertools import product
from functools import lru_cache

import pytest

from sui import f, f_contracts as fc, f_entry as fe
from sui.contracts import ContractBook, ContractRef
from sui.f_model import FModel, f_model_from_json, f_model_json, f_model_ref
from sui.rate import RationalInterval
from sui.records import Observed, Decided, JobOpened, Payload, Category

from gate_f_cases import (
    BUDGET, FIXED, IDS, SECOND, PRODUCER, LEGACY_PREFERENCE,
    METHOD, ScriptedSource, action, candidates, canonical, histories, observations,
    make_case, make_root, make_problem, plain, predicate, resources, context_for, finite_world,
    observation_case, append_record, all_records, add_preference, digest,
    mixed_measure, draw_request, draw_binding, draw_book, continuation_for,
    bit_kernel, execute, policy, declaration, idle_kernel, outcome, diagonal,
    world_request, prepare_case,
    review5_primary_generation_legacy,
    limit_document, c1_case, legacy_case, legacy_input,
    builtin_declarations, callback_declaration, policy_end_case, UNION_CASES, union_case,
)
from sui.ids import Ref, RefKind
from sui.preference import from_ledger
from sui.model import model_from_json, model_json, model_ref
from sui.agent import plan
from pathlib import Path
import json
# 2026-10-12: the derived-input entrance (prepare_f_problem / prepare_f_request /
# freeze_root / FWorldRequest) and the F-b record layer were removed from F-a
# (今の約束 E-01, F04). make_case/make_root/make_problem now run through the facts
# entrance (gate_f_cases.LegacyCase). Tests that exercised the removed entrance
# itself were retired here; their copies are in Desktop/sui_fb_material_20261012/
# tests/test_gate_f_contract.py and the list is in HANDOFF §J (2026-10-12).
# Retired: test_fixture_assembly, test_fixture_variant_assembly, test_review5_legacy_future_measurement_cannot_issue_selected_or_verified_result, test_review_F17_correct_ledger_records_pass_prepare_restore_verify, test_review_F17_ledger_facts_and_record_contents_cannot_be_self_reported, test_review_F17_missing_ledger_cannot_authenticate_any_entrance, test_structure_A_world_is_detached_from_mutable_declaration_and_request_inputs, test_structure_B_resolved_request_is_not_a_caller_authentication, test_structure_preference_conflict_saved_preparation_replays_same_rejection, test_structure_preference_duplicate_Record_CIDs_do_not_invent_transitive_ancestry, test_structure_preference_fixed_parents_ignore_late_style_and_missing_ledger_rejects, test_structure_preference_multiple_papers_and_withdraw_roundtrip, test_structure_preference_same_CID_with_changed_parents_rejected, test_structure_preference_saved_causality_must_match_ledger, test_structure_B_restore_rejects_missing_preference_record_and_fixed_CID, test_extra02_conflicting_measurement_payload_rejected, test_FA02_no_arrival_or_closed, test_extra01_indistinguishable_outcomes, test_extra01_raw_plan_binding, test_structure_B_conflicting_generation_is_rejected_before_world_or_draw, test_v010_observation_generation_digest_from_plan_opportunity_step, test_structure_B_math_verification_requires_explicit_fixed_dependencies, test_v010_05_rootless_preflight_mathematical_certificate, test_v010_06_rootless_limit_verification, test_extra09_selected_mathematical_verification_identity, test_review_F02_child_operation_requires_same_certification_as_first_action, test_FA21_FA07_bridge_both_sides_independent_oracle, test_extra04_scope_mismatch_and_concurrent_styles, test_extra04_scope_and_binary_gamma, test_review_F03_duplicate_candidates_rejected_at_problem_boundary, test_structure_B_tampered_manifest_rejected_by_restore_and_result_verification, test_extra03_problem_draw_restore_and_cross_problem_rejection, test_v010_named_contract_assembly, test_FA06_compute_changes_K_without_E, test_review_F10_missing_resolver_implementation_never_falls_back, test_review_F19_saved_missing_implementation_survives_added_capability_and_binding, test_review_F19_tampered_saved_dependency_rejected_by_verification_and_binding, test_structure_A_all_evaluators_use_the_compiled_world_after_resolvers_are_disabled, test_v010_02_callback_wire_validation_and_implementation_distinction, test_v010_05_preflight_distinguishes_missing_inputs, test_v010_05_rootless_rechecks_reason_against_capability_availability_math, test_FA08_aliases_do_not_add_mass, test_review_F06_display_alias_representatives_evaluate_without_extra_mass, test_review_F18_candidate_id_only_alias_remains_valid, test_v010_01_policy_end_uses_same_model_node_kind, test_v010_01_predicate_reference_failures, test_review5_R08_legacy_typed_binding_plan_and_step_must_match_generation, test_v010_08_continuation_is_part_of_problem_and_must_cover_candidates, test_structure_A_world_factory_and_restore_recheck_fixed_dependencies, test_structure_C9_common_J_shift_keeps_q_and_scales_true_Z, test_structure_C3_new_measurement_and_reveal_existing_evidence_are_different, test_structure_C4_aliases_at_root_and_every_depth_preserve_canonical_probabilities, test_review_F09_unobservable_branches_use_evidence_projection, test_review_F09_unproved_computation_is_not_silently_ignored, test_review_F01_execute_branch_must_be_measurable_in_K, test_review_F04_equal_nonzero_J_preserves_normalization_factor, test_review_F13_zero_time_cycle_is_distinct_from_finite_work_and_quiet, test_review_F10_complete_references_checked_before_draw, test_review_F11_local_choose_aliases_preserve_mass_or_reject_return_conflict, test_review_F12_unknown_termination_cannot_reach_scope_prefix_or_tail, test_review_F18_candidate_own_proof_is_checked_even_with_normal_model, test_structure_B_prepare_checks_unregistered_predicate_even_under_short_circuit, test_FA08_uncertified_candidate_not_deleted, test_FA09_continuous_choice_uncertified



def rational(value):
    return F(*value)


@lru_cache(maxsize=None)
def independent_log_bounds(value):
    """Fraction-only atanh series with a proved geometric remainder; no sui math."""
    value = F(value)
    assert value > 0
    if value == 1:
        return F(0), F(0)
    if value < 1:
        low, high = independent_log_bounds(1/value)
        return -high, -low
    # Reduce to [1,2], so z <= 1/3. 160 terms give far more than 100 digits.
    power = 0
    while value > 2:
        value /= 2
        power += 1
    z = (value-1)/(value+1)
    term, total = z, F(0)
    for k in range(160):
        total += 2*term/(2*k+1)
        term *= z*z
    remainder = 2*term/(321*(1-z*z))
    low, high = total, total+remainder
    if power:
        l2, h2 = independent_log_bounds(F(2))
        low, high = low+power*l2, high+power*h2
    return low, high


def reference_interval(value):
    if isinstance(value, dict):
        if 'coeffs' in value:
            low = high = F(0)
            for prime, coefficient in value['coeffs'].items():
                c = rational(coefficient)
                lo, hi = independent_log_bounds(F(prime))
                low += c*(lo if c >= 0 else hi)
                high += c*(hi if c >= 0 else lo)
            return low, high
        return tuple(F(x) for x in value['interval'])
    point = rational(value) if isinstance(value, (list, tuple)) else F(value)
    return point, point


def negate(value):
    if isinstance(value, dict) and 'coeffs' in value:
        return {'coeffs': {p: [-c[0], c[1]] for p, c in value['coeffs'].items()}}
    low, high = reference_interval(value)
    return {'interval': (str(-high), str(-low))}


def interval_product(left, right):
    products = [x*y for x in left for y in right]
    return min(products), max(products)


@lru_cache(maxsize=None)
def expression_bounds(expr):
    """Independently enclose the public expression grammar using outward rounding.

    Decimal ln/exp are correctly rounded; adjacent Decimal values bracket their
    exact result. Rational input conversion is directed before monotone functions.
    This only checks returned expressions, never generates a fixture's oracle.
    """
    if expr.op == 'rational':
        return F(expr.value), F(expr.value)
    if expr.op == 'neg':
        lo, hi = expression_bounds(expr.arg)
        return -hi, -lo
    if expr.op == 'add':
        parts = [expression_bounds(x) for x in expr.args]
        return sum((x[0] for x in parts), F(0)), sum((x[1] for x in parts), F(0))
    if expr.op == 'mul':
        result = (F(1), F(1))
        for arg in expr.args:
            result = interval_product(result, expression_bounds(arg))
        return result
    if expr.op == 'div':
        lo, hi = expression_bounds(expr.denominator)
        assert not lo <= 0 <= hi
        return interval_product(expression_bounds(expr.numerator), (1/hi, 1/lo))
    if expr.op in ('log', 'exp'):
        lo, hi = expression_bounds(expr.arg)
        if expr.op == 'log' and lo == hi:
            return independent_log_bounds(lo)
        if expr.op == 'exp' and lo == hi == 0:
            return F(1), F(1)
        result = []
        with localcontext() as ctx:
            ctx.prec = 110
            for point, rounding in ((lo, ROUND_FLOOR), (hi, ROUND_CEILING)):
                ctx.rounding = rounding
                d = Decimal(point.numerator)/Decimal(point.denominator)
                value = d.ln() if expr.op == 'log' else d.exp()
                result.append(F(value.next_minus() if rounding == ROUND_FLOOR else value.next_plus()))
        return tuple(result)
    raise AssertionError(f'unknown public ExactReal op: {expr.op!r}')


def exact_rational(expr):
    low, high = expression_bounds(expr)
    assert low == high, 'expected an exactly rational expression'
    return low


def assert_expression_sum(terms, expected):
    parts = [expression_bounds(x) for x in terms]
    low, high = sum((x[0] for x in parts), F(0)), sum((x[1] for x in parts), F(0))
    elo, ehi = expression_bounds(expected) if isinstance(expected, f.ExactReal) else reference_interval(expected)
    # The difference must enclose zero; the width check prevents vacuous overlap.
    assert low-ehi <= 0 <= high-elo
    assert (high-low)+(ehi-elo) <= F(1, 10**90)


def assert_quantity(actual, expected, *, wrong=None):
    low, high = reference_interval(expected)
    assert actual.status == 'finite', actual
    assert actual.bounds is not None or actual.exact is not None
    if actual.bounds is not None:
        lo, hi = actual.bounds.lower, actual.bounds.upper
        # Enclosing an independently proved interval is sufficient to enclose truth.
        # No tolerance may repair a bound on the wrong side of the true value.
        assert lo <= low <= high <= hi, ('does not enclose oracle', lo, hi, low, high)
        if actual.exact is None:
            assert low-F(1, 10**24) <= lo and hi <= high+F(1, 10**24)
        else:
            assert hi-lo <= high-low + F(1, 10**20), 'vacuous bounds'
    if actual.exact is not None:
        elo, ehi = expression_bounds(actual.exact)
        # Expression identity is checked numerically against the independent oracle;
        # the returned bounds above have the stronger, directed containment check.
        assert elo <= high and low <= ehi, ('exact expression disagrees', elo, ehi, low, high)
        assert ehi-elo <= F(1, 10**90)
        if actual.bounds is not None:
            assert lo <= ehi and elo <= hi
        else:
            lo, hi = elo, ehi
    if wrong is not None:
        wlo, whi = reference_interval(wrong)
        assert hi < wlo or lo > whi, 'returned bounds still admit wrong_*'


def assert_evaluation_axes(evaluation, names):
    assert evaluation.candidates == names
    for name in ('expected_cost', 'information', 'G', 'J', 'q_star'):
        assert len(getattr(evaluation, name)) == len(names), name
    assert len(evaluation.cumulative) == len(names)+1
    assert evaluation.cumulative[0] == RationalInterval(lower=F(0), upper=F(0))
    assert evaluation.cumulative[-1] == RationalInterval(lower=F(1), upper=F(1))
    assert evaluation.normalization is not None
    assert evaluation.normalization.admissible == names
    assert evaluation.normalization.Z.lower > 0
    assert evaluation.certificate.problem_key == evaluation.root.problem_key
    assert evaluation.certificate.root_key == evaluation.root.root_key


def assert_selected(result, root, name, u):
    assert isinstance(result, f.Selected), result
    assert result.root.root_key == root.root_key
    assert result.choice.id == name
    assert result.evaluation.candidates[result.index] == name
    assert result.choice == root.candidates.candidates[result.index]
    assert result.u == u
    assert result.previous.upper <= u < result.current.lower
    assert result.certificate.root_key == root.root_key



@pytest.mark.parametrize('pending,nonzero', [(False, False), (True, False), (True, True)])
def test_legacy_bridge_input_assembly(pending, nonzero):
    model, ledger, hand = legacy_input(pending=pending, nonzero=nonzero)
    records = all_records(ledger)
    assert model.states == ('x0', 'x1')
    assert model.actions == (('M', 'Q', 'P') if pending else ('M', 'Q'))
    assert not model.learnable and model.Q is None
    assert tuple(r.body.content.as_json() for r in records if isinstance(r.body, JobOpened)) == (
        ({'action': 'P'},) if pending else ())
    assert not [r for r in records if isinstance(r.body, Observed) and r.body.route == 'executor']
    if pending: assert hand.clock.mono_ns() == SECOND


def test_FA01_contract_registration_assembly():
    book = ContractBook()
    for contract in fc.DECLARATIONS:
        book.register(contract)
        assert book.get(contract.ref) == contract
        for field in ('meaning', 'unit', 'state_owner', 'persistence', 'failure', 'cancel', 'redelivery'):
            assert getattr(contract, field).strip()
    for constant, name in [('PROBLEM', 'problem'), ('VALUE', 'value'), ('STYLE', 'style'),
                           ('OBSERVATION_PLAN', 'observation_plan'), ('OBSERVATION_BINDING', 'observation_binding'),
                           ('FIRING', 'firing'), ('LIMIT_PROBLEM', 'limit_problem'), ('LIMIT_CERTIFICATE', 'limit_certificate')]:
        assert getattr(fc, constant) == ContractRef('sui.f.'+name, '2' if constant in ('PROBLEM', 'VALUE') else '1')


def test_FA01_model_canonical_roundtrip():
    data = canonical(finite_world('FA01')[0])  # model.10 reader stays (E-07)
    model = f_model_from_json(data)
    assert f_model_json(model) == data
    assert f_model_ref(model) == digest(json.loads(data))


@pytest.mark.parametrize('bad,reason', [
    ('duplicate_key', 'schema'), ('bool_integer', 'shape'), ('bool_numerator', 'shape'),
    ('unreduced_rational', 'rational'), ('zero_denominator', 'rational'), ('negative_duration', 'unit'),
    ('unknown_version', 'unknown_version'), ('axis_shape', 'shape'), ('unknown_key', 'shape'),
    ('missing_key', 'shape'), ('noncanonical', 'noncanonical'), ('probability_mass', 'normalization'),
    ('unresolved_kernel', 'unresolved_reference')])
def test_FA01_model_rejection_reasons(bad, reason):
    doc = deepcopy(finite_world('FA01')[0])  # model.10 reader stays (E-07)
    if bad == 'bool_integer': doc['kernels'][0]['outcomes'][0]['elapsed_ns'] = True
    if bad == 'bool_numerator': doc['initial'][0] = [True, 2]
    if bad == 'unreduced_rational': doc['initial'][0] = [2, 4]
    if bad == 'zero_denominator': doc['initial'][0] = [1, 0]
    if bad == 'negative_duration': doc['kernels'][0]['outcomes'][0]['elapsed_ns'] = -1
    if bad == 'unknown_version': doc['contract']['version'] = 'future'
    if bad == 'axis_shape': doc['kernels'][0]['outcomes'][0]['matrix'].pop()
    if bad == 'unknown_key': doc['unexpected'] = 0
    if bad == 'missing_key': del doc['units']
    if bad == 'probability_mass': doc['initial'][0] = [3, 4]
    if bad == 'unresolved_kernel': doc['policies'][0]['nodes'][0]['kernel'] = 'absent'
    data = canonical(doc)
    if bad == 'duplicate_key': data = b'{"scheme":"sui.model.10",' + data[1:]
    if bad == 'noncanonical': data += b' '
    with pytest.raises(f.FInputError) as caught: f_model_from_json(data)
    assert caught.value.reason == reason
    assert caught.value.field is None or caught.value.field.startswith('/')
    assert isinstance(caught.value.detail, str)


@pytest.mark.parametrize('unavailable', [False, True])
def test_FA01_frame_union_roundtrip(unavailable):
    frame = make_case('FA05').frames[0]
    if unavailable: frame = replace(frame, value=f.Unavailable(reason='not_measured', basis=()))
    data = canonical(plain(frame))
    assert json.loads(data)['value']['kind'] == ('unavailable' if unavailable else 'value')
    assert fe.f_json(frame) == data
    assert fe.f_from_json(data, contract=fc.MEASUREMENT) == frame


def test_FA01_auxiliary_exact_expression():
    value = f.ExactReal(op='log', arg=f.ExactReal(op='rational', value=F(2)))
    expected = canonical({'type': 'ExactReal', 'value': {'op': 'log',
                         'arg': {'op': 'rational', 'value': [2, 1]}}})
    assert fe.f_json(value) == expected
    assert fe.f_from_json(expected, contract=fc.VALUE_FACTS) == value
    with pytest.raises(f.FInputError): fe.f_json(replace(value, value=F(3)))


def test_FA01_structured_mapping_and_duplicate():
    E, K = histories(make_case('FA01'))
    q = f.FQuantity(status='finite', exact=f.ExactReal(op='rational', value=F(1)), bounds=RationalInterval(F(1), F(1)), proof=None, reason=None)
    snapshot = f.PredicateSnapshot(model_ref=None, E=E, K=K, quantities={f.QuantityRef(key='z'): q, f.QuantityRef(key='a'): q}, dependencies=(), policy_position=None)
    data = canonical({'type': 'PredicateSnapshot', 'value': plain(snapshot)})
    assert [v['key'] for v in json.loads(data)['value']['quantities']] == [{'key': 'a'}, {'key': 'z'}]
    assert fe.f_json(snapshot) == data
    assert fe.f_from_json(data, contract=fc.VALUE_FACTS) == snapshot
    bad = json.loads(data)
    bad['value']['quantities'].append(bad['value']['quantities'][0])
    with pytest.raises(f.FInputError): fe.f_from_json(canonical(bad), contract=fc.VALUE_FACTS)


def test_FA01_semantic_key_and_alias():
    original = make_case('FA01').actions[0]
    registry = f.builtin_f_registry()
    assert f.canonical_action(original, registry=registry).semantic_key == original.semantic_key
    assert f.canonical_action(replace(original, id='display-only'), registry=registry).semantic_key == original.semantic_key
    with pytest.raises(f.FInputError) as caught:
        f.canonical_action(replace(original, semantic_key='sha256:'+'0'*64), registry=registry)
    assert caught.value.reason == 'semantic_key_mismatch'


@pytest.mark.parametrize('bad', ['duplicate_declaration', 'orphan_implementation'])
def test_FA01_registry_rejections(bad):
    ref = ContractRef('fixture.unimplemented', '1')
    decl = f.CapabilityDeclaration(kind='predicate', ref=ref, args_contract=fc.VALUE_FACTS, input_contract=fc.VALUE_FACTS, output_contract=fc.VALUE_FACTS, dependencies=(), conditions=())
    impl = f.CapabilityImplementation(kind='predicate', ref=ref, implementation=lambda *, args, input, context: input, identity='fixture.echo/1')
    with pytest.raises(f.FInputError):
        f.make_f_registry(declarations=(decl, decl) if bad == 'duplicate_declaration' else (),
                          implementations=() if bad == 'duplicate_declaration' else (impl,))


def test_FA03_shared_law_two_raw_windows():
    case = make_case('FA03')
    belief = f.initial_finite_belief(case.model)
    for obs in observations(case): belief = f.apply_f_observation(case.model, belief, observation=obs)
    assert belief.joint == (F(16, 17), F(1, 17))
    assert belief.evidence_mass == rational(FIXED['FA03']['evidence_shared_law'])
    assert belief.evidence_mass != rational(FIXED['FA03']['wrong_redraw_or_average_per_window']['evidence'])
    assert f.finite_marginal(belief, target='x') == 1


def assert_path_table(table, root, *, complete):
    assert (table.problem_key, table.root_key) == (root.problem_key, root.root_key)
    assert table.kind == ('complete' if complete else 'prefix')
    assert table.candidates == tuple(a.id for a in root.candidates.candidates)
    for row in table.rows:
        assert row.candidate in table.candidates
        assert_expression_sum(row.joint_target, row.probability)
        assert row.terminal.kind in ('ended', 'horizon')
        assert row.E_trace and row.K_trace
    for row in table.frontier:
        assert_expression_sum(row.joint_state, row.probability)
    for name in table.candidates:
        assert_expression_sum((row.probability for row in table.rows+table.frontier
                               if row.candidate == name), 1)
    if complete:
        assert table.frontier == () and table.steps is None
        assert tuple(r.candidate for r in table.residual) == table.candidates
        for r in table.residual: assert_quantity(r.mass, 0)


@pytest.mark.parametrize('variant', ['default', 'nonzero'])
def test_FA04_two_level_paths_child_nodes_and_four_wrong_costs(variant):
    root = make_root(make_case('FA04', variant))
    paths = f.enumerate_f_paths(root, budget=BUDGET)
    assert_path_table(paths, root, complete=True)
    assert {tuple(a.args['path_action'] for a in row.actions) for row in paths.rows} == {
        ('M', 'M'), ('M', 'Q'), ('Q', 'M'), ('Q', 'Q')}
    oracle = FIXED['FA04_nonzero_path_cost' if variant == 'nonzero' else 'FA04']
    children = [n for n in paths.nodes if n.alternatives == ('M2', 'Q2')]
    assert {n.candidate for n in children} == {'M', 'Q'}
    assert len({n.knowledge_key for n in children if n.candidate == 'M'}) == 2
    for node in children:
        row = oracle['after_first_M_y1' if node.candidate == 'M' else 'after_first_Q']
        for i, name in enumerate(('M', 'Q')): assert_quantity(node.J[i], row[f'J_{name}'])
        assert_quantity(node.q_star[0], row['q_M'])
        assert_quantity(node.V, row['V'])
    wrongs = [v for k, v in oracle.items() if k.startswith('wrong_')]
    for result in (f.evaluate_f_enumerated(root, paths, budget=BUDGET), f.evaluate_f_recursive(root, budget=BUDGET)):
        assert_evaluation_axes(result, ('M', 'Q'))
        for i, name in enumerate(('M', 'Q')):
            assert_quantity(result.G[i], oracle['root'][f'J_{name}'])
            for wrong in wrongs: assert_quantity(result.J[i], oracle['root'][f'J_{name}'], wrong=wrong[f'J_{name}'])
            assert_quantity(result.expected_cost[i], oracle['root_cost'][name] if variant == 'nonzero' else 0)
            assert_quantity(result.information[i].additional,
                oracle['root_information'][name] if variant == 'nonzero' else negate(oracle['root'][f'J_{name}']))
        for wrong in wrongs: assert_quantity(result.q_star[0], oracle['root']['q_M'], wrong=wrong['q_M'])
        for node in paths.nodes:
            if node.alternatives == ('M', 'Q'): assert_quantity(node.V, oracle['root']['V'])
    if variant == 'nonzero':
        assert 'finite_terminal_cost' in {c.contract.name for c in result.certificate.trace}


@pytest.mark.parametrize('variant', ['default', 'independent'])
def test_FA05_redelivery_vs_independent(variant):
    case = make_case('FA05', variant)
    E, K = histories(case)
    assert tuple(link.measurement for link in E.links) == tuple(dict.fromkeys(case.measurements))
    assert {ref for link in E.links for ref in link.records} == {r.id for r in case.records if r.body.contract == fc.MEASUREMENT}
    assert K.available == K.incorporated == ()
    belief = f.initial_finite_belief(case.model)
    for obs in observations(case):
        belief = f.apply_f_observation(case.model, belief, observation=obs)
        assert f.apply_f_observation(case.model, belief, observation=obs) == belief
    key = 'posterior_two_independent_same_value' if variant == 'independent' else 'posterior_one_measurement_redelivered_twice'
    expected = rational(FIXED['FA05'][key])
    assert belief.joint == (expected, 1-expected)
    assert belief.evidence_mass == (F(5, 16) if variant == 'independent' else F(1, 2))


def test_FA05_raw_identity_assembly():
    duplicated, independent = make_case('FA05'), make_case('FA05', 'independent')
    assert duplicated.ledger.record(duplicated.raw[0]).id != duplicated.ledger.record(duplicated.raw[1]).id
    assert duplicated.ledger.record(duplicated.raw[0]).body.content == duplicated.ledger.record(duplicated.raw[1]).body.content
    assert duplicated.measurements[0] == duplicated.measurements[1]
    assert independent.frames[0].value == independent.frames[1].value == 0
    assert independent.measurements[0] != independent.measurements[1]


def test_extra02_transition_without_measurement_is_idempotent():
    case = make_case('FA02')
    belief = f.initial_finite_belief(case.model)
    args = dict(kernel='open', outcome='none', measurement=None, transition_key='fixture-step-0')
    changed = f.update_finite_belief(case.model, belief, **args)
    assert changed.joint == (F(4, 5), F(1, 5))
    assert f.update_finite_belief(case.model, changed, **args) == changed
    with pytest.raises(f.FInputError) as caught:
        f.update_finite_belief(case.model, changed, **{**args, 'outcome': 'arrived'})
    assert caught.value.reason == 'measurement_conflict'


@pytest.mark.parametrize('nonzero', [False, True])
def test_FA07_H_zero_received_once_first_action_cost(nonzero):
    root = make_root(make_case('FA07', 'first_action_cost' if nonzero else 'default', H=0))
    result = f.evaluate_f_recursive(root, budget=BUDGET)
    assert_evaluation_axes(result, ('M', 'Q'))
    for i, name in enumerate(('M', 'Q')):
        part = result.information[i]
        assert_quantity(part.already_received, FIXED['FA07']['already_received'])
        assert_quantity(part.additional, 0)
        assert_quantity(f.legacy_information(part), FIXED['FA07']['total_information'])
        expected = FIXED['FA07_first_action_cost']['J'][name] if nonzero else FIXED['FA07']['old_G']
        assert_quantity(result.J[i], expected, wrong=(FIXED['FA07_first_action_cost']['wrong_drop_common_term_J'][name]
                        if nonzero else FIXED['FA07']['wrong_reflect_twice_G']))
        assert_quantity(result.expected_cost[i], FIXED['FA07_first_action_cost']['cost'][name] if nonzero else 0)
    if nonzero:
        for q, expected in zip(result.q_star, FIXED['FA07_first_action_cost']['q']): assert_quantity(q, expected)
    assert f.evaluate_f_recursive(root, budget=BUDGET).root.root_key == root.root_key


@pytest.mark.parametrize('cells', [1, 2])
def test_FA09_mixed_measure_partition(cells):
    partition = f.MeasurePartition(atoms=('now',), cells=tuple(
        f.MeasureCell(component='later', lower=F(2*i, cells), upper=F(2*(i+1), cells)) for i in range(cells)))
    checked = f.check_f_measure_partition(mixed_measure(), partition=partition)
    assert checked.measure == mixed_measure() and checked.partition == partition
    assert checked.atom_masses == (f.AtomMass(id='now', mass=F(1)),)
    assert checked.cell_masses == (F(1, cells),)*cells and checked.total == 2
    probability = checked.atom_masses[0].mass/checked.total
    assert probability == rational(FIXED['FA09']['now'])
    assert probability != rational(FIXED['FA09']['wrong_cells_as_points'])


@pytest.mark.parametrize('bounds', [[(0, 1), (F(1, 2), 2)], [(0, F(1, 2)), (1, 2)]], ids=['overlap', 'gap'])
def test_FA09_invalid_partition(bounds):
    part = f.MeasurePartition(atoms=('now',), cells=tuple(f.MeasureCell(component='later', lower=F(a), upper=F(b)) for a, b in bounds))
    with pytest.raises(f.FInputError): f.check_f_measure_partition(mixed_measure(), partition=part)


def test_FA10_later_information_not_time_tie():
    result = f.evaluate_f_recursive(make_root(make_case('FA10')), budget=BUDGET)
    assert_evaluation_axes(result, ('Q', 'M'))
    assert_quantity(result.information[0].additional, FIXED['FA10']['I_now'])
    assert_quantity(result.information[1].additional, FIXED['FA10']['I_later'])
    assert_quantity(result.q_star[1], FIXED['FA10']['q_later'], wrong=FIXED['FA10']['wrong_time_tie'])


@pytest.mark.parametrize('H,key', [(None, 'unbounded'), (SECOND, 'finite_H_1')])
def test_FA11_scope_changes_selection(H, key):
    root = make_root(make_case('FA11', H=H))
    result = f.evaluate_f_recursive(root, budget=BUDGET)
    assert_evaluation_axes(result, ('W', 'A'))
    oracle = FIXED['FA11'][key]
    for i, name in enumerate(('W', 'A')):
        assert_quantity(result.information[i].additional, oracle[f'I_{name}'])
        assert_quantity(result.J[i], negate(oracle[f'I_{name}']))
    assert_quantity(result.q_star[0], oracle['q_W'])
    assert_selected(f.certify_f_choice(result, u=F(1, 2)), root, oracle['selected'], F(1, 2))


def test_FA12_permanent_nonarrival_not_automatic_waiting():
    root = make_root(make_case('FA12'))
    result = f.evaluate_f_recursive(root, budget=BUDGET)
    for i, name in enumerate(('W', 'A')): assert_quantity(result.information[i].additional, FIXED['FA12'][f'I_{name}'])
    assert_quantity(result.q_star[0], FIXED['FA12']['q_W'])
    assert_selected(f.certify_f_choice(result, u=F(1, 2)), root, 'A', F(1, 2))


@pytest.mark.parametrize('steps', [0, 1, 2])
def test_FA13_prefix_joint_frontier_and_permanent_mass(steps):
    root = make_root(make_case('FA13'))
    paths = f.enumerate_f_prefix(root, steps=steps, budget=BUDGET)
    assert_path_table(paths, root, complete=False)
    assert paths.steps == steps
    wait_rows = [row for row in paths.frontier if row.candidate == 'W']
    assert wait_rows
    expected = (F(3, 8*2**steps), F(1, 8), F(0))*2
    got = tuple(sum((F(exact_rational(row.joint_state[i])) for row in wait_rows), F(0)) for i in range(6))
    assert got == expected
    assert_quantity(next(r.mass for r in paths.residual if r.candidate == 'W'), F(1, 4)+F(3, 4*2**steps))
    tail = f.certify_f_tail(root, candidate='W', prefix=paths, budget=BUDGET)
    assert tail.prefix.kind == 'prefix' and tail.prefix.steps == steps and tail.prefix.candidate == 'W'
    assert tail.prefix.table_digest
    assert_quantity(tail.residual_mass, F(1, 4)+F(3, 4*2**steps))
    assert_quantity(tail.cost_total, 0)
    if steps:
        oracle = FIXED['FA13'][f'n{steps}']
        assert_quantity(tail.information_prefix, oracle['I_W_lower'])
        assert_quantity(tail.information_remaining, oracle['tail_R'])
        result = f.evaluate_f_prefix(root, steps=steps, budget=BUDGET)
        lo, hi = result.q_star[0].bounds.lower, result.q_star[0].bounds.upper
        low, high = [reference_interval(x) for x in oracle['q_W_interval']]
        assert lo <= low[0] and hi >= high[1]
        assert low[0]-lo <= F(1, 10**24) and hi-high[1] <= F(1, 10**24)
        selected = f.certify_f_choice(result, u=F(1, 2))
        if steps == 2: assert_selected(selected, root, 'W', F(1, 2))
        else:
            assert isinstance(selected, f.NoDecision)
            assert (selected.outcome, selected.reason) == ('incomplete', 'selection_boundary')


def test_FA14_quiet_selected_with_permanent_mass():
    root = make_root(make_case('FA14'), u=F(1, 6))
    result = f.evaluate_f_recursive(root, budget=BUDGET)
    for i, name in enumerate(('Q', 'M')):
        assert_quantity(result.G[i], FIXED['FA14'][f'G_{name}'])
        assert_quantity(result.q_star[i], FIXED['FA14']['q'][i])
    prefix = f.enumerate_f_prefix(root, steps=1, budget=BUDGET)
    tail = f.certify_f_tail(root, candidate='Q', prefix=prefix, budget=BUDGET)
    assert_quantity(tail.residual_mass, 1)
    assert_quantity(tail.information_remaining, 0)
    assert_quantity(tail.cost_total, 0)
    assert_selected(f.evaluate_f(root, budget=BUDGET), root, 'Q', F(1, 6))


@pytest.mark.parametrize('variant,key', [('default', 'one_perfect_measurement'), ('hundred', 'hundred_of_same_bit')])
def test_FA15_same_static_bit(variant, key):
    result = f.evaluate_f_recursive(make_root(make_case('FA15', variant)), budget=BUDGET)
    assert_quantity(result.information[0].additional, FIXED['FA15'][key], wrong=FIXED['FA15']['wrong_sum_hundred'])


@pytest.mark.parametrize('both', [False, True], ids=['FA15_new_bits', 'FA17_infinite_difference'])
@pytest.mark.parametrize('proof', ['none', 'missing_checker', 'valid', 'tampered'])
def test_FA15_FA17_limit_diagnostic(both, proof):
    problem = f.limit_problem_from_json(canonical(limit_document(both=both, proof=proof)))
    if proof == 'tampered':
        with pytest.raises(f.FInputError) as caught: f.certify_f_limit(problem, budget=BUDGET)
        assert caught.value.reason == 'proof_mismatch'
        return
    result = f.diagnose_f_limit(problem, budget=BUDGET)
    assert isinstance(result, f.NoDecision) and result.attempt_id is None
    if proof in ('none', 'missing_checker'):
        assert (result.outcome, result.reason) == ('incomplete', 'certificate_incomplete')
    else:
        expected = 'undefined_infinite_difference' if both else 'information_divergent'
        assert (result.outcome, result.reason) == ('rejected', expected)
        cert = f.certify_f_limit(problem, budget=BUDGET)
        assert cert.checker == ContractRef('iid_bits_limit', '1') and cert.conclusion == expected
        assert cert.information.bound == 'diverges' and cert.cost.bound == ('diverges' if both else 'zero')
        assert cert.information.prefix.name == cert.cost.prefix.name == 'linear'
        ln2 = reference_interval(FIXED['FA15']['one_perfect_measurement'])
        slope = expression_bounds(cert.information.prefix.args.slope)
        assert slope[0] <= ln2[1] and ln2[0] <= slope[1]
        assert slope[1]-slope[0] <= F(1, 10**90)
        assert exact_rational(cert.information.prefix.args.intercept) == 0
        assert exact_rational(cert.cost.prefix.args.intercept) == 0
        if both: assert cert.cost.prefix.args.slope == cert.information.prefix.args.slope
        else: assert exact_rational(cert.cost.prefix.args.slope) == 0


@pytest.mark.parametrize('variant,oracle', [('default', 'arrive_at_1'), ('at_2', 'arrive_at_2')])
@pytest.mark.parametrize('H,key', [(None, 'unbounded'), (SECOND, 'finite_H_1')])
def test_FA16_arrival_after_horizon(variant, oracle, H, key):
    result = f.evaluate_f_recursive(make_root(make_case('FA16', variant, H=H)), budget=BUDGET)
    assert_quantity(result.information[1].additional, FIXED['FA16'][oracle][key])


@pytest.mark.parametrize('variant,scope,key', [
    ('composite', 'one_step', 'one_step_composite'),
    ('composite', 'unbounded_total', 'one_composite_wait_then_measure'),
    ('split', 'one_step', 'one_step_two_operations_first'),
    ('split', 'unbounded_total', 'two_operations_wait_and_measure')])
def test_v010_08_FA16_four_information_values(variant, scope, key):
    case = make_case('FA16', variant, scope_name=scope)
    root = make_root(case)
    result = f.evaluate_f_recursive(root, budget=BUDGET)
    assert_evaluation_axes(result, ('C' if variant == 'composite' else 'W',))
    assert root.continuation == case.continuation
    assert root.E.links == () and root.K.available == ()
    assert root.gamma == 1
    info = result.information[0]
    assert_quantity(info.already_received, 0)
    zero = variant == 'split' and scope == 'one_step'
    wrong = FIXED['FA16']['packaging']['one_step_composite'] if zero else 0
    assert_quantity(info.additional, FIXED['FA16']['packaging'][key], wrong=wrong)
    assert_quantity(info.total_information, FIXED['FA16']['packaging'][key], wrong=wrong)
    assert_quantity(result.expected_cost[0], 0)
    assert_quantity(result.q_star[0], 1, wrong=[1, 2])


def predicate_snapshot(*, missing=False):
    case = make_case('FA18')
    E, K = histories(case)
    left, right = f.QuantityRef(key='left'), f.QuantityRef(key='right')
    quantities = {left: f.FQuantity(status='finite', exact=None, bounds=RationalInterval(F(0), F(2)), proof=None, reason=None),
                  right: f.FQuantity(status='finite', exact=None, bounds=RationalInterval(F(1), F(3)), proof=None, reason=None)}
    deps = (f.DependencyRef(key='left', basis=(case.ledger.record(case.raw[0]).id,)),) if missing else ()
    if missing:
        del quantities[left]
        quantities.pop(right)
        right, known = f.certify_f_quantity(definition=f.FQuantityDefinition(
            kind='rational_constant', value=F(2), unit='dimensionless', provenance=(case.ledger.record(case.raw[0]).id,)),
            evaluation=None, resources=resources(case))
        quantities[right] = known
    snapshot = f.PredicateSnapshot(model_ref=None, E=E, K=K, quantities=quantities, dependencies=deps, policy_position=None)
    unknown = f.PredicateRef(name='interval_compare', version='1',
        args={'left': plain(left), 'relation': 'lt', 'right': plain(right), 'provenance': [str(case.ledger.record(case.raw[0]).id)]})
    return case, snapshot, {'true': predicate(True), 'false': predicate(False), 'unknown': unknown}


@pytest.mark.parametrize('op', ['and', 'or'])
@pytest.mark.parametrize('a,b', list(product(('true', 'false', 'unknown'), repeat=2)))
def test_FA18_three_valued_boolean(op, a, b):
    case, snapshot, terms = predicate_snapshot()
    expression = f.PredicateRef(name=op, version='1', args={'terms': [plain(terms[a]), plain(terms[b])]})
    assert f.check_predicate(expression, snapshot=snapshot, resources=resources(case)).value == FIXED['FA18'][op][f'{a},{b}']


@pytest.mark.parametrize('value', ['true', 'false', 'unknown'])
def test_FA18_not(value):
    case, snapshot, terms = predicate_snapshot()
    assert f.check_predicate(f.PredicateRef(name='not', version='1', args={'term': plain(terms[value])}),
                             snapshot=snapshot, resources=resources(case)).value == FIXED['FA18']['not'][value]


@pytest.mark.parametrize('relation', ['lt', 'le', 'eq'])
def test_FA18_overlapping_intervals(relation):
    case, snapshot, terms = predicate_snapshot()
    pred = replace(terms['unknown'], args={**terms['unknown'].args, 'relation': relation})
    assert f.check_predicate(pred, snapshot=snapshot, resources=resources(case)).value == 'unknown'


def test_FA18_same_missing_quantity_same_work_100_times():
    case, snapshot, terms = predicate_snapshot(missing=True)
    results = [f.check_predicate(terms['unknown'], snapshot=snapshot, resources=resources(case)) for _ in range(100)]
    assert {r.value for r in results} == {'unknown'}
    assert all(r.work is not None for r in results)
    first = results[0].work
    assert first.work_id and all(r.work == first for r in results)
    assert first.predicate == terms['unknown'] and first.snapshot == snapshot
    assert first.missing == snapshot.dependencies
    assert all(r.missing == snapshot.dependencies for r in results)






def test_FA19_exact_boundary_and_float():
    root = make_root(make_case('FA19'))
    evaluation = f.evaluate_f_recursive(root, budget=BUDGET)
    assert_selected(f.certify_f_choice(evaluation, u=0.5), root, 'M', F(1, 2))
    binary = F.from_float(0.1)
    assert binary != F(1, 10)
    root2 = make_root(make_case('FA19'), u=binary)
    e2 = f.evaluate_f_recursive(root2, budget=BUDGET)
    assert_selected(f.certify_f_choice(e2, u=0.1), root2, 'Q', binary)
    again = f.evaluate_f_recursive(root, budget=replace(BUDGET, tolerance=F(1, 10**30)))
    assert again.root.problem_key == root.problem_key and again.root.selection_draw == root.selection_draw


def test_FA19_resume_retains_root_and_u():
    root = make_root(make_case('FA13'))
    pending = f.certify_f_choice(f.evaluate_f_prefix(root, steps=1, budget=BUDGET), u=F(1, 2))
    assert isinstance(pending, f.NoDecision) and pending.reason == 'selection_boundary'
    assert pending.attempt_id is None and pending.root_key == root.root_key and pending.resume is not None
    selected = f.evaluate_f(root, budget=BUDGET, resume=pending.resume)
    assert_selected(selected, root, 'W', F(1, 2))
    assert selected.root.selection_draw == root.selection_draw


def begin_attempt(case, *, root=None, problem=None):
    return fe.begin_f_attempt(request_id='request-1', firing_id='firing-1', policy_generation='generation-1',
        parents=case.ledger.heads(), evidence=tuple(r.id for r in case.records if r.body.contract == fc.MEASUREMENT), problem=problem, root=root,
        clock=case.clock, ids=case.ids, membrane=PRODUCER)






@pytest.mark.parametrize('variant', ['10', '01'])
@pytest.mark.parametrize('label', ['y0', 'y1'])
@pytest.mark.parametrize('delay', [0, 123456789])
def test_FA20_two_real_windows_p_outcome_and_delay(variant, label, delay):
    world, model, records, ctx, report = c1_case(variant, outcome_label=label, boot_ns=37, delay_ns=delay)
    resource = fe.make_f_resources(models=(model,), records=records, registry=f.builtin_f_registry(), ledger=world.ledger)
    parsed = fe.read_c1_frames(model, records, context=ctx, resources=resource)
    assert [(r.start_ns, r.end_ns, r.count) for r in parsed.frames] == [
        (37, 37+SECOND, int(variant[0])), (37+SECOND, 37+2*SECOND, int(variant[1]))]
    assert parsed.frames[0].probe is None
    assert parsed.frames[1].probe.variable == 'p' and parsed.frames[1].probe.label == label
    assert parsed.frames[1].source_record == report.id
    summary = f.initial_c1_summary(model, run=world.clock.run, origin_ns=37)
    assert (summary.N, summary.T_s, summary.A0, summary.A1, summary.end_ns) == (0, F(0), F(4), F(0), 37)
    for frame in parsed.frames:
        summary = f.update_c1_summary(summary, frame=frame)
        assert f.update_c1_summary(summary, frame=frame) == summary
    expected = rational(FIXED['FA20'][variant]['P_S2_state0'])
    assert f.c1_state_marginal(summary) == (expected, 1-expected)
    assert (summary.N, summary.T_s, summary.end_ns) == (1, F(2), 37+2*SECOND)
    assert (summary.A0, summary.A1) == ((F(4), F(10)) if variant == '10' else (F(4), F(14)))
    assert summary.measurement_ids == tuple(r.measurement_id for r in parsed.frames)
    assert summary.source_records == tuple(r.source_record for r in parsed.frames)
    assert summary.probe_measurements == (parsed.frames[1].probe.measurement_id,)
    assert dict(summary.probe_counts) == {'p': (1, 0) if label == 'y0' else (0, 1)}


@pytest.mark.parametrize('bad', ['saturated', 'gap'])
def test_FA20_unproved_window(bad):
    world, model, records, ctx, _ = c1_case(bad=bad)
    resource = fe.make_f_resources(models=(model,), records=records, registry=f.builtin_f_registry(), ledger=world.ledger)
    with pytest.raises(f.FIncomplete) as caught: fe.read_c1_frames(model, records, context=ctx, resources=resource)
    assert caught.value.reason == 'c1_closure_unproved'


def test_FA20_midwindow_clock_not_count_zero():
    world, model, records, ctx, _ = c1_case(midwindow=True)
    resource = fe.make_f_resources(models=(model,), records=records, registry=f.builtin_f_registry(), ledger=world.ledger)
    first = fe.read_c1_frames(model, records, context=ctx, resources=resource)
    assert [(r.start_ns, r.end_ns, r.count) for r in first.frames] == [(0, SECOND, 1)]
    unfinished = tuple(r for r in records if isinstance(r.body, JobOpened) or r.id.kind == RefKind.ATTEMPT)
    later = fe.read_c1_frames(model, unfinished, context=ctx, resources=resource)
    assert later.frames == ()
    assert later.pending and all(isinstance(dep, f.DependencyRef) for dep in later.pending)
    assert world.clock.mono_ns() == SECOND+SECOND//2


def assert_legacy_number(actual, expected):
    # Legacy float compatibility only (§3-10-2); not an F interval guarantee.
    low, high = reference_interval(expected)
    assert float(low)-1e-12 <= actual <= float(high)+1e-12


@pytest.mark.parametrize('scene', ['FA21', 'FA07', 'FA07_first_action_cost'])
def test_legacy_public_plan_independent_oracle(scene):
    _, _, _, _, view, resolved = legacy_case(pending=scene != 'FA21', nonzero=scene == 'FA07_first_action_cost')
    draft = plan(view, ('M', 'Q'), u=.5)
    content = draft.content.as_json()
    oracle = FIXED['FA21_minimal_bridge' if scene == 'FA21' else scene]
    assert content['candidates'] == ['M', 'Q'] and content['u'] == .5
    for i, name in enumerate(('M', 'Q')):
        assert_legacy_number(content['J'][i], oracle['J'][name] if scene != 'FA07' else oracle['old_G'])
        assert_legacy_number(content['q_pi'][i], oracle['q'][i] if scene != 'FA07' else F(1, 2))
    assert content['chosen'] == ('Q' if scene == 'FA07' else 'M')
    assert resolved.H_ns == (0 if scene != 'FA21' else None)
    assert draft.content.data == canonical(content)


def golden_models():
    """Only model_json bodies in saved JSON, no inferred raw histories."""
    cases = []
    def visit(value, path):
        if isinstance(value, dict):
            model = value.get('model_json')
            if isinstance(model, dict) and isinstance(model.get('body'), str):
                cases.append((path, model['body'].encode('utf-8'), model.get('sha256')))
            for key, child in value.items(): visit(child, path+'/'+key)
        elif isinstance(value, list):
            for i, child in enumerate(value): visit(child, path+'/'+str(i))
    for name in ('golden_s4b1a.json', 'golden_s4b1b.json', 'golden_s4b1c.json',
                 'golden_s4b_action.json', 'golden_s4b2.json'):
        visit(json.loads(Path(__file__).with_name(name).read_bytes()), name)
    assert cases
    return cases


@pytest.mark.parametrize('scene,data,sha', golden_models(), ids=lambda v: v if isinstance(v, str) and '/' in v else None)
def test_legacy_golden_model_bytes_only(scene, data, sha):
    """Partial regression: model bytes, not full scene outputs (R4)."""
    from hashlib import sha256
    model = model_from_json(data)
    assert model_json(model) == data
    assert model_ref(model) == 'sha256:'+sha256(data).hexdigest()
    if sha is not None: assert sha == sha256(data).hexdigest()


def restore_golden_ledger(rows):
    """Rebuild exported raw records through Ledger.append, never inject entries/state."""
    from sui.ledger import Ledger, decode_record
    class CapturedSalts:
        def __init__(self):
            from sui.ledger import SequentialSalts
            self.next_salt = None
            self.extension = SequentialSalts()
        def new(self):
            if self.next_salt is None: return self.extension.new()
            salt, self.next_salt = self.next_salt, None
            return salt
    salts = CapturedSalts()
    ledger = Ledger(salts=salts)
    remaining = list(rows)
    while remaining:
        ready = [r for r in remaining if set(json.loads(bytes.fromhex(r['header_hex']))['parents'])
                 <= {entry.cid for entry in ledger.entries()}]
        assert ready, 'golden export lacks a parent'
        for row in ready:
            header = bytes.fromhex(row['header_hex'])
            parents = json.loads(header)['parents']
            content = Payload(media_type=row['payload_media_type'], data=bytes.fromhex(row['payload_hex']))
            record = decode_record(header, content)
            salts.next_salt = bytes.fromhex(row['salt_hex'])
            entry = ledger.append(record, parents)
            assert entry.header == header and entry.cid == row['cid']
            assert ledger.record(entry.cid) == record
            remaining.remove(row)
    return ledger


@pytest.mark.parametrize('scene', ['known_laws', 'learned_B_Theta', 'reservation'])
def test_legacy_model8_golden_decision_replay_bytes(scene):
    from sui.agent import replay_decision
    document = json.loads(Path(__file__).with_name('golden_s4b2.json').read_bytes())
    row = document['pre_implementation'][scene]
    model = model_from_json(row['input']['model_json'].encode('utf-8'))
    ledger = restore_golden_ledger(row['persisted_ledger'])
    decisions = [entry for entry in ledger.entries() if entry.body_type is Decided]
    assert len(decisions) == 1
    replayed = replay_decision(model=model, ledger=ledger, decision=decisions[0].cid)
    assert replayed.content.data == row['decision_content'].encode('utf-8')
    assert plain(replayed.contract) == row['decision_contract']
    assert model_json(model) == row['model_json'].encode('utf-8')
    # Compare full stored belief bytes, not merely the number of records.
    beliefs = [ledger.record(entry.cid).body.content.data for entry in ledger.entries()
               if entry.body_type.__name__ == 'Prediction']
    assert row['belief_content'].encode('utf-8') in beliefs


@pytest.mark.parametrize('scene', ['noncanonical', 'unknown_version'])
def test_legacy_model8_golden_loader_rejection(scene):
    document = json.loads(Path(__file__).with_name('golden_s4b2.json').read_bytes())
    row = document['pre_implementation'][scene]
    with pytest.raises(ValueError) as caught:
        model_from_json(row['input']['model_json'].encode('utf-8'))
    error = row['rejection']
    assert type(caught.value).__name__ == error['exception']
    assert str(caught.value) == error['message']
    assert caught.value.reason == error['reason']
    assert caught.value.field == error['field']


@pytest.mark.parametrize('scene', ['all_forbidden', 'incomplete', 'outside_evaluation', 'unexplained'])
def test_legacy_model8_golden_plan_rejection(scene):
    from sui.agent import Agent
    from sui.clock import FakeClock
    from sui.ids import SequentialIds
    row = json.loads(Path(__file__).with_name('golden_s4b2.json').read_bytes())['pre_implementation'][scene]
    inp = row['input']
    ledger = restore_golden_ledger(inp['ledger'])
    last = max((e.at for e in ledger.entries()), key=lambda at: (at.mono_ns, at.seq))
    clock = FakeClock(run=last.run, run_index=last.run_index, mono_ns=last.mono_ns, wall_ns=last.wall_ns)
    for _ in range(last.seq): clock.now()
    with pytest.raises(Exception) as caught:
        model = model_from_json(inp['model_json'].encode('utf-8'))
        agent = Agent(model=model, lineage='gate-f-golden')
        agent.adopt(ledger, clock=clock, ids=SequentialIds('gate-f-golden'))
        view = agent.view(now_ns=inp['now_ns'], observed_ns=inp['observed_ns'], check_events=inp['check_events'])
        plan(view, inp['recipe']['candidates'], u=inp['recipe']['u'])
    expected = row['rejection']
    assert type(caught.value).__name__ == expected['exception']
    assert str(caught.value) == expected['message']
    assert caught.value.reason == expected['reason']
    assert caught.value.field == expected['field']


_ACTION_GOLDEN = json.loads(Path(__file__).with_name('golden_s4b_action.json').read_bytes())['pre_implementation']


@pytest.mark.parametrize('scene', tuple(_ACTION_GOLDEN['invalid']))
def test_legacy_action_golden_loader_rejections(scene):
    row = _ACTION_GOLDEN['invalid'][scene]
    with pytest.raises(ValueError) as caught: model_from_json(row['input'].encode('utf-8'))
    assert type(caught.value).__name__ == row['exception']
    assert str(caught.value) == row['message']


@pytest.mark.parametrize('scene', tuple(_ACTION_GOLDEN['success']))
def test_legacy_action_golden_model_bytes_only(scene):
    row = _ACTION_GOLDEN['success'][scene]
    data = row['model_json'].encode('utf-8')
    model = model_from_json(data)
    assert model_json(model) == data and model_ref(model) == row['model_ref']


def test_FA01_declared_but_unimplemented_capability_is_retained():
    ref = ContractRef('fixture.unimplemented', '1')
    declaration = f.CapabilityDeclaration(kind='predicate', ref=ref, args_contract=fc.VALUE_FACTS,
        input_contract=fc.VALUE_FACTS, output_contract=fc.VALUE_FACTS, dependencies=(), conditions=())
    registry = f.make_f_registry(declarations=(declaration,), implementations=())
    assert registry.declarations == (declaration,) and registry.implementations == ()


def test_FA14_nonterminating_one_step_does_not_claim_completion():
    result = f.evaluate_f(make_root(make_case('FA14', scope_name='one_step')), budget=BUDGET)
    assert isinstance(result, f.NoDecision)
    assert (result.outcome, result.reason) == ('rejected', 'OutsideEvaluationType')
    assert result.detail == 'nonterminating_one_step'




def test_v010_FA16_two_inputs_assembly():
    composite = make_case('FA16', 'composite')
    split = make_case('FA16', 'split')
    assert composite.document == split.document
    assert composite.model.declaration == split.model.declaration
    assert plain(composite.continuation) == {'after': [{'candidate': 'C', 'policy': None}]}
    assert plain(split.continuation) == {'after': [{'candidate': 'W',
        'policy': {'name': 'finite_policy', 'version': '1', 'args': {'id': 'afterW'}}}]}
    assert tuple(a.id for a in composite.actions) == ('C',)
    assert tuple(a.id for a in split.actions) == ('W',)
    ops = {op['id']: op for op in composite.document['operations']}
    assert ops['C']['args'] == {'opportunity': {'fixture': 'FA16', 'wrapper': 'wait_then_measure'},
                                'path_action': None}
    assert [ops[n]['args']['path_action'] for n in ('W', 'M')] == ['W', 'M']
    ps = {p['id']: p for p in composite.document['policies']}
    assert ps['pC']['nodes'] == [
        {'id': 'callW', 'kind': 'choose', 'operations': ['W'], 'rule': plain(fc.SOFT_CHOICE), 'next': {'W': 'callM'}},
        {'id': 'callM', 'kind': 'choose', 'operations': ['M'], 'rule': plain(fc.SOFT_CHOICE), 'next': {'M': 'c_finished'}},
        {'id': 'c_finished', 'kind': 'end'}]
    assert ps['afterW']['nodes'] == [
        {'id': 'callM', 'kind': 'choose', 'operations': ['M'], 'rule': plain(fc.SOFT_CHOICE), 'next': {'M': 'all_finished'}},
        {'id': 'all_finished', 'kind': 'end'}]
    assert composite.document['kernels'][0]['outcomes'][0]['elapsed_ns'] == SECOND
    assert all(o['elapsed_ns'] == 0 for o in composite.document['kernels'][1]['outcomes'])


def test_v010_02_builtin_seven_fields_exact():
    registry = f.builtin_f_registry()
    actual = {(d.kind, d.ref): plain(d) for d in registry.declarations}
    expected = {(d.kind, d.ref): plain(d) for d in builtin_declarations()}
    assert len(registry.declarations) == len(actual) == 28
    assert actual == expected
    assert {(i.kind, i.ref) for i in registry.implementations} == set(expected)
    assert all(callable(i.implementation) for i in registry.implementations)


def assert_records_verification(checked, result_verification):
    verification = checked.verification
    assert verification.kind == 'records'
    assert verification.method == ContractRef('sui.f.verify_records', '2')
    assert verification.input_key == checked.ticket.attempt_id
    assert verification.input_digest == digest(checked.ticket)
    # The public wire representation is the hashed input here, never a math oracle.
    encoded = json.loads(fe.f_json(checked))
    assert encoded['type'] == 'PreparedFRecords'
    direct = encoded['value']
    assert set(direct) == {'root_key', 'parents', 'records', 'dependencies', 'ticket', 'verification'}
    direct.pop('verification')
    expected_digest = digest(direct)
    assert verification.result_digest == expected_digest
    assert plain(verification.certificate) == {
        'contract': {'name': 'sui.f.records_verification', 'version': '2'},
        'value': {'ticket': plain(checked.ticket), 'prepared_digest': expected_digest,
                  'result_verification': plain(result_verification)}}




def test_v010_06_process_digest_input_assembly():
    from hashlib import sha256
    doc = limit_document()
    exact_bytes = b'{"args":{"index_origin":0},"name":"iid_fair_bits","version":"1"}'
    assert canonical(doc['process']) == exact_bytes
    expected = 'sha256:' + sha256(exact_bytes).hexdigest()
    assert doc['proof']['args']['process_digest'] == expected
    assert expected != digest({'type': 'LimitProcess', 'value': doc['process']})
    assert expected != digest(doc)


def test_v010_06_public_process_digest_matches_independent_hash():
    process = f.LimitProcess(name='iid_fair_bits', version='1', args=f.LimitProcessArgs(index_origin=0))
    assert f.limit_process_digest(process) == digest(limit_document()['process'])


@pytest.mark.parametrize('wrong', ['another_process', 'information_slope', 'cost_slope'])
def test_v010_06_wrong_process_or_slope_proof_rejected(wrong):
    doc = limit_document(both=True)
    if wrong == 'another_process':
        other_process = {**doc['process'], 'args': {'index_origin': 1}}
        doc['proof']['args']['process_digest'] = digest(other_process)
    else:
        assert doc['proof']['args']['process_digest'] == digest(doc['process'])
        doc['proof']['args'][wrong] = {'op': 'rational', 'value': [0, 1]}
    problem = fe.limit_problem_from_json(canonical(doc))
    with pytest.raises(f.FInputError) as caught: f.certify_f_limit(problem, budget=BUDGET)
    assert caught.value.reason == 'proof_mismatch'


@pytest.mark.parametrize('name', tuple(n for n in UNION_CASES if n not in ('due_unavailable', 'reservation_at', 'reservation_when', 'status_unavailable', 'status_available')))
def test_v010_07_union_input_assembly(name):
    value, contract, expected = union_case(name)
    assert isinstance(contract, ContractRef) and isinstance(expected, dict)
    assert json.loads(canonical(expected)) == expected
    if name == 'frame_clock':
        assert expected['actual_time']['kind'] == 'clock' and expected['value']['kind'] == 'value'
    elif name == 'frame_unavailable':
        assert expected['actual_time'] == expected['value'] == {
            'kind': 'unavailable', 'value': {'reason': 'not_measured', 'basis': []}}
    elif name == 'policy_own_kind':
        assert expected['value']['nodes'] == [{'id': 'arbitrary-end', 'kind': 'end'}]
    elif name == 'limit_own_kind':
        assert expected['cost'] == {'kind': 'blank'} and expected['proof'] is None
    elif name == 'exact_own_op':
        assert expected['value'] == {'op': 'rational', 'value': [1, 2]}


@pytest.mark.parametrize('name', tuple(n for n in UNION_CASES if n not in ('due_unavailable', 'reservation_at', 'reservation_when', 'status_unavailable', 'status_available')))
def test_v010_07_union_canonical_roundtrip(name):
    value, contract, expected = union_case(name)
    data = canonical(expected)
    assert fe.f_json(value) == data
    assert fe.f_from_json(data, contract=contract) == value


@pytest.mark.parametrize('bad,name,location', [
    (bad, name, location)
    for bad in ('unknown_tag', 'double_wrapper')
    for name, location in [
    ('frame_clock', ('actual_time',)), ('frame_clock', ('value',)),
    ('due_unavailable', ('value', 'due')),
    ('reservation_at', ('value', 'trigger')), ('coverage_claim', ()),
    ('policy_own_kind', ('value', 'nodes', 0)), ('limit_own_kind', ('cost',)),
    ('exact_own_op', ('value',))]
    if name not in ('due_unavailable', 'reservation_at', 'reservation_when', 'status_unavailable', 'status_available') and (bad, name, location) != ('double_wrapper', 'frame_clock', ('value',))])
def test_v010_07_unknown_tag_or_double_wrapper_rejected(name, location, bad):
    _, contract, data = union_case(name)
    cursor = data
    for key in location: cursor = cursor[key]
    original = deepcopy(cursor)
    cursor.clear()
    if bad == 'unknown_tag':
        cursor.update(original)
        cursor['op' if name == 'exact_own_op' else 'kind'] = 'unknown-tag'
    else:
        cursor.update({'kind': original.get('kind', 'value'), 'value': original})
    with pytest.raises(f.FInputError) as caught:
        fe.f_from_json(canonical(data), contract=contract)
    assert caught.value.reason == 'shape'


def test_v010_07_frame_raw_value_wrapper_shape_roundtrip():
    # §3-10-13-補: the outer union tag does not reserve shapes inside raw JSON.
    frame, contract, wire = union_case('frame_clock')
    raw = {'kind': 'value', 'value': 0}
    wire['value'] = {'kind': 'value', 'value': raw}
    data = canonical(wire)
    expected = replace(frame, value=raw)
    decoded = fe.f_from_json(data, contract=contract)
    assert decoded == expected
    assert plain(decoded.value) == raw
    assert fe.f_json(decoded) == data
    assert fe.f_json(expected) == data


def test_v010_07_unknown_value_type_and_version_rejected():
    with pytest.raises(f.FInputError) as caught:
        fe.f_from_json(canonical({'type': 'UnregisteredPythonClass', 'value': {}}), contract=fc.VALUE_FACTS)
    assert caught.value.reason == 'shape'
    with pytest.raises(f.FInputError) as caught:
        fe.f_from_json(canonical({'type': 'ClockReading', 'value': {'run': 'run:x', 'time_ns': 0}}),
                       contract=ContractRef(fc.VALUE_FACTS.name, '999'))
    assert caught.value.reason == 'unknown_version'


def test_v010_08_FA16_same_physical_paths_and_available_information():
    roots = [make_root(make_case('FA16', variant)) for variant in ('composite', 'split')]
    assert roots[0].model_ref == roots[1].model_ref
    assert roots[0].problem_key != roots[1].problem_key
    projections = []
    for root, first_completed in zip(roots, (False, True)):
        prefix = f.enumerate_f_prefix(root, steps=1, budget=BUDGET)
        assert prefix.rows == ()
        waiting, = prefix.frontier
        assert exact_rational(waiting.probability) == 1
        assert waiting.E.links == () and waiting.K.available == ()
        assert waiting.position.elapsed_ns == SECOND
        assert waiting.position.first_completed is first_completed
        table = f.enumerate_f_paths(root, budget=BUDGET)
        assert_path_table(table, root, complete=True)
        rows = sorted(table.rows, key=lambda row: tuple(exact_rational(x) for x in row.joint_target))
        assert [tuple(exact_rational(x) for x in row.joint_target) for row in rows] == [
            (Decimal(0), Decimal('0.5')), (Decimal('0.5'), Decimal(0))]
        projected_rows = []
        for row in rows:
            assert exact_rational(row.probability) == Decimal('0.5')
            physical = [a.args['path_action'] for a in row.actions if a.args['path_action'] is not None]
            assert physical == ['W', 'M']
            assert row.terminal.kind == 'ended'
            assert row.terminal.position.elapsed_ns == SECOND
            assert row.terminal.position.first_completed is True and row.terminal.position.stack == ()
            assert row.E_trace[0].links == () and row.K_trace[0].available == ()
            final_E, final_K = row.E_trace[-1], row.K_trace[-1]
            link, = final_E.links
            assert final_K.available == (link.measurement,)
            assert final_K.pending == ()
            # Control-only packaging may repeat a snapshot, but cannot add evidence/Thought.
            assert all(not e.links or e.links == final_E.links for e in row.E_trace)
            assert all(not k.available or k.available == final_K.available for k in row.K_trace)
            projected_rows.append((plain(final_E.links), plain(final_E.coverage), plain(final_E.gaps),
                                   plain(final_K.available), plain(final_K.incorporated), physical))
        projections.append(projected_rows)
    assert projections[0] == projections[1]


@pytest.mark.parametrize('handle', [f.FRegistry, f.FResources, f.FResolved])
def test_v010_factory_only_handles_are_not_public_injection_points(handle):
    with pytest.raises(TypeError): handle()


def test_v010_replay_mismatch_valid_fields_assembly():
    error = f.FReplayMismatch('result_mismatch', 'changed', '/root', fields=('/root', '/u'))
    assert error.reason == 'result_mismatch' and error.detail == 'changed'
    assert error.field == '/root' and error.fields == ('/root', '/u')


def test_v010_replay_mismatch_includes_primary_field():
    # §3-10-13-1 line 2128: non-null field must be present in fields.
    error = f.FReplayMismatch('result_mismatch', field='/root')
    assert error.field == '/root' and error.fields == ('/root',)


def test_v010_replay_mismatch_rejects_invalid_pointer():
    # §3-10-13-1 line 2128: malformed JSON Pointer -> FInputError(shape).
    with pytest.raises(f.FInputError) as caught:
        f.FReplayMismatch('result_mismatch', fields=('not-a-json-pointer',))
    assert caught.value.reason == 'shape'


@pytest.mark.parametrize('u,chosen', [(F(1, 6), 'Q'), (F(2, 3), 'M')])
def test_FA14_quiet_selected_constant_false(u, chosen):
    # GF-M23; §3-0-7 / §3-10-3: explicit never-ending quiet is selectable.
    case = make_case('FA14')
    quiet, measurement = case.actions
    quiet = replace(quiet, termination=predicate(False), termination_kind='may_never')
    semantic_fields = ('family', 'args', 'start', 'policy', 'termination',
                       'termination_kind', 'prediction', 'execution')
    quiet = replace(quiet, semantic_key=digest({key: getattr(quiet, key) for key in semantic_fields}))
    case.actions = (quiet, measurement)
    case.document['operations'] = plain(case.actions)
    case.model = FModel(declaration=canonical(case.document))
    root = make_root(case, u=u)
    assert root.scope.name == 'unbounded_total'
    assert quiet.termination == predicate(False) and quiet.termination_kind == 'may_never'
    result = f.evaluate_f(root, budget=BUDGET)
    assert_selected(result, root, chosen, u)  # NoDecision is not chosen quiet.
    assert result.evaluation.candidates == tuple(FIXED['FA14']['order'])
    for i, name in enumerate(FIXED['FA14']['order']):
        assert_quantity(result.evaluation.G[i], FIXED['FA14'][f'G_{name}'])
        assert_quantity(result.evaluation.q_star[i], FIXED['FA14']['q'][i])


def assert_commit_keeps_prepared_parents(case, prepared, *, phase):
    # GF-M41; §3-10-12-9: after orders storage, parents are already frozen.
    frozen_parents = {item.record.id: item.parents for item in prepared.records}
    assert frozen_parents
    case.clock.advance(1)
    late = append_record(case.ledger, case.clock, case.ids, Observed(
        route='fixture-late-fact', content=Payload.json({'arrived_after_preparation': phase}),
        contract=ContractRef('fixture.late_fact', '1'), received_ns=case.clock.mono_ns()))
    late_entry, = case.ledger.entries_of(late.id)
    assert late.category is Category.FACT
    assert case.ledger.heads() == frozenset({late_entry.cid})
    assert all(late_entry.cid not in parents and parents != case.ledger.heads()
               for parents in frozen_parents.values())
    fe.commit_f(prepared, ledger=case.ledger)
    for item in prepared.records:
        saved, = case.ledger.entries_of(item.record.id)
        assert saved.parents == frozen_parents[item.record.id]
        assert late_entry.cid not in saved.parents
        assert late_entry.cid not in case.ledger.ancestors((saved.cid,))
        assert case.ledger.record(saved.cid) == item.record
    assert {item.record.id: item.parents for item in prepared.records} == frozen_parents
    before_retry = case.ledger.entries()
    fe.commit_f(prepared, ledger=case.ledger)
    assert case.ledger.entries() == before_retry








def test_review_F05_choice_uses_the_frozen_draw_and_accepts_equal_float():
    root = make_root(make_case('FA19'), u=F(1, 2))
    evaluation = f.evaluate_f_recursive(root, budget=BUDGET)
    with pytest.raises(f.FInputError):
        f.certify_f_choice(evaluation, u=F(1, 10))
    assert_selected(f.certify_f_choice(evaluation, u=0.5), root, 'M', F(1, 2))


@pytest.mark.parametrize('bad_kind', ['midpoint', 'below', 'above'])
def test_review_F07_rejects_non_enclosing_ln2_bounds(bad_kind):
    oracle = FIXED['FA15']['one_perfect_measurement']
    low, high = reference_interval(oracle)
    good = f.FQuantity(status='finite', exact=f.ExactReal(op='log',
        arg=f.ExactReal(op='rational', value=F(2))), bounds=RationalInterval(low, high),
        proof=None, reason=None)
    assert_quantity(good, oracle)
    # These are rational intervals strictly excluding irrational ln2, even though
    # their errors are much smaller than the former 1e-24 comparison margin.
    delta = F(1, 10**100)
    midpoint = (low+high)/2
    bad_bounds = {'midpoint': (midpoint, midpoint), 'below': (low-2*delta, low-delta),
                  'above': (high+delta, high+2*delta)}[bad_kind]
    with pytest.raises(AssertionError):
        assert_quantity(replace(good, bounds=RationalInterval(*bad_bounds)), oracle)


def test_review_F07_real_output_midpoint_is_not_a_guaranteed_interval():
    evaluation = f.evaluate_f_recursive(make_root(make_case('FA15')), budget=BUDGET)
    quantity = evaluation.information[0].additional
    assert_quantity(quantity, FIXED['FA15']['one_perfect_measurement'])
    midpoint = (quantity.bounds.lower+quantity.bounds.upper)/2
    with pytest.raises(AssertionError):
        assert_quantity(replace(quantity, bounds=RationalInterval(midpoint, midpoint)),
                        FIXED['FA15']['one_perfect_measurement'])


def test_review_F07_independent_log_oracle_handles_sign_and_exact_rationals():
    l2, h2 = independent_log_bounds(F(2))
    assert F(69, 100) < l2 < h2 < F(7, 10)
    assert h2-l2 < F(1, 10**100)
    assert independent_log_bounds(F(1, 2)) == (-h2, -l2)
    mixed = {'coeffs': {'2': [1, 1], '3': [-1, 1]}}
    low, high = reference_interval(mixed)
    l3, h3 = independent_log_bounds(F(3))
    assert (low, high) == (l2-h3, h2-l3)
    for rational_value in (F(0), F(1, 3), F(2)):
        assert reference_interval(rational_value) == (rational_value, rational_value)


# v0.11 structural contract (§3-10-14-11). These fixtures only construct public data.
def structure_model(case, kernels, actions, policies):
    case.actions = tuple(actions)
    case.document = declaration(kernels, case.actions, policies)
    case.continuation = continuation_for(case.actions)
    case.model = FModel(declaration=canonical(case.document))
    return case


def structure_refresh_model(case):
    case.model = FModel(declaration=canonical(case.document))
    refreshed = []
    for original in case.actions:
        wire = next(op for op in case.document['operations'] if op['id'] == original.id)
        changes = {}
        for key in ('family', 'start', 'policy', 'termination', 'prediction', 'execution', 'proof'):
            if plain(getattr(original, key)) != wire[key]:
                changes[key] = type(getattr(original, key))(**wire[key])
        for key in ('args', 'termination_kind', 'semantic_key'):
            if plain(getattr(original, key)) != wire[key]: changes[key] = wire[key]
        refreshed.append(replace(original, **changes))
    case.actions = tuple(refreshed)
    return case


def structure_semantic_key(operation):
    keys = ('family', 'args', 'start', 'policy', 'termination', 'termination_kind', 'prediction', 'execution')
    operation['semantic_key'] = digest({key: operation[key] for key in keys})


def structure_hidden_case(variant='split'):
    case = make_case('FA08')
    if variant == 'merged':
        hidden = idle_kernel('hidden')
    else:
        hidden = {'id': 'hidden', 'outcomes': [
            outcome('hidden-0', diagonal((1, 0))), outcome('hidden-1', diagonal((0, 1)))]}
        if variant == 'refined':
            hidden['outcomes'] = [outcome('h0a', diagonal((F(1, 3), 0))),
                outcome('h0b', diagonal((F(2, 3), 0))), outcome('h1', diagonal((0, 1)))]
        if variant == 'reordered':
            hidden['outcomes'].reverse()
            for i, part in enumerate(hidden['outcomes']): part['id'] = 'renamed-'+str(i)
        if variant == 'completion':
            hidden['outcomes'][0]['completion'] = False
        if variant == 'unproved_computation':
            for i, part in enumerate(hidden['outcomes']): part['available']['computation'] = {'bit': i}
    quiet = idle_kernel('quiet')
    return structure_model(case, [hidden, quiet], [action('H', 'hidden'), action('Q', 'quiet')],
                           [policy('H', hidden), policy('Q', quiet)])


def structure_alias_child(case, *, conflict=False):
    child = next(op for op in case.document['operations'] if op['id'] == 'M2')
    alias = deepcopy(child); alias['id'] = 'alias-M2'
    case.document['operations'].append(alias)
    for p in case.document['policies']:
        for node in list(p['nodes']):
            if node['kind'] == 'choose' and 'M2' in node['operations']:
                node['operations'].insert(node['operations'].index('M2')+1, alias['id'])
                node['next'][alias['id']] = 'other-end' if conflict else node['next']['M2']
                if conflict: p['nodes'].append({'id': 'other-end', 'kind': 'end'})
    return structure_refresh_model(case)


def structure_loop_case(*, zero=False, unknown=False):
    kernel = idle_kernel('quiet', elapsed=0 if zero else SECOND, completion=False)
    op = action('Q', 'quiet', never=True)
    if unknown:
        op = replace(op, termination=f.PredicateRef(name='fixture.unknown_end', version='1', args={}))
        wire = plain(op); structure_semantic_key(wire)
        op = replace(op, semantic_key=wire['semantic_key'])
    return structure_model(make_case('FA08'), [kernel], [op], [policy('Q', kernel, loop=True)])


def structure_c1_inputs():
    world, model, records, context, report = c1_case()
    resource = fe.make_f_resources(models=(model,), records=records, registry=f.builtin_f_registry(), ledger=world.ledger)
    read = fe.read_c1_frames(model, records, context=context, resources=resource)
    summary = f.initial_c1_summary(model, run=world.clock.run, origin_ns=0)
    for frame in read.frames: summary = f.update_c1_summary(summary, frame=frame)
    return world, model, records, context, report, read, summary


@pytest.mark.parametrize('past_window', [False, True])
def test_review_F14_new_delivery_record_preserves_measurement_and_extends_provenance(past_window):
    world, model, records, context, report, read, summary = structure_c1_inputs()
    original = next(r for r in records if r.id == read.frames[0 if past_window else 1].source_record)
    duplicate = replace(original, id=world.ids.new(original.id.kind))
    world.ledger.append(duplicate, world.ledger.entries_of(original.id)[0].parents)
    resource = fe.make_f_resources(models=(model,), records=records+(duplicate,),
                                  registry=f.builtin_f_registry(), ledger=world.ledger)
    reread = fe.read_c1_frames(model, (duplicate,), context=context, resources=resource)
    frame, = reread.frames
    assert frame.measurement_id == read.frames[0 if past_window else 1].measurement_id
    updated = f.update_c1_summary(summary, frame=frame)
    for field in ('N','T_s','A0','A1','probe_counts','measurement_ids','probe_measurements','end_ns'):
        assert getattr(updated, field) == getattr(summary, field)
    assert original.id in updated.source_records and duplicate.id in updated.source_records
    assert duplicate.id not in summary.source_records
    assert f.update_c1_summary(updated, frame=frame) == updated


def test_review_F14_conflicting_count_with_same_measurement_is_rejected():
    world, model, records, context, report, read, summary = structure_c1_inputs()
    data = report.body.content.as_json(); data['arrival_count'] = {'kind': 'exact', 'value': 1}
    conflicting = replace(report, id=world.ids.new(report.id.kind), body=replace(report.body, content=Payload.json(data)))
    resource = fe.make_f_resources(models=(model,), records=records+(conflicting,),
                                  registry=f.builtin_f_registry(), ledger=world.ledger)
    with pytest.raises(f.FInputError) as caught:
        frame, = fe.read_c1_frames(model, (conflicting,), context=context, resources=resource).frames
        f.update_c1_summary(summary, frame=frame)
    assert caught.value.reason == 'measurement_conflict'
    assert (summary.N, summary.T_s) == (1, F(2))



def structure_rootless_context(case, *, name='fixture.absent'):
    request = f.FPreflight(parents=case.ledger.heads(), model_ref=None, required_records=(),
        required_capabilities=(f.RequiredCapability(kind='predicate', ref=ContractRef(name, '1'),
                                                    implementation_required=True),))
    resource = resources(case)
    context = fe.FResultContext(attempt=None, input=request)
    result = f.check_f_preflight(request, resources=resource)
    verification = fe.verify_f_result(result, context=context, resources=resource, budget=BUDGET)
    return context, result, verification


def structure_firing(case):
    return fr.Firing(policy_generation='g-structure', firing_id='f-structure', reply_index=0,
                     source='internal', basis=(), detected=f.ClockReading(run=case.clock.run, time_ns=0))








def structure_quantities():
    case = make_case('FA08'); resource = resources(case); E, K = histories(case)
    pairs = [f.certify_f_quantity(definition=f.FQuantityDefinition(kind='rational_constant',
        value=F(value), unit='nat', provenance=()), evaluation=None, resources=resource) for value in (0, 1)]
    snapshot = f.PredicateSnapshot(model_ref=None, E=E, K=K, quantities=dict(pairs),
                                   dependencies=(), policy_position=None)
    predicate_ref = f.PredicateRef(name='interval_compare', version='1', args={
        'left': plain(pairs[0][0]), 'relation': 'lt', 'right': plain(pairs[1][0]), 'provenance': []})
    return case, resource, snapshot, predicate_ref, pairs


@pytest.mark.parametrize('wrapper', ['direct', 'and', 'or', 'not', 'and-short-circuit', 'or-short-circuit'])
def test_review_F16_inconsistent_quantity_rejected_inside_logical_children(wrapper):
    case, resource, snapshot, pred, pairs = structure_quantities()
    left, good = pairs[0]
    bad = replace(good, exact=f.ExactReal(op='rational', value=F(2)), proof=None)
    snapshot = replace(snapshot, quantities={left: bad, pairs[1][0]: pairs[1][1]})
    if wrapper in ('and', 'or'):
        pred = f.PredicateRef(name=wrapper, version='1', args={'terms': [plain(pred), plain(predicate(wrapper == 'and'))]})
    elif wrapper == 'not': pred = f.PredicateRef(name='not', version='1', args={'term': plain(pred)})
    elif wrapper.endswith('-short-circuit'):
        operator = wrapper.split('-')[0]
        pred = f.PredicateRef(name=operator, version='1', args={
            'terms': [plain(predicate(operator == 'or')), plain(pred)]})
    with pytest.raises(f.FInputError) as caught: f.check_predicate(pred, snapshot=snapshot, resources=resource)
    assert caught.value.reason == 'quantity_inconsistent'


def test_review_F16_issued_quantities_compare_but_decoded_or_handmade_values_need_work():
    case, resource, snapshot, pred, pairs = structure_quantities()
    result = f.check_predicate(pred, snapshot=snapshot, resources=resource)
    assert result.value == 'true' and result.work is None and result.missing == ()
    for quantities in (
        {ref: replace(q, proof=None) for ref, q in pairs},
        {ref: fe.f_from_json(fe.f_json(q), contract=fc.VALUE_FACTS) for ref, q in pairs}):
        unissued = replace(snapshot, quantities=quantities)
        result = f.check_predicate(pred, snapshot=unissued, resources=resource)
        assert result.value == 'unknown' and result.missing and result.work is not None


@pytest.mark.parametrize('mutation', ['exact', 'bounds', 'key', 'unit', 'provenance'])
def test_review_F16_quantity_authentication_cannot_be_transferred(mutation):
    case, resource, snapshot, pred, pairs = structure_quantities()
    ref, quantity = pairs[0]
    if mutation == 'exact': quantity = replace(quantity, exact=f.ExactReal(op='rational', value=F(2)))
    elif mutation == 'bounds': quantity = replace(quantity, bounds=RationalInterval(F(2), F(2)))
    elif mutation == 'key':
        ref = f.QuantityRef(key='sha256:'+'f'*64)
        pred = replace(pred, args={**pred.args, 'left': plain(ref)})
    else:
        args = deepcopy(plain(quantity.proof)['args'])
        if mutation == 'unit':
            args['definition']['unit'] = 'dimensionless'; args['unit'] = 'dimensionless'
        else: args['definition']['provenance'] = ['observation:not-the-certified-source']
        quantity = replace(quantity, proof=replace(quantity.proof, args=args))
    changed = replace(snapshot, quantities={ref: quantity, pairs[1][0]: pairs[1][1]})
    with pytest.raises(f.FInputError) as caught: f.check_predicate(pred, snapshot=changed, resources=resource)
    assert caught.value.reason == ('quantity_inconsistent' if mutation in ('exact', 'bounds') else 'quantity_binding_conflict')


def test_review_F16_evaluation_quantity_is_bound_to_root_query_and_unit():
    case = make_case('FA08'); root = make_root(case); resource = resources(case)
    evaluation = f.evaluate_f_recursive(root, budget=BUDGET)
    definition = f.FQuantityDefinition(kind='evaluation', root_key=root.root_key, field='q_star', candidate='Q')
    ref, quantity = f.certify_f_quantity(definition=definition, evaluation=evaluation, resources=resource)
    assert ref.key == digest({'kind': 'evaluation', 'root_key': root.root_key, 'field': 'q_star', 'candidate': 'Q'})
    assert_quantity(quantity, F(1, 2))
    for changed in (replace(definition, root_key='sha256:'+'e'*64), replace(definition, candidate='not-a-candidate')):
        with pytest.raises(f.FInputError) as caught:
            f.certify_f_quantity(definition=changed, evaluation=evaluation, resources=resource)
        assert caught.value.reason == 'quantity_binding_conflict'
    threshold, one = f.certify_f_quantity(definition=f.FQuantityDefinition(kind='rational_constant',
        value=F(1), unit='dimensionless', provenance=()), evaluation=None, resources=resource)
    snapshot = f.PredicateSnapshot(model_ref=root.model_ref, E=root.E, K=root.K,
        quantities={ref: quantity, threshold: one}, dependencies=(), policy_position=None)
    pred = f.PredicateRef(name='interval_compare', version='1', args={
        'left': plain(ref), 'right': plain(threshold), 'relation': 'lt', 'provenance': []})
    assert f.check_predicate(pred, snapshot=snapshot, resources=resource).value == 'true'
    for field, value in (('root_key', 'sha256:'+'d'*64), ('candidate', 'M')):
        args = deepcopy(plain(quantity.proof)['args']); args['definition'][field] = value
        changed = replace(quantity, proof=replace(quantity.proof, args=args))
        with pytest.raises(f.FInputError) as caught:
            f.check_predicate(pred, snapshot=replace(snapshot, quantities={ref: changed, threshold: one}), resources=resource)
        assert caught.value.reason == 'quantity_binding_conflict'


STRUCTURE_MATH_ENTRIES = ('certify_f_scope', 'enumerate_f_paths', 'enumerate_f_prefix',
    'evaluate_f_enumerated', 'evaluate_f_recursive', 'evaluate_f_prefix', 'certify_f_tail',
    'certify_f_choice', 'evaluate_f', 'computation_information')


def test_structure_A_evaluator_import_direction_and_public_entry_inventory():
    import ast
    import inspect
    source = Path(__file__).resolve().parents[1]/'src/sui/_f_eval.py'
    # Only import statements are inspected; never implementation expressions/bodies.
    imports = [node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8-sig')))
               if isinstance(node, (ast.Import, ast.ImportFrom))]
    forbidden_modules = {'f_model', 'f_entry', '_f_world', 'model'}
    forbidden_names = {'FModel', 'FResources', 'FRegistry', 'f_model_from_json', 'f_model_json',
                       'make_f_resources', 'builtin_f_registry', 'prepare_f_problem', 'prepare_f_request'}
    for node in imports:
        module = getattr(node, 'module', '') or ''
        assert module.rsplit('.', 1)[-1] not in forbidden_modules
        for alias in node.names:
            assert alias.name != '*' and alias.name.rsplit('.', 1)[-1] not in forbidden_modules | forbidden_names
    assert any(getattr(node, 'module', '') == '_f_handles' for node in imports)
    # §14-4 is the maintained public entry list; every listed signature remains callable.
    for name in STRUCTURE_MATH_ENTRIES:
        signature = inspect.signature(getattr(f, name))
        assert ('evaluation' if name == 'certify_f_choice' else 'root') in signature.parameters


@pytest.mark.parametrize('entry', ['scope','paths','prefix','recursive','enumerated','prefix-evaluation','tail','evaluate','computation'])
def test_structure_A_unissued_root_is_rejected_by_every_math_entry(entry):
    root = make_root(make_case('FA08'))
    unissued = fe.f_from_json(fe.f_json(root), contract=fc.ROOT_FACTS)
    prefix = f.enumerate_f_prefix(root, steps=0, budget=BUDGET)
    calls = {'scope': lambda: f.certify_f_scope(unissued, budget=BUDGET),
        'paths': lambda: f.enumerate_f_paths(unissued, budget=BUDGET),
        'prefix': lambda: f.enumerate_f_prefix(unissued, steps=0, budget=BUDGET),
        'recursive': lambda: f.evaluate_f_recursive(unissued, budget=BUDGET),
        'enumerated': lambda: f.evaluate_f_enumerated(unissued, f.enumerate_f_paths(root, budget=BUDGET), budget=BUDGET),
        'evaluate': lambda: f.evaluate_f(unissued, budget=BUDGET),
        'computation': lambda: f.computation_information(unissued, computation=f.ComputationSpec(
            method=ContractRef('sui.f.computation_information', '1'), input_measurements=(), input_records=(),
            algorithm_draws=(), output_contract=fc.BELIEF), budget=BUDGET),
        'prefix-evaluation': lambda: f.evaluate_f_prefix(unissued, steps=0, budget=BUDGET),
        'tail': lambda: f.certify_f_tail(unissued, candidate='Q', prefix=prefix, budget=BUDGET)}
    with pytest.raises((f.FInputError, f.FReplayMismatch)): calls[entry]()


@pytest.mark.parametrize('mutation', ['decoded','q','Z','cumulative','other-certificate'])
def test_structure_B_choice_rejects_unissued_or_modified_evaluation(mutation):
    case = make_case('FA08'); root = make_root(case)
    evaluation = f.evaluate_f_recursive(root, budget=BUDGET)
    if mutation == 'decoded': changed = fe.f_from_json(fe.f_json(evaluation), contract=fc.EVALUATION)
    elif mutation == 'q': changed = replace(evaluation, q_star=tuple(reversed((evaluation.q_star[0],
        replace(evaluation.q_star[1], bounds=RationalInterval(F(0), F(0)))))))
    elif mutation == 'Z': changed = replace(evaluation, normalization=replace(evaluation.normalization, Z=RationalInterval(F(1), F(1))))
    elif mutation == 'cumulative': changed = replace(evaluation, cumulative=(RationalInterval(F(0), F(0)),)*3)
    else:
        other = f.evaluate_f_recursive(make_root(make_case('FA15')), budget=BUDGET)
        changed = replace(evaluation, certificate=other.certificate)
    with pytest.raises((f.FInputError, f.FReplayMismatch)):
        f.certify_f_choice(changed, u=F(1, 2))


def test_structure_B_tables_and_tail_cannot_cross_worlds_or_content_changes():
    root = make_root(make_case('FA08')); other = make_root(make_case('FA15'))
    paths = f.enumerate_f_paths(root, budget=BUDGET)
    prefix = f.enumerate_f_prefix(root, steps=0, budget=BUDGET)
    decoded = fe.f_from_json(fe.f_json(paths), contract=fc.VALUE_FACTS)
    checked = f.evaluate_f_enumerated(root, decoded, budget=BUDGET)
    for q in checked.q_star: assert_quantity(q, F(1, 2))
    for changed in (replace(paths, rows=()), replace(decoded, rows=())):
        with pytest.raises((f.FInputError, f.FReplayMismatch)):
            f.evaluate_f_enumerated(root, changed, budget=BUDGET)
    with pytest.raises((f.FInputError, f.FReplayMismatch)):
        f.evaluate_f_enumerated(other, paths, budget=BUDGET)
    with pytest.raises((f.FInputError, f.FReplayMismatch)):
        f.certify_f_tail(other, candidate='M', prefix=prefix, budget=BUDGET)


def structure_nested_alias_case(depth, insert_aliases):
    case = make_case('FA08')
    kernels = [idle_kernel('quiet', elapsed=1)]
    operations = [action(f'L{level}{side}', 'quiet') for level in range(depth+1) for side in ('a', 'b')]
    aliases = [replace(op, id=op.id+'-alias') for op in operations] if insert_aliases else []
    policies = []
    for op in operations:
        level = int(op.id[1:-1])
        nodes = [execute('tick', 'quiet', ['done'], 'end' if level == depth else 'choose'),
                 {'id': 'end', 'kind': 'end'}]
        if level < depth:
            children = [f'L{level+1}a', f'L{level+1}b']
            if insert_aliases: children = [name for child in children for name in (child, child+'-alias')]
            nodes.insert(1, {'id': 'choose', 'kind': 'choose', 'operations': children,
                             'rule': plain(fc.SOFT_CHOICE), 'next': {name: 'end' for name in children}})
        policies.append({'id': op.id, 'entry': 'tick', 'nodes': nodes})
    structure_model(case, kernels, tuple(operations+aliases), policies)
    case.actions = tuple(op for op in operations+aliases if op.id.startswith('L0'))
    case.continuation = continuation_for(tuple(op for op in operations if op.id.startswith('L0')))
    return case


def test_structure_C5_equal_independent_c1_measurements_are_counted_twice():
    world, model, records, context, _ = c1_case('11')
    resource = fe.make_f_resources(models=(model,), records=records, registry=f.builtin_f_registry(), ledger=world.ledger)
    frames = fe.read_c1_frames(model, records, context=context, resources=resource).frames
    assert len(frames) == 2 and frames[0].measurement_id != frames[1].measurement_id
    assert frames[0].count == frames[1].count == 1
    summary = f.initial_c1_summary(model, run=world.clock.run, origin_ns=0)
    once = f.update_c1_summary(summary, frame=frames[0])
    twice = f.update_c1_summary(once, frame=frames[1])
    assert once.N == 1 and twice.N == 2 and twice.T_s == 2
    assert twice.measurement_ids == tuple(frame.measurement_id for frame in frames)
    assert f.update_c1_summary(twice, frame=frames[0]) == twice


STRUCTURE_STYLE = {'kind': 'style', 'scope': {'name': 'unbounded_total', 'version': '1', 'H_ns': None}, 'gamma': [1, 1]}
STRUCTURE_ITEM = {'kind': 'item', 'rule': {'name': 'table', 'version': '1'},
                  'args': {'feature': {'name': 'constant', 'version': '1'}, 'probs': [[None, 1.0]]}}


def structure_assert_causality(case, causality):
    view = from_ledger(case.ledger, case.ledger.heads())
    assert [(point.cid, point.record) for point in causality.points] == sorted(
        [(point.cid, point.id) for point in view.points], key=lambda pair: (str(pair[1]), pair[0]))
    assert causality.before == tuple(sorted(view.before, key=lambda edge: tuple(map(str, edge))))


def structure_conflicting_styles():
    case = make_case('FA08'); request = world_request(case)
    resolved = fe.resolve_f_preferences(from_ledger(case.ledger, case.ledger.heads()), resources=resources(case))
    add_preference(case, STRUCTURE_STYLE, fc.STYLE, parents=())
    add_preference(case, {**STRUCTURE_STYLE, 'gamma': [2, 1]}, fc.STYLE, parents=())
    return case, replace(request, parents=case.ledger.heads(), records=tuple(r.id for r in case.records),
                         context=case.context), resolved


def structure_saved_selection():
    case = make_case('FA08'); root = make_root(case); started = begin_attempt(case, root=root)
    fe.commit_f(fe.verify_f_records(started, resources=resources(case), budget=BUDGET), ledger=case.ledger)
    case.records = all_records(case.ledger); resource = resources(case)
    result = f.evaluate_f(root, budget=BUDGET)
    context = fe.FResultContext(attempt=started.ticket, input=root)
    verification = fe.verify_f_result(result, context=context, resources=resource, budget=BUDGET)
    prepared = fe.make_f_records(result, attempt=started.ticket, verification=verification,
        clock=case.clock, ids=case.ids, producer=PRODUCER, membrane=PRODUCER)
    fe.commit_f(fe.verify_f_records(prepared, resources=resource, budget=BUDGET), ledger=case.ledger)
    decided, = [r.record for r in prepared.records if isinstance(r.record.body, Decided)]
    return case, result, context, verification, prepared, case.ledger.entries_of(decided.id)[0].cid







# §3-10-14-11 audit map. Existing FA tests are retained and are part of coverage.
# A: test_structure_A_*; B: test_structure_B_* plus review_F10/F11/F12/F14/F15/F16,
# review_F05 (other u), extra09/v010_05 commit parents, preference_*.
# C1/2: review_F09 variants; C3: structure_C3; C4: structure_C4 + review_F06;
# C5: FA05 + structure_C5 + review_F14; C6: review_F13; C7: review_F15 sequences;
# C8: review_F16; C9: structure_C9 (fixed z_shift_property).


# Review 3: inputs come from the report and §3-10-14, never implementation bodies.
def review3_roundtrip(value, through_json, contract=fc.VALUE_FACTS):
    return fe.f_from_json(fe.f_json(value), contract=contract) if through_json else value


def review3_freeze(problem, u=F(1, 4)):
    source = ScriptedSource(({'u': plain(u)},))
    draw = draw_book({'selection': source}).for_selection(problem, request_id='review3')
    root = fe.freeze_root(problem, selection_draw=draw)
    assert len(source.calls) == 1
    return root


def review3_rebase_root(root, request, *, records=None):
    """Construct a structural root from a legitimate numerical control world.

    Rebase only the claimed ledger frontier/context. Digest formulas are checked
    against an unchanged public root first; no evaluator/factory state is injected.
    The forged value remains unissued and is submitted only to restore/verify.
    """
    wire = json.loads(fe.f_json(root))
    # 今の約束 E-05 (2026-10-11): drop the root-only fields and restore the
    # problem contract (root/2 -> problem/2) to recover the problem's key.
    assert root.problem_key == digest({**{k: v for k, v in wire.items()
        if k not in ('problem_key', 'root_key', 'selection_draw', 'draw_point', 'draw_record_digest')},
        'contract': {'name': 'sui.f.problem', 'version': '2'}})
    assert root.root_key == digest({'problem_key': root.problem_key, 'selection_draw': wire['selection_draw']})
    wire['world_manifest']['request'] = plain(request)
    if records is not None:
        material={str(record.id):review4_record_digest(record) for record in records}
        for dependency in wire['world_manifest']['dependencies']['records']:
            dependency['digest']=material[dependency['ref']]
    for field in ('parents', 'context', 'E', 'K', 'candidates', 'continuation'):
        wire[field] = plain(getattr(request, field))
    wire['world_key'] = digest({'domain': 'sui.f.world/1', 'manifest': wire['world_manifest']})
    wire['problem_key'] = digest({**{k: v for k, v in wire.items()
        if k not in ('problem_key', 'root_key', 'selection_draw', 'draw_point', 'draw_record_digest')},
        'contract': {'name': 'sui.f.problem', 'version': '2'}})
    wire['selection_draw']['context_key'] = wire['problem_key']
    wire['selection_draw']['request']['context_key'] = wire['problem_key']
    wire['root_key'] = digest({'problem_key': wire['problem_key'], 'selection_draw': wire['selection_draw']})
    return fe.f_from_json(canonical(wire), contract=fc.ROOT_FACTS)


def review3_rebase_result(result, root):
    old = result.root
    substitutions = {old.root_key: root.root_key, old.problem_key: root.problem_key, old.world_key: root.world_key}
    def rewrite(value):
        if isinstance(value, dict):
            if value.get('root_key') == old.root_key and 'world_manifest' in value:
                return plain(root)
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list): return [rewrite(item) for item in value]
        return substitutions.get(value, value) if isinstance(value, str) else value
    return fe.f_from_json(canonical(rewrite(json.loads(fe.f_json(result)))), contract=fc.VALUE_FACTS)


@pytest.fixture(scope='module')
def review3_fact_worlds():
    original = make_case('FA05'); resource = resources(original)
    request = world_request(original, resource=resource)
    root = review3_freeze(make_problem(original)); selected = f.evaluate_f(root, budget=BUDGET)
    assert isinstance(selected, f.Selected) and len(root.E.links) == 1
    variants = {}
    for fault in ('omitted-facts', 'substituted-records'):
        records = []
        for record in original.records:
            if fault == 'omitted-facts' and record.category is Category.FACT: continue
            if fault == 'substituted-records' and record.body.contract in (fc.MEASUREMENT, fc.OBSERVATION_BINDING):
                data = record.body.content.as_json()
                if record.body.contract == fc.MEASUREMENT: data['value']['value'] = 1
                else: data['cell'] = 'cell-1'
                record = replace(record, body=replace(record.body, content=Payload.json(data)))
            records.append(record)
        # A separate, honest ledger supplies a positive numerical control with
        # precisely these measurements. The attack pairs its claim with the OLD ledger.
        ledger = make_case('FA08').ledger
        for record in sorted(records, key=lambda r: r.at.seq): ledger.append(record, ledger.heads())
        witness = replace(original, ledger=ledger, records=tuple(records), context=context_for(ledger, original.clock))
        witness_root = review3_freeze(make_problem(witness))
        witness_result = f.evaluate_f(witness_root, budget=BUDGET)
        assert isinstance(witness_result, f.Selected)
        claimed_context = (replace(request.context, fact_ancestors={cid: frozenset() for cid in request.context.fact_ancestors})
                           if fault == 'omitted-facts' else request.context)
        witness_request = world_request(witness)
        forged_request = replace(witness_request, parents=request.parents, context=claimed_context)
        forged_root = review3_rebase_root(witness_root, forged_request)
        variants[fault] = (tuple(records), forged_request, forged_root, review3_rebase_result(witness_result, forged_root))
    return original, resource, request, root, selected, variants


def review3_missing_kernel():
    case = make_case('FA08'); current = resources(case); base = current.registry
    registry = f.make_f_registry(declarations=base.declarations,
        implementations=tuple(i for i in base.implementations if i.kind != 'kernel'))
    old = fe.make_f_resources(models=(case.model,), records=case.records, registry=registry, ledger=case.ledger)
    preparation, result = fe.prepare_f_request(world_request(case), resources=old, budget=BUDGET)
    assert isinstance(result, f.NoDecision) and (result.outcome, result.reason) == ('incomplete', 'algorithm_unavailable')
    assert result.root_key is None
    kernel, = [d for d in preparation.dependencies.capabilities if d.kind == 'kernel']
    assert kernel.declaration is not None and kernel.implemented is False
    return case, old, current, preparation, result


# Review 4 / §3-10-14-補2: same labels do not authenticate contents.
def review4_record_digest(record):
    """Independent hash of the entire public Record wire shape (not just its ID/body)."""
    from dataclasses import fields
    body = {}
    for field in fields(record.body):
        value = getattr(record.body, field.name)
        body[field.name] = ({'media_type': value.media_type, 'data': list(value.data)}
                            if isinstance(value, Payload) else plain(value))
    return digest({'id': str(record.id), 'at': plain(record.at), 'writer': record.writer.value,
        'producer': plain(record.producer), 'schema': record.schema,
        'body': {'type': type(record.body).__name__, 'value': body}})


from functools import lru_cache


@lru_cache(maxsize=None)
def review4_seed(*, through_json=False, reply_index=0, firing_id='review4-firing', rootless=False):
    case = make_case('FA08'); book = fr.FiringBook()
    firing = fr.Firing(policy_generation='review4-generation', firing_id=firing_id, reply_index=reply_index,
        source='internal', basis=(), detected=f.ClockReading(run=case.clock.run, time_ns=0))
    receipt = book.accept(firing)
    root = None
    if not rootless:
        problem = make_problem(case)
        receipt = book.bind(receipt, problem=problem)
        source = ScriptedSource(({'u': [1, 4]},))
        root = book.select(receipt, draws=draw_book({'selection': source}))
        assert len(source.calls) == 1
    started = fe.begin_f_attempt(request_id=receipt.request_id, firing_id=firing.firing_id,
        policy_generation=firing.policy_generation, parents=case.ledger.heads(), evidence=(),
        problem=None, root=root, clock=case.clock, ids=case.ids, membrane=PRODUCER)
    start_record, = [item.record for item in started.records]
    assert started.ticket.started_digest == review4_record_digest(start_record)
    started = review3_roundtrip(started, through_json)
    checked_start = fe.verify_f_records(started, resources=resources(case), budget=BUDGET)
    fe.commit_f(checked_start, ledger=case.ledger)
    case.records = all_records(case.ledger); resource = resources(case)
    if rootless:
        input_value = f.FPreflight(parents=started.ticket.parents, model_ref=None, required_records=(),
            required_capabilities=(f.RequiredCapability(kind='predicate', ref=ContractRef('review4.absent', '1'),
                                                       implementation_required=True),))
        result = f.check_f_preflight(input_value, resources=resource)
        assert isinstance(result, f.NoDecision) and result.reason == 'missing_contract'
    else:
        input_value = root; result = f.evaluate_f(root, budget=BUDGET)
        assert_selected(result, root, 'Q', F(1, 4))
    context = review3_roundtrip(fe.FResultContext(attempt=started.ticket, input=input_value), through_json)
    if through_json and not rootless:
        restored = fe.restore_f_root(fe.f_json(context.input), resources=resource, budget=BUDGET)
        assert plain(restored) == plain(context.input)
        context = replace(context, input=restored)
    result = review3_roundtrip(result, through_json)
    verification = fe.verify_f_result(result, context=context, resources=resource, budget=BUDGET)
    prepared = fe.make_f_records(result, attempt=context.attempt, verification=verification,
        clock=case.clock, ids=case.ids, producer=PRODUCER, membrane=PRODUCER)
    prepared = review3_roundtrip(prepared, through_json)
    if through_json:
        # Decoding preserves data, but does not issue a live verification handle.
        renewed = fe.verify_f_result(result, context=context, resources=resource, budget=BUDGET)
        assert plain(prepared.verification) == plain(renewed)
        prepared = replace(prepared, verification=renewed)
    checked = fe.verify_f_records(prepared, resources=resource, budget=BUDGET)
    return dict(case=case, book=book, firing=firing, receipt=receipt, root=root, started=started,
        start_record=start_record, resource=resource, context=context, result=result,
        verification=verification, prepared=prepared, checked=checked, problem=None if rootless else problem)


def review4_flow(**options):
    # Share immutable public certificates; every test gets fresh mutable ledger,
    # firing book, clock and ID source, including the positive ledger-copy path.
    from copy import deepcopy
    seed = review4_seed(**options)
    case = make_case('FA08'); case.ledger.merge(seed['case'].ledger)
    case.clock = deepcopy(seed['case'].clock); case.ids = deepcopy(seed['case'].ids)
    case.records = all_records(case.ledger)
    book = fr.FiringBook(); receipt = book.accept(seed['firing'])
    if seed['problem'] is not None:
        receipt = book.bind(receipt, problem=seed['problem'])
        source = ScriptedSource(({'u': [1, 4]},))
        root = book.select(receipt, draws=draw_book({'selection': source}))
        assert plain(root) == plain(seed['root']) and len(source.calls) == 1
    return dict(seed, case=case, book=book, receipt=receipt, resource=resources(case))


def review4_pair(through_json=False):
    a = review4_flow(through_json=through_json)
    b = review4_flow(through_json=through_json, reply_index=1)
    ta, tb = a['started'].ticket, b['started'].ticket
    assert ta.started == tb.started and ta.attempt_id == tb.attempt_id
    assert ta.request_id != tb.request_id and ta.firing_id == tb.firing_id
    assert ta.started_digest != tb.started_digest
    assert a['root'].root_key == b['root'].root_key
    assert a['start_record'].id == b['start_record'].id
    return a, b


def review4_mixed_resources(a, b):
    return fe.make_f_resources(models=(a['case'].model,), records=(b['start_record'],),
        registry=f.builtin_f_registry(), ledger=a['case'].ledger)


def review4_wrong_finished(flow, through_json):
    case = flow['case']; other = make_case('FA08').ledger
    other.merge(case.ledger)
    start_entry, = other.entries_of(flow['started'].ticket.started)
    prepared = review3_roundtrip(flow['checked'], through_json)
    finished = None
    for item in sorted(prepared.records, key=lambda item: item.record.at.seq):
        if item.record.body.contract == fc.DECISION_ATTEMPTED:
            assert item.parents == flow['started'].ticket.parents == frozenset()
            finished = other.append(item.record, (start_entry.cid,))
            assert other.record(finished.cid) == item.record
            assert finished.parents != item.parents
        else:
            other.append(item.record, item.parents)
    assert finished is not None
    resource = fe.make_f_resources(models=(case.model,), records=all_records(other),
        registry=f.builtin_f_registry(), ledger=other)
    return other, finished, resource




















# Mathematics retained when storage/receipt tests moved to tests_fb (v0.14).

def test_v010_03_FA19_selected_mathematics_before_receipt():
    # The Q result is mathematical, independent of FiringBook lifecycle.
    case = make_case('FA19'); root = make_root(case, u=F(1, 4))
    assert_selected(f.evaluate_f(root, budget=BUDGET), root, 'Q', F(1, 4))


def test_v010_03_predicate_unknown_retains_requested_work():
    case, snapshot, terms = predicate_snapshot(missing=True)
    result = f.check_predicate(terms['unknown'], snapshot=snapshot, resources=resources(case))
    assert result.value == 'unknown' and result.work is not None


