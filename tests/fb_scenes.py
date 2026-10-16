"""Paper-authored SC inventory and finite E0 declarations (v0.12).

Only public types/entry points are used. No window/checker implementation is
imported as an oracle. Expectations are frozen before Environment is created.
The embedded paper rows, including all 32 unspecified identification rows,
are the denominator. Unavailable branches are data, never silently filtered.

Session note (vault not written: this task only authorizes these two files):
2026-10-14, project sui, tool codex. Source: this conversation and paper v0.12.
Codex session: 01a13663-40de-7180-9b8c-82a60fe24c29
Record: C:/Users/you11/.codex/sessions/2026/10/14/rollout-2026-10-14T02-50-36-01a13663-40de-7180-9b8c-82a60fe24c29.jsonl
Reused knowledge: historical missing dependencies must not be added on replay;
applicable as a constraint, not new validation. No commit; no external sources.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re

import fb_check as check
from fb_machine import (
    Action, AllowedPlan, Budget, Contract, CorrectWindow, Cut, Descriptor, E0,
    Environment, Event, Guard, Interval, IntervalRequest, NumericalView,
    Outcome, OutcomeKind, PlanRef, Posting, Program, RecordPlan, Scenario,
    Source, TypedReference, UnknownNotice, declare_observation_e0, obj,
    receipt_unit_id, verification_call_id, clock_source_record, clock_reading_record,
    DeliveryBundle, WorkerNotice, HostNotice,
)

PAPER_PATH = "specs/関所F_Fb_今の約束.md"
PAPER_VERSION = "v0.12"
PAPER_ROWS = json.loads(r'''
[
    {
        "line":  929,
        "cells":  [
                      "SC-01 受付",
                      "計算なし、封筒2。同内容/異内容を別ケース。再受付1、初期正常窓口と再建1を分離",
                      "e1/e2の保存、Accept直前/直後、HostAck前の再受付",
                      "50000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  930,
        "cells":  [
                      "SC-02 同番号の再提示",
                      "原本1、同番号の同値/内容変更/r変更/型変更を別ケース。新しいPostによる同文配送を対照",
                      "同じ受付を返す枝と、原本を変えず不一致を検出する枝",
                      "50000",
                      "未実行・機構未対応",
                      "未確認"
                  ]
    },
    {
        "line":  931,
        "cells":  [
                      "SC-03 保存",
                      "受信1、本文と点。commit前失敗/本文応答喪失/点応答喪失を別ケース。再建0/1",
                      "本文だけ保存、点保存後応答不明、同一PreparedEntryの再照合",
                      "50000",
                      "未実行",
                      "未確認"
                  ]
    },
{
    "line":  932,
    "cells":  [
                  "SC-04 Publish・引き渡し",
                  "1単位、最大3記録、後続仕事1。Publishの種類ごとに別ケース (種類はO表のPublish対応から列挙: 初期計画→初期仕事 (O-02)・Q→Wr (O-05)・R→Wp (O-07)・G→Wv (O-09.a)・EQ→Ep (O-10)・PR→D (O-11)・DF→Ee (O-12)・区間要求→MeasureSegment (O-04)・後続仕事を持たない記録だけのPublish (T/B/Xc/W等)。〔v0.12: 旧「5種」は下書きの係の数で列挙の根拠が無かった〕",
                  "Publish直後で依存未保存かつ仕事行あり、保存後開始、二重列挙、二重起動包み",
                  "100000",
                  "未実行",
                  "未確認"
              ]
},
    {
        "line":  933,
        "cells":  [
                      "SC-05 更新3段",
                      "q1、Wr/Wp/Wv各1。まず例外/重複/外部受信なし。必要な失敗位置はSC-03/04との境界ごとに差し替え",
                      "R保存前のWp待ち、R保存後のWp、P後のcompleted1件、G後のWv",
                      "200000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  934,
        "cells":  [
                      "SC-06 取得・認証・採用",
                      "Q/R/P/Cを持つ前提から、ρ1、取得意図1、Wv1。ok/rejected/insufficient/unknownを別ケース",
                      "実際の取得前の採用禁止、対象違いの認証、返答とVの対応、正しい採用",
                      "100000",
                      "未実行・一部機構未対応",
                      "未確認"
                  ]
    },
    {
        "line":  935,
        "cells":  [
                      "SC-07a 同じ前状態からの2要求とStale",
                      "ρ1。現在の採用d0・結果r0に対し、異なるq1/q2をどちらの新しい採用よりも前に作り、両方のprevious_resultをr0へ固定。下流は採用境界へ絞る",
                      "q1由来のr1を採用した後、q2のprevious_resultはr0のままでStaleになる。逆順も対照にする。この2要求をそのまま順に新導出として採用することを到達目標にしない",
                      "200000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  936,
        "cells":  [
                      "SC-07b 新しい前状態からの逐次採用",
                      "ρ1。q1由来の採用d1・結果r1が保存された後にq2を作り、q2.previous_result=r1とする。各採用の意図は別に持つ",
                      "d1の後にq2由来のd2を正常に採用できる。再採用を確かめる枝は別ケースとし、同じ導出C1に対する別の採用意図d1\u0027を作り、previousはその時の実際の採用を指す。元のq1.previous_resultは書き換えず、測定の適用数も増やさない",
                      "各ケース200000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  937,
        "cells":  [
                      "SC-08 Received 2件",
                      "初期q1、対象受信e1/e2、更新要求を最大2件追加可能にする。下流は要求保存までで切る",
                      "Q(e1)保存後にe2保存、e2の義務が残る、まとめたqが両方を含む場合だけ両義務解消",
                      "100000",
                      "未実行・現行Q2上限では不足",
                      "未確認"
                  ]
    },
    {
        "line":  938,
        "cells":  [
                      "SC-09 評価・くじ・選ぶ",
                      "Ep/D/Ee各1、外部受信なし。Ep=FProblem/NoDecision、Ee=Selected/NoDecisionを分ける",
                      "PR前D行、DF前Ee行、NoDecisionで後続禁止、Selectedでselection",
                      "200000",
                      "未実行・Ep分岐未対応",
                      "未確認"
                  ]
    },
    {
        "line":  939,
        "cells":  [
                      "SC-10 評価対象の対応",
                      "有効なPR/Drawの組を1つ、交換用の異なる問題またはDrawを1つ。仕事の一般実行順は省略した局所接続",
                      "別problem_key、別purpose、別Draw Point、別artifactが拒まれる状態",
                      "100000",
                      "未実行・機構未対応",
                      "未確認"
                  ]
    },
    {
        "line":  940,
        "cells":  [
                      "SC-11 区間の結びつき",
                      "k1、有限端点0/1/2/3、Started1、報告2。8種類を別ケース。隣接k2は端の専用ケース",
                      "報告先着、開始後着、同sample_seq別ID、同内容別slot、開閉差、未来Unproved",
                      "100000",
                      "未実行・有限区間未対応",
                      "未確認"
                  ]
    },
    {
        "line":  941,
        "cells":  [
                      "SC-12 被覆と報告待ち",
                      "k1、正のClaimの有限証拠1組。Startedだけ/Endedだけ/報告なし/Gap/Unavailableを対照",
                      "過大被覆禁止、無報告をGapにしない、責務を持つ合法な待ち",
                      "100000",
                      "未実行・機構未対応",
                      "未確認"
                  ]
    },
    {
        "line":  942,
        "cells":  [
                      "SC-13 Hungと受付",
                      "計算1がHung、席1、受信1。測る報告は1件の独立枝",
                      "占有を保持したままAccept/PutBody/AddEntryが可能",
                      "100000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  943,
        "cells":  [
                      "SC-14 他の仕事のHung＋くじ待ち",
                      "PR保存済みでD待ち、別仕事1がHung。席1/2を別ケース",
                      "席1ではD の資源待ちが正当、席2では空席があるのに同じ理由でDを免除しない。受信は双方で進む",
                      "100000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  944,
        "cells":  [
                      "SC-15 仕事一般のUnknown・占有・同着順",
                      "Wr/Wp/Wv/Ep/D/Eeを各別ケース。基本は対象仕事1、Unknownと遅着値1、停止確認あり/なし。追加対照①は仕事1・容量2・返答喪失後Unknown・Stopなし。追加対照②は同じrun・同じrの2通知でreceipt_seqだけを変え、Unknown先着/値先着を別ケースにする",
                      "基本対照では最初の通知未保存の間は終わりを確定せず、後着で上書きしない。①では実際の確保1が停止未確認のまま残り、容量超過がなくてもUnknownを理由とする解放そのものをINV-10.bで拒む。②ではr同着をseqで決め、後のseqを先に保存しても先行通知の保存を待つ。Accept再試行でseqを変えない",
                      "各ケース100000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  945,
        "cells":  [
                      "SC-16 不明＋異値",
                      "対象仕事1、Unknown/A/Bの3通知。Dを必須、他種は同じ表を各差し替え",
                      "Unknown保存後・DU等の発行前にA/B保存、X未保存でも禁止。T保存後の後着は既存Tを保持",
                      "200000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  946,
        "cells":  [
                      "SC-17 A・A・B",
                      "同じ論理鍵、同値再配送2通と異値1通。Wr、Wp、D、区間slotを別ケース",
                      "受信3件、同値だけでは論理処理増加なし、BでConflict、X前から使用禁止",
                      "200000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  947,
        "cells":  [
                      "SC-18 上位食い違い＋準備済み",
                      "R/PRまたは下流計画が既に存在する前提から、上位異値1件。Wr→Wp、Wp→取得、Ep→D、D→Eeを分離",
                      "既存の確定を改変せず、食い違いを含む新しい開始/使用は停止。持ち主は残る",
                      "150000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  948,
        "cells":  [
                      "SC-19 公平性の対照",
                      "封筒1、保存2段、Wait。受付前待ち、保存後待ち、正しい保存、保存に至らない循環を別グラフ",
                      "不公平Waitは反例外、公平な未保存循環は反例、全部保存後Waitは許可",
                      "10000",
                      "未実行・新検査未対応",
                      "未確認"
                  ]
    },
    {
        "line":  949,
        "cells":  [
                      "SC-20 空の起動",
                      "initialなし、受信2、区間1。計算なしで各保存段を通す",
                      "計算0、受信保存、測る責務が存続",
                      "100000",
                      "未実行・区間との結合未対応",
                      "未確認"
                  ]
    },
    {
        "line":  950,
        "cells":  [
                      "SC-21 縦の接続",
                      "①区間/受信→要求、②要求→R/P/C、③取得→認証/採用、④Ep→D/Ee/選択の4場面。隣接境界の同じ記録・義務を照合する",
                      "各接続の正の到達証拠。別に「評価の実行中に受信保存・更新」が重なる短い橋渡し場面",
                      "各200000",
                      "未実行",
                      "未確認"
                  ]
    },
    {
        "line":  1328,
        "cells":  [
                      "I0",
                      "正常な初期窓口、同じrun、空の保存先、E0のBoot/route/容量/initial宣言。再建0を必ず含める。場面でPostする封筒以外を後から暗黙に追加しない。"
                  ]
    },
    {
        "line":  1329,
        "cells":  [
                      "IQ",
                      "許されたQと固定入力が保存済み、Wr行あり、まだ未開始。SC-04/05またはSC-08の対応Publish・保存から作る。"
                  ]
    },
    {
        "line":  1330,
        "cells":  [
                      "IC",
                      "Q/R/P/Cqが正しく保存済み。Wr/Wpの札・入場・生成・終わり・停止履歴と、残る責務を付ける。SC-05の到達状態に対応。取得はまだない。"
                  ]
    },
    {
        "line":  1331,
        "cells":  [
                      "IG",
                      "ICから同じρが必要な一式を実取得し、GとWv行を持つ。SC-06の取得境界に対応。"
                  ]
    },
    {
        "line":  1332,
        "cells":  [
                      "IE",
                      "EQ/PR/FProblemが保存済み、D行あり・未開始。Epの返答・artifact・T・実行履歴を保持。SC-09の前半に対応。"
                  ]
    },
    {
        "line":  1333,
        "cells":  [
                      "ID",
                      "IEから同じDrawの最初の値通知とDFが保存済み、Ee行あり。Dの開始札・入場・返答・停止管理を保持。SC-09の中間に対応。"
                  ]
    },
    {
        "line":  1334,
        "cells":  [
                      "IK",
                      "bootstrapのroute・時計・有限区間要求kとMeasureSegment行。端点は0/1/2/3。Started等は場面ごとに「まだない／既存」を明示し、EIの出来事と保存された証拠を別に列挙。"
                  ]
    },
    {
        "line":  1335,
        "cells":  [
                      "IT(w)",
                      "当該仕事種の合法な前段から、本体入場前または入場後を選んだ状態。必要Point、Desc、札、Held、返答/停止の有無、所有を全て列挙する。Q/PR/DF等だけを置いて入場履歴を省略しない。"
                  ]
    },
    {
        "line":  1336,
        "cells":  [
                      "IP(u)",
                      "合法なPublish直後。未保存の全slot、PlanRef、P.units、全後続P.work行、発行時の根を保持。SC-04/05/09から接続。"
                  ]
    },
    {
        "line":  1337,
        "cells":  [
                      "IA",
                      "ρの保存済み採用d0と結果r0、その取得・認証・生成の実祖先一式。SC-06/07bから接続。"
                  ]
    },
    {
        "line":  1338,
        "cells":  [
                      "IX",
                      "同じEH/ELと固定根X0、および後着を加えたX1の対照。古い計画・PreparedEntry・認証物を残す。別の根を同じ名前に潰さない。"
                  ]
    },
    {
        "line":  1339,
        "cells":  [
                      "IL",
                      "操作札付きの有限グラフ。受信・保存の各段、能力、障害残量、HostEligible、義務鍵を状態に含む。SC-19用。実模型の抽象化との対応は別に検査。"
                  ]
    },
    {
        "line":  1345,
        "cells":  [
                      "K-R",
                      "宣言した受信1/2件とその保存。新しい計算のきっかけは生成しない。Bootの2slotは分割して落とさない。"
                  ]
    },
    {
        "line":  1346,
        "cells":  [
                      "K-U",
                      "指定した1つのPublishまたは保存境界。既に約束した全仕事の行・PlanRef・所有は残す。境界後を未探索とする場合は「未検査」とし、解消・正常終端にはしない。"
                  ]
    },
    {
        "line":  1347,
        "cells":  [
                      "K-B",
                      "更新1要求のWr/Wp/Wvと取得・採用。SC-07では宣言した2要求と各意図。宣言外の追加要求を生成しない。"
                  ]
    },
    {
        "line":  1348,
        "cells":  [
                      "K-Q",
                      "O-03の宣言した受信と対応Qの保存まで。Qで約束したWrは行と責務を保持した境界として引き渡す。Wr以降の合格を出さない。"
                  ]
    },
    {
        "line":  1349,
        "cells":  [
                      "K-E",
                      "EQ/Ep/D/Ee/selectionまで。作用は生成しない。NoDecision等の枝を成功の枝へ変えない。"
                  ]
    },
    {
        "line":  1350,
        "cells":  [
                      "K-K",
                      "宣言した1区間と報告、端専用ケースだけ隣接2区間。未報告セル・停止未確認を消さない。"
                  ]
    },
    {
        "line":  1351,
        "cells":  [
                      "K-T",
                      "対象仕事1つの終わりと指定通知列。Unknown/A/B、A/A/Bは同じ場面に保持。後続は許可/禁止と行設置の境界まで検査し、その先は未検査。"
                  ]
    },
    {
        "line":  1352,
        "cells":  [
                      "K-H",
                      "指定したHung1件、D1件または受信/区間1件。Hungの占有と停止未確認を保持。"
                  ]
    },
    {
        "line":  1353,
        "cells":  [
                      "K-L",
                      "対象eまたはoの進行性に必要な操作・前提を全て残す。Cutで保存へ出る辺を消したグラフを公平性検査に使わない。"
                  ]
    },
    {
        "line":  1354,
        "cells":  [
                      "K-V",
                      "SC-21の4接続と短い並行の橋渡し。局所接続を縦の全直積の探索へ読み替えない。"
                  ]
    },
    {
        "line":  1360,
        "cells":  [
                      "SC-01/03",
                      "通常受信に加え、Bootの2slotを一方だけ保存した中間状態。HostAck前後と再建0/1を分離",
                      "各50000"
                  ]
    },
{
    "line":  1361,
    "cells":  [
                  "SC-04",
                  "HELD-N/R/E、二重列挙、同じ札を持つ二重包み、Publishの種類ごとに別ケース (列挙は(7)のSC-04の行)。各記述に必要な複数参照のうち1つだけ未保存の対照も置く",
                  "各100000"
              ]
},
    {
        "line":  1362,
        "cells":  [
                      "SC-06",
                      "WvのSuccess/Rejected/Insufficient/Unknownを別ケース。Insufficient後の「Wあり・T未保存」「T/V保存済み・元目的未完」を両方到達目標にする",
                      "各100000"
                  ]
    },
    {
        "line":  1363,
        "cells":  [
                      "SC-08",
                      "δを先に固定。e1のみ、e2のみ、両者をまとめられる宣言、まとめられない宣言、別trigger_slotのケース。Nで上位Conflictが後着する枝と、Pで後着する枝を分ける",
                      "各100000"
                  ]
    },
    {
        "line":  1364,
        "cells":  [
                      "SC-11/12",
                      "end=r／end\u003er、端の開閉、actual_time=Unavailable、Claimの全窓/報告生成、未宣言kind、同seq別ID、固定Xの外だけに証拠が増える対照",
                      "各100000"
                  ]
    },
    {
        "line":  1365,
        "cells":  [
                      "SC-14",
                      "容量1/2。DのClaimStart直後にも止めて、Held=1・Free=0でLaunchが提供される通常対照を含める",
                      "各100000"
                  ]
    },
    {
        "line":  1366,
        "cells":  [
                      "SC-15",
                      "6仕事を別ケース。仕事1・容量2・返答喪失→Unknown・Stopなし、同じrでseqだけ異なる2通知、先行通知未保存を必須とする",
                      "各100000"
                  ]
    },
    {
        "line":  1367,
        "cells":  [
                      "SC-18",
                      "Publish前、Publish後未準備、PreparedEntryあり、Launch後Enter前の4境界に上位Conflictが届くケース。既存保存と新規使用を別々に到達確認",
                      "各150000"
                  ]
    },
    {
        "line":  1368,
        "cells":  [
                      "SC-19",
                      "L-RECEIPTの対照に加え、L-DERIVE.NのStableN成立／正当な喪失、Pの回復後保存／公平な未保存循環を別グラフにする",
                      "各10000"
                  ]
    },
    {
        "line":  1369,
        "cells":  [
                      "SC-21",
                      "4接続を個別に計測し、評価を止めたまま受信保存・更新が進む橋渡しを別ケースにする",
                      "各200000"
                  ]
    },
    {
        "line":  1379,
        "cells":  [
                      "SC-04-DESC",
                      "同じwを行設置→確保→起動→入場→終わりへ進め、Descを保持",
                      "E0-04の各固定欄を一欄ずつ、保存や型は正しい別値へ変更する候補前後。PlanRefの正しい一回解決は別の正対照",
                      "正対照はINV-3.b真。各記述変更は同じ行で偽。根だけでなくmethod/版/args/許可/割当等も対象",
                      "100000"
                  ]
    },
    {
        "line":  1380,
        "cells":  [
                      "SC-04-RELEASE",
                      "同じ確保を保持した通常開始/未開始再試行→確かな停止→一回解放",
                      "同じ確保識別に二回目の解放を加える候補遷移",
                      "一回はINV-3.c真、二回目は同じ行で偽。占有カウンタが0で飽和しても履歴から拒む",
                      "100000"
                  ]
    },
    {
        "line":  1381,
        "cells":  [
                      "SC-03-RETRY",
                      "許された初回準備、応答喪失、同一PreparedEntryの再試行",
                      "名前・s・本文・本文内参照・親・salt・seal・header・CIDを各別ケースで変更",
                      "初回と同一ならINV-4.b真。対応が初回と異なる欄を同じ行が検出。saltだけの比較では不可",
                      "50000"
                  ]
    },
    {
        "line":  1382,
        "cells":  [
                      "SC-03-FIRST",
                      "EH/E0の正しい計画から初回準備し、全再試行で保持",
                      "初回からr、本文、または対象/親対応を誤り、seal/header/CIDはその誤った内容に整合させ、以後は完全に不変にする候補",
                      "正対照はINV-4.c真。誤った初回はINV-4.c偽。再試行不変だけを見るINV-4.bが真でもよい",
                      "50000"
                  ]
    },
    {
        "line":  1383,
        "cells":  [
                      "SC-05-PARENT",
                      "許された保存済み要求/報告を親にし、R/Pは本文参照だけ",
                      "同じ保存済みRまたはPのPredictionを、保存候補の親に入れる",
                      "正対照はINV-5.c真。Prediction親は同じ行で拒否。Pointの実在だけでは通さない",
                      "100000"
                  ]
    },
    {
        "line":  1384,
        "cells":  [
                      "SC-05-CYCLE",
                      "許された型の記号a/bについて親グラフがa→bの非循環入力",
                      "候補グラフにb→aを加える。これは受理前の不正グラフ入力であり、保存済みの合法状態とはしない",
                      "非循環はINV-5.cの非循環条件が真、循環は偽。保存不能やINV-4/5.aの検出だけを代用にしない",
                      "10000"
                  ]
    },
    {
        "line":  1385,
        "cells":  [
                      "SC-05-COMPLETE",
                      "Q1/Q2と各R/P/生成時計を持つ合法な前段から、Q1のCqを1件だけ組む",
                      "CqのR、各P、started_clock、finished_clockを、別要求の保存済み対象へ一欄ずつ差し替える。時計値・runは合法な順序を保つ対照も置く",
                      "正しい対応はINV-6.a真。件数1のままの各誤対応もINV-6.a偽。個数検査だけでは不足",
                      "200000"
                  ]
    },
    {
        "line":  1386,
        "cells":  [
                      "SC-06-ANCESTOR",
                      "同じρ・対象・成功認証・取得時刻を持ち、Gが採用の実祖先となる候補",
                      "取得内容と時刻・可視性を保ち、Gを見えるが実祖先ではない兄弟へ変えた採用候補",
                      "実祖先ならINV-9.a真。兄弟だけなら同じ行で採用不可。保存済み/時刻以前というだけでは不可",
                      "100000"
                  ]
    },
    {
        "line":  1387,
        "cells":  [
                      "SC-14-LIMIT",
                      "`(Occ,allocation,capacity)=(1,1,2)`",
                      "①同じ宣言のまま余分な確保を行う候補で(2,1,2)。②独立したcapacity=1にallocation=2を名乗る宣言候補。合法な(1,1,1)からの比較値は(1,2,1)",
                      "基準はINV-10.a真。①はOcc≤allocationが偽、②はallocation≤capacityが偽。②を正しい初期宣言として受理しない",
                      "100000"
                  ]
    },
    {
        "line":  1388,
        "cells":  [
                      "SC-11-FAMILY",
                      "同じsegment/slotで同じGapを再配送",
                      "同slotでGapとUnavailable。同じ二報告を別slotにする対照。必要なら4枝の全異枝対を別ケース化",
                      "同slot同値はClashなし、同slot異枝はINV-7.aのConflictあり、別slotはその差だけではConflictなし",
                      "100000"
                  ]
    },
    {
        "line":  1389,
        "cells":  [
                      "SC-17-FAMILY",
                      "同slotのGap A・同値A・Unavailable Bを3通知として保持",
                      "Bのslotだけを別slotへ変える対照",
                      "同slotならA/Aは重複、A/BはClash。別slotのBは独立報告。3件の受信保存はどちらでも残る",
                      "200000"
                  ]
    },
    {
        "line":  1390,
        "cells":  [
                      "SC-11-CROSS-M",
                      "二つの適合する区間k1/k2へ、同じMeasurementId・全本体欄が同じ原Frameを結ぶ",
                      "同じMeasurementIdのまま、片方のvalue等の本体欄を一欄変更。他の型・区間・時計条件は成立させる",
                      "同じ原FrameならCL-MEASUREMENTなし。異なる本体ならCL-MEASUREMENTあり、INV-7.aが両Frame鍵と共有測定単位をaffectedへ含める",
                      "100000"
                  ]
    },
    {
        "line":  1391,
        "cells":  [
                      "SC-15-WP/VERIFY",
                      "result/GのPublish直後から、それぞれWp/Wvのrunを保持",
                      "WpのFailure/Unknown、WvのInsufficientを別枝にし、T未発行・未保存、Wだけ先に保持する状態まで進む",
                      "非成功でもTの期待義務が発生。Wv不足はT/Vと目的Wを分離。保存前の解消候補をINV-2.cが拒む",
                      "100000"
                  ]
    },
    {
        "line":  1399,
        "cells":  [
                      "INV-1.a",
                      "01/03/13",
                      "I0、Hung枝はIT",
                      "K-R/H",
                      "Post後未Accept、Accept後HostAck前、未保存中Rebuild",
                      "HまたはP.receiptsが各eを保持",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "独立した受信引受け履歴"
                  ]
    },
    {
        "line":  1400,
        "cells":  [
                      "INV-1.b",
                      "02",
                      "I0、原本1件",
                      "K-R",
                      "同番号同値の再受付と、型/内容/run/r/seqの各不一致",
                      "同じeは同じ受付、別Postの同文は別受信",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "全欄照合・不一致時の原本保持"
                  ]
    },
    {
        "line":  1401,
        "cells":  [
                      "INV-1.c",
                      "01/02/03",
                      "I0",
                      "K-R",
                      "同文e1/e2の各保存、Boot片方だけ保存、両方保存",
                      "再書込みは1slot1点、別eは別点",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "Boot複数slotと期待個数"
                  ]
    },
    {
        "line":  1402,
        "cells":  [
                      "INV-2.a",
                      "04/05/08/12/15/18、15-WP/VERIFY",
                      "IP/IQ/IK/IT",
                      "各K-U/B/Q/K/T",
                      "Publish直後、EndKnown成立直後、各保存前、引渡し前後、待ち、停止未確認",
                      "各発生条件から必要な義務を数え、引継ぎ先と同じ歩で所有を移す",
                      "Wp/Wvの行を保存前に欠かす候補、EndKnown後のT責務を欠かす候補はINV-2.a偽。成功報告後だけを母集団にする検査を識別",
                      "新しい条件発生表、削除差分・期待母集団"
                  ]
    },
    {
        "line":  1403,
        "cells":  [
                      "INV-2.b",
                      "04/05/09/20",
                      "I0または各IP",
                      "K-U/B/E",
                      "全Publish種で依存未保存かつ全後続行あり",
                      "行は存在するが開始は不可、NoDecisionで成功後続なし",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "AllowedRecords/WorksとEUの独立照合"
                  ]
    },
    {
        "line":  1404,
        "cells":  [
                      "INV-2.c",
                      "05/06/09/15/16、15-WP/VERIFY",
                      "IQ/IG/IE/ID/IT",
                      "K-B/E/T",
                      "非成功WpのT待ち、Wv不足のT/V待ちと目的W、成功後続の発行/保存前後",
                      "必要T/Vが保存されても元目的/停止責務は別に残る",
                      "WだけでT/V保存を解消する候補、非成功WpをTなしで終了する候補はINV-2.c偽。未発生の成功P/Cqを要求しない正対照も真",
                      "RequiredEndRecordsと条件発生、目的引継ぎ"
                  ]
    },
    {
        "line":  1405,
        "cells":  [
                      "INV-2.d",
                      "08/18/20",
                      "I0/IX",
                      "K-Q",
                      "同じoのN/P/S、e2の未解消、N/Pそれぞれで前提喪失",
                      "initialなしは義務なし。Pの後着Conflictでも固定保存を提供",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "δ/Match/Discharge、段別有効性"
                  ]
    },
    {
        "line":  1406,
        "cells":  [
                      "INV-2.e",
                      "04/14/18",
                      "IT/IE",
                      "K-U/H",
                      "START-0〜3、HELD-N/R/E、容量2のD待ち、Enter前Conflict",
                      "Free=0でもHeld済みLaunch可。Conflict後Enter不可",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "EW由来Stage/StartReadyと操作集合"
                  ]
    },
    {
        "line":  1407,
        "cells":  [
                      "INV-2.f",
                      "06/08/12/14/15/18",
                      "IG/IK/IE/IT/IX",
                      "対応Cut",
                      "各理由のWitness成立/不成立、席2で別Hungのみ",
                      "席1のD待ち、Wv不足でもT/V保存、停止未確認保持",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "理由の対象・免除先・独立Witness"
                  ]
    },
    {
        "line":  1408,
        "cells":  [
                      "INV-3.a",
                      "04/15",
                      "IT",
                      "K-U/T",
                      "二重列挙、2包みが同じ札で入場を試みる境界",
                      "入場1、札消費1",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "実入場と札の独立履歴"
                  ]
    },
    {
        "line":  1409,
        "cells":  [
                      "INV-3.b",
                      "04/15/18、04-DESC",
                      "IT/IP",
                      "K-U/T",
                      "通常Launch待ち、未開始確認後再試行、開始不明、終わり確定後",
                      "全Desc不変、正しいPlanRef一回解決、確かな未開始だけ再Launch",
                      "04-DESCの各一欄変更は同じ行で偽。開始不明からの再Launch/Enter候補も偽。正しい参照解決まで記述改変として拒まない",
                      "Desc全欄と独立した開始不明観測"
                  ]
    },
    {
        "line":  1410,
        "cells":  [
                      "INV-3.c",
                      "04/15、04-RELEASE",
                      "IT",
                      "K-U/T",
                      "HELD-N/R、確かな停止後の一回解放",
                      "同じ確保を保持し、再試行で確保数を増やさない",
                      "同じ確保の二回目解放候補はINV-3.c偽。カウンタが変わらなくても履歴で判定",
                      "確保/解放対応。解放後再確保方式は範囲外"
                  ]
    },
    {
        "line":  1411,
        "cells":  [
                      "INV-4.a",
                      "03/04",
                      "I0/IP",
                      "K-R/U",
                      "本文だけ存在、点追加、照合済み",
                      "孤立本文は合法、Eの全点は本文と整合",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "seal/header/CIDの独立計算"
                  ]
    },
    {
        "line":  1412,
        "cells":  [
                      "INV-4.b",
                      "03/04/18、03-RETRY",
                      "I0/IP",
                      "K-R/U",
                      "許された初回準備、本文/点の応答喪失、再試行、Rebuild後",
                      "全固定欄を初回と一致させる",
                      "各固定欄の変更をINV-4.b自身が偽と判定。初回から同じ誤りを保持するケースは4.cの担当として分離",
                      "salt以外も含む全固定欄"
                  ]
    },
    {
        "line":  1413,
        "cells":  [
                      "INV-4.c",
                      "03/04、03-FIRST",
                      "I0/IP",
                      "K-R/U",
                      "初回準備、確認、準備の片付け直前",
                      "E0/EH/EWの許された内容と初回準備が一致",
                      "初回から誤ったr/本文/対応を固定し、再試行が完全一致でもINV-4.c偽。確認前廃棄も同じ行で拒否",
                      "初回値の独立照合、実読戻し"
                  ]
    },
    {
        "line":  1414,
        "cells":  [
                      "INV-5.a",
                      "04/05/09",
                      "IP/IQ/IE/ID",
                      "K-U/B/E",
                      "後続slotの参照が未保存、保存後に準備可能",
                      "R後P、P後Cq、EV後S",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "型付きPoint全列挙とPlanRef解決"
                  ]
    },
    {
        "line":  1415,
        "cells":  [
                      "INV-5.b",
                      "04/05/09/18",
                      "IT",
                      "K-U/B/E",
                      "各仕事の必要Point1個だけ欠ける状態、揃う状態、Enter前使用禁止",
                      "全Pointと許可が揃って開始",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "仕事別全参照、Claim/Enter双方の照合"
                  ]
    },
    {
        "line":  1416,
        "cells":  [
                      "INV-5.c",
                      "03/05/09、05-PARENT/CYCLE",
                      "合法なIP。CYCLEは受理前の候補グラフ",
                      "K-U/B/E",
                      "許された出来事の親とR/Pの本文参照を分ける保存",
                      "保存済み要求/報告を親にした非循環の接続",
                      "Prediction親候補と循環グラフはINV-5.cの該当節が偽。参照未保存や保存不能の拒否だけを識別成功としない",
                      "親型・因果グラフ、候補検査入口と実台帳との対応"
                  ]
    },
    {
        "line":  1417,
        "cells":  [
                      "INV-6.a",
                      "05/17、05-COMPLETE",
                      "IQと、交換用Q2の合法な前段",
                      "K-B",
                      "Wr終了時Cqなし、Wp後Cq1件、再配送後も1件",
                      "Q/R/全P/生成時計が同じ要求に対応",
                      "件数を1のまま保ちR/P/時計だけを別要求へ替えた各候補はINV-6.a偽。個数だけの判定を識別",
                      "全対応と生成元の独立証拠"
                  ]
    },
    {
        "line":  1418,
        "cells":  [
                      "INV-6.b",
                      "11/15/17/07b",
                      "IK/IT/IA",
                      "K-K/T/B",
                      "A/AからA/A/B、同Draw再通知、同観測の再提示、再採用",
                      "受信増加と論理処理不増加",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "RIGHT-APPLYの/2射影・全権利の独立カウント"
                  ]
    },
    {
        "line":  1419,
        "cells":  [
                      "INV-6.c",
                      "01/11/06/07b",
                      "I0/IK/IC/IA",
                      "K-R/K/B",
                      "同内容別slot、同文別Post、別取得意図、別再採用意図",
                      "別出来事を保持し、同じ測定の再配送だけ同一視",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "item_slot・意図・読み手の区別"
                  ]
    },
    {
        "line":  1420,
        "cells":  [
                      "INV-7.a",
                      "11/16/17、11-FAMILY/CROSS-M、17-FAMILY",
                      "IK/IT。CROSS-Mは適合するk1/k2",
                      "K-K/T",
                      "同値2通、異値追加、同slot異枝、同seq別ID、二つの区間への同じ原Frame",
                      "同値再配送、別slot、同じ原Frameの別区間結合、Unknown＋Aだけ",
                      "同slot異枝はConflict。別slotという差だけでは非Conflict。同じMeasurementIdの異なる本体は区間をまたいでもClash、同一本体は非Clash。両側のaffectedも照合",
                      "共通比較族、CrossKeyClash、affected"
                  ]
    },
    {
        "line":  1421,
        "cells":  [
                      "INV-7.b",
                      "16/18/06/10",
                      "IX/IG/IE/ID",
                      "K-T/U/B/E",
                      "Xc保存前の新規使用禁止、Launch後Enter前禁止",
                      "Xc/W/T/受信の保存と既存PreparedEntry保存は可能",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "用途付きUseDeps/EvidenceRefs閉包"
                  ]
    },
    {
        "line":  1422,
        "cells":  [
                      "INV-7.c",
                      "16/18",
                      "IX",
                      "K-T/U",
                      "旧確定後に異値保存、旧根の再読、新根の使用",
                      "旧T/R/PR/DF/DU不変、新使用だけ禁止",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "根別判定と後着による変更の検査"
                  ]
    },
    {
        "line":  1423,
        "cells":  [
                      "INV-8.a",
                      "05/08/09/21",
                      "IQ/IE/ID/IX",
                      "K-B/Q/E/V",
                      "Wr→Wp→Wv間、Ep→D→Ee間に新受信",
                      "Xnum固定、認証の証拠像だけ別",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "要求から全段への全寿命対応"
                  ]
    },
    {
        "line":  1424,
        "cells":  [
                      "INV-8.b",
                      "05/09/21",
                      "IQ/IE/ID",
                      "K-B/E/V",
                      "新Received保存後に古い仕事が実入力を読む",
                      "古い仕事は旧入力、新要求は新根",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "EWの実読取り観測"
                  ]
    },
    {
        "line":  1425,
        "cells":  [
                      "INV-9.a",
                      "06/15/18、06-ANCESTOR",
                      "IC/IG/IT",
                      "K-B/T",
                      "実取得・各Wv返答・対象付きV・採用候補",
                      "当該ρの実祖先にある必要取得と、対象に結んだ成功認証",
                      "対象・認証・取得時刻が同じでも、取得が見える兄弟だけならINV-9.a偽。実祖先なら他条件成立下で真。Vの返答不一致も従来どおり対象",
                      "実祖先、対象指定認証入口、実DTO結合"
                  ]
    },
    {
        "line":  1426,
        "cells":  [
                      "INV-9.b",
                      "07a/07b",
                      "IA",
                      "K-B",
                      "同じr0から2Q→一方採用後Stale。d1後にQ2生成→d2",
                      "逆順Stale、同Cqの別意図による再採用",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "ρごとの未保存採用予約と実系列"
                  ]
    },
    {
        "line":  1427,
        "cells":  [
                      "INV-10.a",
                      "04/13/14/15、14-LIMIT",
                      "IT/IE、独立した容量宣言",
                      "K-U/H/T",
                      "正常な(1,1,2)、通常確保/Held再試行/Hung/Unknown",
                      "占有・割当・容量を別々に記録して両不等式成立",
                      "(2,1,2)は占有上限の節が偽。(1,2,1)は割当宣言上限の節が偽。後者は不正宣言候補の拒否であり正常到達目標ではない",
                      "EWの占有、有効割当と独立capacityの照合"
                  ]
    },
    {
        "line":  1428,
        "cells":  [
                      "INV-10.b",
                      "15/04",
                      "IT",
                      "K-T/U",
                      "仕事1容量2、返答喪失Unknown、Stopなし。Stopあり枝",
                      "Stopなしは占有保持、確認後だけ一回解放",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "容量超過に頼らない解放の検査"
                  ]
    },
    {
        "line":  1429,
        "cells":  [
                      "INV-11.a",
                      "01/02/13/20",
                      "I0/IT",
                      "K-R/H",
                      "初期正常・再建後・HostEligible先頭、HostAck前",
                      "後方eの待ちは可、先頭は計算非依存",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "正常性/先頭/HostAckの分離"
                  ]
    },
    {
        "line":  1430,
        "cells":  [
                      "INV-11.b",
                      "03/13/20",
                      "I0/IT",
                      "K-R/H",
                      "SAVE-3〜8、能力0/1、失敗予算0で能力あり",
                      "後段能力不足でも前段の操作は有効",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "保存段別の能力と実在照合"
                  ]
    },
    {
        "line":  1431,
        "cells":  [
                      "INV-11.c",
                      "13/14/21",
                      "受信射影が同じI0/ITの対",
                      "K-H/V",
                      "同じ受信段で計算なし/Running/Hung/占有差の状態対",
                      "受信サービスの有効集合が同じ",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "状態対またはガード構造の検査"
                  ]
    },
    {
        "line":  1432,
        "cells":  [
                      "INV-12.a",
                      "11/12",
                      "IK/IX",
                      "K-K",
                      "8報告型、完了窓境界、Unavailable、Claim生成分類、固定Xの外の証拠",
                      "正しいSupport、未来Unproved、Startedだけの被覆0",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "有限セル・時計・全証拠閉包・/2との接続"
                  ]
    },
    {
        "line":  1433,
        "cells":  [
                      "INV-12.b",
                      "12/20",
                      "IK",
                      "K-K",
                      "報告なし、部分報告、証拠待ち、Endedあり未報告セル",
                      "実在するMeasureSegment責務による待ち",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "未報告セルと責務の母集団"
                  ]
    },
    {
        "line":  1434,
        "cells":  [
                      "INV-13.a",
                      "20、対照05/09",
                      "I0 initial=None/あり",
                      "K-R/K/B/E",
                      "initialなしで受信/区間保存、計算行・入場0",
                      "MeasureSegmentは存続、initialありでは宣言した仕事のみ",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "bootstrap由来の全計算仕事の列挙"
                  ]
    },
    {
        "line":  1435,
        "cells":  [
                      "INV-13.b",
                      "20/11/13",
                      "initial以外が同じI0/IKの対",
                      "K-R/K/H",
                      "同じ口・区間・受信段の状態対",
                      "initialなしでも測定/受信の責務とサービスが同じ",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "対照状態の関係。計算の結果まで等しいとはしない"
                  ]
    },
    {
        "line":  1436,
        "cells":  [
                      "INV-14.a",
                      "09/15/17",
                      "IE/IT(D)",
                      "K-E/T",
                      "同Draw通知重複、別WorkId付替えを試す境界",
                      "同じ要求の入場1、DF再書込みは可",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "Draw要求全欄とWorkId横断集計"
                  ]
    },
    {
        "line":  1437,
        "cells":  [
                      "INV-14.b",
                      "15/16/10",
                      "IT(D)/ID",
                      "K-T/E",
                      "Unknown/Failure/遅着後、同根の評価精密化",
                      "再抽選なし、精密化は同じDraw Point/値",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "全終わり枝と精密化の対応"
                  ]
    },
    {
        "line":  1438,
        "cells":  [
                      "INV-15.a",
                      "15/16",
                      "ITの6仕事",
                      "K-T",
                      "同r・異seq、後続だけ先に保存、先行Post未受付",
                      "先行通知の保存後にだけ終わり確定",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "EHの前方受付範囲と保存の照合"
                  ]
    },
    {
        "line":  1439,
        "cells":  [
                      "INV-15.b",
                      "15/16/17",
                      "ITの6仕事",
                      "K-T",
                      "Unknown先着/値先着、後着A/B、T保存前後",
                      "終わり固定、Conflictは全報告から別判定",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "6仕事の終わりと後続生成の全対応"
                  ]
    },
    {
        "line":  1440,
        "cells":  [
                      "INV-16.a",
                      "09/10/15",
                      "ID/IT(Ee)",
                      "K-E/T",
                      "Selected/NoDecision/Unknown/Failure/未認証の各枝",
                      "認証された対応SelectedだけS、他は終わり保存",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "実artifactの認証とselection接続"
                  ]
    },
    {
        "line":  1441,
        "cells":  [
                      "INV-16.b",
                      "09/10/18",
                      "IE/ID/IX",
                      "K-E/U",
                      "異problem/目的/Draw/根/artifactを1欄ずつ交換",
                      "全対応が揃うPR→DF→EV→S",
                      "未具体化 (識別力は未確認。合法な到達だけで確認済みとしない)",
                      "F-a入力・artifact・発行物の実結合"
                  ]
    },
    {
        "line":  1442,
        "cells":  [
                      "L-RECEIPT",
                      "19と追加19-T1/T2、接続01/03/13/20",
                      "IL/I0/IT",
                      "K-L",
                      "合法な受付・保存段、回復後保存、保存後待ち",
                      "不公平候補を除外し、公平な保存経路を許す",
                      "19-T1は対象別に不公平で候補外。19-T2は公平な未保存候補として違反。操作種類だけの公平性判定を識別",
                      "対象付き操作札、候補部分グラフと完全グラフの対応"
                  ]
    },
    {
        "line":  1443,
        "cells":  [
                      "L-DERIVE",
                      "19と追加19-N1〜N4、08/18",
                      "IL/IX",
                      "K-L/Q",
                      "N/P、安定前提でPublish→Q保存、正当な前提喪失時の所有保持",
                      "ReadyN交互では発行保証対象外。安定後は合法Publishと保存",
                      "19-N1を強い公平性で違反にしない。N2の未選択は不公平として除外。N3は達成。N4は安定前提なのに操作欠落で違反",
                      "StableN、対象別公平性、実際のReadyNの根拠との接続"
                  ]
    },
    {
        "line":  1455,
        "cells":  [
                      "SC-19-T1 対象を無視した見かけの公平",
                      "e1/e2は受付・本文確認まで済み、未保存。状態pで`a1=AddEntry(e1)`と`a2=AddEntry(e2)`が継続して有効。完全グラフには両方の辺がある",
                      "pに留まるa1の辺だけを無限に巡る候補C1。a2の有効性は完全グラフから取る",
                      "a2を永久に実行しないので対象別の弱い公平性を満たさず、この候補は反例から除く",
                      "AddEntryという操作種類が繰り返されたことだけでは公平としない"
                  ]
    },
    {
        "line":  1456,
        "cells":  [
                      "SC-19-T2 両対象を実行しても未保存",
                      "T1と同じ有効性。保存呼出しは能力あり・正常応答だが、誤った窓口遷移により対象eの正しい保存対応が成立しない抽象負例。永久の置き場失敗とはしない",
                      "a1/a2両方の辺を含むC2を、各辺を無限回通る形で巡る。同じe1/e2が未保存",
                      "公平性と環境前提を満たす未保存実行としてL-RECEIPT違反候補",
                      "公平性を満たす側を誤って除外しない。保存操作を呼んだ回数だけでSavedにしない"
                  ]
    },
    {
        "line":  1457,
        "cells":  [
                      "SC-19-N1 ReadyNが交互",
                      "未発行oについてtではReadyN真、fでは偽。`t→f→t`。PublishMatching(o)はtで有効、fで無効。完全グラフのtには合法Publishの出口も置く",
                      "Publishせずt/fを交互に無限巡回",
                      "Publishは継続有効ではないので、この不選択は弱い公平性に反しない。StableNは不成立。要求未発行だけではL-DERIVE違反にしない",
                      "強い公平性への取り違えを識別"
                  ]
    },
    {
        "line":  1458,
        "cells":  [
                      "SC-19-N2 安定したReadyNで不選択",
                      "有限の前置列の後、ReadyN真のtだけに留まり、PublishMatching(o)が継続有効",
                      "Waitだけを無限に選ぶ",
                      "StableNは成立するが、対象操作の弱い公平性を満たさない。この候補は反例から除く",
                      "「ReadyNが安定したから全てのWait経路が反例」という誤判定を防ぐ"
                  ]
    },
    {
        "line":  1459,
        "cells":  [
                      "SC-19-N3 安定前提で達成",
                      "N2と同じ前提から合法Publishを選び、P段のL-ENVと対象slot別公平性も成立",
                      "合法Publish→必要slot保存→Dischargeδ",
                      "N/P双方の保証を達成。保存後Waitは反例でない",
                      "N2と同じ前提の正の到達対照"
                  ]
    },
    {
        "line":  1460,
        "cells":  [
                      "SC-19-N4 前提成立なのに操作を隠す",
                      "ReadyNが独立した根拠から継続して真。しかし誤った窓口はPublishMatchingを提供せず、Waitだけを提供",
                      "o未発行のまま無限Wait",
                      "実際のEnabledに対する公平性は空振りで成立しても、StableNの下で発行されないのでL-DERIVE違反。同時にINV-2.dの操作提供違反",
                      "Readyを実操作集合から逆算して、操作欠落を保証対象外にする抜けを識別"
                  ]
    },
    {
        "line":  891,
        "cells":  [
                      "H-01 原典と条件一覧",
                      "S:267–405の各約束・仕事・記録・例外が条件一覧にあるか。前提→結論が弱化/過強化されていないか。未対応条件が合格の分母から消えていないか",
                      "全行。表の非空やIDの存在だけでは意味の網羅を保証しない"
                  ]
    },
    {
        "line":  892,
        "cells":  [
                      "H-02 同一性と依存",
                      "意味の比較欄、相互排他、同じ権利の単位、依存の閉包がS:313–346と一致するか",
                      "2、6、7、14、15。特殊な値・誤実装名・作者の印を参照しない"
                  ]
    },
    {
        "line":  893,
        "cells":  [
                      "H-03 F-aとの接続",
                      "DTO、発行済みartifact、対象に結んだ認証物、実際の取得を区別しているか。有限記号の対応を実DTO/入口で確かめられるか",
                      "9、16と終わりの表。模型のokという値だけでは実認証を保証しない。結合試験は別"
                  ]
    },
    {
        "line":  894,
        "cells":  [
                      "H-04 被覆の意味",
                      "有限セルの対応と証拠の生成関係がA-13〜15および個別の観測契約と一致するか",
                      "12。実機の測定契約・実時計の精度は有限模型の合格から導かない"
                  ]
    },
    {
        "line":  895,
        "cells":  [
                      "H-05 独立した観測",
                      "環境の控えが窓口の自己申告の写しになっていないか。環境だけが書ける領域と、窓口が変えられる領域が分かれているか",
                      "E0/EH/EW/EP/EA/EI、11/13。書込み領域は形式検査、観測の意味は人の点検"
                  ]
    },
    {
        "line":  896,
        "cells":  [
                      "H-06 公平性と場面",
                      "操作の対象単位、失敗枝の前提、ホスト順、切断、有限化が保証文と一致するか",
                      "L各行と場面表。小さい範囲の合格を任意サイズへ広げない"
                  ]
    }
]
''')

ROWS_BY_LINE = {r["line"]: tuple(r["cells"]) for r in PAPER_ROWS}
SC_TABLE = {ROWS_BY_LINE[n][0].split()[0]: n for n in range(929, 951)}
IDENTIFICATION_TABLE = {ROWS_BY_LINE[n][0]: n for n in range(1379, 1392)}
FAIRNESS_TABLE = {ROWS_BY_LINE[n][0].split()[0]: n for n in range(1455, 1461)}
CONDITION_TABLE = {ROWS_BY_LINE[n][0]: n for n in range(1399, 1444)}
UNSPECIFIED_ROWS = tuple(k for k, n in CONDITION_TABLE.items()
                         if "未具体化" in ROWS_BY_LINE[n][6])
HUMAN_ROWS = tuple((f"H-{i:02}", "未点検") for i in range(1, 7))
EXECUTION_BOUND_NOTE = (
    "第2回SC-01 I0: 2封筒・同内容/異内容・再受付1・再建0/1を維持し、"
    "計算/区間/起動障害/保存障害/資源/引継ぎの無関係な宣言を空に明示。"
    "上限は50,000とし、超えても上げない。局所完走はI0全体の完走に数えない。"
)
READ_SCOPE_AUDIT = (
    "CorrectWindow/Environmentの本体と各INV判定式は未読。",
    "declare_observation_e0のdocstring抽出時、直後1544-1546の3行を誤表示。"
    "期待値・場面選択・指摘の根拠には用いていない。厳密な読取り制限からの逸脱として報告する。",
    "外部Web資料は使用していない。紙は(7)(10)の表全文と関連節の該当部分を読んだ。",
    "第2回: docstringは指定開始行から閉じ引用符までで切り出した。型別名の範囲指定598-604で"
    "fb_check.py:598のreturn tuple(result)を1行余分に表示した。場面/期待値の根拠には使わず、INV本体は未読。",
    "第3回: 公開宣言の旧行範囲を併用した読みでfb_machine.py:628と789-810の公開ヘルパー本体を余分に表示した。"
    "窓口本体とINV判定本体は未読。表示した本体は場面/期待値の根拠に使用せず、以後は宣言名から型の欄/公開契約定数だけを抽出。",
    "第4回: PUBLIC_MODEL_CONTRACTS/PUBLIC_CHECK_CONTRACTS、宣言名から抽出した凍結型/欄/docstring、"
    "許可されたtest_fb_machine.pyの作例、紙769-802/933-950/1328-1370/1505-1516の該当部分を読んだ。"
    "公開ヘルパーを含む本体の表示なし。外部資料なし。",
    "第5回: 紙944/1044/1328-1354/1366とPUBLIC_CHECK_CONTRACTSの該当部分を読んだ。"
    "窓口・判定・公開ヘルパーの本体は未読。P-10の原因と修正箇所3732は依頼の報告を出所とし、"
    "場面と6歩の回帰を公開入口で再実行して解消を確認。外部資料なし。",
)

# These restrictions are part of the *input*, not inferred from a passing run.
ASSUMPTIONS = (
    "紙に無い仮定 A-SHAPE: Event/Objectは有限模型の欄表記。実DTOの外形検査を証明しない (紙451-467; fb_machine.py:261)。",
    "紙に無い仮定 A-IO: 同一I/O再試行は状態内の無限履歴でなく辺に残す (fb_machine.py:936-944)。",
    "紙に無い仮定 A-PRESENT: 通常は原提示+再提示1回。局所構造の宣言でpresentation_limit=1の枝は再提示を未検証として分離。SC-01の再受付1は保持 (fb_machine.py:902-905)。",
)


@dataclass(frozen=True)
class Goal:
    id: str
    text: str
    probe: str
    args: tuple = ()


@dataclass(frozen=True)
class Scene:
    id: str
    paper_id: str
    lines: tuple[int, ...]
    initial_id: str
    cut: Cut
    max_states: int
    e0: E0 | None
    goals: tuple[Goal, ...]
    prefix: str = ""
    blocker: str = ""
    assumptions: tuple[str, ...] = ASSUMPTIONS
    negative_controls: tuple[str, ...] = ()
    # A positive executable slice never certifies omitted branches of its SC.
    remaining: tuple[str, ...] = ()
    scope_class: str = "a"
    scope_reason: str = "紙の構造を模型で確かめる。"
    implementation_scope: tuple[str, ...] = ()
    parts: tuple[Scene, ...] = ()

    @property
    def applicable_rows(self):
        overrides = {
            "SC-04-DESC": ("INV-3.b",), "SC-04-RELEASE": ("INV-3.c",),
            "SC-03-RETRY": ("INV-4.b",), "SC-03-FIRST": ("INV-4.c",),
            "SC-05-PARENT": ("INV-5.c",), "SC-05-CYCLE": ("INV-5.c",),
            "SC-05-COMPLETE": ("INV-6.a",), "SC-06-ANCESTOR": ("INV-9.a",),
            "SC-14-LIMIT": ("INV-10.a",), "SC-11-FAMILY": ("INV-7.a",),
            "SC-17-FAMILY": ("INV-7.a",), "SC-11-CROSS-M": ("INV-7.a",),
            "SC-15-WP/VERIFY": ("INV-2.a", "INV-2.c"),
        }
        if self.paper_id in overrides:
            return overrides[self.paper_id]
        if self.paper_id == "SC-19-N4":
            # The 45-row index at 1405 omits this extra branch; paper 1460
            # explicitly requires both rows. Keep that additional connection.
            return ("L-DERIVE", "INV-2.d")
        if self.paper_id.startswith("SC-19-"):
            return ("L-RECEIPT",) if "-T" in self.paper_id else ("L-DERIVE",)
        key = self.paper_id.removeprefix("SC-")
        rows = tuple(row for row, n in CONDITION_TABLE.items()
                     if key in re.findall(r"(?<!\d)(\d{2}[ab]?)(?!\d)", ROWS_BY_LINE[n][1]))
        if self.paper_id == "SC-15" and "-tie-" in self.id:
            # Paper 794-801/944/1366: Post/Accept order, ownership and saving
            # also apply to the new tied-r contrast, beyond the old row index.
            rows = tuple(dict.fromkeys((*rows, "INV-1.a", "INV-2.b", "INV-11.a", "L-RECEIPT")))
        return rows

    @property
    def paper_requirements(self):
        # Preserve the complete original row, including contrasts not executable.
        return tuple((n, ROWS_BY_LINE[n]) for n in self.lines if n in ROWS_BY_LINE)

    @property
    def specified_contrast(self):
        if self.paper_id not in IDENTIFICATION_TABLE:
            return None
        cells = ROWS_BY_LINE[IDENTIFICATION_TABLE[self.paper_id]]
        return {"legal_precondition": cells[1], "condition_difference": cells[2],
                "expected": cells[3],
                "legal_input_contrast": self.paper_id in (
                    "SC-11-FAMILY", "SC-17-FAMILY", "SC-11-CROSS-M", "SC-15-WP/VERIFY"),
                "identification_execution": "未実行・正しい窓口の件数へ負の対照を加算しない"}


def fixed(base: E0, extra_conditions=(), extra_references=()) -> E0:
    """Declare before creating Environment; never consume observed Point/CID."""
    expected = declare_observation_e0(base)
    # Paper 1205: interval save[k] starts at H undertaking, before Publish.
    # Replace that same instance's default Publish trigger, never duplicate it.
    overrides = {b.key for b in extra_conditions}
    expected = replace(expected, completions=tuple(b for b in expected.completions if b.key not in overrides) + tuple(extra_conditions),
                       references=expected.references + tuple(extra_references))
    return replace(base, observation_declarations=expected)


def received(data=b"same"):
    # Paper 458/464: unknown internal names are retained, not resolved to Point.
    return Event("Received", obj(route_epoch="route-0", media_type="application/octet-stream",
                                 data=data, claims=obj(request="unknown-request", segment="unknown-segment")))


def receipt_e0(count=1, different=False, boot=False, budget=Budget()):
    events = tuple(received(b"different" if different and i else b"same") for i in range(count))
    if boot:
        events = (Event("Boot", obj(declaration=obj(capacity=(("think", 1), ("measure", 1)),
                         scope="one", routes=("route-0",), initial=None, environment="finite"))),)
    return fixed(E0(capacity=(("think", 1), ("measure", 1)),
                    allocation=(("think", 1), ("measure", 1)),
                    postings=tuple(Posting(f"e{i+1}", event, 1) for i, event in enumerate(events)),
                    receipt_kinds=tuple((i, event.kind) for i, event in enumerate(events)), budget=budget))


def lifecycle_e0(*, stop=True, budget=Budget(), capacity=1, external=False):
    """SC-04's initial Publish and execution boundary, not a completed SC-05.

    紙に無い仮定 A-INITIAL-WIRE: process/reader records use finite symbolic
    contracts because the paper has no full initial-process wire definition.
    This assumption is confined to this boundary slice; it supplies no R/P/C,
    mathematical truth, completed update, certificate or lawful IC/IG/IE/ID.
    """
    process, reader, request = (PlanRef("initial", s) for s in ("process", "reader", "q"))
    records = (
        RecordPlan("process", Contract("model.process", "1"), "Event", obj(origin="bootstrap")),
        RecordPlan("reader", Contract("model.reader", "1"), "Event", obj(origin="bootstrap")),
        RecordPlan("q", Contract("computation_requested", "1"), "Event",
                   obj(origin=reader, method=Contract("finite_update", "1"),
                       args=obj(model=reader, previous_result=None), inputs=(reader,), algorithm_draws=()),
                   (TypedReference("PATH-Q0", ("origin",), reader, "UE", "numerical"),
                    TypedReference("PATH-Q0", ("args", "model"), reader, "UE", "numerical"),
                    TypedReference("PATH-Q0", ("inputs", 0), reader, "UE", "numerical"))),
    )
    work = Descriptor("wr", process, request, "belief_update", "result", reader,
                      Contract("finite_update", "1"), Contract("finite_update_result", "1"),
                      obj(model=reader, previous_result=None), frozenset((reader,)),
                      NumericalView(frozenset((reader,))), "bootstrap", frozenset((process,)),
                      request, "Wr", (("think", 1),), frozenset((process, reader, request)))
    initial = obj(generator="bootstrap", initial_slot="q1", reader=reader,
                  method=Contract("finite_update", "1"))
    resource = (("think", capacity), ("measure", 1))
    boot = Event("Boot", obj(declaration=obj(initial=initial, capacity=resource, scope="one",
                                             routes=("route-0",), environment="finite")))
    plan = AllowedPlan("initial", "O-02", ("bootstrap", "q1"), records, (work,),
                       (Guard("saved", PlanRef(receipt_unit_id("run-0", 0), "declaration")),))
    # semantic_limits is a missing execution contract, not a general H-03 QA
    # note (a public call returned MissingContract when the note was put there).
    # Keep A-INITIAL-WIRE in Scene.assumptions and never credit this local
    # declared symbolic contract as an IC/IG/IE/ID or F-a-valid prefix.
    posts = (Posting("boot", boot, 0),)
    if external:
        posts += (Posting("incoming", received(), 1, frozenset((request,))),)
    return fixed(E0(initial=initial, capacity=resource, allocation=(("think", 1), ("measure", 1)),
                    postings=posts, plans=(plan,), programs=(Program("wr", (), stop),),
                    receipt_kinds=((0, "Boot"),) + (((1, "Received"),) if external else ()),
                    budget=budget))


def interval_undertaking_e0(count=0, *, boot=False):
    """The H undertaking and receipt slice; k publication remains a named gap."""
    # Paper 723: independent finite cells for [0,2), not copied from Support.
    from fb_machine import Cell
    cells = frozenset((Cell(0, 0), Cell(0, 1), Cell(1, 1), Cell(1, 2)))
    request = IntervalRequest("k1", PlanRef("segment", "k"), "route-0", "measure-k1",
                              Interval("run-0", "M", 0, 2, True, False),
                              Contract("model.measure", "1"), Contract("model.clock", "1"), cells)
    base = replace(receipt_e0(count, boot=boot), intervals=(request,), observation_declarations=None)
    key, slot = check.IntervalKey("k1", "route-0", "run-0"), check.SlotKey("segment", "k")
    conditions = tuple(check.CompletionBinding(
        check.CompletionKey("O-04", ("route-0", "k1"), kind, target), "IntervalRequest", key,
        (slot,) if kind == "save" else (), check.Owner("H", "k1"))
        for kind, target in (("save", slot), ("handle", check.WorkKey("measure-k1"))))
    return fixed(base, conditions)


def _goal(key, text, probe, *args):
    return Goal(key, text, probe, args)


RECEIPT_GOALS = (
    _goal("post-before-accept", "Post後未Accept", "post_pending"),
    _goal("accept-before-ack", "Accept後HostAck前", "accepted_pending_ack"),
    _goal("reaccept-before-ack", "HostAck前の同番号再受付", "reaccept"),
    _goal("saved", "宣言した全受信の保存", "receipts_saved"),
)
LIFECYCLE_ASSUMPTIONS = ASSUMPTIONS + (
    "紙に無い仮定 A-INITIAL-WIRE: model.process/readerはPublish・所有・開始と局所Q/R/P/Cの構造だけに使用。合法IC/IG/IE/IDの数値検証は範囲外として実装の段でF-aの実物に繋ぐ。紙1507-1511; fb_machine.py:683-727。",
)
INTERVAL_ASSUMPTIONS = ASSUMPTIONS + (
    "紙に無い仮定 A-INTERVAL-STEP: RequestIntervalの歩をHの引受けとする。紙629/1205; 窓口係の手引き。",
)


def make_scenes():
    scenes = []

    def add(id, paper_id, initial="I0", cut="K-R", e0=None, goals=(), prefix="",
            blocker="", remaining=(), extra_lines=(), assumptions=ASSUMPTIONS,
            negative=(), limit=50_000, excluded=()):
        n = (SC_TABLE.get(paper_id) or IDENTIFICATION_TABLE.get(paper_id)
             or FAIRNESS_TABLE[paper_id])
        scenes.append(Scene(id, paper_id, (n,) + tuple(extra_lines), initial,
                            Cut(cut, frozenset(excluded), tuple(remaining)), limit, e0,
                            tuple(goals), prefix, blocker, tuple(assumptions), tuple(negative), tuple(remaining)))

    # The two deliveries remain together. No prefix saves the first one.
    for different in (False, True):
        for rebuild in (0, 1):
            add(f"SC-01-{'different' if different else 'same'}-rebuild{rebuild}", "SC-01",
                e0=receipt_e0(2, different, budget=Budget(window_faults=rebuild)),
                goals=RECEIPT_GOALS + ((_goal("rebuild", "未保存中Rebuild", "rebuild"),) if rebuild else ()),
                extra_lines=(1360,), limit=5_000)
    for rebuild in (0, 1):
        add(f"SC-01-boot-rebuild{rebuild}", "SC-01", e0=receipt_e0(boot=True, budget=Budget(window_faults=rebuild)),
            goals=RECEIPT_GOALS + (_goal("boot-one-slot", "Bootの片方だけ保存", "boot_partial"),), extra_lines=(1360,), limit=5_000)
    for different in (False, True):
        for first in ("e1", "e2"):
            for rebuild in (0, 1):
                add(f"SC-01-local-{'different' if different else 'same'}-{first}-rebuild{rebuild}", "SC-01",
                    initial=f"I0→{first}保存・他方まだPost前", e0=receipt_e0(2, different, budget=Budget(window_faults=rebuild)),
                    prefix=f"receipt-first:{first}", goals=RECEIPT_GOALS, limit=5_000,
                    remaining=("I0の未完探索を置換しない。2封筒が同時に未保存の組み合わせの完走は未確認。",))

    add("SC-02-same-and-new-post", "SC-02", e0=receipt_e0(2), goals=RECEIPT_GOALS,
        limit=5_000,
        remaining=("同番号の内容/r/型/run/seqを一つずつ変える不正入力候補は未実行。E0には原本変更候補欄がない。",),
        negative=tuple(f"②同番号の{field}不一致を拒み原本保持 (紙1400)" for field in ("内容", "r", "型", "run", "seq")))

    add("SC-03-normal", "SC-03", e0=receipt_e0(), goals=RECEIPT_GOALS + (
        _goal("body-only", "本文だけ保存", "body_only"),), extra_lines=(1360,))
    for mode in ("precommit", "entry-precommit", "body-lost", "entry-lost"):
        for rebuild in (0, 1):
            budget = Budget(window_faults=rebuild, precommit_failures=int("precommit" in mode),
                            lost_responses=int("precommit" not in mode))
            add(f"SC-03-{mode}-rebuild{rebuild}", "SC-03", initial="I0→SAVE局所境界",
                e0=receipt_e0(budget=budget), prefix=mode,
                goals=(_goal("fault", "指定の保存失敗位置", "fault", mode),
                       _goal("saved", "同一PreparedEntryから再照合・保存", "receipts_saved"),
                       _goal("retry", "同一対象のI/O再試行", "io_retry")) +
                      ((_goal("rebuild", "点保存・応答不明を保ったRebuild", "rebuild_unconfirmed")
                        if mode == "entry-lost" else
                        _goal("rebuild", "実際のPost済み未保存受信を保ったRebuild", "rebuild"),) if rebuild else ()),
                extra_lines=(1360,),
                remaining=("故障以前の別順序はI0の正常場面。局所前置列は探索順の同値化ではない。",))
    add("SC-03-boot", "SC-03", e0=receipt_e0(boot=True), goals=RECEIPT_GOALS + (
        _goal("boot-one-slot", "Bootの片方だけ保存", "boot_partial"),), extra_lines=(1360,), limit=5_000)
    # Paper 925/1328/1360: local save boundaries supplement, not replace, the
    # unfinished I0 combinations above. Keep both choices of first Boot slot.
    for slot in ("boot", "declaration"):
        for rebuild in (0, 1):
            add(f"SC-03-boot-local-{slot}-rebuild{rebuild}", "SC-03", initial="I0→Boot片slot保存",
                e0=receipt_e0(boot=True, budget=Budget(window_faults=rebuild)), prefix=f"boot-slot:{slot}",
                goals=(_goal("boot-one-slot", "Bootの片方だけ保存", "boot_partial"),
                       _goal("saved", "Bootの両slot保存", "receipts_saved")), extra_lines=(1360,), limit=5_000,
                remaining=("前段の全順序はI0場面が担当し探索未完。これは片slot保存後の局所接続。",))

    boundary_goals = (
        _goal("published-unsaved", "Publish直後の全仕事行・依存未保存", "published_unsaved"),
        _goal("one-missing", "必要な複数参照の1つだけ未保存", "one_missing"),
        _goal("resolved", "PlanRefの一回解決", "resolved"),
        _goal("held-n", "HELD-N: 確保後Launch前", "held_n"),
        _goal("held-r", "HELD-R: Launch後Enter前", "held_r"),
        _goal("held-e", "HELD-E: 本体入場後", "entered"),
        _goal("drain-twice", "二重列挙の同じ仕事行", "drain"),
    )
    add("SC-04-initial-publish", "SC-04", initial="I0→Boot保存→IP(initial)", cut="K-U",
        e0=lifecycle_e0(), prefix="boot", goals=boundary_goals, extra_lines=(1361,),
        assumptions=LIFECYCLE_ASSUMPTIONS, limit=5_000,
        remaining=("v0.12の9種類はSC-04-other-publish-kindsの内訳で個別に報告。紙932/1361。",))
    add("SC-04-one-reference-missing", "SC-04", initial="IP(initial)→process/reader保存・Q未保存", cut="K-U",
        e0=lifecycle_e0(), prefix="one-missing", goals=boundary_goals,
        extra_lines=(1361,), assumptions=LIFECYCLE_ASSUMPTIONS, limit=5_000,
        remaining=("Publishからこの局所境界までの全順序はSC-04-initial-publishで探索未完。",))
    for branch, budget in (("double-wrapper", Budget(duplicate_wrappers=1)),
                           ("not-started-retry", Budget(launch_failures=1)),
                           ("start-unknown", Budget(uncertain_launches=1))):
        add(f"SC-04-{branch}", "SC-04", initial="IQ(有限記号・F-a未確認)", cut="K-U",
            e0=lifecycle_e0(budget=budget), prefix="pending", assumptions=LIFECYCLE_ASSUMPTIONS,
            goals=(_goal(branch, branch, branch), _goal("held-n", "開始前の保持", "held_n")),
            extra_lines=(1361,), limit=10_000)

    for paper_id, goalset, budget in (
        ("SC-04-DESC", (_goal("resolved", "正しいPlanRef一回解決", "resolved"),
                        _goal("entered", "本体入場", "entered"), _goal("stop", "停止後もDesc保持", "released"),
                        _goal("terminal", "論理の終わり確定後もDesc保持", "end_known")), Budget()),
        ("SC-04-RELEASE", (_goal("held", "同じ確保の保持", "held_n"),
                           _goal("release", "確かな停止後一回解放", "released")), Budget(launch_failures=1)),
    ):
        add(paper_id, paper_id, initial="IQ(有限記号・F-a未確認)", cut="K-U", e0=lifecycle_e0(budget=budget),
            prefix="pending", goals=goalset, assumptions=LIFECYCLE_ASSUMPTIONS, limit=10_000,
            negative=(ROWS_BY_LINE[IDENTIFICATION_TABLE[paper_id]][2],),
            remaining=("負の候補前後は別段。今回の合法枝だけでは識別力未確認。",))
    for paper_id in ("SC-03-RETRY", "SC-03-FIRST"):
        add(paper_id, paper_id, e0=receipt_e0(budget=Budget(lost_responses=1)),
            goals=RECEIPT_GOALS + (_goal("prepared", "許された初回準備", "prepared"),
                                 _goal("retry", "同じPreparedEntryの再試行", "io_retry")),
            negative=(ROWS_BY_LINE[IDENTIFICATION_TABLE[paper_id]][2],))

    add("SC-13-hung-receipt", "SC-13", initial="IT(Wr)・入場後", cut="K-H", e0=lifecycle_e0(stop=False, external=True),
        prefix="entered", goals=(_goal("hung-receive", "占有と停止未確認を保持して受信保存", "hung_receipt"),
                                  _goal("accept-held", "占有中Accept", "held_operation", "Accept"),
                                  _goal("body-held", "占有中PutBody", "held_operation", "PutBody"),
                                  _goal("entry-held", "占有中AddEntry", "held_operation", "AddEntry")),
        assumptions=LIFECYCLE_ASSUMPTIONS, limit=10_000,
        remaining=("測る報告1件との独立枝はSC-13-measure-reportで未実行として残す。",))
    add("SC-14-LIMIT", "SC-14-LIMIT", initial="IQ(有限記号・F-a未確認)", cut="K-H",
        e0=lifecycle_e0(stop=False, capacity=2), prefix="pending",
        goals=(_goal("limit", "(Occ,allocation,capacity)=(1,1,2)", "resource_triple", 1, 1, 2),),
        assumptions=LIFECYCLE_ASSUMPTIONS, limit=5_000,
        negative=("①余分な確保(2,1,2)", "②不正宣言(1,2,1)は正常E0として受理させない"))

    # Preserve live H ownership without pretending k/MeasureSegment was made.
    interval_gap = "引受けだけをSC全体の合格にしない。SC-12-structure-measure-rowで行/入場の局所構造を別計上したが、合法なbootstrap/route/k wireとSupportは未具体化。紙629/1019/1334; fb_machine.py:616-665,794-812。"
    add("SC-12-undertaking-no-report", "SC-12", cut="K-K", e0=interval_undertaking_e0(),
        goals=(_goal("undertaken", "未報告セルをHが引き受ける", "undertaken"),
               _goal("measure-row", "実在するMeasureSegment行が報告責務を保持", "unconnected", interval_gap)),
        assumptions=INTERVAL_ASSUMPTIONS, remaining=(interval_gap,), limit=5_000, extra_lines=(1364,))
    add("SC-20-empty-receipts-interval", "SC-20", e0=interval_undertaking_e0(2), cut="K-K",
        goals=RECEIPT_GOALS + (_goal("no-computation", "initialなしで計算行・入場0かつ受信保存", "no_computation"),
                              _goal("undertaken", "区間引受けの責務が存続", "undertaken"),
                              _goal("measure-row", "MeasureSegmentの報告責務", "unconnected", interval_gap)),
        assumptions=INTERVAL_ASSUMPTIONS, remaining=(interval_gap,), limit=5_000)
    add("SC-19-receipt-positive", "SC-19", cut="K-L", e0=receipt_e0(), limit=10_000,
        goals=RECEIPT_GOALS + (_goal("before-wait", "受付前Wait", "wait_pending"),
                               _goal("after-wait", "全保存後Wait", "wait_saved")),
        remaining=("公平な未保存循環・N/PはSC-19-T1/T2/N1〜N4の抽象入力で別計上。実模型からの到達とN4のINV-2.dへの接続は未実行。",), extra_lines=(1368,))

    # Missing contracts are explicit dependencies, not convenient exclusions.
    update_gap = ("v0.12: 時計・呼出しID・T/V計画は公開契約で宣言可能。構造部分はthird_round_scenesで接続し、"
                  "合法IC/IG/IAと実F-a数値の残りは紙1509に従い実装の段へ分類する。"
                  "fb_machine.py:607-616,739-775,1819-1836; fb_check.py:3346-3389。")
    eval_gap = ("EQ/PR/FProblem/Draw/artifactの対応を持つ合法なIE/IDの前段が未接続。"
                "ArtifactPortBinding/resolve_artifact_portで有限ポートは宣言可能になったが、全artifact入力閉包・"
                "math_artifact/2の発行/検査意味とEQ/PR/Drawの実wireは未具体化。紙1025/1038-1043/1089-1096; "
                "fb_machine.py:701-715; fb_check.py:3134-3154,3794-3802。")
    derivation_gap = ("ReceiptSourceとPlanRefで受信を事前宣言する入口は追加済み。SC-08-structureで局所接続を別計上。"
                      "bootstrap/2の数値射影、生成契約別閉包、まとめるδとConflictの合法な前段は未具体化。"
                      "紙616-620/1081/1363; fb_machine.py:669-681; fb_check.py:3020-3071,4571-4578。")
    interval_support_gap = ("IntervalEvidenceBinding(PlanRef,RecordPlan)の入口は追加済み。証拠運搬は局所場面で別計上。"
                            "Supportのkind/contract別生成意味と全閉包、route/時計/kの実wire、合法なIKの前段は未具体化。"
                            "紙1019/1087/1096/1334; fb_machine.py:806-812; fb_check.py:3196-3205,3767-3776。")

    def blocked(id, parent, reason, *, initial, cut, lines=(), limit=50_000, goals=(), negative=()):
        n = SC_TABLE.get(parent) or IDENTIFICATION_TABLE.get(parent) or FAIRNESS_TABLE[parent]
        required = ROWS_BY_LINE[n][2] if parent in SC_TABLE else ROWS_BY_LINE[n][1]
        add(id, parent, initial=initial, cut=cut, blocker=reason,
            goals=goals or (_goal("paper-required", required, "unconnected", reason),),
            extra_lines=lines, limit=limit, negative=negative)

    blocked("SC-04-other-publish-kinds", "SC-04", "紙932/1361 v0.12の9種類をthird_round_scenesで列挙。" + update_gap + eval_gap,
            initial="IP(u)", cut="K-U", lines=(1361,))
    blocked("SC-05", "SC-05", update_gap, initial="IQ", cut="K-B", limit=50_000)
    for branch in ("Success", "Rejected", "Insufficient", "Unknown", "wrong-target"):
        blocked(f"SC-06-{branch}", "SC-06", update_gap + " IC→IGの取得・認証を同じQ/R/P/Cへ結ぶ前段を要する。",
                initial="IC→IG", cut="K-B", lines=(1362,))
    for parent, branches in (("SC-07a", ("q1-first", "q2-first")), ("SC-07b", ("sequential", "readopt"))):
        for branch in branches:
            blocked(f"{parent}-{branch}", parent, update_gap + " IAの実取得/認証/採用祖先を欠いたfixtureは作らない。",
                    initial="IA", cut="K-B", limit=50_000)
    for branch in ("e1-only", "e2-only", "group", "no-group", "other-trigger-slot", "conflict-N", "conflict-P"):
        blocked(f"SC-08-{branch}", "SC-08", derivation_gap, initial="I0/IX", cut="K-Q", lines=(1363,))
    for branch in ("FProblem-Selected", "FProblem-NoDecision", "Ep-NoDecision"):
        blocked(f"SC-09-{branch}", "SC-09", eval_gap, initial="I0→IE→ID", cut="K-E")
    for field in ("problem_key", "purpose", "draw-point", "artifact"):
        blocked(f"SC-10-{field}", "SC-10", eval_gap, initial="IE/ID", cut="K-E")
    for branch in ("Frame", "Started", "Ended", "RouteApplied", "Gap", "Unavailable", "Claim", "Unproved",
                   "report-before-start", "same-seq-other-id", "same-content-other-slot", "end-equals-r", "end-after-r",
                   "open-closed-neighbor", "actual-time-unavailable", "claim-window", "claim-generation", "unknown-kind",
                   "future-unproved", "evidence-outside-X"):
        blocked(f"SC-11-{branch}", "SC-11", interval_support_gap, initial="IK", cut="K-K", lines=(1364,))
    for branch in ("positive-claim", "started-only", "ended-only", "Gap", "Unavailable", "partial-report", "evidence-wait"):
        blocked(f"SC-12-{branch}", "SC-12", interval_support_gap, initial="IK", cut="K-K", lines=(1364,))
    blocked("SC-13-measure-report", "SC-13", interval_support_gap, initial="IT(Wr)/IK", cut="K-H")
    for capacity in (1, 2):
        blocked(f"SC-14-capacity{capacity}", "SC-14", eval_gap, initial="IE+IT(Hung)", cut="K-H", lines=(1365,))
    for stage in ("Wr", "Wp", "Wv", "Ep", "D", "Ee"):
        reason = update_gap if stage in ("Wr", "Wp", "Wv") else eval_gap
        for branch in ("stop", "no-stop", "lost-reply-capacity2", "tie-unknown-first", "tie-value-first"):
            blocked(f"SC-15-{stage}-{branch}", "SC-15", reason + " Tと種類別後続の全完了条件を要する。",
                    initial=f"IT({stage})", cut="K-T", lines=(1366,))
        blocked(f"SC-16-{stage}-Unknown-A-B", "SC-16", reason,
                initial=f"IT({stage})", cut="K-T")
    for stage in ("Wr", "Wp", "D", "interval-slot"):
        blocked(f"SC-17-{stage}-A-A-B", "SC-17", interval_support_gap if stage == "interval-slot" else
                eval_gap if stage == "D" else update_gap, initial=f"IT({stage})", cut="K-T")
    for link in ("Wr-Wp", "Wp-acquire", "Ep-D", "D-Ee"):
        for boundary in ("pre-publish", "published-unprepared", "prepared", "launched-not-entered"):
            blocked(f"SC-18-{link}-{boundary}", "SC-18", update_gap if link.startswith("W") else eval_gap,
                    initial="IX/IP/IT", cut="K-U", lines=(1367,))
    for branch, reason in (("interval-receipt-Q", derivation_gap), ("Q-R-P-C", update_gap),
                           ("acquire-verify-adopt", update_gap), ("Ep-D-Ee-selection", eval_gap),
                           ("evaluation-hung-receive-update", eval_gap + derivation_gap)):
        blocked(f"SC-21-{branch}", "SC-21", reason, initial="前段からの実到達状態", cut="K-V", lines=(1369,))

    for parent in IDENTIFICATION_TABLE:
        if any(s.paper_id == parent for s in scenes):
            continue
        reason = (interval_support_gap if parent in ("SC-11-FAMILY", "SC-17-FAMILY", "SC-11-CROSS-M")
                  else update_gap)
        if parent == "SC-05-CYCLE":
            reason = "公開acyclicで受理前の非循環グラフを評価する。負の循環候補と実模型の保存到達は未実行。紙1384/1393; fb_check.py:527-536。"
        n = IDENTIFICATION_TABLE[parent]
        if parent == "SC-15-WP/VERIFY":
            for branch in ("Wp-Failure", "Wp-Unknown", "Wv-Insufficient"):
                blocked(f"SC-15-WP-VERIFY-{branch}", parent, reason, initial=f"IP(result/G)→IT({branch})", cut="K-T",
                        negative=("③T/V保存前に保存責務を解消する候補前後はINV-2.c偽 (紙1391/1404)。",))
            continue
        blocked(parent, parent, reason, initial="IK" if "FAMILY" in parent or "CROSS-M" in parent else "合法な前段未接続",
                cut="K-K" if "SC-11" in parent else "K-T" if "SC-15" in parent or "SC-17" in parent else "K-B",
                negative=() if parent in ("SC-11-FAMILY", "SC-17-FAMILY", "SC-11-CROSS-M") else (ROWS_BY_LINE[n][2],),
                limit=10_000 if parent == "SC-05-CYCLE" else 50_000)
    for parent, n in FAIRNESS_TABLE.items():
        blocked(parent, parent,
                "公開fair_cycle/progress_counterexamples/derive_progressで完全Enabledと候補辺を分離して評価する。"
                "実模型の到達対応は未確認。紙1451/1464-1468; fb_check.py:605-639,1749-1769。"
                "T2/N4は誤った窓口の抽象負例であり正しい窓口の合格へ加算しない。",
                initial="IL", cut="K-L", limit=10_000,
                goals=(_goal("candidate", ROWS_BY_LINE[n][2], "unconnected", "abstract candidate entry required"),),
                negative=(ROWS_BY_LINE[n][3],))
    return tuple(scenes)


# SCENES is assembled below the second-round builders.


@dataclass(frozen=True)
class AbstractVertex:
    id: str
    unsaved_receipts: tuple[str, ...] = ()
    unpublished: tuple[str, ...] = ()
    ready_n: tuple[tuple[str, bool], ...] = ()
    phase: str = ""
    environment: tuple[str, ...] = ("能力あり", "正常応答", "障害残量0", "HostEligible前段完了")


@dataclass(frozen=True)
class AbstractFairnessCase:
    """Paper IL data only; no invented adapter to a normal Scenario.

    The ReadyN literals here are expressly the abstract inputs of paper
    1451-1467, never a substituted ready stamp in a running window's State.
    Candidate edges and complete Enabled are deliberately separate.
    """
    id: str
    line: int
    vertices: tuple[AbstractVertex, ...]
    enabled: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]
    full_edges: tuple[tuple[str, str, tuple[str, ...]], ...]
    candidate_edges: tuple[tuple[str, str, tuple[str, ...]], ...]
    target: tuple[str, ...]
    expected: str
    negative: bool
    max_states: int = 10_000
    concrete_connection: str = "未確認・正しい窓口の合格に加算しない"


def abstract_fairness_cases():
    a1, a2 = ("AddEntry", "run-0", "e1", "receipt"), ("AddEntry", "run-0", "e2", "receipt")
    wait, publish, save = ("Wait",), ("PublishMatching", "o"), ("Save", "u", "q")
    p = AbstractVertex("p", ("e1", "e2"), phase="本文確認済み・点未保存")
    receipt_edges = (("p", "p", a1), ("p", "p", a2))
    cases = [AbstractFairnessCase("SC-19-T1", 1455, (p,), (("p", (a1, a2)),), receipt_edges,
                                 (receipt_edges[0],), ("e1", "e2"), ROWS_BY_LINE[1455][3], False),
             AbstractFairnessCase("SC-19-T2", 1456, (p,), (("p", (a1, a2)),), receipt_edges,
                                 receipt_edges, ("e1", "e2"), ROWS_BY_LINE[1456][3], True)]
    t = AbstractVertex("t", unpublished=("o",), ready_n=(("o", True),), phase="N")
    f = AbstractVertex("f", unpublished=("o",), ready_n=(("o", False),), phase="N")
    issued = AbstractVertex("issued", phase="P")
    saved = AbstractVertex("saved", phase="S・Dischargeδ")
    tail = (("t", "issued", publish), ("issued", "saved", save), ("saved", "saved", wait))
    alternating = (("t", "f", ("前提の正当な喪失", "o")), ("f", "t", ("前提の回復", "o")))
    cases.append(AbstractFairnessCase("SC-19-N1", 1457, (t, f, issued, saved),
        (("t", (alternating[0][2], publish)), ("f", (alternating[1][2],)), ("issued", (save,)), ("saved", (wait,))),
        alternating + tail, alternating, ("o",), ROWS_BY_LINE[1457][3], False))
    enabled = (("t", (wait, publish)), ("issued", (save,)), ("saved", (wait,)))
    full = (("t", "t", wait),) + tail
    cases.append(AbstractFairnessCase("SC-19-N2", 1458, (t, issued, saved), enabled, full,
        (("t", "t", wait),), ("o",), ROWS_BY_LINE[1458][3], False))
    cases.append(AbstractFairnessCase("SC-19-N3", 1459, (t, issued, saved), enabled, full,
        tail, ("o",), ROWS_BY_LINE[1459][3], False))
    cases.append(AbstractFairnessCase("SC-19-N4", 1460, (t,), (("t", (wait,)),), (("t", "t", wait),),
        (("t", "t", wait),), ("o",), ROWS_BY_LINE[1460][3], True))
    return tuple(cases)


ABSTRACT_FAIRNESS_CASES = abstract_fairness_cases()


def connection_snapshot(state, actions):
    """Enumerate the actual prefix; this is evidence, never an E0 oracle."""
    return {
        "actions": [(a.operation, repr(a.target[0].key) if a.operation == "Accept" else repr(a.target), a.outcome) for a in actions],
        "records": [(e.point.cid, e.header.record.contract.name, e.header.record.name) for e in state.core.e],
        "work": [{"id": w.descriptor.work_id, "stage": w.descriptor.stage, "required": repr(w.descriptor.required),
                  "phase": w.phase, "held": w.held, "stopped": w.stopped, "released": w.released,
                  "token": w.token, "first": w.first, "knowledge": repr(w.knowledge)} for w in state.core.p.work],
        "unmet": [repr(c) for c in state.core.p.conditions if c.unmet],
        "EH": {"originals": [(e.key, e.source, e.event.kind, e.receipt_seq, repr(e.r)) for e in state.evidence.eh.originals],
               "acknowledgements": state.evidence.eh.acknowledgements},
        "EW": [(f.kind, repr(f.key), repr(f.value) if f.kind in ("BodyEntered", "Returned", "Stop", "Release", "Reserve") else "actual event retained")
               for f in state.evidence.ew.events],
        "EA": {"acquisitions": [repr(a) for a in state.evidence.ea.acquisitions], "calls": len(state.evidence.ea.calls),
               "replies": len(state.evidence.ea.replies), "issued": len(state.evidence.ea.issued),
               "adoptions": [repr(a) for a in state.evidence.ea.adoptions]}, "EI": repr(state.evidence.ei),
        "EP": repr(state.evidence.ep), "EU": repr(state.evidence.eu),
        "H": repr(state.core.h), "P": repr(state.core.p),
    }


def instantiate(scene):
    """Execute only a declared legal prefix, keeping every state/edge/history.

    This uses the public step pattern illustrated at test_fb_machine.py:68-99.
    No State/ledger/PreparedEntry/history is fabricated. The prefix is reported
    separately and never treated as an exhaustive graph or a vertical pass.
    """
    if scene.e0 is None:
        raise ValueError(scene.blocker)
    if scene.prefix.startswith("v2:"):
        return instantiate_v2(scene)
    if not scene.prefix:
        return Scenario(scene.id, scene.e0, scene.max_states, cut=scene.cut,
                        initial_connection="I0; EH/EW/EA/EI/EL/P empty before declared inputs"), (), (), ()
    from fb_machine import Edge, View
    environment, window = Environment(scene.e0), CorrectWindow(scene.e0)
    state = environment.initial()
    states, edges, enabled, actions = [state], [], [], []

    def take(action):
        nonlocal state
        all_actions = tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(environment.actions(state))
        if action not in all_actions:
            alternatives = tuple(a for a in all_actions if a.operation == action.operation)
            raise ValueError(f"Prefix action is not offered: {action!r}; offered same-operation actions={alternatives!r}")
        enabled.append(all_actions)
        before = state
        step = environment.step(before, action, window)
        state = step.state
        edges.append(Edge(len(states)-1, len(states), action, step.events, step.result))
        states.append(state)
        actions.append(action)

    def save(unit, slots):
        for slot in slots:
            for operation in ("PrepareReceipt" if unit.startswith("receipt/") else "PrepareOne",
                              "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
                take(Action(operation, (unit, slot)))

    posting = (scene.prefix.split(":", 1)[1] if scene.prefix.startswith("receipt-first:") else
               "e1" if scene.prefix in ("precommit", "entry-precommit", "body-lost", "entry-lost")
               or scene.prefix.startswith("boot-slot:") else "boot")
    take(Action("Post", (posting,)))
    envelope = state.core.h.queue[0]
    take(Action("Accept", (envelope,)))
    take(Action("HostAck", envelope.key))
    receipt_unit = receipt_unit_id(scene.e0.run, 0)
    if scene.prefix.startswith("receipt-first:"):
        save(receipt_unit, ("receipt",))
    elif scene.prefix.startswith("boot-slot:"):
        save(receipt_unit, (scene.prefix.split(":", 1)[1],))
    elif posting == "e1":
        key = (receipt_unit, "receipt")
        take(Action("PrepareReceipt", key))
        if scene.prefix.startswith("entry-"):
            take(Action("PutBody", key))
        take(Action("AddEntry" if scene.prefix.startswith("entry-") else "PutBody", key,
                    "precommit_failure" if "precommit" in scene.prefix else "lost_response"))
    else:
        save(receipt_unit, ("boot", "declaration"))
        if scene.prefix in ("pending", "entered", "one-missing"):
            take(Action("PublishUnit", ("initial",)))
            save("initial", ("process", "reader") if scene.prefix == "one-missing" else ("process", "reader", "q"))
            if scene.prefix != "one-missing":
                take(Action("ResolveWork", ("wr",)))
        if scene.prefix == "entered":
            take(Action("ClaimStart", ("wr",)))
            take(Action("Launch", ("wr",)))
            take(Action("EnterWorker", ("wr:wrapper:0",)))
    enabled.append(tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(environment.actions(state)))
    connection = json.dumps(connection_snapshot(state, actions), ensure_ascii=False)
    scenario = Scenario(scene.id, scene.e0, scene.max_states, state, scene.cut, connection)
    return scenario, tuple(states), tuple(edges), tuple(enabled)


# Second-round declarations. Every value below is fixed before any model call.
STRUCTURAL_LIMIT = (
    "範囲外 (実装の段へ): 合法IC/IG/IE/IDの数値、実F-a値、/2の数値射影、"
    "contract別Support、artifact全閉包はF-aの実物に繋いで確かめる。"
    "模型は記録・参照・時計・仕事・取得・採用の構造まで。紙1507-1511。"
)
V2_ASSUMPTIONS = LIFECYCLE_ASSUMPTIONS + (
    "紙に無い仮定 A-SOURCE: started_clock/finished_clock/acquisition_clockは公開Sourceで実生成・取得時計を宣言する。紙1001/1084; fb_machine.py:554-580。",
    "紙に無い仮定 A-CLOCK-SOURCE: model.clock_source/1の保存済みPointをclock_reading/1.sourceにする。紙1511; fb_machine.py:607-616。",
    "紙に無い仮定 A-READING-NS: 模型Reading.rankをtime_nsとする。実時計の精度は保証しない。fb_machine.py:608-613。",
)


def update_structure_e0():
    """Paper 354-359/933: Q -> R/Wp -> P -> C, finite structural slice."""
    base = lifecycle_e0()
    process, model, q = (PlanRef("initial", x) for x in ("process", "reader", "q"))
    r, p = PlanRef("result", "r"), PlanRef("proof", "p")
    c = PlanRef("completed", "c")
    # Independent normative result/statement; Program replies below are not
    # manufactured from an observed output or from this expected RecordPlan.
    result_value = obj(contract=Contract("finite_update_result", "1"), value=obj(joint=(1,), evidence_mass=1))
    rr = RecordPlan("r", Contract("computation_result", "1"), "Prediction",
        obj(request=q, output=result_value, about=(q,), basis=(q, model)),
        (TypedReference("PATH-RESULT", ("request",), q, "UE", "generate"),
         TypedReference("PATH-R-OUTER", ("about", 0), q, "E", "outer"),
         TypedReference("PATH-R-OUTER", ("basis", 0), q, "UE", "outer"),
         TypedReference("PATH-R-OUTER", ("basis", 1), model, "UE", "outer")), frozenset((q,)))
    wp = replace(base.plans[0].works[0], work_id="wp", stage="Wp", stage_slot="proof",
        method=Contract("finite_update_proof", "1"), output_contract=Contract("finite_update_statement", "1"),
        args=obj(model=model, request=q, result=r), input_points=frozenset((q, model, r)),
        numerical_view=NumericalView(frozenset((q, model, r))), required=frozenset((process, model, q, r)))
    result = AllowedPlan("result", "O-06", ("wr",), (rr,), (wp,),
        (Guard("first", "wr"), Guard("outcome", "wr", (OutcomeKind.RETURNED, "Success"))))
    pp = RecordPlan("p", Contract("computation_proof", "1"), "Prediction",
        obj(request=q, result=r, statement=obj(contract=Contract("finite_update_statement", "1"),
            value=obj(model=model, request=q, result=r)),
            checker=obj(name="finite_update_replay", version="1", args=obj()), about=(q, r), basis=(q, r, model)),
        tuple(TypedReference("PATH-STATEMENT", path, ref, "UE", "proof_target") for path, ref in
              ((("request",), q), (("result",), r), (("statement", "value", "model"), model),
               (("statement", "value", "request"), q), (("statement", "value", "result"), r))) +
        tuple(TypedReference("PATH-P-OUTER", (kind, i), ref, role, "outer")
              for kind, refs, role in (("about", (q, r), "E"), ("basis", (q, r, model), "UE"))
              for i, ref in enumerate(refs)), frozenset((q,)))
    clock_source = AllowedPlan("clock-source", "O-02", ("clock-source", base.run, base.clock_source),
                               (clock_source_record(base.run, base.clock_source),))
    clocks = tuple(clock_reading_record(slot, PlanRef("clock-source", "source"),
        Source(source, work)) for slot, work, source in
        (("started", "wr", "started_clock"), ("finished", "wp", "finished_clock")))
    proof = AllowedPlan("proof", "O-07", ("wp",), (pp, *clocks), guards=
        (Guard("first", "wp"), Guard("outcome", "wp", (OutcomeKind.RETURNED, "Success"))))
    refs = (("request", q), ("result", r), ("started_clock", PlanRef("proof", "started")),
            ("finished_clock", PlanRef("proof", "finished")))
    cr = RecordPlan("c", Contract("computation_completed", "1"), "Event",
        obj(request=q, result=r, proofs=(p,), started_clock=PlanRef("proof", "started"),
            finished_clock=PlanRef("proof", "finished")),
        tuple(TypedReference("PATH-COMPLETE", (name,), ref, "UE", "generation") for name, ref in refs) +
        (TypedReference("PATH-COMPLETE", ("proofs", 0), p, "UE", "generation"),), frozenset((q,)))
    complete = AllowedPlan("completed", "O-07", ("wp", "completion"), (cr,), guards=
        tuple(Guard("saved", ref) for ref in (p, PlanRef("proof", "started"), PlanRef("proof", "finished"))))
    programs = (
        Program("wr", (Outcome(OutcomeKind.RETURNED, obj(variant="Success", output=
            obj(contract=Contract("finite_update_result", "1"), value=obj(joint=(1,), evidence_mass=1)))),)),
        Program("wp", (Outcome(OutcomeKind.RETURNED, obj(variant="Success", statement=
            obj(contract=Contract("finite_update_statement", "1"), value=obj(model=model, request=q, result=r)),
            checker=obj(name="finite_update_replay", version="1", args=obj()))),)),
    )
    return fixed(replace(base, plans=base.plans + (clock_source, result, proof, complete), programs=programs,
                         receipt_kinds=((0, "Boot"), (1, "WorkFinished"), (2, "WorkFinished")),
                         presentation_limit=1, observation_declarations=None))


def instantiate_v2(scene):
    """Public-operation prefix. No fabricated ledger/history or expected CID."""
    from fb_machine import Edge, View
    env, window = Environment(scene.e0), CorrectWindow(scene.e0)
    state = env.initial()
    states, edges, enabled, actions = [state], [], [], []

    def take(action):
        nonlocal state
        offered = tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(env.actions(state))
        if action not in offered:
            # Ask the public transition boundary for its diagnostic only. Never
            # continue a prefix through an action omitted from Enabled.
            diagnostic = "step accepted an operation omitted from Enabled"
            try:
                env.step(state, action, window)
            except Exception as error:
                diagnostic = f"{type(error).__name__}: {error}"
            raise ValueError(f"public prefix action unavailable: {action!r}; {diagnostic}; same operation=" +
                             repr(tuple(a for a in offered if a.operation == action.operation)))
        enabled.append(offered)
        step = env.step(state, action, window)
        state = step.state
        edges.append(Edge(len(states)-1, len(states), action, step.events, step.result))
        states.append(state)
        actions.append(action)

    def save(unit, slots):
        for slot in slots:
            for operation in ("PrepareReceipt" if unit.startswith("receipt/") else "PrepareOne",
                              "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
                take(Action(operation, (unit, slot)))

    def accept_saved():
        envelope = state.core.h.queue[0]  # route actual input, never declare E0 from it
        take(Action("Accept", (envelope,)))
        take(Action("HostAck", envelope.key))
        save(receipt_unit_id(scene.e0.run, envelope.number),
             ("boot", "declaration") if envelope.event.kind == "Boot" else ("receipt",))

    def finish(work, stop=True):
        for operation in ("ResolveWork", "ClaimStart", "Launch"):
            take(Action(operation, (work,)))
        take(Action("EnterWorker", (work + ":wrapper:0",)))
        take(Action("WorkerStep", (work,)))
        take(Action("Deliver", ("report:" + work + ":0",)))
        accept_saved()
        if stop:
            take(Action("Stop", (work,)))
            take(Action("Release", (work,)))

    def save_terminal(work):
        take(Action("RecognizeTerminal", (work,)))
        save("terminal:" + work, ("T",))

    def tied_notices(work):
        # Public A-DELIVERY-BUNDLE example. Generation order is fixed host,
        # then worker in BOTH cases; only the E0 bundle's delivery order varies.
        take(Action("ResolveWork", (work,)))
        take(Action("ClaimStart", (work,)))
        take(Action("Launch", (work,), "uncertain_after"))
        take(Action("HostUnknown", ("unknown-" + work,)))
        take(Action("WorkerStep", (work,)))
        take(Action("DeliverBundle", ("same-r",)))
        delivered = state.core.h.queue
        assert len(delivered) == 2
        for envelope in delivered:
            # Actual envelopes route calls only. E0 and all expectations were
            # frozen before this prefix; numbers/clock/seq are never predicted.
            take(Action("Accept", (envelope,)))
            take(Action("Accept", (envelope,)))
            take(Action("HostAck", envelope.key))
        save(receipt_unit_id(delivered[1].run, delivered[1].number), ("receipt",))
        # The earlier receipt is deliberately not Saved. Its body-only prefix
        # localizes the remaining storage/terminal boundary without dropping it.
        unit = receipt_unit_id(delivered[0].run, delivered[0].number)
        take(Action("PrepareReceipt", (unit, "receipt")))
        take(Action("PutBody", (unit, "receipt")))
        if localize_verification_save:
            # Paper 1328-1341 / 1351: retain the earlier-unsaved state and
            # all of its EH/EW/EA/EI in the prefix, then start at an IP(T)
            # boundary. The independent E0 still declares both T and V.
            for operation in ("AddEntry", "ConfirmWrite", "CompleteWrite"):
                take(Action(operation, (unit, "receipt")))
            take(Action("RecognizeTerminal", (work,)))
            verification_plan = next(p for p in scene.e0.publication_plans
                                     if p.unit == "verification:" + work)
            save(verification_plan.unit, tuple(r.slot for r in verification_plan.records))

    def result():
        enabled.append(tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(env.actions(state)))
        return (Scenario(scene.id, scene.e0, scene.max_states, state, scene.cut,
                         json.dumps(connection_snapshot(state, actions), ensure_ascii=False)),
                tuple(states), tuple(edges), tuple(enabled))

    boundary = scene.prefix.removeprefix("v2:")
    localize_verification_save = boundary == "tie:wv-v-saved"
    if localize_verification_save:
        boundary = "tie:wv"
    if boundary.startswith("interval:"):
        if any(plan.unit == "segment-env" for plan in scene.e0.plans):
            take(Action("Post", ("boot",)))
            accept_saved()
            take(Action("PublishUnit", ("segment-env",)))
            save("segment-env", ("process", "route", "clock"))
        take(Action("RequestInterval", ("k1",)))
        take(Action("PublishUnit", ("segment",)))
        if not any(plan.unit == "segment-env" for plan in scene.e0.plans):
            save("segment", ("process", "route", "clock"))
        if boundary != "interval:k-published":
            save("segment", ("k",))
        return result()
    take(Action("Post", ("boot",)))
    accept_saved()
    if any(plan.unit == "clock-source" for plan in scene.e0.plans):
        # Public A-CLOCK-SOURCE; independent plan, not a fourth initial slot.
        take(Action("PublishUnit", ("clock-source",)))
        save("clock-source", ("source",))
    take(Action("PublishUnit", ("initial",)))
    save("initial", ("process", "reader", "q"))
    if boundary == "tie:wr":
        tied_notices("wr")
        return result()
    if boundary == "artifact":
        for operation in ("ResolveWork", "ClaimStart", "Launch"):
            take(Action(operation, ("wr",)))
        take(Action("EnterWorker", ("wr:wrapper:0",)))
        return result()
    if boundary == "unknown-wr":
        for operation in ("ResolveWork", "ClaimStart", "Launch"):
            take(Action(operation, ("wr",)))
        take(Action("EnterWorker", ("wr:wrapper:0",)))
        take(Action("HostUnknown", ("unknown-wr",)))
        take(Action("Deliver", ("host-unknown:unknown-wr",)))
        return result()
    if boundary in ("desc-terminal", "record-only"):
        finish("wr")
        if boundary == "record-only":
            take(Action("RecognizeTerminal", ("wr",)))
        return result()
    if boundary.startswith("delta:"):
        first = boundary.split(":")[1]
        take(Action("Post", (first,)))
        accept_saved()
        take(Action("PublishUnit", ("q-" + first,)))
        save("q-" + first, ("q",))
        return result()
    if boundary == "q-published":
        # Close only the physical initial execution; its logical run/handle
        # obligation remains. The new Q has its own external Received trigger.
        for operation in ("ResolveWork", "ClaimStart", "Launch"):
            take(Action(operation, ("wr",)))
        take(Action("EnterWorker", ("wr:wrapper:0",)))
        take(Action("Stop", ("wr",)))
        take(Action("Release", ("wr",)))
        take(Action("Post", ("e1",)))
        accept_saved()
        take(Action("PublishUnit", ("q-e1",)))
        return result()
    if boundary != "iq":
        finish("wr")
        take(Action("PublishUnit", ("result",)))
    if boundary not in ("iq", "r-published"):
        save("result", ("r",))
        if boundary.startswith("tie:"):
            save_terminal("wr")
        if boundary == "tie:wp":
            tied_notices("wp")
            return result()
        finish("wp")
        take(Action("PublishUnit", ("proof",)))
    if boundary == "p-clocks-saved":
        save("proof", ("started", "finished"))
        return result()
    if boundary not in ("iq", "r-published", "p-published"):
        save("proof", ("p", "started", "finished"))
    if boundary not in ("iq", "r-published", "p-published", "p-saved"):
        take(Action("PublishUnit", ("completed",)))
        save("completed", ("c",))
    if boundary.startswith("verify:") or boundary == "tie:wv":
        if boundary == "tie:wv":
            save_terminal("wp")
        take(Action("Acquire", ("acquire-rp",)))
        take(Action("PublishUnit", ("acquisition",)))
        save("acquisition", ("clock",) if boundary == "verify:g-published" else ("clock", "g"))
        if boundary == "verify:g-published":
            # G depends on its clock Point. Keep the G save boundary live.
            return result()
        if boundary in ("verify:adopt", "verify:reply-saved"):
            finish("wv", stop=boundary == "verify:adopt")
        if boundary == "tie:wv":
            tied_notices("wv")
    return result()


def acquisition_structure_e0():
    from fb_machine import AcquisitionIntent
    base = update_structure_e0()
    intent = AcquisitionIntent("acquire-rp", PlanRef("initial", "reader"),
        frozenset((PlanRef("result", "r"), PlanRef("proof", "p"))), PlanRef("completed", "c"), frozenset())
    return fixed(replace(base, acquisitions=(intent,), observation_declarations=None))


def verification_structure_e0():
    """SC-06/1386/1507: structure, actual acquisition, verification and ancestry.

    F-a numerical certificate/closure validation belongs to implementation.
    Clock evidence is the canonical clock_reading/1 Point, not a value field.
    """
    from fb_machine import (AcquisitionIntent, AdoptionIntent, CausalPort, ReadContents,
                            Certificate, CertificatePortEvent, VerificationReply, UpdateTarget, digest)
    base = update_structure_e0()
    process, reader, q = (PlanRef("initial", s) for s in ("process", "reader", "q"))
    r, p, c = PlanRef("result", "r"), PlanRef("proof", "p"), PlanRef("completed", "c")
    g, clock = PlanRef("acquisition", "g"), PlanRef("acquisition", "clock")
    target = UpdateTarget(q, r, frozenset((p,)), c)
    view = NumericalView(frozenset((reader,)))
    closure = frozenset((reader, q, r, p, c))
    check_view = closure | {g, clock, process, PlanRef("proof", "started"), PlanRef("proof", "finished")}
    expected_result = obj(port_result="symbolic-only")
    issued = Certificate("finite-issuer", target, reader, ReadContents(frozenset((q, r, p, c))), view,
                         closure, check_view, "finite-registry", Contract("model.verify", "1"), digest(expected_result))
    reply = VerificationReply("Success", target, reader, ReadContents(frozenset((q, r, p, c))), view,
                              closure, check_view, "finite-registry", Contract("model.verify", "1"),
                              obj(port_result="symbolic-only"), (), frozenset(), issued)
    wv = replace(base.plans[0].works[0], work_id="wv", stage="Wv", stage_slot="verification", purpose="verification",
        method=Contract("model.verify", "1"), output_contract=Contract("model.verification_reply", "1"),
        args=obj(target=target, check_view=check_view, registry="finite-registry", checker=Contract("model.verify", "1")),
        input_points=closure, numerical_view=view, required=check_view)
    gr = RecordPlan("g", Contract("content_acquired", "1"), "Event",
        obj(origin=reader, contents=(r, p), clock=clock),
        tuple(TypedReference("PATH-ACQUIRE", path, ref, "UE", "acquire") for path, ref in
              ((("origin",), reader), (("contents", 0), r), (("contents", 1), p), (("clock",), clock))))
    cr = clock_reading_record("clock", PlanRef("clock-source", "source"),
                              Source("acquisition_clock", "acquire-rp"))
    gp = AllowedPlan("acquisition", "O-08", ("acquire-rp",), (cr, gr), (wv,), (Guard("acquired", "acquire-rp"),))
    ar = RecordPlan("a", Contract("knowledge_adopted", "1"), "Event", obj(origin=reader, previous=None, completion=c),
        (TypedReference("PATH-ADOPT", ("origin",), reader, "UE", "adopt"),
         TypedReference("PATH-ADOPT", ("completion",), c, "UE", "adopt")), frozenset((g,)))
    ap = AllowedPlan("adoption", "O-09.b", ("adopt-r",), (ar,), operation="Adopt")
    stale = AllowedPlan("stale", "O-09.b", ("adopt-r-stale",), (), operation="Adopt")
    intent = AcquisitionIntent("acquire-rp", reader, frozenset((r, p)), c, frozenset(), record=g)
    adoption = AdoptionIntent("adopt-r", reader, c, r, None, "wv", ("acquire-rp",), "adoption", "stale")
    actual = Program("wv", (Outcome(OutcomeKind.RETURNED, reply),), True,
                     certificate_events=(CertificatePortEvent(0, issued),))
    declared = fixed(replace(base, plans=base.plans + (gp, ap, stale), programs=base.programs + (actual,),
        acquisitions=(intent,), adoptions=(adoption,), receipt_kinds=base.receipt_kinds + ((3, "WorkFinished"),),
        causal_ports=(CausalPort(check.SlotKey("acquisition", "g"), frozenset((reader, r, p, c))),
                      CausalPort(check.SlotKey("adoption", "a"), frozenset((g, c)))), observation_declarations=None))
    # A-VERIFY-CALL is retired in favour of public A-CALL-ID. Validate the
    # pre-execution adapter, never replace a key using observed VerifyCall.
    assert any(b.key == check.VerificationKey("wv", verification_call_id())
               for b in declared.observation_declarations.verifications)
    assert declared.observation_declarations.adoptions
    return declared


def delta_structure_e0(first):
    """Paper 937/1363: e1-Q1 precedes e2, with both original obligations kept.

    A-DELTA-FINITE (紙に無い仮定): this independently authored /1 relation
    maps raw input to a structural request only; /2 observation projection and
    legal numerical Q are still unsupported. It is not generated from EU.
    """
    from fb_machine import FieldRole, DerivationContract
    base = lifecycle_e0(stop=False)
    process, reader, q0 = (PlanRef("initial", s) for s in ("process", "reader", "q"))
    other = "e2" if first == "e1" else "e1"
    sources = {name: check.ReceiptSource("source-" + name, "upstream", received(name.encode()), run=base.run)
               for name in ("e1", "e2")}
    plans, bindings = [], []
    base_root = frozenset((process, reader, q0, PlanRef(receipt_unit_id(base.run, 0), "boot"),
                           PlanRef(receipt_unit_id(base.run, 0), "declaration")))
    for name in (first, other):
        alias = sources[name]
        trigger = PlanRef(alias.unit, alias.slot)
        unit = "q-" + name
        q = PlanRef(unit, "q")
        record = RecordPlan("q", Contract("computation_requested", "1"), "Event",
            obj(origin=reader, method=Contract("finite_update", "1"),
                args=obj(model=reader, previous_result=None, observations=()), inputs=(reader,), algorithm_draws=(),
                link=obj(process=process, trigger=trigger, reader=reader, purpose="belief_update", trigger_slots=(name,))),
            tuple(TypedReference("PATH-Q0", path, reader, "UE", "numerical") for path in
                  (("origin",), ("args", "model"), ("inputs", 0))) +
            tuple(TypedReference("PATH-LINK-GENERATION", ("link", field), ref, "UE", "derive")
                  for field, ref in (("process", process), ("trigger", trigger), ("reader", reader))), frozenset((trigger,)))
        work = replace(base.plans[0].works[0], work_id="wr-" + name, trigger=trigger, request=q,
                       stage_slot="stage-" + name, required=frozenset((q, reader, process, trigger)))
        plan = AllowedPlan(unit, "O-03", ("delta", name), (record,), (work,), (Guard("saved", trigger),))
        plans.append(plan)
        root = base_root | {trigger}
        if name == other:
            root |= {PlanRef(sources[first].unit, "receipt"), PlanRef("q-" + first, "q")}
        bindings.append(check.DerivationBinding(process, "1", process, reader, "belief_update", alias,
            check.SlotKey(alias.unit, "receipt"), name, "stage-" + name, frozenset((name,)), work.method,
            frozenset((reader,)), frozenset((trigger,)), root, None, check.SlotKey(unit, "q"), plan,
            ("PATH-QOBS/bootstrap /2 numerical projection remains unverified",)))
    posts = tuple(Posting(name, sources[name].event, 1, frozenset((q0,)) if name == first else
                         frozenset((PlanRef("q-" + first, "q"),)), "upstream") for name in (first, other))
    fields = tuple(FieldRole(Contract("computation_requested", "1"), "PATH-LINK-GENERATION",
                             ("link", field), "UE", "derive") for field in ("process", "trigger", "reader"))
    declared = fixed(replace(base, postings=base.postings + posts, plans=base.plans + tuple(plans),
        programs=base.programs + tuple(Program("wr-" + name, (), False) for name in (first, other)),
        receipt_kinds=((0, "Boot"), (1, "Received"), (2, "Received")), presentation_limit=1,
        field_roles=base.field_roles + fields, observation_declarations=None))
    return replace(declared, observation_declarations=replace(declared.observation_declarations,
        receipt_sources=tuple(sources.values()), derivations=tuple(bindings)))


def interval_structure_e0(tag=None, *, split=False):
    """Paper 1019/1205-1207: independent finite route/k/MeasureSegment wiring.

    A-INTERVAL-WIRE is 紙に無い仮定: model.* contracts transport the listed
    fields only. The real route/k wire and Support semantics remain unverified.
    """
    from fb_machine import Cell, FieldRole, IntervalOccurrence, IntervalFact, Reading, ReferencePath
    process, route, clock = (PlanRef("segment-env" if split else "segment", s) for s in ("process", "route", "clock"))
    k = PlanRef("segment", "k")
    interval = Interval("run-0", "M", 0, 2, True, False)
    cells = frozenset((Cell(0, 0), Cell(0, 1), Cell(1, 1), Cell(1, 2)))
    request = IntervalRequest("k1", k, "route-0", "measure-k1", interval,
                              Contract("model.measure", "1"), Contract("model.clock", "1"), cells)
    kr = RecordPlan("k", Contract("model.interval_request", "1"), "Event",
        obj(route=route, process=process, permission=route, clock=clock, segment_slot="k1", interval=interval,
            measurement_contract=request.measurement_contract, clock_contract=request.clock_contract),
        tuple(TypedReference("PATH-INTERVAL", (field,), ref, "UE", "measure") for field, ref in
              (("route", route), ("process", process), ("permission", route), ("clock", clock))))
    records = (RecordPlan("process", Contract("model.process", "1"), "Event", obj(origin="bootstrap")),
               RecordPlan("route", Contract("model.route", "1"), "Event", obj(origin="bootstrap", route_epoch="route-0")),
               RecordPlan("clock", Contract("model.clock", "1"), "Event", obj(source="M", run="run-0")), kr)
    work = Descriptor("measure-k1", process, k, "measure", "k1", route, request.measurement_contract,
        Contract("model.segment_report", "1"), obj(interval=interval), frozenset((route, clock, k)),
        NumericalView(frozenset((route, clock, k))), "bootstrap", frozenset((route,)), k,
        "MeasureSegment", (("measure", 1),), frozenset((process, route, clock, k)))
    plan = AllowedPlan("segment", "O-04", ("route-0", "k1"), records[-1:] if split else records, (work,), (Guard("interval_intent", "k1"),))
    setup = (AllowedPlan("segment-env", "O-02", ("bootstrap", "route-env"), records[:-1], guards=(
        Guard("saved", PlanRef(receipt_unit_id("run-0", 0), "declaration")),)),) if split else ()
    base = E0(capacity=(("measure", 1),), allocation=(("measure", 1),), intervals=(request,), plans=setup + (plan,),
              programs=(Program("measure-k1", (), False),), presentation_limit=1)
    if split:
        initial = obj(generator="bootstrap", initial_slot="route-env", routes=("route-0",))
        boot = Event("Boot", obj(declaration=obj(initial=initial, capacity=(("measure", 1),),
            scope="one", routes=("route-0",), environment="finite")))
        base = replace(base, initial=initial, postings=(Posting("boot", boot, 0),), receipt_kinds=((0, "Boot"),))
    # Paper 1019 supplies these four reference fields. The spelling of this
    # finite wire/path is A-INTERVAL-WIRE, not a new canonical contract.
    base = replace(base, references=base.references + (ReferencePath("PATH-INTERVAL", ("model.interval_request/1",),
        ("route", "process", "permission", "clock"), "UE", "measure", "direct"),))
    roles = tuple(FieldRole(kr.contract, "PATH-INTERVAL", ref.path, "UE", "measure") for ref in kr.references)
    conditions = tuple(check.CompletionBinding(check.CompletionKey("O-04", ("route-0", "k1"), kind, target),
        "IntervalRequest", check.IntervalKey("k1", "route-0", "run-0"),
        (check.SlotKey("segment", "k"),) if kind == "save" else (), check.Owner("H", "k1"))
        for kind, target in (("save", check.SlotKey("segment", "k")), ("handle", check.WorkKey("measure-k1"))))
    if tag is None:
        return fixed(replace(base, field_roles=base.field_roles + roles), conditions)
    point = PlanRef("evidence", "event")
    er = RecordPlan("event", Contract("model.interval_evidence", "1"), "Event", obj(kind=tag, interval=interval))
    ep = AllowedPlan("evidence", "O-04", ("k1", tag), (er,), guards=(Guard("saved", k),))
    actual = IntervalOccurrence("event", IntervalFact(tag, "k1", "route-0", Reading("run-0", "M", 0),
                               cells if tag == "Monitored" else frozenset(), point, obj(kind=tag, interval=interval)))
    expectation = check.IntervalObserved(Reading("run-0", "M", 0), interval,
        cells if tag == "Monitored" else frozenset(), "measure-k1", point, obj(kind=tag, interval=interval))
    binding = check.IntervalEvidenceBinding(point, check.IntervalKey("k1", "route-0", "run-0"), tag, expectation, er)
    declared = fixed(replace(base, plans=(plan, ep), field_roles=base.field_roles + roles,
                             interval_occurrences=(actual,)), conditions)
    return replace(declared, observation_declarations=replace(declared.observation_declarations, interval_evidence=(binding,)))


def artifact_structure_e0():
    """Separate EQ and independently declared actual/expected finite ports.

    A-ARTIFACT-WIRE (紙に無い仮定): model.evaluation_request/artifact only
    transport the paper fields. No legal IE/ID or full math_artifact/2 closure.
    """
    from fb_machine import ProgramPortEvent, FieldRole
    base = lifecycle_e0()
    eq, process, reader = (PlanRef("initial", s) for s in ("q", "process", "reader"))
    eqr = RecordPlan("q", Contract("model.evaluation_request", "1"), "Event", obj(input=reader, operation="prepare"),
        (TypedReference("PATH-ARTIFACT-INPUT", ("input",), reader, "UE", "math"),))
    work = replace(base.plans[0].works[0], stage="Ep", purpose="evaluation", method=Contract("model.prepare", "1"),
                   output_contract=Contract("model.artifact", "1"), args=obj(input=reader, operation="prepare"))
    plan = replace(base.plans[0], records=base.plans[0].records[:2] + (eqr,), works=(work,))
    expected = check.ArtifactValue(Contract("model.artifact", "1"), Contract("model.compiler", "1"),
        "fixed-view", "registry", obj(request=eq, model=reader), (), obj(variant="FProblem"))
    actual = check.ArtifactValue(Contract("model.artifact", "1"), Contract("model.compiler", "1"),
        "fixed-view", "registry", obj(request=eq, model=reader), (), obj(variant="FProblem"))
    binding = check.ArtifactPortBinding("wr", expected.contract, expected.compiler, "fixed-view", "registry",
                                       obj(request=eq, model=reader), (expected,))
    program = Program("wr", (Outcome(OutcomeKind.RETURNED, obj(variant="FProblem")),), True,
                      (ProgramPortEvent(0, "ArtifactIssued", check.WorkKey("wr"), actual),))
    declared = fixed(replace(base, plans=(plan,), programs=(program,), presentation_limit=1,
        field_roles=base.field_roles + (FieldRole(eqr.contract, "PATH-ARTIFACT-INPUT", ("input",), "UE", "math"),),
        receipt_kinds=((0, "Boot"), (1, "WorkFinished")), observation_declarations=None))
    return replace(declared, observation_declarations=replace(declared.observation_declarations, artifacts=(binding,)))


def second_round_scenes(original):
    scenes = list(original)
    for index, scene in enumerate(scenes):
        if scene.id == "SC-04-DESC":
            # Paper 1379 requires a logical end, not specifically a successful
            # numerical result. A declared Failure supplies a real terminal
            # notice without inventing successful F-a output.
            base = lifecycle_e0()
            terminal = fixed(replace(base, programs=(Program("wr", (
                Outcome(OutcomeKind.FAILURE, obj(reason="finite worker failure")),), True),),
                receipt_kinds=((0, "Boot"), (1, "WorkFinished")), presentation_limit=1, observation_declarations=None))
            scenes[index] = replace(scene, e0=terminal, prefix="v2:desc-terminal", max_states=300,
                initial_id="IQ→実Failure受信保存・Stop/Release、論理終端直前",
                remaining=scene.remaining)
        if scene.paper_id in FAIRNESS_TABLE or scene.paper_id == "SC-05-CYCLE":
            scenes[index] = replace(scene, initial_id="IL" if scene.paper_id in FAIRNESS_TABLE else "受理前の有限記号グラフ",
                blocker="公開の抽象入口で別計上。実模型の合法到達・正しい窓口の合格への接続は未確認。",
                remaining=("抽象入力の期待分類だけ。N4のINV-2.d行への接続と実模型の到達は未実行。",))
        if scene.id.startswith(("SC-01-same-rebuild", "SC-01-different-rebuild")):
            # Paper 954: no Boot, worker, interval, I/O faults, launch, wrapper,
            # acquisition, adoption or handoff product. BOTH external receipts,
            # both content cases, one reacceptance and required rebuild remain.
            base = E0(postings=scene.e0.postings, receipt_kinds=scene.e0.receipt_kinds,
                      capacity=(), allocation=(), budget=Budget(window_faults=scene.e0.budget.window_faults),
                      delivery_limit=1, presentation_limit=2)
            scenes[index] = replace(scene, e0=fixed(base), max_states=50_000)
    e0 = update_structure_e0()
    for boundary, goals in (
        ("r-published", (_goal("wp-before-r", "R未保存でWp行あり・まだ開始不可", "wp_wait"),
                         _goal("r-saved", "R保存後Wp開始可能", "wp_ready"))),
        ("p-published", (_goal("p-saved", "Pと時計証拠保存", "saved_slots", "proof", "p", "started", "finished"),)),
        ("p-saved", (_goal("completed", "P後にCqがただ1件保存", "one_completed"),)),
        ("p-clocks-saved", (_goal("p-saved", "時計保存後にP保存", "saved_slots", "proof", "p", "started", "finished"),
                            _goal("c-before-p", "時計保存済みでもP未保存中はCのPublish/準備を提供しない", "c_blocked_before_p"),
                            _goal("completed", "P保存後Cが1件", "one_completed"))),
    ):
        scenes.append(Scene("SC-05-structure-" + boundary, "SC-05", (933, 1330, 1341),
            "IQ→局所構造:" + boundary + "（合法IC未確認）",
            Cut("K-U", frozenset(("RecognizeTerminal", "WorkerStep", "Acquire", "Adopt")), (STRUCTURAL_LIMIT,)),
            500, e0, goals, "v2:" + boundary, assumptions=V2_ASSUMPTIONS, remaining=(STRUCTURAL_LIMIT,)))
    scenes.append(Scene("SC-06-structure-acquire", "SC-06", (934, 1330, 1331, 1341),
        "局所Q/R/P/C保存→実取得（合法IC未確認）", Cut("K-B", frozenset(("RecognizeTerminal",)), (STRUCTURAL_LIMIT,)),
        100, acquisition_structure_e0(), (_goal("acquire", "同じ読み手がR/Pを実取得", "acquired"),),
        "v2:c-saved", assumptions=V2_ASSUMPTIONS, remaining=(STRUCTURAL_LIMIT,)))
    for boundary in ("pending", "adopt"):
        scenes.append(Scene("SC-06-structure-verification-" + boundary, "SC-06", (934, 1085, 1086, 1341),
            "局所Q/R/P/C→実取得→G/Wv" + ("→認証返答" if boundary == "adopt" else ""),
            Cut("K-B", frozenset(("RecognizeTerminal",)), (STRUCTURAL_LIMIT,)), 200,
            verification_structure_e0(), (_goal("issued", "返答とは別の認証物発行ポート", "tag", "CertificateIssued"),
                _goal("verify", "実認証返答ポート", "tag", "VerifyReply"),
                _goal("adopt", "実祖先Gを持つ採用", "adopt_ancestor")),
            "v2:verify:" + ("reply-saved" if boundary == "pending" else boundary),
            assumptions=V2_ASSUMPTIONS + (
                "紙に無い仮定 A-CALL-ID: A-VERIFY-CALLを公開verification_call_id()へ置換。宣言変換のVerificationBinding/AdoptionBindingを使用。fb_machine.py:739-746,1819-1829。",
                "紙に無い仮定 A-CERTIFICATE-PORT: 有限の実発行と返答台本を独立に宣言する。実F-a証明・全閉包は実装の段へ。紙1507。"),
            remaining=(STRUCTURAL_LIMIT, "Rejected/Insufficient/Unknown/対象違い・Staleは未実行。")))
    for first in ("e1", "e2"):
        scenes.append(Scene("SC-08-structure-" + first + "-then-other", "SC-08", (937, 1363),
            "IQ→先行受信とQ保存、他方未Post", Cut("K-Q", frozenset(("ClaimStart", "RecognizeTerminal")),
            ("数値射影/まとめるδ/下流Wrは未確認",)), 500, delta_structure_e0(first),
            (_goal("two-received", "独立な2原本の保存", "received_count", 2),
             _goal("two-requests", "先行Qの後も別受信用Qを保存", "derived_count", 2)),
            "v2:delta:" + first, assumptions=LIFECYCLE_ASSUMPTIONS + (
                "紙に無い仮定 A-RECEIPT-SELECTOR/A-POST-SOURCE: 出所+全Event+runの別名。fb_check.py:3020-3039; fb_machine.py:685-697。",
                "紙に無い仮定 A-DELTA-FINITE: /1の局所構造用有限関係。/2数値射影や合法な観測Qは未確認。"),
            remaining=("SC-08全体のまとめたQ・他trigger-slot・Conflictと数値射影は未実行。",)))
    scenes.append(Scene("SC-09-structure-artifact-port", "SC-09", (938, 1025, 1089, 1341),
        "EQ/Ep入場の局所構造（合法IE未確認）", Cut("K-E", frozenset(("RecognizeTerminal",)), (STRUCTURAL_LIMIT,)),
        300, artifact_structure_e0(), (_goal("issued", "EQの同じ入力から独立した実artifact発行", "tag", "ArtifactIssued"),),
        "v2:artifact", assumptions=LIFECYCLE_ASSUMPTIONS + ("紙に無い仮定 A-ARTIFACT-WIRE: model.*は有限ポート運搬だけ。紙1089-1096; fb_check.py:3134-3154。",),
        remaining=("PR/D/Ee/selectionと実F-a artifact閉包は未接続。",)))
    interval_assumptions = INTERVAL_ASSUMPTIONS + (
        "紙に無い仮定 A-INTERVAL-WIRE: model.route/process/clock/interval_requestは1019欄の局所構造だけ。実IK/Supportは未確認。",
        "紙に無い仮定 A-EI-PORT: EI証拠は独立した有限台本。MonitoredセルはClaimや実測の証明にしない。紙739/1087/1334。")
    scenes.append(Scene("SC-12-structure-measure-row", "SC-12", (941, 1205, 1206, 1207, 1334),
        "区間引受け→k Publish（局所構造）", Cut("K-K", untested=("実IK/Support",)), 200,
        interval_structure_e0(), (_goal("measure-row", "k未保存からMeasureSegment行を保持", "measure_row"),
            _goal("measure-enter", "k保存後に測る仕事へ入場", "stage_entered", "MeasureSegment"),
            _goal("unreported", "報告なしをGapへ変えず未報告責務を保持", "unreported")),
        "v2:interval:k-published", assumptions=interval_assumptions, remaining=("実IK/Support/型別報告の意味は未確認。",)))
    for tag, paper_id in (("MeasurementStarted", "SC-11"), ("MeasurementEnded", "SC-11"), ("Monitored", "SC-12")):
        scenes.append(Scene(paper_id + "-structure-" + tag, paper_id, (SC_TABLE[paper_id], 1334, 1364),
            "k保存→EIと保存証拠（局所構造）", Cut("K-K", frozenset(("ClaimStart",)), ("実IK/Support",)),
            200, interval_structure_e0(tag), (_goal("evidence", "事前宣言した証拠slotの保存", "saved_slots", "evidence", "event"),
                _goal("actual", "保存証拠とは独立した実EI出来事", "tag", tag)),
            "v2:interval:k-saved", assumptions=interval_assumptions, remaining=("Supportや被覆達成とは数えない。",)))
    for stop in (False, True):
        base = lifecycle_e0(stop=stop)
        unknown = fixed(replace(base, unknown_notices=(UnknownNotice("unknown-wr", "wr", obj(reason="not_confirmed")),),
            programs=(Program("wr", (Outcome(OutcomeKind.RETURNED, obj(variant="Success", value="late")),), stop),),
            receipt_kinds=((0, "Boot"), (1, "WorkFinished"), (2, "WorkFinished")), presentation_limit=1,
            observation_declarations=None))
        scenes.append(Scene("SC-15-structure-Wr-" + ("stop" if stop else "no-stop"), "SC-15", (944, 1366),
            "IQ→Wr入場→Unknown Post、後着値あり", Cut("K-T", frozenset(("RecognizeTerminal",)), ("T/種類別後続",)),
            300, unknown, (_goal("unknown-held", "Unknown原本の時点で占有を保持", "unknown_held"),
                _goal("late-saved", "Unknownと後着値の受信保存", "work_reports", 2)), "v2:unknown-wr",
            assumptions=LIFECYCLE_ASSUMPTIONS, remaining=("T/種類別後続・r同着対照は未確認。",)))
    scenes.append(Scene("SC-21-structure-Q-R-P-C", "SC-21", (950, 1369),
        "IQ→局所Q/R/P/時計/C（合法IC未確認）", Cut("K-V", frozenset(("RecognizeTerminal",)), (STRUCTURAL_LIMIT,)),
        50, update_structure_e0(), (_goal("completed", "同じQ/R/PからCを1件保存", "one_completed"),),
        "v2:c-saved", assumptions=V2_ASSUMPTIONS, remaining=(STRUCTURAL_LIMIT, "他の縦接続は未実行。")))
    scenes.append(Scene("SC-05-PARENT-structure-positive", "SC-05-PARENT", (1383, 1341),
        "局所Q/R/P/Cの親対照", Cut("K-B", frozenset(("RecognizeTerminal",)), (STRUCTURAL_LIMIT,)),
        50, update_structure_e0(), (_goal("parents", "R/PはPredictionを親にせず保存済みQを親に持つ", "prediction_parents"),),
        "v2:c-saved", assumptions=V2_ASSUMPTIONS, remaining=(STRUCTURAL_LIMIT, "負のPrediction親候補は未実行。")))
    return tuple(scenes)


def single_received_publish_e0():
    """Paper 932/1203/1208: one Received -> Q and a distinct Wr row.

    A-DELTA-FINITE: /1 symbolic structure only; /2 numerical mapping is outside
    this case. No observed receipt number, r, CID or output supplies the E0.
    """
    declared = delta_structure_e0("e1")
    base = replace(declared, postings=tuple(p for p in declared.postings if p.id != "e2"),
        plans=tuple(p for p in declared.plans if p.unit != "q-e2"),
        programs=(Program("wr", (), True), Program("wr-e1", (), False)),
        receipt_kinds=((0, "Boot"), (1, "Received")), observation_declarations=None)
    fixed_base = fixed(base)
    return replace(fixed_base, observation_declarations=replace(fixed_base.observation_declarations,
        receipt_sources=declared.observation_declarations.receipt_sources[:1],
        derivations=declared.observation_declarations.derivations[:1]))


def publish_kind_scenes():
    """Paper 932/1361: nine cases within the original SC-04 branch ID.

    The initial case is O-02. The separate Q case has an independently declared
    Received trigger and O-03 publication/O-05 execution. Expected plans precede
    execution; this does not claim every /2 numerical derivation of Q.
    """
    cut = Cut("K-U", frozenset(("PublishUnit", "WorkerStep", "RecognizeTerminal", "Stop", "Release", "Acquire", "Adopt", "Post")),
              ("対象Publishから保存・開始・二重包みまで。返答・停止・後続Publishは未検査、責務を保持。紙1346。",))
    initial = lifecycle_e0(stop=False, budget=Budget(duplicate_wrappers=1))
    result = update_structure_e0()
    acquisition = verification_structure_e0()
    evaluation = artifact_structure_e0()
    interval = interval_structure_e0(split=True)
    terminal = fixed(replace(lifecycle_e0(), programs=(Program("wr", (
        Outcome(OutcomeKind.FAILURE, obj(reason="finite worker failure")),), True),),
        receipt_kinds=((0, "Boot"), (1, "WorkFinished")), presentation_limit=1, observation_declarations=None))
    cases = []
    for name, e0, prefix, unit, work, source in (
        ("initial", initial, "one-missing", "initial", "wr", "O-02"),
        ("Q-Wr", single_received_publish_e0(), "v2:q-published", "q-e1", "wr-e1", "O-05"),
        ("R-Wp", result, "v2:r-published", "result", "wp", "O-07"),
        ("G-Wv", acquisition, "v2:verify:g-published", "acquisition", "wv", "O-09.a"),
        ("EQ-Ep", evaluation, "one-missing", "initial", "wr", "O-10"),
        ("interval-MeasureSegment", interval, "v2:interval:k-published", "segment", "measure-k1", "O-04"),
        ("record-only", terminal, "v2:record-only", "terminal:wr", "", "T"),
    ):
        # Preserve already-frozen extra port declarations while changing only
        # the finite scheduling budget; never use a returned artifact as E0.
        e0 = replace(e0, budget=Budget(duplicate_wrappers=1) if work else Budget(), presentation_limit=1)
        slots = tuple(r.slot for p in e0.plans if p.unit == unit for r in p.records) if work else ("T",)
        goals = (_goal("publish", "対象Publish直後に全仕事行、依存未保存", "publish_kind", unit, work),
                 _goal("saved", "対象Publishの全slotが保存", "saved_slots", unit, *slots))
        if work:
            goals += (_goal("start", "依存保存後に対象仕事開始", "work_entered", work),
                      _goal("drain-twice", "二重列挙で同じ仕事行を保持", "drain"),
                      _goal("double-wrapper", "対象仕事の同じ札を持つ二重包み", "work_wrappers", work))
        else:
            goals += (_goal("no-successor", "TのPublishで後続仕事を追加しない", "record_only", unit),)
        cases.append(Scene("SC-04-publish-" + name, "SC-04", (932, 1361, 1346),
            "到達履歴付きIP(" + unit + ") / " + source, cut, 500, e0, goals, prefix,
            assumptions=V2_ASSUMPTIONS + ((
                "紙に無い仮定 A-DELTA-FINITE: ReceivedとQの/1有限対応だけ。/2数値射影は実装の段へ。紙1081/1509。",
                "紙に無い仮定 A-RECEIPT-SELECTOR/A-POST-SOURCE: 出所+全Event+runで原本を宣言。番号/r/seqを実観測から先取りしない。fb_check.py:3379-3382。",
            ) if name == "Q-Wr" else ()),
            implementation_scope=(STRUCTURAL_LIMIT,)))
    for name, initial_id in (("PR-D", "IE"), ("DF-Ee", "ID")):
        reason = ("範囲外 (実装の段へ): " + initial_id + "のFProblem/Draw/artifactの数値的な生成・全閉包を"
                  "実装の段でF-aの実物に繋いで確かめる。紙932/1332-1333/1509。"
                  "模型のPR/DFからの構造的なPublish接続もこの枝では未観測であり、合格に数えない。")
        cases.append(Scene("SC-04-publish-" + name, "SC-04", (932, 1361, 1332, 1333, 1509),
            initial_id, Cut("K-U"), 500, None, (_goal("paper-required", ROWS_BY_LINE[932][2], "unconnected", reason),),
            blocker=reason, scope_class="b", scope_reason=reason, implementation_scope=(reason,)))
    return tuple(cases)


def third_round_scenes(original):
    """v0.12 scope decisions preserve all 193 IDs and their original rows."""
    by_id = {s.id: s for s in original}
    # These original branches now have sufficient public structural entries.
    reuse = {
        "SC-05": "SC-06-structure-verification-pending",
        "SC-06-Success": "SC-06-structure-verification-pending",
        "SC-05-PARENT": "SC-05-PARENT-structure-positive",
        "SC-05-COMPLETE": "SC-05-structure-p-clocks-saved",
        "SC-06-ANCESTOR": "SC-06-structure-verification-adopt",
        "SC-21-Q-R-P-C": "SC-21-structure-Q-R-P-C",
        "SC-21-acquire-verify-adopt": "SC-06-structure-verification-pending",
        "SC-11-Started": "SC-11-structure-MeasurementStarted",
        "SC-11-Ended": "SC-11-structure-MeasurementEnded",
        "SC-12-started-only": "SC-11-structure-MeasurementStarted",
        "SC-12-ended-only": "SC-11-structure-MeasurementEnded",
    }
    result = []
    for scene in original:
        if scene.id == "SC-04-other-publish-kinds":
            scene = replace(scene, parts=publish_kind_scenes(), blocker="9種類を同じ枝の内訳として実行/範囲外に分離。紙932/1361/1509。",
                            max_states=500, scope_reason="a: 9種類の構造。内訳のPR-D/DF-Eeはbとして残す。", remaining=())
        elif scene.id in reuse:
            source = by_id[reuse[scene.id]]
            goals = source.goals
            if scene.id == "SC-05":
                goals = (_goal("wp-before-r", "R保存前にWp行があり開始待ち", "wp_wait"),
                         _goal("wp-after-r", "R保存後にWpを開始", "wp_ready"),
                         _goal("completed", "P保存後にCqを1件保存", "one_completed"),
                         _goal("g-wv", "G発行後、G未保存からWv行を保持", "publish_kind", "acquisition", "wv"))
            if scene.id in ("SC-12-started-only", "SC-12-ended-only"):
                goals += (_goal("unreported", "Started/Endedだけで未報告責務を解消しない", "unreported"),)
            scene = replace(scene, e0=source.e0, prefix=source.prefix, cut=source.cut,
                initial_id=source.initial_id, max_states=source.max_states, goals=goals, blocker="",
                assumptions=source.assumptions, remaining=(), implementation_scope=(STRUCTURAL_LIMIT,),
                scope_reason="a: 同じ紙の要求の構造部分を公開入口で実行。F-a数値だけを実装の段へ分離。")
            if scene.paper_id == "SC-21":
                scene = replace(scene, cut=replace(scene.cut, id="K-V"))
        elif scene.id.startswith("SC-15-") and "-tie-" in scene.id:
            # The fourth-round declaration below replaces the old P-09 entry
            # deficit. Keep the original ID/contrast until that final mapping.
            pass
        elif scene.e0 is None and scene.paper_id not in FAIRNESS_TABLE and scene.paper_id != "SC-05-CYCLE":
            # The original blocked declaration required a numerically lawful
            # prefix, not just an arbitrary set of records. v0.12 explicitly
            # moves that requirement to real F-a integration. The complete
            # original ID, reach text, contrast and rows remain the denominator.
            domain = ("/2数値射影・生成契約別閉包" if scene.paper_id == "SC-08" or scene.id == "SC-21-interval-receipt-Q" else
                      "区間のcontract別Supportと実測・生成の意味" if scene.paper_id in ("SC-11", "SC-12", "SC-13", "SC-11-FAMILY", "SC-11-CROSS-M", "SC-17-FAMILY") or scene.id == "SC-17-interval-slot-A-A-B" else
                      "IE/ID・artifact全閉包・FProblem/Drawの数値対応" if scene.paper_id in ("SC-09", "SC-10", "SC-14", "SC-14-LIMIT") or any(k in scene.id for k in ("-Ep", "-D-", "-Ee", "-Ep-D", "-D-Ee", "evaluation-")) else
                      "合法IC/IG/IA・Q/R/P/Cの実値・認証の数値的な正しさ")
            reason = ("範囲外 (実装の段へ): " + domain + "を実装の段でF-aの実物に繋いで確かめる。"
                      "紙1509。元の枝の条件差・必須到達は未観測のまま残し、構造の局所場面で置き換えて合格にしない。")
            scene = replace(scene, scope_class="b", scope_reason=reason, blocker=reason,
                            implementation_scope=(reason,), remaining=())
        else:
            scene = replace(scene, implementation_scope=(STRUCTURAL_LIMIT,) if "structure" in scene.id else ())
        if scene.id == "SC-06-structure-verification-pending":
            scene = replace(scene, initial_id="IG→Wv実発行/返答保存済み・Stop前 (前置履歴付き)",
                scope_reason="a: 上限200を保持。旧200未完はWvの発行/返答/通知保存/停止/採用保存の直積。"
                "今回は返答保存まで実行して局所化し、停止・採用・保存の残る全順序を探索。前置の別順序は未検査。紙925/1341/1347。")
        result.append(scene)
    assert len(result) == 193 and {s.id for s in result} == set(by_id)
    return tuple(result)


def same_r_structure_e0(stage, unknown_first):
    """SC-15, paper 794-801/944/1366: independent order, not predicted r.

    紙に無い仮定 A-DELIVERY-BUNDLE (fb_machine.py:1008-1017): one
    environment step Posts already generated notices consecutively using its
    actual entry clock; each Post independently assigns its receipt_seq.
    Numeric legality of the pre-existing symbolic Q/R/P/C remains outside
    this structural scene (paper 1509). No record/CID supplies an expectation.
    """
    base = verification_structure_e0() if stage == "Wv" else update_structure_e0()
    work = stage.lower()
    unknown, value = HostNotice("unknown-" + work), WorkerNotice(work, 0)
    return fixed(replace(base,
        programs=tuple(replace(p, stop_available=False) if p.work == work else p for p in base.programs),
        unknown_notices=(UnknownNotice("unknown-" + work, work, obj(reason="result-not-confirmed")),),
        delivery_bundles=(DeliveryBundle("same-r", (unknown, value) if unknown_first else (value, unknown)),),
        budget=Budget(uncertain_launches=1), presentation_limit=2,
        # Only the shape is declared; receipt numbers/r/seq come from real Post.
        receipt_kinds=(), observation_declarations=None))


def fourth_round_scenes(original):
    verification_assumptions = next(s.assumptions for s in original
                                   if s.id == "SC-06-structure-verification-adopt")
    result = []
    for scene in original:
        if not (scene.id.startswith("SC-15-") and "-tie-" in scene.id):
            result.append(scene)
            continue
        stage = scene.id.split("-")[2]
        if stage in ("Ep", "D", "Ee"):
            reason = ("範囲外 (実装の段へ): 同r配送の入口はDeliveryBundleで解消済み。"
                + stage + "の元枝が要する合法IE/ID・評価artifact/くじの数値対応と全閉包を、"
                "実装の段でF-aの実物に繋いで確かめる (紙944/1366/1509)。"
                "同r・別seq・先行未保存・終端選択は未確認。元IDと条件差を保持する。")
            result.append(replace(scene, scope_class="b", blocker=reason, scope_reason=reason,
                                  implementation_scope=(reason,), remaining=()))
            continue
        first = "unknown-first" in scene.id
        work = stage.lower()
        goals = (
            _goal("same-r-seq", "同じrun/r・異なる番号/seqでE0の通知順を再現", "tie_order", work, first),
            _goal("accept-retry", "再Acceptでも番号/r/seqと受信計画が不変", "tie_retry", work, first),
            _goal("first-unsaved", "後のseqを先に保存、先行通知未保存では終端を発行しない", "tie_wait", work, first),
            _goal("first-terminal", "先行通知保存後、E0で指定した先着の種類/受信PointでTを保存", "tie_terminal", work, first),
        )
        localized = stage == "Wv" and not first
        if localized:
            goals += (_goal("verification-saved", "発行したVの保存を前置に残す", "saved_slots", "verification:wv", "V"),)
        result.append(replace(scene, e0=same_r_structure_e0(stage, first),
            initial_id=("IP(T): 同r先行未保存を経て先行Saved・T/V発行・V Saved・T未準備 (全前置履歴付き)"
                        if localized else "IT(" + stage + "): 同r通知2件受付/再受付・後着Saved・先行bodyのみ (全前置履歴付き)"),
            prefix="v2:tie:" + work + ("-v-saved" if localized else ""), goals=goals, max_states=500,
            cut=Cut("K-T", frozenset(("PublishUnit", "ResolveWork", "ClaimStart", "Launch", "EnterWorker",
                "WorkerStep", "Acquire", "Adopt", "Stop", "Release")),
                ("指定通知の終端T/V保存まで。成功後続のPublish/開始/採用と前置の別順序は未検査。"
                 "宣言済み計画・責務・占有・実際の開始/停止履歴は保持。紙1351。",)),
            blocker="", scope_class="a", scope_reason="a: DeliveryBundleによる同r・seq対照。終端の構造を局所探索。",
            remaining=("K-T外の成功後続Publish/開始/採用と前置の全順序は未検査。",) +
                      (("V保存を合法な前置に局所化。T/V全保存順序の直積は未検査。"
                        "先行通知未保存は前置で確認し、T準備後にVを保存する逆順はP-10回帰で別途確認。",)
                       if localized else ()),
            assumptions=(verification_assumptions if stage == "Wv" else V2_ASSUMPTIONS) + ("紙に無い仮定 A-DELIVERY-BUNDLE: 実通知の連続Postを実配送開始時計で束ねる。"
                "順序だけE0で宣言しr/番号/seqは予測しない (fb_machine.py:1008-1036)。",),
            implementation_scope=(STRUCTURAL_LIMIT,)))
    assert len(result) == 193 and not any(s.scope_class == "c" for s in result)
    return tuple(result)


SCENES = fourth_round_scenes(third_round_scenes(second_round_scenes(make_scenes())))
