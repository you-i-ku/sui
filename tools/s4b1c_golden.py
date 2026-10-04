"""S4b-1c v0.24 §6-1 / §3-8: d09b639 の実装前の基準。

作成時点では未実行。以下の「予想」は現行 src と既存 golden の読みからの予想。
採取・照合・pytest は Claude の Python 3.12.10 / numpy 2.5.3 / scipy 1.18.1 で行う。
    .venv/Scripts/python.exe -B tools/s4b1c_golden.py tests/golden_s4b1c.json
    .venv/Scripts/python.exe -B tools/s4b1c_golden.py --check tests/golden_s4b1c.json
    .venv/Scripts/python.exe -B tools/s4b1c_golden.py --check --implemented tests/golden_s4b1c.json

印 P = preserve (許す変更なし)、I = intentional_change。
変更欄は observed の直下のキー。D = decision_content, decision_contract, replay_ok,
no_write_on_refusal, refused。M = model_json, roundtrip_ok, refused。
モデルの作り方:
  L1..4 / N6 / L5 / L5h: 凍結した 1a/1b 台本の fixture をそのまま呼ぶ。
  E: GenerativeModel、2状態・2結果・a は名前を学ぶ、b は固定、Qなし。
     両行動の DurationPrior(2, atoms[(1ns,.5),(3ns,.5)])、単一 exact "1"。
  T: E の λ を width=4ns、phase=point(0)/point(3)、各 .5、share=all_actions に。
     bの原子の質量は(1ns,.25)/(3ns,.75)。報告順を反転すると結合の読みが変わる。
  Z: E の既知所要版 (duration_priorsなし、両行動の所要0、report)。
  F: E の a だけ atoms[(1ns,.5),(None,.5)]、候補は a (永久未着を含む)。
  A5: _lattice_model、全行動の既知所要が正 (a=1/3秒、b=1秒、f=2秒)。
  R: E の起動・事実を2つの run に分ける (run_index=0/1、壁時計差1秒)。
  C: E の constructor kwargs に Q=[[-.25,.25],[.25,-.25]] を加える。
公開の入口:
  S=plan_s4c、DS=Agent.decide_s4c、P=plan、AD=Agent.decide、
  LA=sui.lookahead.evaluate (preference.current/resolve で好みを解決)、
  J=model_from_json、C=GenerativeModel、QI=posterior(...).future_records(...).information。
成功の新規行は prepare/commit・Agent.restore・replay_decision も通る。

各行の表 (結果はすべて予想。既存26行は既存基準でも確認できる):
| 行 | 入口 | モデル / 事実 | 印 | 許す変更 | 今の結果の予想 / 実装後の条件 |
|---|---|---|---|---|---|
| model1/plan_s4c | S | L1 | P | なし | 成功 |
| model1/decide_s4c | DS | L1 | P | なし | 成功 |
| model1/one_step | P | L1 | P | なし | 成功 |
| model1/lookahead | P | L1 | P | なし | ValueError (所要なし) |
| model2/plan_s4c | S | L2 | P | なし | 成功 |
| model2/decide_s4c | DS | L2 | P | なし | 成功 |
| model2/one_step | P | L2 | P | なし | 成功 |
| model2/lookahead | P | L2 | P | なし | ValueError (所要なし) |
| model3/plan_s4c | S | L3 | P | なし | 成功 |
| model3/decide_s4c | DS | L3 | P | なし | 成功 |
| model3/one_step | P | L3 | P | なし | 成功 |
| model3/lookahead | P | L3 | P | なし | 成功 |
| model4/plan_s4c | S | L4 | P | なし | ValueError (model.4) |
| model4/decide_s4c | DS | L4 | P | なし | ValueError (model.4) |
| model4/one_step | P | L4 | P | なし | 成功 |
| model4/lookahead | P | L4 | P | なし | 成功 |
| model3/null_q/one_step | P | N6 | P | なし | 成功 (保存q=null) |
| model3/null_q/lookahead | P | N6 | P | なし | 成功 (保存q=null) |
| model5/plan_s4c | S | L5 | P | なし | ValueError |
| model5/decide_s4c | DS | L5 | P | なし | ValueError |
| model5/one_step | P | L5 | P | なし | 成功 |
| model5/lookahead | P | L5、所要なし | I | refused | OutsideEvaluationType → 所要なしの拒否 |
| model5/hand/plan_s4c | S | L5h | P | なし | ValueError |
| model5/hand/decide_s4c | DS | L5h | P | なし | ValueError |
| model5/hand/one_step | P | L5h | P | なし | 成功 |
| model5/hand/lookahead | P | L5h、b/f=0 | I | refused | OutsideEvaluationType → 所要0の拒否 |
| model6/exact/empty/one_step | P | E、試みなし | P | なし | 成功 |
| model6/exact/complete/one_step | P | E、aを1nsで完了 | P | なし | 成功 |
| model6/exact/pending/one_step | P | E、a未着を1nsで確かめる | P | なし | 成功 |
| model6/exact/complete_pending/one_step | P | E、完了後のaが未着 | P | なし | 成功 |
| model6/exact/complete_pending/decide | AD | 同上 | P | なし | 成功 |
| model6/tick/empty/one_step | P | T、試みなし | P | なし | 成功 |
| model6/tick/pending/one_step | P | T、a未着・受信読値0 | P | なし | 成功 |
| model6/tick/shared_check/one_step | P | T、a/b未着に同じ受信 | P | なし | 成功 |
| model6/tick/tie_ab/one_step | P | T、読値4の報告をa,b順 | P | なし | 成功 |
| model6/tick/tie_ba/one_step | P | T、読値4の報告をb,a順 | P | なし | 成功 |
| model6/tick/after_before/one_step | P | T、未記録tickのafterが開始前 | P | なし | 成功 |
| model6/tick/after_start/one_step | P | T、未記録tickのafterが開始後 | P | なし | 成功 |
| model6/old_run/pending/one_step | P | R、前のrunの未着 | P | なし | 成功 |
| model6/old_run/complete/one_step | P | R、前のrunで完了 | P | なし | 成功 |
| model6/old_run/late_receipt/one_step | P | R、後のrunで受信・所要不明 | P | なし | 成功 |
| model6/unknown_time/one_step | P | E、received_nsなしの結果 | P | なし | 成功 (所要unknown) |
| model6/unreadable_outcome/one_step | P | E、結果本文を読めない | P | なし | 成功 (所要complete) |
| model6/unreadable_attempt/one_step | P | E、開始本文を読めない | P | なし | 成功 (所要unreadable) |
| model6/unknown_attempt/one_step | P | E、不明な試みへの観測 | P | なし | 成功 (名前はunknown_attempt) |
| model6/broken_clock/one_step | P | E、同じrun_indexの別run | P | なし | ModelFalsified、書かない |
| model6/missing_check/one_step | P | E、check_eventsを渡さない | P | なし | ValueError、書かない |
| model6/bad_after/one_step | P | T、未知のCIDをafterに | P | なし | ValueError、書かない |
| model6/no_delivery_law/one_step | P | R、同じjobを両runで開始 | P | なし | ModelFalsified (S5)、書かない |
| model5/positive/lookahead | P | A5、H=2秒 | I | D | OutsideEvaluationType → 成功 |
| model5/positive/direct_lookahead | LA | 同上 | I | D | OutsideEvaluationType → 成功 |
| model6/positive/lookahead | P | E、H=4ns | I | D | OutsideEvaluationType → 成功 |
| model6/positive/direct_lookahead | LA | 同上 | I | D | OutsideEvaluationType → 成功 |
| constructor/Q_duration_priors | C | C | I | M | ValueError → 新方式model.7で成功 |
| model6_json/Q_duration_priors | J | Q付きの旧model.6 JSON | P | なし | ValueError |
| model_json/unknown_scheme | J | 未知の方式 | P | なし | ValueError |
| model6_json/unknown_base_version | J | atomsの版999 | P | なし | ValueError |
| model6_json/unknown_measure_version | J | exactの版999 | P | なし | ValueError |
| model6_json/noncanonical | J | 正準本文の前に空白 | P | なし | ValueError |
| model3/zero/one_step | P | Z | P | なし | 成功 |
| model3/zero/lookahead | P | Z、H=4ns | P | なし | ValueError (正の所要が要る) |
| model6/infinite_candidate/one_step | P | F | P | なし | OutsideEvaluationType |
| model6/incomplete/information | QI | T、terms=1、series_budget=0 | P | なし | IntegrationIncomplete、書かない |
| model6/compat/plan_s4c | S | E | P | なし | ValueError |
| model6/compat/decide_s4c | DS | E | P | なし | ValueError |

既存18+8行は既存基準の observed をそのまま継ぐ。両既存の台本を再採取して
全欄の正準バイトを既存ファイルと照合し、書き換えない。新規成功行は元の
model_json.body / belief_content / decision_content をUTF-8本文のまま残す。
model.6 の情報の区間・中点・time/check_events は decision_content の全文に含む。
分類・共有の確かめ・同着順は reading_timing_content にも元の読みから保存する。
失敗は例外の型・文面を残し、計画で台帳の先端・信念・revision・frontierが
変わらないことを確かめる。model.6 の旧の信念の復元も全 content を照合する。

--check は preserve の行の全欄、I の行の許す変更欄以外をバイト照合する。
採取時とsrcのハッシュが同じなら全行を完全照合する。srcが違う場合、または
--implemented 指定時は、I の新しい合格条件も必須 (旧拒否のままでは通らない)。
既存model.5の所要なし/0の2行だけは旧の拒否または下記の具体的な新拒否を許す。
正の先読み4行の成功は、保存/復元/再生と有限値・候補・u・J=C-Iを検査する。
その数値の正しさをこの基準から作らない。独立な定規は §6-2 の別台本が担う。
model.7の構築/先読みや「未認証のg_mon」の新入口は現行srcに存在しないので、
成功値/新しい未完了理由はここでは採取できない。実装後の独立の試験が必要。
旧の数学入口の明示的な計算予算の未完了を、最後のQI行で別に採取する。

ハッシュ: JSONの provenance に環境、台本/依存/仕様書/src各ファイルのSHA-256、
src集合のSHA-256、scenesのSHA-256を保存。ファイル全体のSHA-256は自己参照に
なるためJSON内に埋めず、採取/照合の標準出力に残す (その出力をログへ残す)。
採取は下のd09b639のsrcハッシュに限る。gitは呼ばない。時刻/名札/salt/uを固定、
二度組み立てて決定性を検査。書き込みは指定の tests/golden_s4b1c.json 1個だけ。
今回の作業記録: 台本だけという指定によりObsidian/Projects/Heatは未更新。
再利用した知見: 「実装の前に基準を撮り、素通りは壊して確かめる」は採取と
元本文の保存に有効。intentional_changeは古い知見の除外方針より本仕様を優先。
読んだ範囲: 仕様の§3-8/3-9/3-10/4/6-1全文、既存台本全文、関連src/testsの該当箇所。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import scipy

from s4b1a_golden import NS, U, Scene, canonical, content_text, setup
from s4b1b_golden import build_golden as legacy_golden
from sui.agent import Agent, plan, plan_s4c, replay_decision
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind
from sui.lookahead import evaluate
from sui.model import GenerativeModel, model_from_json, model_json
from sui.preference import current, resolve
from sui.quantity import BaseSpec, DurationPrior, FutureRecordsQuery, posterior, timing_context
from sui.records import AttemptStarted, Observed, Payload
from sui.s1_contracts import ATTEMPT, OUTCOME
from sui.values import MeasureSpec
from worlds import HandHistory, _lattice_model

BASE_COMMIT = "d09b639f5ec5ff0e268866e800e21f34813e8b6a"
BASE_SRC_SHA256 = "01dd4475c4543c73a86d256310f92a3d12dbfd35cb6091339b5a8a32e5c47a87"
SPEC = "specs/S4b1c_変わる世界で学んだ信念を先読みと選択につなぐ.md"
DEPENDENCIES = ("tools/s4b1a_golden.py", "tools/s4b1b_golden.py", "tests/worlds.py",
                "tests/golden_s4b1a.json", "tests/golden_s4b1b.json", SPEC)
ENVIRONMENT = {"python": "3.12.10", "numpy": "2.5.3", "scipy": "1.18.1"}
DECISION_CHANGES = ("decision_content", "decision_contract", "no_write_on_refusal", "refused", "replay_ok")
MODEL_CHANGES = ("model_json", "refused", "roundtrip_ok")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def encoded_model(model):
    data = model_json(model)
    return {"body": data.decode("utf-8"), "sha256": sha256(data)}


def source_hashes():
    return {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes())
            for path in sorted((ROOT / "src" / "sui").rglob("*.py"))}


def source_digest(files):
    return sha256("".join(f"{name}:{files[name]}\n" for name in sorted(files)).encode("utf-8"))


def environment():
    return {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}


def preflight():
    if environment() != ENVIRONMENT:
        raise SystemExit(f"expected {ENVIRONMENT}, got {environment()}; do not substitute Python")
    expected = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    if Path(sys.executable).resolve() != expected:
        raise SystemExit(f"run with {expected}; got {sys.executable}")


def prior(points=(1, 3)):
    return DurationPrior(2., BaseSpec("atoms", "1", {"points": [[d, 1. / len(points)] for d in points]}))


def measure(tick=False):
    specs = [(MeasureSpec("exact", "1", {}), 1.)] if not tick else [
        (MeasureSpec("tick", "1", {"width_ns": 4, "phase": {"point_ns": phase},
                                    "check": "uniform_in_tick"}), .5) for phase in (0, 3)]
    return {"share": "all_actions", "candidates": [{**spec.as_json(), "weight": w} for spec, w in specs]}


def quantity_kwargs(*, tick=False, infinite=False):
    return dict(states=("s", "t"), outcomes=("x", "y"), actions=("a", "b"),
        a={"a": np.array([[2., 1.], [1., 2.]]), "b": np.array([[.75, .25], [.25, .75]])},
        learnable=frozenset({"a"}), D=np.array([.6, .4]), log_C=np.log([.5, .5]), gamma=1.,
        duration_priors={"a": prior((1, None) if infinite else (1, 3)), "b": prior()},
        measure=measure(tick))


def receipt(h, reading, *, recorded=None, attempt=None, content=None):
    return h.add(Observed(route="executor" if attempt is not None else "membrane",
        contract=OUTCOME if attempt is not None else ContractRef("test.s4b1c.check", "1"),
        content=Payload.json({}) if content is None else content,
        caused_by=None if attempt is None else attempt.id, received_ns=reading),
        (h.clock.mono_ns() if recorded is None else recorded) / NS)


@dataclass
class Case:
    scene: Scene
    check: object = None
    after: str | None = None
    horizon: int = 4


def quantity_case(kind):
    tick = kind.startswith("tick/") or kind in ("bad_after", "incomplete")
    kwargs = quantity_kwargs(tick=tick, infinite=kind == "infinite_candidate")
    if tick:
        kwargs["duration_priors"]["b"] = DurationPrior(2., BaseSpec("atoms", "1", {"points": [[1, .25], [3, .75]]}))
    model = GenerativeModel(**kwargs)
    h = HandHistory(run="goldenquantity", wall=100)
    boot = h.boot()
    check, after, candidates = boot, None, ("a", "b")
    if kind.startswith("exact/"):
        tail = kind.split("/")[1]
        if tail in ("complete", "complete_pending"):
            h.observe(h.start("a"), "x", 1 / NS)
        if tail in ("pending", "complete_pending"):
            h.start("a", h.clock.mono_ns() / NS)
            check = receipt(h, h.clock.mono_ns() + 1, recorded=h.clock.mono_ns() + 1)
        elif tail == "complete":
            check = h.records[-1]
    elif kind.startswith("tick/"):
        tail = kind.split("/")[1]
        if tail in ("pending", "shared_check"):
            h.start("a")
            if tail == "shared_check":
                h.start("b")
            check = receipt(h, 0, recorded=4)
        elif tail in ("tie_ab", "tie_ba"):
            a, b = h.start("a"), h.start("b")
            for attempt, outcome in (((a, "x"), (b, "y")) if tail == "tie_ab" else ((b, "y"), (a, "x"))):
                check = h.observe(attempt, outcome, 4 / NS)
        elif tail in ("after_before", "after_start"):
            h.start("a")
            after = "boot" if tail == "after_before" else "frontier"
            h.at(4 / NS)
    elif kind.startswith("old_run/") or kind == "no_delivery_law":
        old = h
        attempt = old.start("a")
        tail = kind.split("/")[-1]
        if tail == "complete":
            old.observe(attempt, "x", 1 / NS)
        else:
            receipt(old, 1, recorded=1)
        h = HandHistory(run="goldenquantitynew", index=1, wall=101)
        check = h.boot()
        if tail == "late_receipt":
            check = h.observe(attempt, "x", 1 / NS)
        elif kind == "no_delivery_law":
            h.start("a", job=attempt.body.job)
        h.records = old.records + h.records
    elif kind == "unknown_time":
        attempt = h.start("a")
        receipt(h, None, recorded=1, attempt=attempt, content=Payload.json({"outcome": "x"}))
    elif kind == "unreadable_outcome":
        attempt = h.start("a")
        check = receipt(h, 1, recorded=1, attempt=attempt, content=Payload.text("unreadable name"))
    elif kind == "unreadable_attempt":
        good = h.start("a")
        # 同じ名札を差し替えず、実際の開始の本文そのものを不正にする。
        from dataclasses import replace
        bad = replace(good, body=AttemptStarted(job=good.body.job, contract=ATTEMPT, content=Payload.text("bad")))
        h.records[-1] = bad
        check = h.observe(bad, "x", 1 / NS)
    elif kind == "unknown_attempt":
        check = h.add(Observed(route="executor", caused_by=Ref(RefKind.ATTEMPT, "missing"),
            contract=OUTCOME, content=Payload.json({"outcome": "x"}), received_ns=1), 1 / NS)
    elif kind == "broken_clock":
        other = HandHistory(run="goldenconcurrent", index=0, wall=100)
        other.boot()
        h.records.extend(other.records)
    elif kind == "bad_after":
        h.start("a")
        after = "invalid"
    elif kind == "infinite_candidate":
        candidates = ("a",)
    elif kind not in ("missing_check", "positive", "incomplete"):
        raise AssertionError(f"unknown case {kind}")
    observed = 0 if check.body.received_ns is None else check.body.received_ns
    return Case(Scene(model, h, candidates, h.clock.mono_ns(), observed),
                None if kind == "missing_check" else check, after=after)


def positive5_case():
    model = _lattice_model(durations={"a": ((1., .5), (3., .5)), "b": ((1., 1.),), "f": ((2., 1.),)},
                           measures={a: "report" for a in ("a", "b", "f")})
    h = HandHistory(run="goldenpositive5", wall=100)
    boot = h.boot()
    return Case(Scene(model, h, ("a", "b", "f"), 0, 0), check=boot, horizon=2 * NS)


def zero_case():
    kwargs = quantity_kwargs()
    kwargs.pop("duration_priors")
    kwargs.pop("measure")
    kwargs.update(durations={a: ((0., 1.),) for a in ("a", "b")},
                  measures={a: "report" for a in ("a", "b")})
    h = HandHistory(run="goldenzero", wall=100)
    boot = h.boot()
    return Case(Scene(GenerativeModel(**kwargs), h, ("a", "b"), 0, 0), check=boot)


def state(agent, ledger):
    return (ledger.heads(), agent.frontier, agent.revision, agent._belief.body.content.data)


def exception(error):
    return {"type": type(error).__name__, "message": str(error)}


def timing_text(timing):
    if timing is None:
        return None
    ref = lambda value: None if value is None else str(value)
    data = {"events": [{"id": ref(e.id), "run": ref(e.run), "run_index": e.run_index,
                        "seq": e.seq, "reading": e.reading, "kind": e.kind, "attempt": ref(e.attempt)}
                       for e in sorted(timing.events.values(), key=lambda e: (e.run_index, e.seq, str(e.id)))],
            "attempts": [{"attempt": ref(a.attempt), "job": ref(a.job), "action": a.action,
                          "start_event": ref(a.start_event), "check_events": list(map(ref, a.check_events)),
                          "report_event": ref(a.report_event), "state": a.state} for a in timing.attempts]}
    return content_text(Payload.json(data))


def capture_case(case, mode="one_step"):
    scene = case.scene
    ahead = mode in ("lookahead", "direct_lookahead")
    agent, ledger, ids, belief = setup(scene, "lookahead" if ahead else mode)
    if ahead and case.horizon != 2 * NS:
        # setupの既存Hは2秒。最後のstyleでnsの有限の小さな木へ変更する。
        from sui.records import Preference, Record, Producer, Role
        from sui.s4d_contracts import PREFERENCE
        record = Record(id=ids.new(RefKind.PREFERENCE), at=scene.h.clock.now(), writer=Role.MODEL,
            producer=Producer(component="test.s4b1c_golden", code_version="1"),
            body=Preference(basis=(), contract=PREFERENCE,
                content=Payload.json({"kind": "style", "H_ns": case.horizon, "gamma": 1.25})))
        ledger.append(record, ledger.heads())
        belief = agent.adopt(ledger, clock=scene.h.clock, ids=ids)
        assert belief is not None
    roundtrip = model_from_json(model_json(scene.model))
    assert model_json(roundtrip) == model_json(scene.model)
    entry, = ledger.entries_of(belief.id)
    restored = Agent.restore(model=roundtrip, lineage="s4b1c-restored", ledger=ledger, belief=entry.cid)
    assert restored._belief.body.content.data == belief.body.content.data
    sources = () if case.check is None else ({"fact": str(case.check.id)},)
    if case.after:
        after = ([ledger.entries_of(scene.h.records[0].id)[0].cid] if case.after == "boot" else
                 sorted(agent.frontier) if case.after == "frontier" else ["unknown-cid"])
        sources = ({"unrecorded": {"kind": "tick", "reading": scene.observed_ns, "after": after}},)
    axis = agent.view().reading.timeline
    now = scene.now_ns if axis is None else axis.to_axis(scene.h.clock.run, scene.now_ns)
    observed = scene.observed_ns if axis is None else axis.to_axis(scene.h.clock.run, scene.observed_ns)
    view = agent.view(now_ns=now, observed_ns=observed, check_events=sources)
    saved = {"model_json": encoded_model(scene.model), "belief_content": content_text(belief.body.content),
        "belief_contract": {"name": belief.body.contract.name, "version": belief.body.contract.version},
        "reading_timing_content": timing_text(view.reading.timing),
        "roundtrip_ok": True, "restore_ok": True,
        "request": {"candidates": list(scene.candidates), "u": U, "now_ns": now, "observed_ns": observed,
                    "H_ns": case.horizon if ahead else None, "check_events": list(sources)},
        "decision_content": None, "decision_contract": None, "refused": None,
        "replay_ok": None, "no_write_on_refusal": None}
    before = state(agent, ledger)
    try:
        if mode == "incomplete":
            context = timing_context(view.reading.timing, run=scene.h.clock.run,
                observed_ns=observed, check_events=sources, fact_ancestors=view.fact_ancestors)
            law = posterior(scene.model.duration_priors, scene.model.measure, context).future_records(
                FutureRecordsQuery("a", now, scene.h.clock.run))
            law.information(terms=1, series_budget=0)
            raise AssertionError("the explicit exhausted information budget was accepted")
        if mode == "direct_lookahead":
            draft = evaluate(view, scene.candidates, resolve(current(view.preferences), view), u=U)
        else:
            planner = plan_s4c if mode in ("plan_s4c", "decide_s4c") else plan
            draft = planner(view, scene.candidates, u=U)
    except (AssertionError, ImportError, AttributeError, NameError, TypeError):
        # 台本の間違い・内部の不具合を期待する拒否として採取しない。
        raise
    except Exception as error:
        assert state(agent, ledger) == before
        if mode == "decide_s4c":
            try:
                agent.decide_s4c(scene.candidates, u=U, ledger=ledger, ids=ids, clock=scene.h.clock,
                                now_mono_ns=scene.now_ns, observed_mono_ns=scene.observed_ns)
            except Exception as again:
                assert exception(again) == exception(error)
            else:
                raise AssertionError("decide_s4c accepted what plan_s4c refused")
            assert state(agent, ledger) == before
        return {**saved, "refused": exception(error), "no_write_on_refusal": True}
    assert state(agent, ledger) == before
    if mode == "decide":
        decision, _ = agent.decide(scene.candidates, u=U, ledger=ledger, ids=ids, clock=scene.h.clock,
            now_mono_ns=scene.now_ns, observed_mono_ns=scene.observed_ns, check_events=sources)
    else:
        prepared = agent.prepare(draft, clock=scene.h.clock, ids=ids)
        agent.commit(prepared, ledger=ledger)
        decision = prepared.decided
    assert decision.body.content.data == draft.content.data
    assert agent._belief.body.content.data == before[-1]
    decided_entry, = ledger.entries_of(decision.id)
    rebuilt = replay_decision(model=scene.model, ledger=ledger, decision=decided_entry.cid)
    assert rebuilt.content.data == draft.content.data
    assert rebuilt == draft
    return {**saved, "decision_content": content_text(decision.body.content), "replay_ok": True,
            "decision_contract": {"name": decision.body.contract.name, "version": decision.body.contract.version}}


def json_kwargs(values):
    return {key: (value.tolist() if isinstance(value, np.ndarray) else sorted(value) if isinstance(value, frozenset)
                 else {a: p.as_json() for a, p in value.items()} if key == "duration_priors"
                 else {a: p.tolist() for a, p in value.items()} if key == "a" else value)
            for key, value in values.items()}


def capture_model_call(kind):
    kwargs = quantity_kwargs()
    valid = json.loads(model_json(GenerativeModel(**kwargs)))
    if kind in ("constructor", "old_Q"):
        Q = np.array([[-.25, .25], [.25, -.25]])
        kwargs["Q"] = Q
        valid["Q"] = Q.tolist()
    if kind == "unknown_scheme":
        valid["scheme"] = "sui.model.999"
    elif kind == "unknown_base":
        valid["duration_priors"]["a"]["base"]["version"] = "999"
    elif kind == "unknown_measure":
        valid["measure"]["candidates"][0]["version"] = "999"
    raw = canonical(json_kwargs(kwargs)) if kind == "constructor" else canonical(valid)
    if kind == "noncanonical":
        raw = b" " + raw
    saved = {"input_json": {"body": raw.decode("utf-8"), "sha256": sha256(raw)},
             "model_json": None, "refused": None, "roundtrip_ok": None}
    try:
        model = GenerativeModel(**kwargs) if kind == "constructor" else model_from_json(raw)
    except ValueError as error:
        return {**saved, "refused": exception(error)}
    data = model_json(model)
    assert model_json(model_from_json(data)) == data
    return {**saved, "model_json": encoded_model(model), "roundtrip_ok": True}


def row(observed, prediction="success", *, allowed=(), post="unchanged"):
    return {"mark": "intentional_change" if allowed else "preserve", "allowed_changes": sorted(allowed),
            "prediction_at_d09b639": prediction, "implemented_condition": post, "observed": observed}


def build_scenes():
    scenes = {}
    old = legacy_golden()
    baseline = json.loads((ROOT / "tests/golden_s4b1b.json").read_text(encoding="utf-8"))
    if set(old) != set(baseline):
        raise AssertionError("legacy scene names changed")
    for name, data in old.items():
        reason_change = {"model5/lookahead": "missing_durations", "model5/hand/lookahead": "zero_duration"}.get(name)
        saved = baseline[name]
        if canonical({k: v for k, v in data.items() if k != "refused" or not reason_change}) != canonical(
                {k: v for k, v in saved.items() if k != "refused" or not reason_change}):
            raise AssertionError(f"{name}: existing 1b golden changed outside allowed refusal")
        prediction = "success" if saved["refused"] is None else saved["refused"]["type"]
        scenes[name] = row(data, prediction, allowed=("refused",) if reason_change else (),
                           post=reason_change or "unchanged")
    for kind in ("empty", "complete", "pending", "complete_pending"):
        scenes[f"model6/exact/{kind}/one_step"] = row(capture_case(quantity_case(f"exact/{kind}")))
    scenes["model6/exact/complete_pending/decide"] = row(capture_case(quantity_case("exact/complete_pending"), "decide"))
    for kind in ("empty", "pending", "shared_check", "tie_ab", "tie_ba", "after_before", "after_start"):
        scenes[f"model6/tick/{kind}/one_step"] = row(capture_case(quantity_case(f"tick/{kind}")))
    for kind in ("pending", "complete", "late_receipt"):
        scenes[f"model6/old_run/{kind}/one_step"] = row(capture_case(quantity_case(f"old_run/{kind}")))
    for kind in ("unknown_time", "unreadable_outcome", "unreadable_attempt", "unknown_attempt"):
        scenes[f"model6/{kind}/one_step"] = row(capture_case(quantity_case(kind)))
    for kind, prediction in (("broken_clock", "ModelFalsified"), ("missing_check", "ValueError"),
                             ("bad_after", "ValueError"), ("no_delivery_law", "ModelFalsified")):
        scenes[f"model6/{kind}/one_step"] = row(capture_case(quantity_case(kind)), prediction)
    for version, factory in ((5, positive5_case), (6, lambda: quantity_case("positive"))):
        for mode in ("lookahead", "direct_lookahead"):
            scenes[f"model{version}/positive/{mode}"] = row(capture_case(factory(), mode),
                "OutsideEvaluationType", allowed=DECISION_CHANGES, post="lookahead_success")
    scenes["constructor/Q_duration_priors"] = row(capture_model_call("constructor"), "ValueError",
                                                  allowed=MODEL_CHANGES, post="model7_success")
    for name, kind in (("model6_json/Q_duration_priors", "old_Q"), ("model_json/unknown_scheme", "unknown_scheme"),
        ("model6_json/unknown_base_version", "unknown_base"), ("model6_json/unknown_measure_version", "unknown_measure"),
        ("model6_json/noncanonical", "noncanonical")):
        scenes[name] = row(capture_model_call(kind), "ValueError")
    scenes["model3/zero/one_step"] = row(capture_case(zero_case()))
    scenes["model3/zero/lookahead"] = row(capture_case(zero_case(), "lookahead"), "ValueError")
    scenes["model6/infinite_candidate/one_step"] = row(capture_case(quantity_case("infinite_candidate")), "OutsideEvaluationType")
    scenes["model6/incomplete/information"] = row(capture_case(quantity_case("incomplete"), "incomplete"), "IntegrationIncomplete")
    for mode in ("plan_s4c", "decide_s4c"):
        scenes[f"model6/compat/{mode}"] = row(capture_case(quantity_case("exact/empty"), mode), "ValueError")
    assert len(scenes) == 65, ("unexpected scene count", len(scenes))
    return scenes


def check_predictions(scenes):
    for name, item in scenes.items():
        refusal = item["observed"]["refused"]
        actual = "success" if refusal is None else refusal["type"]
        if actual != item["prediction_at_d09b639"]:
            raise AssertionError(f"{name}: prediction={item['prediction_at_d09b639']}, observed={actual}")


def postcondition(name, item):
    data, condition = item["observed"], item["implemented_condition"]
    if condition in ("missing_durations", "zero_duration"):
        old_message = "lookahead with learning under a changing state is 1d"
        new_message = ("lookahead: durations are required" if condition == "missing_durations" else
                       "lookahead: every finite duration must be positive in ns")
        if data["refused"] not in ({"type": "OutsideEvaluationType", "message": old_message},
                                  {"type": "ValueError", "message": new_message}):
            raise AssertionError(f"{name}: refusal is outside the explicitly allowed reasons")
        assert data["decision_content"] is None
    elif condition == "model7_success":
        assert data["refused"] is None and data["roundtrip_ok"] is True, name
        model = json.loads(data["model_json"]["body"])
        assert model["scheme"] == "sui.model.7", (name, "old model.6 must not become a Q model")
        assert model["Q"] == [[-.25, .25], [.25, -.25]], (name, "Q was lost")
        inputs = json.loads(data["input_json"]["body"])
        for key in ("states", "outcomes", "actions", "a", "learnable", "D", "log_C", "gamma"):
            assert model[key] == inputs[key], (name, key, "constructor input was changed")
    elif condition == "lookahead_success":
        assert data["refused"] is None and data["replay_ok"] is True and data["restore_ok"] is True, name
        assert data["decision_contract"] is not None and data["no_write_on_refusal"] is None, name
        decision = json.loads(data["decision_content"])
        request = data["request"]
        assert decision["evaluation"] == "lookahead" and decision["H_ns"] == request["H_ns"], name
        assert decision["candidates"] == request["candidates"] and decision["u"] == request["u"], name
        assert decision["chosen"] in request["candidates"] and decision["gamma"] == 1.25, name
        count = len(request["candidates"])
        for key in ("expected_cost", "information", "J", "q_pi"):
            assert len(decision[key]) == count and all(type(v) in (int, float) and math.isfinite(v)
                                                      for v in decision[key]), (name, key)
        assert all(c == 0. for c in decision["expected_cost"]), (name, "empty items must have zero cost")
        assert all(i >= 0. for i in decision["information"]), name
        assert all(j == c - i for c, i, j in zip(decision["expected_cost"], decision["information"], decision["J"])), name
        assert all(0 <= p <= 1 for p in decision["q_pi"]) and abs(math.fsum(decision["q_pi"]) - 1) <= 1e-12, name


def compare(baseline, current_scenes, *, implemented):
    expected = baseline["scenes"]
    if set(expected) != set(current_scenes):
        raise AssertionError("scene names differ")
    for name in sorted(expected):
        old, new = expected[name], current_scenes[name]
        # 印・許す欄・新しい条件も凍結した基準と照合する。現行側だけで緩められない。
        assert canonical({k: v for k, v in old.items() if k != "observed"}) == canonical(
            {k: v for k, v in new.items() if k != "observed"}), (name, "policy changed")
        if not implemented or old["mark"] == "preserve":
            assert canonical(old) == canonical(new), (name, "byte mismatch")
        else:
            assert old["mark"] == "intentional_change" and old["allowed_changes"], name
            allowed = set(old["allowed_changes"])
            assert set(old["observed"]) == set(new["observed"]), (name, "columns changed")
            assert allowed <= set(old["observed"]), (name, "unknown allowed column")
            for key in old["observed"]:
                if key not in allowed:
                    assert canonical(old["observed"][key]) == canonical(new["observed"][key]), (name, key, "byte mismatch")
            postcondition(name, new)


def provenance(scenes, files):
    return {"base_commit": BASE_COMMIT, "spec_version": "v0.24", "environment": environment(),
            "environment_sha256": sha256(canonical(environment())),
            "script_sha256": sha256(Path(__file__).read_bytes()),
            "dependency_sha256": {name: sha256((ROOT / name).read_bytes()) for name in DEPENDENCIES},
            "source_file_sha256": files, "source_sha256": source_digest(files),
            "scenes_sha256": sha256(canonical(scenes)),
            "baseline_file_sha256": "printed to stdout; a whole-file digest cannot include itself"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true", help="read and compare; never write")
    parser.add_argument("--implemented", action="store_true", help="require every intentional transition even with unchanged src")
    args = parser.parse_args()
    if args.implemented and not args.check:
        parser.error("--implemented requires --check")
    preflight()
    target = (ROOT / "tests" / "golden_s4b1c.json").resolve()
    if args.path.resolve() != target:
        raise SystemExit(f"the only supported baseline path is {target}")
    files = source_hashes()
    digest = source_digest(files)
    if not args.check:
        if digest != BASE_SRC_SHA256:
            raise SystemExit(f"capture requires d09b639 src={BASE_SRC_SHA256}; got {digest}")
        if args.path.exists():
            raise SystemExit("baseline already exists; use --check (do not regenerate)")
    first = build_scenes()
    if canonical(first) != canonical(build_scenes()):
        raise AssertionError("golden generation is not deterministic")
    if files != source_hashes():
        raise AssertionError("src changed during capture/check; do not mix code versions")
    if not args.check:
        check_predictions(first)
        metadata = provenance(first, files)
        raw = canonical({"schema": "sui.s4b1c.golden.1", "provenance": metadata, "scenes": first})
        # 排他的作成。途中で他の担当が基準を書いていた場合も上書きしない。
        with args.path.open("xb") as output:
            output.write(raw)
        print(f"Wrote {args.path}: {len(first)} scenes, {len(raw)} bytes, sha256={sha256(raw)}")
    else:
        raw = args.path.read_bytes()
        baseline = json.loads(raw)
        assert canonical(baseline) == raw, "baseline is not canonical UTF-8 JSON"
        assert baseline["schema"] == "sui.s4b1c.golden.1"
        metadata = baseline["provenance"]
        assert metadata["base_commit"] == BASE_COMMIT and metadata["spec_version"] == "v0.24"
        assert metadata["environment"] == environment()
        assert metadata["environment_sha256"] == sha256(canonical(environment()))
        assert metadata["source_sha256"] == BASE_SRC_SHA256
        assert source_digest(metadata["source_file_sha256"]) == BASE_SRC_SHA256
        assert metadata["scenes_sha256"] == sha256(canonical(baseline["scenes"]))
        assert metadata["script_sha256"] == sha256(Path(__file__).read_bytes()), "capture script changed"
        # 旧台本/旧基準は凍結。仕様の実装記録やworldsの追記は保存済みの
        # provenanceを更新しない。fixtureの動作の変化は各行のバイト照合で検出。
        for name in DEPENDENCIES[:2] + DEPENDENCIES[3:5]:
            assert metadata["dependency_sha256"][name] == sha256((ROOT / name).read_bytes()), (name, "frozen dependency changed")
        implemented = args.implemented or digest != BASE_SRC_SHA256
        compare(baseline, first, implemented=implemented)
        print(f"P5-a matched: {args.path}: {len(first)} scenes, {len(raw)} bytes, sha256={sha256(raw)}, implemented={implemented}")
    print(f"environment_sha256={sha256(canonical(environment()))} environment={canonical(environment()).decode('utf-8')}")
    print(f"script_sha256={sha256(Path(__file__).read_bytes())} source_sha256={digest}")
    print(f"scenes_sha256={sha256(canonical(first))}")
    for name, item in sorted(first.items()):
        outcome = "success" if item["observed"]["refused"] is None else item["observed"]["refused"]["type"]
        print(f"{name}: {item['mark']}, allowed={','.join(item['allowed_changes']) or '-'}, outcome={outcome}, condition={item['implemented_condition']}")


if __name__ == "__main__":
    main()
