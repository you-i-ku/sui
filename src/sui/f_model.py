"""model.10 の宣言・正準 JSON・入力検査 (関所 F v0.10 §3-10-3・12・13)。

宣言の DTO を手で構築しても意味・認証・実行適合の検査済みにはならない。
F-a の入口で再検査し、旧 model.1〜9 は変更しない。
"""

from dataclasses import dataclass as _dataclass
from functools import lru_cache as _lru_cache

from .f_contracts import FINITE_MODEL as CONTRACT

SCHEME = "sui.model.10"
KEYS = ("scheme", "contract", "units", "targets", "states", "initial",
        "kernels", "operations", "policies", "certificate_capabilities")


@_dataclass(frozen=True, slots=True, kw_only=True)
class FModel:
    """宣言bytesを受ける本物のコンストラクター。区切り0では未検査。

    F-a で検査する: 正準UTF-8 JSONの10キー、版、単位、非空で一意の軸、
    参照閉包、行列の軸と列の正規化、対象の静的性、K可測な分岐。
    bool整数、未知キー・版、非既約RはFInputError。意味が正しく認証能力
    だけが不足する宣言は受け、評価時に未完了とする。モデル参照と検査済み
    派生欄を信頼する証明ではない。KernelRef は finite_kernel/1・args.id、
    PolicyRef は finite_policy/1・args.id。choose.next は操作終了後の戻り先。
    最上位10キーは維持。初手終了後の明示方針 FContinuation は問題/根で固定する。
    finite_option.prediction は最初に実行する核で、操作全体は policy と組で読む。
    透明な包装の path_action=null は実 execute がなく O/A 射影が一致する条件で検査する。
    """
    declaration: bytes


def f_model_from_json(data: bytes) -> FModel:
    """F-aで正準宣言を検査して返す。不正はFInputError、意味不足は
    FSpecificationMissing。未対応の認証能力だけで不正入力としない。
    """
    model = FModel(declaration=data)
    _checked(model)
    return model


def f_model_json(model: FModel) -> bytes:
    """F-aで検査済み宣言の正準bytesを返す。異なる型はFInputError。
    認証能力の不足は符号化の失敗ではない。model.1〜9へ移し替えない。
    """
    if type(model) is not FModel:
        from .f import FInputError
        raise FInputError('shape',field='/model')
    _checked(model)
    return model.declaration


def f_model_ref(model: FModel) -> str:
    """F-aで正準bytesのsha256:参照を返す。不正入力はFInputError。
    参照の生成は数学・実行の認証を含意しない。
    """
    from .f import _digest,FInputError
    if type(model) is not FModel:raise FInputError('shape',field='/model')
    return _digest(_checked(model))


def _checked(model):
    """Check the declaration afresh; a DTO is never a proof."""
    from . import f
    if type(model) not in (FModel, FModel11):
        raise f.FInputError("shape", "FModel required", "model")
    primary = type(model) is FModel11
    data = f._load_json(model.declaration)
    f._keys(data, KEYS, "")
    if data["scheme"] != (SCHEME_11 if primary else SCHEME):
        raise f.FInputError("unknown_version", field="/scheme")
    contract = f._decode(data["contract"], f._ContractRef, "/contract")
    if contract != (CONTRACT_11 if primary else CONTRACT):
        raise f.FInputError("unknown_version", field="/contract")
    f._keys(data["units"], ("record", "duration", "information", "cost"), "/units")
    if data["units"] != {"record": "ns", "duration": "ns", "information": "nat", "cost": "nat"}:
        raise f.FInputError("unit", field="/units")
    targets = f._decode(data["targets"], tuple[str, ...], "/targets")
    f._unique(targets, "/targets", nonempty=True)
    f._array(data["states"], "/states")
    ids = []
    for i, state in enumerate(data["states"]):
        field = f"/states/{i}"
        f._keys(state, ("id", "target"), field)
        ids.append(f._decode(state["id"], str, field + "/id"))
        if state["target"] not in targets:
            raise f.FInputError("unresolved_reference", field=field + "/target")
    f._unique(ids, "/states", nonempty=True)
    initial = f._decode(data["initial"], tuple[f._Fraction, ...], "/initial")
    if len(initial) != len(ids):
        raise f.FInputError("shape", field="/initial")
    if min(initial) < 0 or sum(initial) != 1:
        raise f.FInputError("normalization", field="/initial")
    kernels = f._decode(data["kernels"], tuple[f.FiniteKernel, ...], "/kernels")
    policies = f._decode(data["policies"], tuple[f.FinitePolicy, ...], "/policies")
    operations = (_primary_actions(data["operations"]) if primary else
                  f._decode(data["operations"], tuple[f.ActionSpec, ...], "/operations"))
    for name, values in (("kernels", kernels), ("policies", policies), ("operations", operations)):
        f._unique(tuple(v.id for v in values), "/" + name, nonempty=True)
    ks, ps, ops = ({v.id: v for v in values} for values in (kernels, policies, operations))
    for k in kernels:
        f._unique(tuple(o.id for o in k.outcomes), "/kernels", nonempty=True)
        for o in k.outcomes:
            if len(o.matrix) != len(ids) or any(len(row) != len(ids) for row in o.matrix):
                raise f.FInputError("shape", field="/kernels")
            for i, row in enumerate(o.matrix):
                for j, value in enumerate(row):
                    if value < 0:
                        raise f.FInputError("normalization", field="/kernels")
                    if value and data["states"][i]["target"] != data["states"][j]["target"]:
                        raise f.FInputError("shape", "target must be static", "/kernels")
        if any(sum(o.matrix[i][j] for o in k.outcomes for i in range(len(ids))) != 1 for j in range(len(ids))):
            raise f.FInputError("normalization", field="/kernels")
    for p in policies:
        f._unique(tuple(n.id for n in p.nodes), "/policies", nonempty=True)
        nodes = {n.id: n for n in p.nodes}
        if p.entry not in nodes:
            raise f.FInputError("unresolved_reference", field="/policies")
        for n in p.nodes:
            if isinstance(n, f.EndNode):
                continue
            if isinstance(n, f.ExecuteNode):
                if n.kernel not in ks:
                    raise f.FInputError("unresolved_reference", field="/policies")
                expected = {o.id for o in ks[n.kernel].outcomes}
                # K-measurability is a semantic obligation of the world compiler.
            else:
                f._unique(n.operations, "/policies", nonempty=True)
                expected = set(n.operations)
                if not expected <= ops.keys():
                    raise f.FInputError("unresolved_reference", field="/policies")
            if set(n.next) != expected or not set(n.next.values()) <= nodes.keys():
                raise f.FInputError("unresolved_reference", field="/policies")
    # Structural decoding must not pick an implicit registry. Reachable references,
    # implementations and semantic keys are certified by the world compiler.
    f._decode(data["certificate_capabilities"], tuple[f._ContractRef, ...], "/certificate_capabilities")
    return data


def _parts(model):
    from . import f
    if type(model) not in (FModel, FModel11) or type(model.declaration) is not bytes:
        raise f.FInputError("shape", "FModel with immutable bytes required")
    return _parts_from_bytes(model.declaration, type(model) is FModel11)


@_lru_cache(maxsize=128)
def _parts_from_bytes(declaration, primary=False):
    """Reuse validation only for identical immutable declaration bytes."""
    from . import f
    model = (FModel11 if primary else FModel)(declaration=declaration)
    data = _checked(model)
    return (f._freeze(data),
            f._MappingProxyType({k.id: k for k in f._decode(data["kernels"], tuple[f.FiniteKernel, ...])}),
            f._MappingProxyType({p.id: p for p in f._decode(data["policies"], tuple[f.FinitePolicy, ...])}),
             f._MappingProxyType({a.id: a for a in (_primary_actions(data["operations"]) if primary else f._decode(data["operations"], tuple[f.ActionSpec, ...]))}))


def _primary_actions(values):
    """Derive internal keys from primary meaning; never accept a supplied key."""
    from . import f
    declarations = f._decode(values, tuple[f.FActionDeclaration, ...], "/operations")
    result = []
    for declaration in declarations:
        value = f._encode(declaration)
        material = {k: v for k, v in value.items() if k not in ("id", "proof")}
        result.append(f._decode(dict(value, semantic_key=f._digest(material)), f.ActionSpec))
    return tuple(result)


def _model_ref(model):
    """Internal common reference reader; public versioned readers remain strict."""
    return f_model11_ref(model) if type(model) is FModel11 else f_model_ref(model)


# v0.13 primary-operation model. The model.10 readers/validation above are
# deliberately unchanged. Model.11 semantics are certified by the facts compiler.
from .f_contracts import FINITE_MODEL_V2 as CONTRACT_11

SCHEME_11 = "sui.model.11"
KEYS_11 = KEYS


@_dataclass(frozen=True, slots=True, kw_only=True)
class FModel11:
    """model.11宣言bytesを持つ手組み可能な未検査DTO。

    最上位10欄/単位はmodel.10と同じ。operationsはFActionDeclarationで
    semantic_keyを要求しない。finite_model/2。読み書きと意味の認証を分ける。
    旧bytesの意味・既存FModel/model.10の読取り口を変更しない。
    """
    declaration: bytes


def f_model11_from_json(data: bytes) -> FModel11:
    """model.11の正準10欄・一次操作を読む。意味認証はcompiler。

    不正型/未知版/bool整数/非既約Rを拒否する契約。model.10へ偽装せず、
    semantic_keyの自己申告を要求しない。
    """
    model = FModel11(declaration=data)
    _checked(model)
    return model


def f_model11_json(model: FModel11) -> bytes:
    """model.11の正準宣言bytesを返す。旧モデルへ移し替えない。

    構造の符号化と認証を区別する。
    """
    if type(model) is not FModel11:
        from .f import FInputError
        raise FInputError("shape", field="model")
    _checked(model)
    return model.declaration


def f_model11_ref(model: FModel11) -> str:
    """model.11の正準document内容hashを返す。台帳Pointとは別。

    参照の生成は数学や実行の認証ではない。
    """
    from .f import _digest
    f_model11_json(model)
    return _digest(_checked(model))
