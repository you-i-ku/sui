"""S1 の記録と一緒に運ぶ約束の宣言。登録は使う側で明示的に行う。"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef

BELIEF = _ContractRef("sui.s1.belief", "2")
DECISION = _ContractRef("sui.s1.decision", "2")
ACTION = _ContractRef("sui.s1.action", "1")
OUTCOME = _ContractRef("sui.s1.outcome", "1")
ATTEMPT = _ContractRef("sui.s1.attempt", "1")


_BELIEF_DECLARATION = _Contract(
    ref=BELIEF,
    meaning='主体の信念の記録 (`Prediction`、target "belief")。content = {states, outcomes, q, a, n}。states・outcomes は軸の名前と順。n[行動] = その行動で各観測を実際に見た回数 (int、全部の行動)。q = (生成モデル, n) から計算した状態の事後の確率。とても小さい確率は 0.0 と表示されうるが構造上の不可能ではない (不可能は D の 0 か、回数が正の升目にある事前の数え上げの 0 から決まる)。a[学ぶ行動] = 状態の仮説ごとの帳面 (列 k は「状態が k なら」の Dirichlet の数え上げ = 事前が正の升目にだけ回数を足したもの。事前の 0 は 0 のまま)、a[学ばない行動] = モデルの数え上げ。q・a は同じモデルと n からぴったり作り直せる派生物。状態は時間で変わらない前提',
    unit='q は確率 (和 1)、a は Dirichlet の数え上げ、n は回数',
    state_owner='sui.agent (Producer.state の lineage・revision)',
    persistence='メモリの中の台帳だけ。保存と、作り直しに要るモデルの参照は未実装 (S2)',
    failure='起こりえない観測 (ModelViolation)・回数の範囲外 (ValueError)・数値の失敗 (FloatingPointError) の時は記録を作らず、主体の状態も変えない',
    cancel='取り消しはない (手放すは S8)',
    redelivery='同じ観測 ID の再配送では新しい信念の記録を作らない',
)


_DECISION_DECLARATION = _Contract(
    ref=DECISION,
    meaning='決定の記録 (`Decided`)。content = {candidates, risk, ambiguity, novelty, G, q_o, q_pi, gamma, u, chosen}。candidates は重複を除いて名前の昇順に並べた行動の名前で、ほかの配列はこの順。G = risk + ambiguity − novelty (1 回の観測の期待自由エネルギー)。q_o = 候補ごとの予測の観測分布。q_pi = softmax(−γG)。u は外から渡した [0, 1) の数で、chosen は q_pi の累積が初めて u を超える候補。inputs はその時の最新の信念の記録',
    unit='risk・ambiguity・novelty・G は nat、q_o・q_pi は確率、gamma は方策の確信度 (無次元)',
    state_owner='sui.agent',
    persistence='メモリの中の台帳だけ (S2)',
    failure='候補が空・知らない行動・型の誤り・信念の記録がない時は記録を作らず、状態を変えない',
    cancel='決定の取り消しはない。実行は仕事と試みの記録で別に',
    redelivery='主体が作る記録で、再配送の対象ではない',
)


_ACTION_DECLARATION = _Contract(
    ref=ACTION,
    meaning='仕事を開いた記録 (`JobOpened`) の content = {action}。action は決定で選ばれた行動の名前。仕事を開いたことは、実行したこと・成功したことを意味しない (実行の開始は試みの記録)',
    unit='行動の名前 (生成モデルの actions の 1 つ)',
    state_owner='sui.agent (開いた仕事の表)',
    persistence='メモリの中だけ (S2)',
    failure='決定と一緒に作り、決定を作れない時は作らない',
    cancel='仕事の取り消しはない (S5)',
    redelivery='主体が作る記録で、再配送の対象ではない',
)


_OUTCOME_DECLARATION = _Contract(
    ref=OUTCOME,
    meaning='観測の記録 (`Observed`) の content = {outcome}。outcome は生成モデルの outcomes の 1 つの名前で、観測した値 (真の状態ではない)。caused_by が主体の開いた試みを指す時だけ、その試みの行動の結果として読む (行動によらない観測の読み方は ROADMAP §2b P6、未実装)',
    unit='観測の名前',
    state_owner='none (膜が受け取った事実。主体は読むだけ)',
    persistence='メモリの中の台帳だけ。S1 の run_step は推論が成功した歩だけを台帳に書く (ROADMAP §2b P1 で S2 から改める)',
    failure='中身が約束の形でない時は ValueError、モデル上起こりえない観測は ModelViolation。どちらも主体の状態を変えない',
    cancel='なし',
    redelivery='同じ ID の再配送は無視、違う中身は IdConflict。同じ試みの 2 つ目の観測 (別の ID) は S1 では読まない (ROADMAP §2b P6 で改める)',
)


_ATTEMPT_DECLARATION = _Contract(
    ref=ATTEMPT,
    meaning='試みを始めた記録 (`AttemptStarted`)。content は空の JSON オブジェクト {}。job が親の仕事を指す。始めたことだけを記録し、成功・完了は意味しない',
    unit='なし (content は空)',
    state_owner='none (膜が書く事実)',
    persistence='メモリの中の台帳だけ (S2)',
    failure='中身が {} でない・知らない仕事・約束の版が違う時は拒み、試みを覚えない',
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
