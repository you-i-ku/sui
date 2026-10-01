"""S4bの約束。登録は呼ぶ側で明示する。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef


BELIEF = _ContractRef("sui.s4b.belief", "1")

DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(ref=BELIEF,
        meaning='sui.model.5のPrediction target=belief。content={model,states,outcomes,q,theta_mean,fixed,n,lattice,unread,time,arrivals}。qはanchorの状態の周辺、theta_meanは学ぶ行動だけの観測×状態の事後の期待値、fixedは学ばないmodel.a、nは観測の回数。lattice={components}はanchorの有限のキーの数。time={anchor,anchor_ns,clock_issues}。到着は状態・行動と独立',
        unit='qとtheta_meanは確率、componentsとnは個数、anchor_nsは原点からns、arrivalsのbeta_sは秒',
        state_owner='sui.agent', persistence='台帳の葉。要約から学習せず、親の事実とモデルから全欄を再構築して照合',
        failure='説明不能はq=null・theta_mean=null・components=0。時間軸を作れなければcomponents=null。起動前は事前でanchorとanchor_nsがnull。数を表せなければNumericalRangeで保存しない',
        cancel='なし', redelivery='測定時刻順に事実の集合から格子を作り直す。未到着は信念を変えない'),
)
