"""S4bの約束。登録は呼ぶ側で明示する。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef


BELIEF = _ContractRef("sui.s4b.belief", "1")
QUANTITY_BELIEF = _ContractRef("sui.s4b.quantity_belief", "1")
DECISION = _ContractRef("sui.s4b.decision", "1")

DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(ref=BELIEF,
        meaning='sui.model.5のPrediction target=belief。content={model,states,outcomes,q,theta_mean,fixed,n,lattice,unread,time,arrivals}。qはanchorの状態の周辺、theta_meanは学ぶ行動だけの観測×状態の事後の期待値、fixedは学ばないmodel.a、nは観測の回数。lattice={components}はanchorの有限のキーの数。time={anchor,anchor_ns,clock_issues}。到着は状態・行動と独立',
        unit='qとtheta_meanは確率、componentsとnは個数、anchor_nsは原点からns、arrivalsのbeta_sは秒',
        state_owner='sui.agent', persistence='台帳の葉。要約から学習せず、親の事実とモデルから全欄を再構築して照合',
        failure='説明不能はq=null・theta_mean=null・components=0。時間軸を作れなければcomponents=null。起動前は事前でanchorとanchor_nsがnull。数を表せなければNumericalRangeで保存しない',
        cancel='なし', redelivery='測定時刻順に事実の集合から格子を作り直す。未到着は信念を変えない'),
)

DECLARATIONS += (
    _Contract(ref=QUANTITY_BELIEF,
        meaning='sui.model.6のPrediction target=belief。content={model,states,outcomes,q,a,n,unread,time,arrivals,durations,measure,quantity}。durationsは行動ごとのcomplete/pending/queued/unknown/unreadableの個数。measure.weightsはモデル順の事後の重み。quantity.partitionsは全行動/候補の分割の項の数、空は1',
        unit='qとweightsは確率、nとdurationsとpartitionsは個数、time.anchor_nsは軸のns',
        state_owner='sui.agent', persistence='台帳の葉。親の事実とmodel.6から結合のK/DP/λの事後を作り直し全欄を照合。平均や件数から学習しない',
        failure='所要だけ説明不能ならqは名前の側のまま・weights=null・partitions=0。軸が作れないならweights=null・partitions=null。起動前/空なら事前の重み・partitions=1。NumericalRangeは保存しない',
        cancel='なし', redelivery='事実の集合と正準の試み/候補/分割の順で作り直す。runをまたぐ受け取りは数値の時刻を使わず、古いDの有限の印だけ使う'),
    _Contract(ref=DECISION,
        meaning='sui.model.6の1歩。S4dの決定の欄とtime.check_events、information_parts、information_bounds、tolerance。情報は区間の中点、J=期待費用−情報、softmaxとuで選ぶ。費用は名前の有限の予測からの和',
        unit='情報と区間とtoleranceはnat、費用とJは好みの費用、時刻は軸のns、q_piは確率',
        state_owner='sui.agent', persistence='決定時の親と好みと時刻/確かめの出どころを固定して記録。replayは同じ約束とcontentを完全照合',
        failure='保証するのは級数/記録の尾/求積を正規化と条件づけまで運んだ計算の幅。丸めと選ぶ手の一致は保証しない。永久未着の候補と先読みはOutsideEvaluationType、数値範囲はNumericalRange、計算量の中断はIntegrationIncomplete',
        cancel='なし', redelivery='同じ親、好み、now_ns/observed_ns/check_events、uから再計算。γの増幅の限界に備え区間を残す'),
)
