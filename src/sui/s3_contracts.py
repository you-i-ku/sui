"""S3 の事実の約束。登録は呼ぶ側で明示する (C1・W6・W7)。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef

ENDED = _ContractRef("sui.s3.ended", "1")
ABANDON = _ContractRef("sui.s3.abandon", "1")

DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(
        ref=ENDED,
        meaning='作用が結果なしに終わった膜の事実 (Observed)。content = {error}、error は例外の型名だけ。caused_by は試み、route は窓口が受け取った経路。資源を返し進行中から外すが、outcome としては学ばない',
        unit='例外の型の名前',
        state_owner='none (膜が受け取った事実)',
        persistence='台帳。書く前の記録はホストの Pledges に預ける',
        failure='書けなければ窓口を作り直し、同じ記録を書き直す',
        cancel='作用の停止を記す事実であって、取り消しの依頼ではない',
        redelivery='同じ記録の書き直しは点を増やさない。受け取り直しは同じ試みでも毎回新しい名札で残し、駆動に知らせる。資源は最初の結果だけで返る (P7)',
    ),
    _Contract(
        ref=ABANDON,
        meaning='待つのをやめた主体の決定 (Decided、MODEL)。content = {job}、job は仕事の参照の文字列、inputs = (仕事,)、親は主体の先端。進行中の予測から外す。手の作用を止めず、資源を返さず、順番待ちの仕事も撤回しない',
        unit='仕事の参照',
        state_owner='sui.agent (producer は決定時の主体)',
        persistence='台帳。書く前の記録はホストの Pledges に預ける',
        failure='書けなければ同じ記録で続ける。後から届いた結果は通常の事実として受け取る',
        cancel='待つのをやめるだけ。作用の取り消し・仕事の撤回は S5',
        redelivery='同じ ID は点を増やさない。進行中でない仕事への依頼は何も書かない',
    ),
)
