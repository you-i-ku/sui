"""S4a の約束。登録は呼ぶ側で明示する (M11・Q7・H8)。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef

BOOT = _ContractRef("sui.s4.boot", "1")
LISTEN = _ContractRef("sui.s4.listen", "1")
BELIEF = _ContractRef("sui.s4.belief", "1")
DECISION = _ContractRef("sui.s4.decision", "1")

DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(ref=BOOT,
        meaning='runの起動の膜の事実。モデルによらず書く。Observed、route=membrane、caused_by=null、content={}。最初の起動の受信がDの原点。同runの複数起動は最小seqを使いextra_bootを残す',
        unit='received_nsはそのrunの単調時計のナノ秒', state_owner='膜',
        persistence='台帳。書く前はPledges。同じ受け取りの記録を再作成しない',
        failure='起動のないrunではQを持つモデルの決定をしない', cancel='なし',
        redelivery='同じ記録の書き直しはまとめ、別の受け取りは別の名札'),
    _Contract(ref=LISTEN,
        meaning='経路の開閉の膜の事実。モデルによらず書く。Observed、route=membrane、caused_by=null、content={route,open}。routeは空でない非membrane文字列、openはbool。区間は受信時刻とseq順、runをまたがず最後の観測受信で打ち切る',
        unit='区間の和T_nsはナノ秒', state_owner='膜', persistence='台帳、書く前はPledges',
        failure='形が違えばunread content', cancel='なし',
        redelivery='同じ記録は一度。開いている時のopen、閉じている時のcloseは区間を変えない'),
    _Contract(ref=BELIEF,
        meaning='Prediction target=belief。content={model,states,outcomes,q,a,n,unread,time,arrivals}。Qありは時刻順の対数濾過、なしはS1c。time={anchor,anchor_ns,clock_issues}。arrivals[route]={N,T_ns,alpha,beta_s,outside}は状態・行動と独立のGamma-Poisson。Nは区間内の自発的到着、本文と約束を問わない。qはanchor時点、nは事実の要約',
        unit='qは確率、時刻は原点からns、beta_sは秒、Nは回数', state_owner='sui.agent',
        persistence='台帳の葉。親の事実とモデルから全キーを再構築して照合',
        failure='説明不能・同run_indexの別runはq=null。時刻の要る読みだけ時刻不明を読まない。Qなしの行動の結果は起動・受信時刻なしでもS1cの回数として読む',
        cancel='なし', redelivery='読みは名札で一度だけ数える事実の集合の関数'),
    _Contract(ref=DECISION,
        meaning='Qを持つモデルのDecided。S3の11キーにtime={anchor,anchor_ns,now_ns,dt_s,pending_measures}。nowまで進め、進行中と候補は今を測る近似(now)。枝のrisk・ambiguity・novelty・q_oをそれぞれ平均しGから選ぶ。到着の見込みはGに使わない。Qなしの決定はsui.s1.decision "3"のまま、timeキーなし',
        unit='Gはnat、dt_sは秒、時刻は原点からns', state_owner='sui.agent',
        persistence='見た事実を親として台帳に保存。Thinkは確定したnowを保持',
        failure='起動前・nowなし・anchorより前はValueError、説明不能は決定しない',
        cancel='始める前に選び直す規則はない',
        redelivery='同じCommitの再試行は点を増やさない'),
)
