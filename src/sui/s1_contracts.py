"""S1 の記録と一緒に運ぶ約束の宣言。登録は使う側で明示的に行う。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef

BELIEF = _ContractRef("sui.s1.belief", "3")
DECISION = _ContractRef("sui.s1.decision", "2")
ACTION = _ContractRef("sui.s1.action", "1")
OUTCOME = _ContractRef("sui.s1.outcome", "2")
ATTEMPT = _ContractRef("sui.s1.attempt", "1")


_BELIEF_DECLARATION = _Contract(
    ref=BELIEF,
    meaning='主体の信念の記録 (`Prediction`、target "belief")。content = {model, states, outcomes, q, a, n, unread}。states・outcomes は軸の名前と順。n[行動] = その行動で各観測を実際に見た回数 (int、全部の行動)。q = (生成モデル, n) から計算した状態の事後の確率。とても小さい確率は 0.0 と表示されうるが構造上の不可能ではない (不可能は D の 0 か、回数が正の升目にある事前の数え上げの 0 から決まる)。a[学ぶ行動] = 状態の仮説ごとの帳面 (列 k は「状態が k なら」の Dirichlet の数え上げ = 事前が正の升目にだけ回数を足したもの。事前の 0 は 0 のまま)、a[学ばない行動] = モデルの数え上げ。model は生成モデルの参照。unread は読めなかった観測 ID と理由の列。q は説明できない時には null。basis は ()、取り込んだ事実は点の親。n・q・a・unread は (モデル, 親から下の事実の集合) の関数で、読む順によらずぴったり作り直せる派生物。状態は時間で変わらない前提',
    unit='q は確率 (和 1)、a は Dirichlet の数え上げ、n は回数',
    state_owner='sui.agent (Producer.state の lineage・revision)',
    persistence='台帳の葉 (S2a メモリ、S2b 永続)',
    failure='記録を作れない時 (ID の発行・数値の失敗 FloatingPointError・台帳の拒否) は記録を作らず主体の状態も変えない。読めない観測は失敗ではなく unread に理由つきで残る。読めた観測の組がモデルのどの仮説でも説明できない時も失敗ではなく、q を null にした記録 (説明できない状態) を作る',
    cancel='取り消しはない (手放すは S8)',
    redelivery='同じ観測 ID の再配送では新しい信念の記録を作らない',
)


_DECISION_DECLARATION = _Contract(
    ref=DECISION,
    meaning='決定の記録 (`Decided`)。content = {candidates, risk, ambiguity, novelty, G, q_o, q_pi, gamma, u, chosen}。candidates は重複を除いて名前の昇順に並べた行動の名前で、ほかの配列はこの順。G = risk + ambiguity − novelty (1 回の観測の期待自由エネルギー)。q_o = 候補ごとの予測の観測分布。q_pi = softmax(−γG)。u は外から渡した [0, 1) の数で、chosen は q_pi の累積が初めて u を超える候補。inputs はその時の最新の信念の記録',
    unit='risk・ambiguity・novelty・G は nat、q_o・q_pi は確率、gamma は方策の確信度 (無次元)',
    state_owner='sui.agent',
    persistence='台帳 (S2a メモリ、S2b 永続)',
    failure='候補が空・知らない行動・型の誤り・信念の記録がない・説明できない状態 (ModelFalsified) の時は記録を作らず、状態を変えない',
    cancel='決定の取り消しはない。実行は仕事と試みの記録で別に',
    redelivery='主体が作る記録で、再配送の対象ではない',
)


_ACTION_DECLARATION = _Contract(
    ref=ACTION,
    meaning='仕事を開いた記録 (`JobOpened`) の content = {action}。action は決定で選ばれた行動の名前。仕事を開いたことは、実行したこと・成功したことを意味しない (実行の開始は試みの記録)',
    unit='行動の名前 (生成モデルの actions の 1 つ)',
    state_owner='台帳 (主体は仕事を読む)',
    persistence='台帳 (S2a メモリ、S2b 永続)',
    failure='決定と一緒に作り、記録を作れない時は台帳に足さない。採用: 形が違う・行動がモデルに無い仕事は読めない仕事になる',
    cancel='仕事の取り消しはない (S5)',
    redelivery='主体が作る記録で、再配送の対象ではない',
)


_OUTCOME_DECLARATION = _Contract(
    ref=OUTCOME,
    meaning='観測の記録 (`Observed`) の content = {outcome}。outcome は膜が受け取った観測の名前 (str、真の状態ではない)。caused_by は直接の結果として記録された試みの参照。None は対応が記録されていないことを表す',
    unit='観測の名前',
    state_owner='none (膜が受け取った事実。主体は読むだけ)',
    persistence='膜が受け取った時に台帳へ (推論の成否に関わらない。S2a メモリ、S2b 永続)',
    failure='受理 (台帳): 同じ ID で違う中身は IdConflict。それ以外は中身・約束の版に関わらず受け取る。採用 (主体の読み): 読めない観測は信念の記録の unread に理由つきで残り、学ばない',
    cancel='なし',
    redelivery='同じ ID は新しい点を作らない。同じ試みの別の ID の観測も事実として残る (読みは主体の ambiguous_attempt)',
)


_ATTEMPT_DECLARATION = _Contract(
    ref=ATTEMPT,
    meaning='試みを始めた記録 (`AttemptStarted`)。content は空の JSON オブジェクト {}。job が親の仕事を指す。始めたことだけを記録し、成功・完了は意味しない',
    unit='なし (content は空)',
    state_owner='none (膜が書く事実)',
    persistence='台帳 (S2a メモリ、S2b 永続)',
    failure='受理: 同じ ID で違う中身は IdConflict、それ以外は受け取る。採用: 中身が {} でない・仕事が読めない・約束の版が違う試みは読めない試みになり、その試みの観測は unreadable_attempt',
    cancel='なし (S5)',
    redelivery='同じ ID の試みを別の仕事に付け替えると IdConflict',
)


DECLARATIONS: tuple[_Contract, ...] = (
    _BELIEF_DECLARATION,
    _DECISION_DECLARATION,
    _ACTION_DECLARATION,
    _OUTCOME_DECLARATION,
    _ATTEMPT_DECLARATION,
)
