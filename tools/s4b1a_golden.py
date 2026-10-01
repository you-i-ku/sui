"""709c2dd の P5-a 基準を作る、実装前の台本 (S4b1a v0.6 §6-3 E10)。

実行 (プロジェクトの Python 3.12.10 / numpy 2.5.3 / scipy 1.18.1):
    .venv/Scripts/python.exe -B tools/s4b1a_golden.py tests/golden_s4b1a.json
実装後の照合 (既存ファイルを変更しない):
    .venv/Scripts/python.exe -B tools/s4b1a_golden.py --check tests/golden_s4b1a.json

ファイルへの書き込みは main の指定された出力1個だけ。台帳はすべてメモリ内。
build_golden() は書き込まず dict を返す。時刻・名札・salt・u は固定。
model_json.body / belief_content / decision_content は UTF-8 本文そのものの文字列。
JSONへ戻して丸めたり欄を落としたりせず、contentの1バイトの変化も残す。
model_json.sha256 は元の model_json bytes の SHA-256。

現行の適用境界 (成功しない組合せを成功に見せるためにモデルは変更しない):
  model.1/2 × lookahead: ValueError("lookahead: durations are required")
  model.4 × plan_s4c/decide_s4c: ValueError("plan_s4c: sui.model.4 is not supported")
model.1〜4 × 4 入口の全部 (16 場面) と null_q の 2 場面を持つ。拒む場面は
decision_content = null、refused = 例外の型と文面 (拒む振る舞いも P5-a で守る)。
拒む時は台帳の先端と主体の信念が変わらないことも確かめる。成功の場面は refused = null。
S4b-1a で受け付けに変わる learnable × Q (model.py:169) は入れない。
model.4 の one_step は None を持たない候補 (look, peek) を明示して使う。
先読みの H は 2秒 (Noneではない)。model.3/4 だけが対応する。

由来: tests/worlds.py の _model/_time_model/_hand_model/_lookahead_model/HandHistory、
tests/test_lookahead.py の _rig と N6 の ratio=True の世界。
この台本は tests の試験関数を呼ばず、pytest は不要。既存ファイルは変更しない。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys


# import時も __pycache__ を作らない。CLI以外からの呼び出しでも同じ。
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np

from sui.agent import Agent, plan, plan_s4c, replay_decision
from sui.ids import RefKind, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.model import GenerativeModel, model_json
from sui.records import Payload, Preference, Producer, Record, Role
from sui.s4d_contracts import PREFERENCE
from worlds import HandHistory, _hand_model, _lookahead_model, _model, _time_model


NS = 1_000_000_000
U = 0.375


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_text(payload):
    """バイトを保持する。非正準なcontentが来たら基準を黙って書き換えない。"""
    text = payload.data.decode("utf-8")
    assert canonical(json.loads(text)) == payload.data
    return text


@dataclass
class Scene:
    model: GenerativeModel
    h: HandHistory
    candidates: tuple[str, ...]
    now_ns: int
    observed_ns: int


def model_scene(version):
    """同じモデル・同じ事実で互換と新入口を比較。mode毎に新しく組み立てる。"""
    h = HandHistory(run="goldenrun", wall=100)
    h.boot()
    if version == 1:
        model = _model(learnable=frozenset({"look1", "look2"}))
        h.observe(h.start("look1"), "o0", 1)
        h.observe(h.start("look2", seconds=1), "o1", 1)
        h.start("look1", seconds=1)
        candidates = ("look1", "look2", "wait")
    elif version == 2:
        model = _time_model()
        h.observe(h.start("look"), "o0", 1)
        h.start("look", seconds=1)
        candidates = ("look", "wait")
    elif version == 3:
        # _hand_model の wait=0 は先読みで拒否されるので、同じ世界の正の所要版。
        # 全mode共通のモデル。入口に応じてモデルを差し替えない。
        model = _hand_model(durations={"look": ((1., .5), (4., .5)), "wait": ((1., 1.),)})
        h.observe(h.start("look"), "o0", 1)
        h.start("look", seconds=1)
        candidates = ("look", "wait")
    elif version == 4:
        model = _lookahead_model()
        h.observe(h.start("look"), "o0", 1)
        h.start("wait", seconds=1)  # 永久未着の進行中も条件に含む
        candidates = ("look", "peek")
    else:
        raise ValueError("expected model version 1..4")
    h.at(2)
    assert json.loads(model_json(model))["scheme"] == f"sui.model.{version}"
    return Scene(model, h, candidates, 2 * NS, NS)


def null_q_scene():
    """N6 ratio=True: 普通の確率では潰れる2状態の比1:2を新入口が復元する。"""
    rate = 1e-200
    Q = np.array([[-rate, 0., 0., 0.], [rate, -3 * rate, 0., 0.],
                  [0., rate, 0., 0.], [0., 2 * rate, 0., 0.]])
    a = {"probe": np.array([[1., 1., 1., 0.], [0., 0., 0., 1.]]),
         "safe": np.array([[1., 1., 1., 1.], [0., 0., 0., 0.]]),
         "sense": np.array([[1., 1., 0., 0.], [0., 0., 1., 1.]])}
    model = _lookahead_model(states=("s0", "s1", "s2", "s3"), outcomes=("o0", "o1"),
        actions=tuple(a), a=a, D=np.array([1., 0., 0., 0.]), Q=Q,
        log_C=np.log([.5, .5]), durations={name: ((1., 1.),) for name in a},
        measures={name: "report" for name in a})
    h = HandHistory(run="goldenrare", wall=100)
    h.boot()
    h.observe(h.start("sense"), "o1", 1)
    return Scene(model, h, ("probe",), NS, NS)


def preference_items(scene, mode, *, rare=False):
    """評価の型に対応した既存の特徴。H=2秒、gamma=1.25を固定する。"""
    ahead = mode == "lookahead"
    if ahead:
        if rare:
            # N6の既存fixtureと同じH=1秒、1報告の2結果。
            probs = [[[["probe", "o0"]], .8], [[["probe", "o1"]], .2]]
            return ({"kind": "item", "rule": {"name": "table", "version": "1"},
                "args": {"feature": {"name": "outcome_multiset", "version": "1"},
                         "probs": probs}}, {"kind": "style", "H_ns": NS, "gamma": 1.25})
        # 空の付箋でもHが数なら先読みになる。型を変えず再帰・情報の基準を残す。
        return ({"kind": "style", "H_ns": 2 * NS, "gamma": 1.25},)
    probabilities = (.8, .2) if rare else ((.6, .3, .1) if len(scene.model.outcomes) == 3 else (.6, .4))
    return ({"kind": "item", "rule": {"name": "table", "version": "1"},
        "args": {"feature": {"name": "candidate_outcome", "version": "1"},
                 "probs": [[name, p] for name, p in zip(scene.model.outcomes, probabilities)]}},
        {"kind": "style", "H_ns": None, "gamma": 1.25})


def setup(scene, mode, *, rare=False):
    """FakeClock、決まったID、SequentialSalts。ファイルI/Oのない本物の台帳。"""
    ledger = Ledger(salts=SequentialSalts())
    ids = SequentialIds(prefix="golden")
    for record in scene.h.records:
        ledger.append(record, ledger.heads())
    for data in preference_items(scene, mode, rare=rare):
        record = Record(id=ids.new(RefKind.PREFERENCE), at=scene.h.clock.now(), writer=Role.MODEL,
            producer=Producer(component="test.s4b1a_golden", code_version="1"),
            body=Preference(basis=(), contract=PREFERENCE, content=Payload.json(data)))
        ledger.append(record, ledger.heads())
    agent = Agent(model=scene.model, lineage="s4b1agolden")
    belief = agent.adopt(ledger, clock=scene.h.clock, ids=ids)
    assert belief is not None
    return agent, ledger, ids, belief


def capture(scene, mode, *, rare=False):
    """計画だけでなく決定の記録を作り、contentの一致とreplayも調べる。"""
    agent, ledger, ids, belief = setup(scene, mode, rare=rare)
    saved_belief = belief.body.content.data
    if rare:
        assert belief.body.content.as_json()["q"] is None
    view = agent.view(now_ns=scene.now_ns, observed_ns=scene.observed_ns)
    planner = plan_s4c if mode in ("plan_s4c", "decide_s4c") else plan
    encoded = model_json(scene.model)
    saved = {"model_json": {"sha256": hashlib.sha256(encoded).hexdigest(), "body": encoded.decode("utf-8")},
             "belief_content": content_text(belief.body.content)}
    decide = lambda: agent.decide_s4c(scene.candidates, u=U, clock=scene.h.clock, ids=ids,
        ledger=ledger, now_mono_ns=scene.now_ns, observed_mono_ns=scene.observed_ns)
    heads = ledger.heads()
    try:
        draft = planner(view, scene.candidates, u=U)
    except Exception as error:
        # 拒む場面: 例外の型・文面を残し、台帳にも主体にも何も書いていないことを確かめる。
        refused = {"type": type(error).__name__, "message": str(error)}
        if mode == "decide_s4c":
            try:
                decide()
            except Exception as again:
                assert {"type": type(again).__name__, "message": str(again)} == refused
            else:
                raise AssertionError("decide_s4c accepted what plan_s4c refused")
        assert ledger.heads() == heads
        assert agent._belief.body.content.data == saved_belief
        return {**saved, "decision_content": None, "refused": refused}
    if mode == "decide_s4c":
        decision, _ = decide()
    else:
        prepared = agent.prepare(draft, clock=scene.h.clock, ids=ids)
        agent.commit(prepared, ledger=ledger)
        decision = prepared.decided
    assert decision.body.content.data == draft.content.data
    entry, = ledger.entries_of(decision.id)
    assert replay_decision(model=scene.model, ledger=ledger, decision=entry.cid) == draft
    assert agent._belief.body.content.data == saved_belief
    return {**saved, "decision_content": content_text(decision.body.content), "refused": None}


def build_golden():
    result = {}
    for version in range(1, 5):
        for mode in ("plan_s4c", "decide_s4c", "one_step", "lookahead"):
            result[f"model{version}/{mode}"] = capture(model_scene(version), mode)
        assert result[f"model{version}/plan_s4c"] == result[f"model{version}/decide_s4c"]
    for mode in ("one_step", "lookahead"):
        result[f"model3/null_q/{mode}"] = capture(null_q_scene(), mode, rare=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="output path (or existing baseline with --check)")
    parser.add_argument("--check", action="store_true", help="compare bytes without writing")
    args = parser.parse_args()
    # 二度組み立て、固定ID/時計以外の非決定的な入力が混ざっていないことも確認。
    first = canonical(build_golden())
    second = canonical(build_golden())
    if first != second:
        raise AssertionError("golden generation is not deterministic")
    if args.check:
        if args.path.read_bytes() != first:
            raise SystemExit("P5-a mismatch: generated bytes differ from the baseline")
        print(f"P5-a matched: {args.path} ({len(first)} bytes)")
    else:
        # UTF-8, BOMなし, 改行なし。既存ディレクトリだけを利用する。
        args.path.write_bytes(first)
        print(f"Wrote {args.path}: {len(json.loads(first))} scenes, {len(first)} bytes, "
              f"sha256={hashlib.sha256(first).hexdigest()}")


if __name__ == "__main__":
    main()
