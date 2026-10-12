"""関所 F v0.11 §3-10-12〜14 の契約データ。登録は呼出側が明示する。

参照名・版は正本に従う。登録だけで意味・証明・実行適合を認証しない。
CONTENTS_CODEC は予約名のみであり DECLARATIONS に登録しない。物理形式は S2b。
組み込み能力の七欄の表は、CapabilityDeclaration を持つ f.py のデータに置く。
能力条件や宣言の登録だけを数学・実行の認証として扱わない。
"""

from .contracts import Contract as _Contract, ContractRef as _ContractRef


FINITE_MODEL = _ContractRef("sui.f.finite_model", "1")
SOFT_CHOICE = _ContractRef("sui.f.soft_choice", "1")
MEASUREMENT = _ContractRef("sui.f.measurement", "1")
MEASUREMENT_RUN = _ContractRef("sui.f.measurement_run", "1")
ROUTE_CONFIG = _ContractRef("sui.f.route_config", "1")
COVERAGE = _ContractRef("sui.f.coverage", "1")
DRAW = _ContractRef("sui.f.draw", "1")
DECISION_ATTEMPTED = _ContractRef("sui.f.decision_attempted", "2")
BELIEF = _ContractRef("sui.f.belief", "1")
EVALUATION = _ContractRef("sui.f.evaluation", "2")
DECISION = _ContractRef("sui.f.decision", "2")
JOB = _ContractRef("sui.f.job", "1")
COMPUTATION = _ContractRef("sui.f.computation", "1")
RESERVATION = _ContractRef("sui.f.reservation", "1")
REFINEMENT = _ContractRef("sui.f.refinement", "2")

# §3-10-12-2 で採用した部品の参照。
PREDICATE = _ContractRef("sui.f.predicate", "1")
CANDIDATE_SET = _ContractRef("sui.f.candidate_set", "1")
EVIDENCE_HISTORY = _ContractRef("sui.f.evidence_history", "1")
ROOT = _ContractRef("sui.f.root", "2")
CERTIFICATE = _ContractRef("sui.f.certificate", "1")
DRIVE = _ContractRef("sui.f.drive", "1")
STATUS = _ContractRef("sui.f.status", "1")
RESUME_POINT = _ContractRef("sui.f.resume_point", "1")
CONTENTS_CODEC = _ContractRef("sui.f.contents_codec", "1")
PROBLEM = _ContractRef("sui.f.problem", "2")
VALUE = _ContractRef("sui.f.value", "2")
PREPARE_WORLD = _ContractRef("sui.f.prepare_world", "1")
OBSERVATION_PLAN = _ContractRef("sui.f.observation_plan", "1")
OBSERVATION_BINDING = _ContractRef("sui.f.observation_binding", "1")
STYLE = _ContractRef("sui.f.style", "1")
FIRING = _ContractRef("sui.f.firing", "1")
LIMIT_PROBLEM = _ContractRef("sui.f.limit_problem", "1")
LIMIT_CERTIFICATE = _ContractRef("sui.f.limit_certificate", "1")


DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(ref=PREPARE_WORLD,
        meaning="到達する参照・E/K・候補・時間過程を共通 compiler で解決し不変の FCertifiedWorld を発行する",
        unit="元の宣言の単位。budget は実行制限",
        state_owner="世界の発行元",
        persistence="要求・必要依存 snapshot・world_key。実装のメモリー上のアドレスを保存しない",
        failure="不正・意味不足・能力不足・証明不足・予算切れを区別し未認証の世界を発行しない",
        cancel="入力変更は別世界。既存の世界へ後着事実を混ぜない",
        redelivery="保存から同じ compiler で再構築し manifest 全体を照合する"),
    _Contract(ref=FINITE_MODEL,
        meaning="model.10 の共同生成法則・操作・実行中の方針・ψ。静的有限対象、既知測定、有限初手、明示後続の認証範囲を保持する",
        unit="確率は既約R、実時計と所要はns、情報と費用はnat",
        state_owner="モデルの宣言",
        persistence="正準bytesとdigest、実装と証明の参照を保持。更新は別版でありmodel.1〜9を移行しない",
        failure="不正入力FInputError。意味不足FSpecificationMissing。認証能力の不足を不正入力にしない。未知版を推測しない",
        cancel="宣言の更新は別版。既存の根の意味を変えない",
        redelivery="同じ正準宣言を再読して意味を変えない"),
    _Contract(ref=SOFT_CHOICE,
        meaning="有限木の各選択節で同じ評価のsoftmaxを取り、後続Jをその確率で平均する。全路のsoftmaxやsoft minimumへ替えない",
        unit="基準質量と確率は無次元、Jはnat、gammaは無次元",
        state_owner="根に固定した方策の宣言",
        persistence="操作順・基準測度・評価範囲・好み・版を根に保存。無限回の再選択は未認証",
        failure="Zの正の下端と有限上端が未証明なら未完了。未認証候補を除いて正規化しない",
        cancel="集合変更は別問題。確定した意思の取消は別操作",
        redelivery="同じ根の再開と精密化は候補順とselection drawを保持"),
    _Contract(ref=PREDICATE,
        meaning="K/Eに対する三値の条件。状態型・依存・検査法・認証範囲を版とともに保持",
        unit="真・偽・Unknown。時刻は時計領域付きns",
        state_owner="選んだ方針。重い検査は計算の仕事",
        persistence="述語の引数と閾値のprovenance、方針の世代と発火IDを保存。方針変更で明示的に置換",
        failure="UnknownをFalseにしない。未計算の検査はPredicateWorkへ渡す",
        cancel="選んだ方針の置換と作用の取消を区別",
        redelivery="同じ方針の世代・発火は一度。観測していない成立時刻を作らない"),
    _Contract(ref=CANDIDATE_SET,
        meaning="比較する操作、順序、別名対応、基準質量、生成器と根拠を固定",
        unit="候補の質量と正規化定数は無次元",
        state_owner="根",
        persistence="候補・順序・測度・生成根拠・用途別drawを保存。集合の変更は別問題",
        failure="未認証候補を消さない。測度なしcandidate_measure_missing、Z未証明normalization_unproved",
        cancel="除外は開始不能または許容不能の検査可能な証明を要する",
        redelivery="同じ意味の表示別名で質量を増やさない。再開で同じ集合"),
    _Contract(ref=EVIDENCE_HISTORY,
        meaning="Eは実測・被覆・欠落の生成関係。MeasurementIdは実測機会を識別し本文ハッシュではない",
        unit="測定連番は整数、時刻は時計領域付きns",
        state_owner="膜の原記録",
        persistence="原記録・生成元・派生元と契約の参照を保存。本文と塩はS2bに保持",
        failure="同じIDの生成内容の衝突はFInputError(measurement_conflict)。本文欠落を0や空へ替えない",
        cancel="配送を取り消しても実際の測定事実は消さない",
        redelivery="同じ測定の再配送は情報を増やさない。別機会の同値は別測定"),
    _Contract(ref=MEASUREMENT,
        meaning="Observed・MEMBRANEのMeasurementFrame。実測機会、区間、実時刻、値、quality、gap、cursorの全欄",
        unit="連番は整数、時計領域とns。値とqualityは宣言単位",
        state_owner="膜・経路実装",
        persistence="生の全欄をS2bの本文へ可逆保存。生成契約と測定IDを保持。ヘッダーへ生フレームを逃がさない",
        failure="欠測・被覆未証明を測って0または同値の繰り返しにしない",
        cancel="測定事実は配送取消で消えない。手放す方針はS8",
        redelivery="測定IDを保持し、配送の分割でE/Kを変えない"),
    _Contract(ref=MEASUREMENT_RUN,
        meaning="Observed・MEMBRANEの実測列の可逆Run。RefKind.RUNの時計runとは別型",
        unit="連番は整数、各欄の時計領域とnsを保持",
        state_owner="膜・経路実装",
        persistence="列・例外・欠番・時刻のずれ・quality・cursorを保存。旧記録の塊への置換移行は別契約",
        failure="予定の刻みから実測時刻を復元しない。expand(pack(frames))は全欄一致を要する",
        cancel="配送取消で原測定を消さない",
        redelivery="配送を一塊にしても測定ID・E/K・抽選数は不変"),
    _Contract(ref=ROUTE_CONFIG,
        meaning="Observed・MEMBRANEのRouteApplied。configにRouteConfig、実適用時刻・実行・根拠を保存。bootstrapと選択による設定変更を区別",
        unit="適用時刻は時計領域付きns、設定値は各契約の単位",
        state_owner="膜・経路実装",
        persistence="設定の版と測定・時計・欠損契約を保持。selectedは意思と実行記録を参照。提案と有効化を分ける",
        failure="適合未認証を成功にしない。測る単位・配送単位・ψ検査時機を混同しない",
        cancel="変更の意思と実行結果を別記録にする",
        redelivery="同じ実行結果を再利用し、配送分割で意味を変えない"),
    _Contract(ref=COVERAGE,
        meaning="Observed・MEMBRANEのCoverageClaim、Gap、MeasurementUnavailable、CoverageUnproved",
        unit="測定列の連番と時計領域付きns区間",
        state_owner="膜・経路実装",
        persistence="被覆のkind・契約・根拠を保存。欠測と完全性未証明を別に保持",
        failure="見張り役の生存を実測列の完全性としない。閉じた区間や停止中を無到着の測定にしない",
        cancel="取消でも既存の被覆・欠落の事実を消さない",
        redelivery="原記録の生成関係を検査し同じ証拠を二度加えない"),
    _Contract(ref=DRAW,
        meaning="Observed・MEMBRANEの用途別DrawRecord。selectionは候補固定後に取得する専用のu",
        unit="selection uは0以上1未満の既約R。他用途の値は生成器の契約",
        state_owner="ホストの預かりと台帳",
        persistence="ID・用途・生成器の版・context_key・ordinal・値を保存。実際の抽選の事実であり世界の測定ではない",
        failure="候補生成・予約・計算法の乱数をselectionへ使い回さない。境界を引き直しで回避しない",
        cancel="取消後も既抽選の事実は残る",
        redelivery="同じ受付・精密化・再開・replayは保存したdrawを使い、新しく引かない"),
    _Contract(ref=BELIEF,
        meaning="Prediction・MODELのE/K、反映範囲、共同核、正規化、照会の証明。Kのavailableとincorporatedは別",
        unit="共同確率はR、情報はnat、時刻は時計領域付きns",
        state_owner="F専用の主体状態",
        persistence="モデル・版・原記録・生成関係から再構築。古い結果は対象範囲を付けて保持。十分な核と生の層を分ける",
        failure="未計算を完全な信念にしない。核の現行性は正規化や照会の認証を含意しない",
        cancel="Supersedeでも証拠と引き受けを失わない",
        redelivery="測定集合と依存を検査し、再配送と再反映で同じ証拠を二度加えない"),
    _Contract(ref=ROOT,
        meaning="同じ問い・候補・continuation・測度・E/K・モデル・好み・範囲・時刻・方法とselection drawを固定したFRoot",
        unit="gammaは無次元、時刻は時計領域付きns",
        state_owner="不変の入力と係の派生物",
        persistence="開始時の事実集合と台帳の親に結び付ける。problem_keyに予算や表示桁を含めない",
        failure="根違い・別問題のdrawを拒否。後から来た事実を凍結入力へ混ぜない",
        cancel="新着だけで元の根を無効化しない。確定した選択の取消は別操作",
        redelivery="同じ問題の精密化・再開はproblem_key、root_key、uを保持"),
    _Contract(ref=CERTIFICATE,
        meaning="凍結した問いと抽選に対する数学の保証。式・区間・尾・trace・版・実行予算を保持",
        unit="情報・費用・G/Jはnat、確率と残余質量は無次元",
        state_owner="不変の入力と係の派生物",
        persistence="元の根と方法・arithmetic・入力digestを固定。尾と費用は独立に保証。方法変更は別証明系列",
        failure="自己申告のproofを信用しない。未認証を0にせず、発散と計算失敗を区別。∞−∞を相殺しない",
        cancel="確定した決定を追加精密化で変更しない",
        redelivery="同じ根と保存した版・traceから検査。表示の近似値を選択へ戻さない"),
    _Contract(ref=EVALUATION,
        meaning="Prediction・MODELのFEvaluation。expected_cost、already_received、additional、総情報、G/J、q_star、累積区間と尾",
        unit="情報と費用とG/Jはnat、確率とZは無次元",
        state_owner="係の不変結果",
        persistence="FRootと保証・残りを保存。O0を一度保持し、計算だけではEに測定を追加しない",
        failure="尾未証明や予算切れは未完了。全路でない部分列を全列挙と呼ばない。費用未証明を0にしない",
        cancel="新着だけで元の根の結果を捨てない",
        redelivery="同じ問いの保証を保存。後続softmax平均と共同信念を保持して再計算"),
    _Contract(ref=DECISION_ATTEMPTED,
        meaning="Observed・MEMBRANEの評価試行。startedとfinishedは別Record.idで同じattempt_id。NoDecisionは選択ではない",
        unit="理由・参照と時計領域付き受信時刻ns",
        state_owner="ホストの預かり、膜の記録",
        persistence="startedを保存してから仕事を配送。finished selectedは実際のDecided参照、それ以外はNoDecisionの理由",
        failure="保存故障は元の例外を保つ。未完了・拒否・故障を区別。偽のDecidedやJobOpenedを作らない",
        cancel="NoDecisionを静けさの選択や作用の取消にしない",
        redelivery="同じ終了記録を再試行しIDを作り直さない"),
    _Contract(ref=DECISION,
        meaning="Decided・MODELのFDecisionContent。root、候補、draw、値、Z、尾、selection、intent、certificate、display=null",
        unit="natと確率の有理数保証、selection uはR",
        state_owner="主体とホスト",
        persistence="検査した意思と証明を保存してから配送。凍結した親、候補順、測度、u、traceを再現",
        failure="previous.upper <= u < current.lowerまたは証明した境界等値を要する。改ざんFReplayMismatch、根拠欠落FReplayUnavailable",
        cancel="作用失敗と評価失敗を区別。意思の取消は別操作",
        redelivery="同じCommitを再利用。後の事実や新しい予算・計算法で決定を書き換えない"),
    _Contract(ref=JOB,
        meaning="JobOpened・MODELの選ばれた操作とroot_key。操作・対象・引数を選択証明と一致させる",
        unit="操作の実行契約に従う。時刻は時計領域付きns",
        state_owner="主体とホストの引き受け",
        persistence="意思を保存してから配送。本文→点、親→子の保存順。未完の引き受けを預かる",
        failure="作用失敗と評価失敗を区別。旧Hand.execute(str)へ操作を文字列化しない",
        cancel="取消の意思と実行結果を別に扱い、awaitingや実資源を推定で消さない",
        redelivery="同じCommitと仕事IDを再利用。プロセスをまたぐ実行復旧はS5"),
    _Contract(ref=DRIVE,
        meaning="不変snapshotから有限のDriveReplyを返す。変更の返事は一致するSelectedを持つ",
        unit="返事・参照、世代と発火ID",
        state_owner="方針の世代はホスト",
        persistence="有限列を最後まで受けて一括登録。依存・内発・現方針・進行中・比較候補の根拠を保持",
        failure="react中でderive、G、証明再生、ディスク走査をしない。generator例外で半分の作用を登録しない",
        cancel="旧の明示的な互換入口と新FのSelected要求を区別",
        redelivery="同じ知らせを再通知しうる。同じ発火とreply_indexの受付とdrawを再利用"),
    _Contract(ref=STATUS,
        meaning="受信・永続化・組み込み・正規化・照会・残りを分ける読み取り専用snapshot",
        unit="件数・参照と時計領域付きns",
        state_owner="値は各所有者からの不変の写し",
        persistence="取得済みのキャッシュを返す。未取得値はUnavailable。取得を契機に時計・推論・抽選を進めない",
        failure="未計算を0やFalseへ替えない。kernel_currentはposterior認証を含意しない",
        cancel="状態取得は作用を起こさない",
        redelivery="取得回数で計算や抽選数を変えない。旧8欄の名前と意味を保持"),
    _Contract(ref=COMPUTATION,
        meaning="Observed・MEMBRANEのwork_id、状態遷移、根、理由、再開地点。実行予算は好みではない",
        unit="実行予算、参照と時計領域付きns。生のCPUや電力をnat費用へ換算しない",
        state_owner="係の不変結果とホストの預かり",
        persistence="根と検査済み入力・結果のdigestを結び付ける。書くSQLite接続や可変主体を係へ渡さない",
        failure="paused_runtimeと本人が選んだsuspendedを区別。予期しないPython例外を数学の結論へ変換しない",
        cancel="Supersedeでも証拠・引き受け・確定選択を失わない",
        redelivery="同じ仕事と凍結入力を保持。感覚と他の引き受けを止めない"),
    _Contract(ref=RESERVATION,
        meaning="Observed・MEMBRANEの将来の約束の登録・満了・取消結果・送出・確認。操作に含まれる予約を保持",
        unit="予定・検出・実行は別々の時計領域付きns",
        state_owner="ホストのPledgesと経過の記録",
        persistence="意思を保存してから配送。実行後は新しい記録を追加しReservationDueを上書きしない",
        failure="別run期限はclock_unaligned。送出済み作用を取消済みと推定しない。実行適合未認証はunverified",
        cancel="窓口が採用した取消と満了の因果順、送出前後を記録",
        redelivery="同じ発火IDと抽選を使用。満了は新しいGや周期Tickではない。再起動の実行復旧はS5"),
    _Contract(ref=RESUME_POINT,
        meaning="同じ根・方法・arithmeticの作業途中。traceと状態digest、前の証明を保持",
        unit="実行予算と不変の再開状態",
        state_owner="係の不変結果とホストの預かり",
        persistence="同一プロセスの再計算・再開を固定。checkpoint内部配置はF-c前に確定。実行復旧はS5",
        failure="別根へcheckpointを流用しない。予算を評価範囲や本人の好みにしない",
        cancel="PauseとSuspendを区別。Supersedeで証拠と引き受けを失わない",
        redelivery="同じ根・候補・測度・uを保持して再開"),
    _Contract(ref=REFINEMENT,
        meaning="Prediction・MODELの元の根・決定・証明と追加の保証。診断精密化は元の意思を変更しない",
        unit="元の評価と同じnat・確率・保証区間",
        state_owner="係の不変結果",
        persistence="元の根と決定、前の証明を参照する追加記録。方法変更は別系列との関係を明示",
        failure="根・入力・版・保証の不一致を拒否。未認証を追加保証と呼ばない",
        cancel="元の確定した決定やdrawを変更しない",
        redelivery="同じ精密化の記録を再利用。世界の新しい測定としてEへ加えない"),
    _Contract(ref=PROBLEM,
        meaning="drawを除く凍結FProblem。候補・continuation・測度・原記録・E/K・好み・範囲・モデル・方法を先に固定",
        unit="gammaは無次元、時計領域付きns",
        state_owner="評価係の不変入力",
        persistence="版・digestと資源の原記録を保存。予算・再開・表示桁を問題に含めない",
        failure="手作り/構造復号を認証にしない。意味不足と能力不足を分ける",
        cancel="新事実は別問題。既存問題を変えない",
        redelivery="同問題を再利用しdrawは問題固定後に結合"),
    _Contract(ref=VALUE,
        meaning="公開補助型の全欄の往復。{type:公開型名,value:全欄}、動的import禁止",
        unit="各欄の契約の単位",
        state_owner="構造値を渡す呼出側",
        persistence="正準UTF-8 JSON。型名は公開allow-list。全欄・和型・構造キーを明示",
        failure="構文/型/版はFInputError。復号をproofや外部参照の認証にしない",
        cancel="保存された構造を取消で改変しない",
        redelivery="同正準bytesを再読。ハンドルの認証はfactoryで再検査"),
    _Contract(ref=OBSERVATION_PLAN,
        meaning="Prediction・MODELの原値/時刻射影と有限kernelの観測セル・outcome群の予測宣言",
        unit="時間射影は時計契約、確率はR",
        state_owner="モデルの予測宣言",
        persistence="model_ref・測定契約・生成契約・kernel版・全セルを保存",
        failure="対応欠落はFSpecificationMissing(observation_binding_missing)。矛盾はFInputError(observation_binding_mismatch)",
        cancel="取消で原記録の予測宣言を上書きしない",
        redelivery="同宣言を再利用。同観測に写る隠れたoutcomeを二観測にしない"),
    _Contract(ref=OBSERVATION_BINDING,
        meaning="Observed・MEMBRANEのPlanと実生成機会/step/slot・測定IDの対応",
        unit="生成機会のRef・整数step・実測連番",
        state_owner="膜の生成記録",
        persistence="原記録・plan・生成元・派生元を保存。生の測定と予測を分ける",
        failure="欠落と不一致を分け、証拠質量0はFModelFalsified(zero_evidence)",
        cancel="取消しても受信済み証拠を消さない",
        redelivery="同機会は一回。派生要約/再配送の尤度を二度掛けない"),
    _Contract(ref=STYLE,
        meaning="FStyleのscope/gamma。旧紙・F紙・白紙をFResolvedへ因果的に解決",
        unit="gammaは無次元R、Hはns",
        state_owner="好みの宣言と凍結問題",
        persistence="styleのRefをsourceとして保存。旧gammaはfloatの二進有理数を保持",
        failure="整合しないstyleはFSpecificationMissing。無限路費用の未証明はFIncomplete(cost_certificate)",
        cancel="既存の因果的current/取消規則を保持",
        redelivery="同じ紙の再読で好みを変えない。白紙はunbounded_total/gamma=1"),
    _Contract(ref=FIRING,
        meaning="方針世代・firing_id・reply_index・出どころ・検出時計で同発火を受け付ける",
        unit="時計領域付きnsと参照",
        state_owner="F-aは同一プロセスのFiringBook、F-bはFPledges",
        persistence="FiringReceiptにrequest/problem/root/draw/workの対応を保持",
        failure="同キーのdraw法則/引数の衝突はFInputError(draw_request_conflict)。検出時刻を成立時刻としない",
        cancel="途中例外や取消で既取得drawを消さない",
        redelivery="同発火の100配送でも最初のreceipt/root/uを再利用"),
    _Contract(ref=LIMIT_PROBLEM,
        meaning="独立公平ビットの全列情報と白紙/prefix log-lossの負の極限診断",
        unit="情報と費用はnat、prefixは整数",
        state_owner="検査用の数学宣言",
        persistence="過程・観測・対象・費用・範囲・proofの全欄",
        failure="model.10/選択の入口にしない。誤proofはFInputError(proof_mismatch)、証明不足はFIncomplete(certificate_incomplete)",
        cancel="取消から費用や情報の極限を推定しない",
        redelivery="同問題の診断を再現。有限prefixの反復から発散を捏造しない"),
    _Contract(ref=LIMIT_CERTIFICATE,
        meaning="検査器の版・問題digest・情報/費用の厳密列と別々の極限を保持",
        unit="情報と費用はnat、ExactSequenceの係数は厳密式",
        state_owner="検査係の数学結果",
        persistence="iid_bits_limit/1の条件とinformation_divergent/undefined_infinite_differenceを保存",
        failure="登録だけで証明しない。無限差を相殺しSelectedを返さない",
        cancel="取消で未証明を0や証明済みにしない",
        redelivery="同宣言/版の証明を検査し、構造復号を認証にしない"),
)


# v0.13 §3-10-16: primary facts and mathematical rereading. The model.10
# constants/declarations above retain their original versions and meanings.
FINITE_MODEL_V2 = _ContractRef("sui.f.finite_model", "2")
KNOWLEDGE_ORIGIN = _ContractRef("sui.f.knowledge_origin", "1")
CONTENT_ACQUIRED = _ContractRef("sui.f.content_acquired", "1")
COMPUTATION_REQUESTED = _ContractRef("sui.f.computation_requested", "1")
COMPUTATION_RESULT = _ContractRef("sui.f.computation_result", "1")
COMPUTATION_PROOF = _ContractRef("sui.f.computation_proof", "1")
COMPUTATION_COMPLETED = _ContractRef("sui.f.computation_completed", "1")
KNOWLEDGE_ADOPTED = _ContractRef("sui.f.knowledge_adopted", "1")
CLOCK_READING = _ContractRef("sui.f.clock_reading", "1")
CONTEXT_OBSERVED = _ContractRef("sui.f.context_observed", "1")
MODEL_SOURCE = _ContractRef("sui.f.model_source", "1")
CANDIDATE_DECLARATION = _ContractRef("sui.f.candidate_declaration", "1")
DRAW_FACT = _ContractRef("sui.f.draw_fact", "1")
MEASUREMENT_REQUESTED = _ContractRef("sui.f.measurement_requested", "1")
MEASUREMENT_JOB = _ContractRef("sui.f.measurement_job", "1")
LIMIT_DECLARATION = _ContractRef("sui.f.limit_declaration", "1")
QUANTITY_DECLARATION = _ContractRef("sui.f.quantity_declaration", "1")
MATH_ARTIFACT = _ContractRef("sui.f.math_artifact", "1")
MATH_VERIFICATION = _ContractRef("sui.f.math_verification", "1")
FINITE_UPDATE = _ContractRef("sui.f.finite_update", "1")
FINITE_UPDATE_RESULT = _ContractRef("sui.f.finite_update_result", "1")
FINITE_UPDATE_STATEMENT = _ContractRef("sui.f.finite_update_statement", "1")
FINITE_UPDATE_REPLAY = _ContractRef("sui.f.finite_update_replay", "1")

# Digest domains, not body Contracts or registered capability implementations.
KNOWLEDGE_DEPENDENCY_DOMAIN = "sui.f.knowledge_dependency/1"
CANDIDATE_REQUEST_DOMAIN = "sui.f.candidate_request/1"


def _facts_contract(ref, meaning, unit, owner):
    return _Contract(ref=ref, meaning=meaning, unit=unit, state_owner=owner,
        persistence="版と全欄を正準化。Pointは実CID/header/seal/Record bytesで照合し、Refや派生欄の自己申告を認証にしない",
        failure="不正・改変・必須本文欠落・意味不足・能力不足・予算不足を区別。登録や構造復号は検査済みを意味しない",
        cancel="一次記録を上書きしない。新入力は別問題、取消から未観測や数学的結論を作らない",
        redelivery="同じ固定入力と方法を再読。配送と測定を区別し、後着事実や現在の能力を過去へ継ぎ足さない")


FACTS_DECLARATIONS: tuple[_Contract, ...] = tuple(_facts_contract(*row) for row in (
    (FINITE_MODEL_V2, "model.11の一次操作宣言。semantic_keyは要求せずcompiler内で生成する。model.10/旧bytesとは別版", "確率R、ns、nat", "一次モデル宣言"),
    (KNOWLEDGE_ORIGIN, "Observed/MEMBRANE/FACT。モデルの宣言された初期状態から知識系列を開始。checkpointではない", "モデルPoint", "膜の一次記録"),
    (CONTENT_ACQUIRED, "Observed/MEMBRANE/FACT。指定系列による内容取得。availableのみを進め、取得を採用としない", "origin/contents/clockのPoint", "膜の一次記録"),
    (COMPUTATION_REQUESTED, "Decided/MODEL/FACT。目的・方法・args・全入力・算法draw・結果契約を固定した要求", "Pointと閉じたargs契約", "計算を要求した記録"),
    (COMPUTATION_RESULT, "Prediction/MODEL/PREDICTION。要求に対応する結果の主張で、新しい実測でも認証済み信念でもない", "output契約で固定", "計算結果の主張"),
    (COMPUTATION_PROOF, "Prediction/MODEL/PREDICTION。要求/結果/役割/statement/checkerを結合した検査可能な証明の主張", "statement契約で固定", "証明の主張"),
    (COMPUTATION_COMPLETED, "Observed/MEMBRANE/FACT。指定結果と証明が生成された出来事。取得・採用とは区別", "Pointと開始/終了の時計Point", "膜の一次記録"),
    (KNOWLEDGE_ADOPTED, "Decided/MODEL/FACT。取得と証明の検査を伴う採用系列。previousと導出の入力を照合し競合を勝手に選ばない", "origin/previous/completionのPoint", "採用した記録"),
    (CLOCK_READING, "Observed/MEMBRANE/FACT。ClockSourceとrun/time_nsの実際の読み。Record.atへ置換しない", "時計領域付きns", "膜の一次記録"),
    (CONTEXT_OBSERVED, "Observed/MEMBRANE/FACT。系列・観測時計・判断時計・順序付き検査出来事から文脈を導く。Tickを追加しない", "Pointと時計領域付きns", "膜の一次記録"),
    (MODEL_SOURCE, "Prediction/MODEL/PREDICTION。モデル宣言document全体。宣言の内容hashと台帳Pointを区別", "モデル宣言の単位", "一次モデル宣言"),
    (CANDIDATE_DECLARATION, "Prediction/MODEL/PREDICTION。操作ID入力順・測度・生成器/args/basis/draw・正準化前continuation", "候補の基準質量は無次元", "一次候補宣言"),
    (DRAW_FACT, "Observed/MEMBRANE/FACT。生成器/stream/request/valueを固定。選択は問題固定後のPointを別範囲で読む", "宣言されたlaw。選択uは既約R", "膜の一次抽選記録。実消費はF-b"),
    (MEASUREMENT_REQUESTED, "Decided/MODEL/FACT。plan Pointとstepで観測を要求。Selectedや選択証明を偽造しない", "plan Pointと整数step", "観測生成の一次記録"),
    (MEASUREMENT_JOB, "JobOpened/MODEL/FACT。plan Point/step、body.decisionは実要求。開始は既存AttemptStarted", "plan Pointと整数step", "観測生成の一次記録"),
    (LIMIT_DECLARATION, "Prediction/MODEL/PREDICTION。既存FLimitProblemの全欄。無限過程を有限モデルへ偽装しない", "既存の極限宣言の単位", "一次極限宣言"),
    (QUANTITY_DECLARATION, "Prediction/MODEL/PREDICTION。定数/provenanceまたは数学結果Pointへの照会。存在/取得だけで区間を保証しない", "natまたはdimensionless", "一次数量照会宣言"),
    (MATH_ARTIFACT, "一次入力・不変reader/registry像・型付き数学手順/保存予算・全出力を結合する正準の包み", "対応する数学出力の単位", "数学のfactory。実保存/試行はF-b"),
    (MATH_VERIFICATION, "数学artifactを一次事実から再構築し全bytes一致後に発行。実試行/受付/保存成功/乱数消費を証明しない", "入力/結果/artifact/各callのdigest", "数学検査factory"),
    (FINITE_UPDATE, "モデル/previous_result/観測Bindingからの決定的有限更新。全入力閉包を検査しalgorithm_drawsは空", "jointと証拠質量は既約R", "数学の更新方法"),
    (FINITE_UPDATE_RESULT, "有限更新のjointとevidence_mass全欄。自己申告値を採用せず核の合算から再計算", "無次元の既約R", "数学結果の主張"),
    (FINITE_UPDATE_STATEMENT, "有限更新のmodel/request/result Pointを結合したnormalization statement", "Point", "数学的statement"),
    (FINITE_UPDATE_REPLAY, "初期/検査済みprevious_resultから再計算しjoint/証拠質量を照合。同transitionは一度だけ適用", "確率は既約R", "数学の検査器"),
))

# Registration remains explicit. No implementations are installed by this data.
LEGACY_DECLARATIONS = DECLARATIONS
DECLARATIONS = LEGACY_DECLARATIONS + FACTS_DECLARATIONS

# Scope labels only; old contract data/versions are not silently rewritten.
F_B_CONTRACT_REFS = (DECISION_ATTEMPTED, DECISION, JOB, COMPUTATION, RESERVATION,
                    REFINEMENT, FIRING, DRIVE, STATUS)


# v0.14 supplement. Keep math_artifact/1 and quantity/1 meanings unchanged.
MATH_ARTIFACT_V2 = _ContractRef("sui.f.math_artifact", "2")
PREFLIGHT_FACTS = _ContractRef("sui.f.preflight_facts", "1")
QUANTITY_FACTS_PROOF = _ContractRef("sui.f.quantity", "2")
QUANTITY_POINT_DOMAIN = "sui.f.quantity_point/1"
LEGACY_BRIDGE_V2 = _ContractRef("sui.f.legacy_bridge", "2")
LEGACY_BRIDGE_FACTS = _ContractRef("sui.f.legacy_bridge_facts", "1")
SUPPLEMENT_DECLARATIONS: tuple[_Contract, ...] = tuple(_facts_contract(*row) for row in (
    (MATH_ARTIFACT_V2, "共通facts compilerの包みv2。preflightの実行budget、legacy_bridge入力・op・claimを追加。v1を書き換えない", "対応する数学出力の単位", "数学factory"),
    (PREFLIGHT_FACTS, "内部生成FPreflightFactsAuditを出力する証拠。全件検査/不変像の捕捉前に可否を発行しない", "request/記録digestと能力可否", "preflight数学factory"),
    (QUANTITY_FACTS_PROOF, "ProofRef args={binding:FQuantityFactsBinding}。実数量宣言Point/Record digestから内部キーを作り量・単位・評価・依存を照合", "natまたはdimensionless", "数量認証factory"),
    (LEGACY_BRIDGE_V2, "旧モデル一次factsから比較問題を固定し後のdrawで旧新数学を比較。旧公開adoptを呼ばず書込み/ID/時計取得なし", "既存の橋の単位・認証範囲", "旧橋の数学factory"),
    (LEGACY_BRIDGE_FACTS, "LegacyComparison.assumptionsの出力対応。request/軸/所要/report測定/scope/O0周辺化/実draw/uを全欄結合", "ns、nat、既約u", "旧橋compilerの出力"),
))
DECLARATIONS = DECLARATIONS + SUPPLEMENT_DECLARATIONS

# The primary compiler is a distinct version; legacy prepare_world/1 stays put.
# 今の約束 E-05: prepare_world/3 (world_manifest/3, problem/3, root/3).
PREPARE_FACTS = _ContractRef("sui.f.prepare_world", "3")
PROBLEM_FACTS = _ContractRef("sui.f.problem", "3")
ROOT_FACTS = _ContractRef("sui.f.root", "3")
WORLD_MANIFEST_FACTS = _ContractRef("sui.f.world_manifest", "3")
# 今の約束 E-05: VALUE/3 decodes with the compiler/3 type list ({type,value}).
VALUE_FACTS = _ContractRef("sui.f.value", "3")
DECLARATIONS = DECLARATIONS + tuple(_Contract(ref=ref,
    meaning=meaning,unit="CID / canonical bytes",state_owner="sui.f",
    persistence="Retain primary facts and mathematical calls; decoding is not issuance",
    failure="Missing input / mismatching bytes / incomplete certification stay distinct",
    cancel="none",redelivery="Rebuild from the same primary closure") for ref,meaning in (
        (PREPARE_FACTS,"Facts-only compiler; derive histories, context and canonical declarations"),
        (PROBLEM_FACTS,"Certified primary-input problem, before a selection draw"),
        (ROOT_FACTS,"Certified primary-input problem bound to draw CID and content digest")))
