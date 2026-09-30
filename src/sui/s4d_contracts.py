"""S4dの約束。登録は呼ぶ側で明示する。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef


BELIEF = _ContractRef("sui.s4d.belief", "1")
PREFERENCE = _ContractRef("sui.s4d.preference", "1")
DECISION = _ContractRef("sui.s4d.decision", "1")

DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(ref=DECISION,
        meaning='Decidedのcontent={evaluation,items,style,H_ns,gamma,candidates,u,chosen,J,q_pi,expected_cost,information[,time]}。itemsはRecord.idの昇順の{id,rule:{name,version}}。styleはRecord.idかnull。候補ごとの配列はcandidatesと同じ順。inputs=(信念,付箋たち,紙)。白紙は1歩・gamma=1・外の費用0。モデルのlog_Cとgammaは読まない',
        unit='J・expected_cost・informationはnat、H_nsと時刻は整数ns',
        state_owner='sui.agent', persistence='考え始めた先端を親にする因果の出来事',
        failure='Jとexpected_costの+∞は文字列"+inf"。続きが未定義ならinformation=null。undefined_reasonは候補順の同長の配列で、未定義は"no_admissible_continuation"、ほかはnull。未定義が無ければ鍵ごと省く。全候補+∞や好みの読みの失敗は決定を残さず例外。数を表せない時は理由つきNumericalRangeで決定を残さない',
        cancel='なし', redelivery='親の先端・モデル・候補・uから再構築し全欄とinputsを照合。timeはS4cの使用する欄、deadline_nsは先読みだけ'),
    _Contract(ref=PREFERENCE,
        meaning='MODELが定めた好みの原記録。item={kind,rule:{name,version},args}、withdraw={kind,items:[PreferenceのRecord.id]}、style={kind,H_ns,gamma}。付箋は費用を足す。はがせるのは祖先の付箋だけ。紙はRecord.idの祖先グラフの末尾の強連結成分に残す',
        unit='H_nsは非負整数nsかnull、gammaは有限の非負数。P*は対数の確率',
        state_owner='sui.agent', persistence='因果の出来事。古い紙とはがした付箋も残す',
        failure='読めない本文・未知の約束・不正なwithdrawはPreferenceUnreadable。紙が複数残ればAmbiguousPreference。採用では印を保持し評価で例外にする',
        cancel='withdrawで祖先の付箋を名指す。本文の破棄をwithdrawとみなさない',
        redelivery='Record.idで一度。採用した範囲の実際の祖先関係から読み直す'),
    _Contract(ref=BELIEF,
        meaning='sui.model.4のPrediction target=belief。content={model,states,outcomes,q,a,n,unread,time,arrivals}。time={anchor,anchor_ns,clock_issues}。所要のNoneは永久に届かない見込みで、観測ではない。Qありは測定時刻順の対数濾過、Qなしは回数からS1cの信念。静的なanchorは起動。startは試みの記録の時刻、reportは受信時刻。到着は状態・行動と独立',
        unit='qは確率、anchor_nsは原点からns、arrivalsのbeta_sは秒', state_owner='sui.agent',
        persistence='台帳の葉。親の事実とモデルから全キーを再構築して照合',
        failure='説明不能はq=null。startの試みが軸にない観測はQありだけunread no_clock、Qなしは回数として読む',
        cancel='なし', redelivery='測定時刻の順に事実の集合から作り直す。未到着は信念を変えない'),
)
