"""S4b v0.19 §3-10 contracts; expectations are written from the specification.

New classes live in action_types per class-definition-only search, not a read
of implementation bodies. This import location remains a specification omission.
No production action module is imported during collection.
"""
from copy import deepcopy
from dataclasses import fields, is_dataclass
from fractions import Fraction as F
import inspect
import json

import pytest

from s4b_action_cases import (api, at_path, budget, command, contract_variants,
    declaration, encoded, load_model, object_paths, rational, rig)

TOP_KEYS = {"scheme", "states", "outcomes", "actions", "a", "learnable", "D", "log_C",
            "gamma", "work", "completion", "clock", "activity", "effects", "execution",
            "choices", "arrivals"}
COMMAND_KEYS = {"action", "choice", "run", "not_before_ns", "reservation_rule", "dispatch",
                "effect", "late", "causal_stage", "causal_position"}
FIELDS = {
    "ActionBudget": "tolerance node_budget series_budget refinement_budget envelope_budget",
    "Bounds": "lower upper exact",
    "ActionTimeContext": "run now_ns observed_ns check_events fact_ancestors clock_source",
    "ActionSupport": "status stage reason method conditions",
    "DecisionReading": "run reading_ns work parents",
    "Command": "action choice run not_before_ns reservation_rule dispatch effect late causal_stage causal_position",
    "FixedLabel": "time_s causal_stage causal_position side",
    "TargetRef": "attempt position side",
    "ActionBelief": "model_ref context evidence_key status log_evidence evidence_kind",
    "ActionNode": "belief controls targets terminal trigger",
    "ReferenceMarginal": "root_key controls targets certificate",
    "DiscreteMarginal": "targets cells",
    "BranchAtom": "probability records child",
    "BranchMeasure": "atoms total_mass certificate",
}
REASONS = {
    "ActionInputError": ("builtins", "ValueError", "schema noncanonical unknown_version shape normalization unit unknown_candidate invalid_u invalid_budget"),
    "ActionSpecificationMissing": ("builtins", "ValueError", "receipt_kernel dispatch_kernel clock_process causal_order notification_kernel completion_position"),
    "ActionIncomplete": ("quantity", "IntegrationIncomplete", "noninterference_unproved latent_label_envelope continuous_branches continuous_timing nonconjugate_learning pending_scope arrival_scope tail_bound accuracy budget uniqueness_unproved algorithm_unavailable"),
    "ActionIncompatible": ("lookahead", "OutsideEvaluationType", "family_requirement negative_increment_counterexample unsupported_family_encoding"),
    "ActionOutsideEvaluationType": ("lookahead", "OutsideEvaluationType", "certain_zero_repetition restart_delivery_law one_step_nonreturn infinite_information"),
    "ActionModelFalsified": ("agent", "ModelFalsified", "zero_evidence clock_contradiction event_contradiction"),
    "ActionNumericalRange": ("inference", "NumericalRange", "positive_underflow overflow invalid_interval"),
    "ActionNoAdmissibleCandidate": ("lookahead", "NoAdmissibleCandidate", "all_forbidden no_continuation"),
    "ActionRuntimeUnverified": ("builtins", "RuntimeError", "clock_fit dispatch_fit dispatch_point"),
}


@pytest.mark.parametrize("variant", tuple(contract_variants()))
def test_model8_all_declared_variants_roundtrip_without_defaults(variant):
    d = contract_variants()[variant]
    assert set(d) == TOP_KEYS and len(TOP_KEYS) == 17
    raw = encoded(d)
    mod = api("action_model")
    model = mod.ActionModel(declaration=raw)
    assert model.declaration == raw
    assert model.states == ("0", "1") and model.outcomes == ("0", "1")
    assert model.actions == ("a",) and model.choices == ("a",)
    assert mod.action_model_json(model) == raw
    assert mod.action_model_json(mod.action_model_from_json(raw)) == raw
    assert mod.action_model_ref(model) == model.ref
    legacy = api("model")
    assert legacy.model_json(legacy.model_from_json(raw)) == raw
    assert legacy.model_ref(model) == model.ref
    for name, value in (("declaration", b"{}"), ("states", ("wrong",)), ("ref", "wrong")):
        with pytest.raises((AttributeError, TypeError)):
            setattr(model, name, value)


@pytest.mark.parametrize("variant", tuple(contract_variants()))
def test_model8_every_object_rejects_missing_and_extra_keys(variant):
    """Each fixed-key Spec object, nested row, params and declared axis is covered.

    §3-10 does not map every malformed field to exactly one of schema/shape/
    normalization; require a declared ActionInputError reason, not bare ValueError.
    Missing mandatory kernels may instead have their declared missing-spec reason.
    arrivals is an open route map: removing a route (including the last one) is
    valid. Its per-route {alpha,beta_s} objects still have fixed mandatory keys.
    """
    source = contract_variants()[variant]
    types = api("action_types")
    for path, obj in object_paths(source):
        for key in (*obj.keys(), "__extra_key__"):
            bad = deepcopy(source)
            target = at_path(bad, path)
            if key == "__extra_key__":
                target[key] = 0
            else:
                del target[key]
                if path == ("arrivals",):
                    assert api("action_model").action_model_json(load_model(bad)) == encoded(bad)
                    continue
            with pytest.raises((types.ActionInputError, types.ActionSpecificationMissing)) as caught:
                load_model(bad)
            error = caught.value
            allowed = REASONS[type(error).__name__][2].split()
            assert error.reason in allowed, (variant, path, key, error.reason)
            assert isinstance(error.detail, str)
            assert error.field is None or isinstance(error.field, str)


@pytest.mark.parametrize("kind", ["whitespace", "key_order", "duplicate", "NaN", "Infinity", "ascii_escape"])
def test_model8_rejects_noncanonical_and_non_json_numbers(kind):
    d = declaration(actions=("猫",))
    raw = encoded(d)
    if kind == "whitespace":
        raw = b" " + raw
    elif kind == "key_order":
        raw = json.dumps(d, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode()
    elif kind == "duplicate":
        raw = b'{"scheme":"sui.model.8",' + raw[1:]
    elif kind in ("NaN", "Infinity"):
        raw = raw.replace(b'"gamma":1.0', ('"gamma":' + kind).encode())
    else:
        raw = json.dumps(d, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(api("action_types").ActionInputError) as caught:
        api("action_model").action_model_from_json(raw)
    assert caught.value.reason in ("schema", "noncanonical")


INVALID_VALUES = [
    (("D",), [[1, 2], [1, 3]], "normalization"),
    (("effects", "a", "B", "values"), [[[1, 2], [1, 2]]], "shape"),
    (("clock", "version"), "999", "unknown_version"),
    (("completion", "version"), "999", "unknown_version"),
    (("choices", "a", "reservation", "not_before_ns"), True, None),
    (("choices", "a", "reservation", "not_before_ns"), 0.5, None),
    (("execution", "think", "rows", 0, "points", 0, 0), [-1, 1], None),
    (("execution", "think", "rows", 0, "points", 0, 0), [2, 4], None),
    (("execution", "think", "rows", 0, "points", 0, 0), [1, -2], None),
    (("execution", "think", "rows", 0, "points", 0, 0), [True, 1], None),
    (("completion", "speed_unit"), "seconds", "unit"),
    (("execution", "chi", "candidates", 0, "weight"), [0, 1], None),
    (("effects", "a", "B", "values", 0, 0), [-1, 2], None),
    (("activity", "Q_by_mode", "idle"), [[1., 0.], [-1., 0.]], None),
]


@pytest.mark.parametrize("path,value,reason", INVALID_VALUES)
def test_model8_shapes_versions_normalization_and_units(path, value, reason):
    d = declaration()
    at_path(d, path[:-1])[path[-1]] = value
    with pytest.raises(api("action_types").ActionInputError) as caught:
        load_model(d)
    assert caught.value.reason in REASONS["ActionInputError"][2].split()
    if reason:
        assert caught.value.reason == reason


def test_model8_keeps_seconds_ns_work_and_negative_clock_origins_separate():
    d = declaration()
    d["choices"]["a"]["reservation"]["not_before_ns"] = -17
    d["execution"]["think"]["rows"][0]["points"][0][0] = [1, 1_000_000_000]
    raw = encoded(d)
    assert api("action_model").action_model_json(load_model(d)) == raw
    # Seconds below one ns are representable declarations, not rounded silently.
    d["execution"]["think"]["rows"][0]["points"][0][0] = [1, 2_000_000_000]
    assert api("action_model").action_model_json(load_model(d)) == encoded(d)
    assert d["work"]["a"]["points"][0][0] == 1_000_000_000


@pytest.mark.parametrize("name", tuple(FIELDS))
def test_public_value_type_fields_match_spec(name):
    cls = getattr(api("action_types"), name)
    expected = set(FIELDS[name].split())
    # Field introspection is the public type shape, never source-body inspection.
    if is_dataclass(cls):
        actual = {f.name for f in fields(cls) if not f.name.startswith("_")}
    else:
        actual = {key for key in inspect.get_annotations(cls) if not key.startswith("_")}
    assert actual == expected


@pytest.mark.parametrize("module,name,names", [
    ("dispatch", "ActionResult", "outcome effect_notice measurement_reading_ns completion_reading_ns"),
    ("dispatch", "DispatchNotice", "kind attempt command run reading_ns point"),
    ("runtime", "Act", "attempt action command"),
    ("runtime", "Thought", "work draft error decision_reading"),
])
def test_dispatch_and_runtime_public_fields(module, name, names):
    cls = getattr(api(module), name)
    actual = ({f.name for f in fields(cls) if not f.name.startswith("_")}
              if is_dataclass(cls) else set(inspect.get_annotations(cls)))
    assert actual == set(names.split())


SIGNATURES = [
    ("action_model", "action_model_from_json", "data", ""),
    ("action_model", "action_model_json", "model", ""),
    ("action_model", "action_model_ref", "model", ""),
    ("action_entry", "certify_action_scope", "view candidates resolved", "budget"),
    ("action_entry", "rebuild_action_belief", "model reading", "context budget"),
    ("action_entry", "public_evaluate", "view candidates resolved", "u budget"),
    ("dispatch", "build_command", "", "model choice decision causal_stage causal_position"),
    ("dispatch", "command_json", "command", ""),
    ("dispatch", "command_from_json", "data", ""),
    ("action_joint", "target_marginal", "belief targets", "budget"),
    ("action_joint", "parameter_moment", "belief", "parameter action powers budget"),
    ("action_joint", "hypothesis_weights", "belief", "parameter budget"),
    ("action_reference", "reference_target", "root current targets", "certificate budget"),
    ("action_reference", "reference_state_marginal", "reference", "budget"),
    ("action_reference", "information_potential", "root current", "certificate budget"),
    ("action_lookahead", "branches", "node command", "deadline_ns certificate budget"),
]


@pytest.mark.parametrize("module,name,positional,keyword", SIGNATURES)
def test_public_function_parameter_names_and_keyword_boundary(module, name, positional, keyword):
    signature = inspect.signature(getattr(api(module), name))
    expected = positional.split() + keyword.split()
    assert list(signature.parameters) == expected
    for key in positional.split():
        assert signature.parameters[key].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for key in keyword.split():
        assert signature.parameters[key].kind is inspect.Parameter.KEYWORD_ONLY


def test_specified_budget_is_immutable_and_keeps_all_five_values():
    value = budget()
    assert (value.tolerance, value.node_budget, value.series_budget,
            value.refinement_budget, value.envelope_budget) == (1e-9, 20000, 2000, 5, 20000)
    with pytest.raises((AttributeError, TypeError)):
        value.node_budget = 1


@pytest.mark.parametrize("status,stage,reason", [
    ("certified", "1a", None), ("certified", "1b", None), ("certified", "2", None),
    ("certified", "3", None), ("certified", "reduction", None),
    ("incomplete", None, "accuracy"), ("incompatible", None, "family_requirement"),
    ("missing_spec", None, "dispatch_kernel"), ("runtime_unverified", None, "clock_fit")])
def test_action_support_values_and_immutability(status, stage, reason):
    value = api("action_types").ActionSupport(status=status, stage=stage, reason=reason,
        method=None, conditions=("fixture",))
    assert (value.status, value.stage, value.reason, value.method, value.conditions) == (
        status, stage, reason, None, ("fixture",))
    with pytest.raises((AttributeError, TypeError)):
        value.reason = "changed"


@pytest.mark.parametrize("name", tuple(REASONS))
def test_exception_inheritance_and_every_reason_code(name):
    import builtins
    module, base, codes = REASONS[name]
    parent = getattr(builtins if module == "builtins" else api(module), base)
    cls = getattr(api("action_types"), name)
    assert issubclass(cls, parent)
    for code in codes.split():
        error = cls(reason=code, detail="spec fixture", field="test.field")
        assert (error.reason, error.detail, error.field) == (code, "spec fixture", "test.field")
        assert cls(reason=code, detail="default field").field is None


def test_command_all_ten_fields_and_decision_reading_is_not_control():
    d = declaration()
    d["choices"]["a"]["reservation"] = {"kind": "next", "step_ns": 1}
    # build_command needs a model and an explicit DecisionReading, not an Agent.
    from sui.ids import Ref, RefKind
    t, dispatch = api("action_types"), api("dispatch")
    run = Ref(RefKind.RUN, "s4b-command")
    decision = t.DecisionReading(run=run, reading_ns=100, work="fixture", parents=frozenset())
    result = dispatch.build_command(model=load_model(d), choice="a", decision=decision,
                                    causal_stage=2, causal_position=3)
    expected = {"action": "a", "choice": "a", "run": str(run), "not_before_ns": 101,
        "reservation_rule": {"kind": "next", "step_ns": 1},
        "dispatch": {"name": "wait-dispatch", "version": "1"},
        "effect": {"name": "start-impulse", "version": "2"}, "late": "send_when_ready",
        "causal_stage": 2, "causal_position": 3}
    assert set(expected) == COMMAND_KEYS
    assert dispatch.command_json(result) == encoded(expected)
    assert dispatch.command_json(dispatch.command_from_json(encoded(expected))) == encoded(expected)
    with pytest.raises((AttributeError, TypeError)):
        result.not_before_ns = 200
    with pytest.raises(TypeError):
        result.reservation_rule["step_ns"] = 2


def command_fixture():
    from sui.ids import Ref, RefKind
    return {"action": "a", "choice": "a", "run": str(Ref(RefKind.RUN, "command")),
        "not_before_ns": -1, "reservation_rule": {"kind": "at", "not_before_ns": -1},
        "dispatch": {"name": "wait-dispatch", "version": "1"},
        "effect": {"name": "start-impulse", "version": "2"}, "late": "send_when_ready",
        "causal_stage": 0, "causal_position": 0}


@pytest.mark.parametrize("key", sorted(COMMAND_KEYS | {"reading_ns"}))
def test_command_rejects_missing_or_extra_control_fields(key):
    data = command_fixture()
    if key == "reading_ns":
        data[key] = 100
    else:
        del data[key]
    with pytest.raises(api("action_types").ActionInputError) as caught:
        api("dispatch").command_from_json(encoded(data))
    assert caught.value.reason == "schema"


@pytest.mark.parametrize("kind", ["whitespace", "duplicate", "bool_ns", "float_ns", "bool_stage"])
def test_command_canonicality_and_integer_units(kind):
    data = command_fixture()
    if kind == "bool_ns":
        data["not_before_ns"] = True
    elif kind == "float_ns":
        data["not_before_ns"] = 0.5
    elif kind == "bool_stage":
        data["causal_stage"] = True
    raw = encoded(data)
    if kind == "whitespace":
        raw += b" "
    elif kind == "duplicate":
        raw = b'{"action":"a",' + raw[1:]
    with pytest.raises(api("action_types").ActionInputError) as caught:
        api("dispatch").command_from_json(raw)
    assert caught.value.reason in ("schema", "noncanonical", "unit")


def test_command_immediate_null_reservation_and_late():
    data = command_fixture()
    data.update(not_before_ns=None, reservation_rule={"kind": "immediate"},
                dispatch={"name": "immediate-start", "version": "1"}, late=None)
    dispatch = api("dispatch")
    assert dispatch.command_json(dispatch.command_from_json(encoded(data))) == encoded(data)


@pytest.mark.parametrize("u", [-.1, 1., float("nan"), float("inf"), True])
def test_public_evaluate_rejects_invalid_u_with_reason(u):
    from s4b_action_cases import view_of
    from sui.preference import current, resolve
    view = view_of(rig(declaration()))
    with pytest.raises(api("action_types").ActionInputError) as caught:
        api("action_entry").public_evaluate(view, ("a",), resolve(current(view.preferences), view),
                                            u=u, budget=budget())
    assert caught.value.reason == "invalid_u"


@pytest.mark.parametrize("candidates", [(), ("missing",)])
def test_public_evaluate_rejects_unknown_or_empty_candidates(candidates):
    from s4b_action_cases import view_of
    from sui.preference import current, resolve
    view = view_of(rig(declaration()))
    with pytest.raises(api("action_types").ActionInputError) as caught:
        api("action_entry").public_evaluate(view, candidates, resolve(current(view.preferences), view),
                                            u=.25, budget=budget())
    assert caught.value.reason == "unknown_candidate"
