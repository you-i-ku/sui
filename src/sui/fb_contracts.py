"""関所 F の F-b の新しい契約の名札 (紙 F-b v0.25 §2-5-3・§2-5-9・§2-5-19・§6)。

段 0 は名前と版だけ。V-08 と同じ全欄 (meaning・unit・state_owner・persistence・failure・
cancel・redelivery) と Body/Role/Category の宣言は、その契約を使う段で足す。既存の契約の
意味は変えない (旧 `/1` も変えない)。
"""

from .contracts import ContractRef as _ContractRef

# 入れ子の値契約 (Boot の中、§2-5-3。独立 Record ではない)
SEATS = _ContractRef("sui.fb.seats", "1")
RESOURCE_SCOPE = _ContractRef("sui.fb.resource_scope", "1")
ALLOCATION = _ContractRef("sui.fb.allocation", "1")
# /2 (§6-10 K27 新しい決定 2): 取りに行き方の欄 repeat を足した (旧 /1 は片付けた、Z37)
BOOTSTRAP_ROUTE = _ContractRef("sui.fb.bootstrap_route", "2")
INITIAL_PROCESS = _ContractRef("sui.fb.initial_process", "1")
ENVIRONMENT = _ContractRef("sui.fb.environment", "1")
# δ の契約 (§2-5-4)。v0.25 §6-4 で火種を受信だけから保存済みの事実へ広げ、段 3 で `received_update/1` から
# 置き換えた (§6-10 J1・K2: 火種は保存した原報告、結びつき B は要求を作る前提)
SAVED_SEGMENT_UPDATE = _ContractRef("sui.fb.saved_segment_update", "1")
# 採用の後に考え直す最初の方法 (§6-10 J6・K1・K10)
REUSE_CANDIDATES = _ContractRef("sui.fb.reuse_candidates", "1")
# Need の呼出しの構造契約 (FBS0-R02)。入力 NEED_INPUT = {"work": Desc の正準 JSON, "scope": ResourceScope の
# 正準 JSON}。出力 QUANTITY_VALUE = QuantityValue の正準 JSON {"contract": 量の契約, "value": その契約の値}
# (この版の量の契約は SEATS = 非負整数一つで、SEATS 自身の意味は変えない)。F-a の能力の呼出しの構造検査が
# この 2 つの契約を受け付けるようにするのは段 1。名前は段 0 で決めた (紙に無い名前だけの仮定)。
NEED_INPUT = _ContractRef("sui.fb.need_input", "1")
QUANTITY_VALUE = _ContractRef("sui.fb.quantity_value", "1")

# 原報告 (Observed / MEMBRANE / FACT、§2-5-9)
RECEIVED = _ContractRef("sui.fb.received", "1")
# I-7 の時計の知らせ (§6-9 K1)。窓口が同じ run の起動との対応を確かめて既存 sui.clock.source/1 を発行する
CLOCK_NOTICE = _ContractRef("sui.fb.clock_notice", "1")
# /2 (§6-10 K26-a (ア)): 型のついた欄 observation_models を足した。/3 (K27): 中の bootstrap_route が /2 に
# なった (旧版は片付けた、Z37)
BOOT_DECLARATION = _ContractRef("sui.fb.boot_declaration", "3")
SEGMENT_REPORT = _ContractRef("sui.fb.segment_report", "1")
WORK_REPORT = _ContractRef("sui.fb.work_report", "1")
DRAW_REPORT = _ContractRef("sui.fb.draw_report", "1")

# sui の要求・選択・採用の確定 (Decided / MODEL / FACT)
# /2 (§6-10 K27): 測る仕事の要求の args に route から写した取りに行き方 repeat を足した (旧 /1 は片付けた)
SEGMENT_REQUESTED = _ContractRef("sui.fb.segment_requested", "2")
CANDIDATE_REQUEST = _ContractRef("sui.fb.candidate_request", "1")
WORK_REQUESTED = _ContractRef("sui.fb.work_requested", "1")
EVALUATION_REQUESTED = _ContractRef("sui.fb.evaluation_requested", "1")
DRAW_REQUESTED = _ContractRef("sui.fb.draw_requested", "1")
SELECTION = _ContractRef("sui.fb.selection", "1")
ACQUISITION_REQUESTED = _ContractRef("sui.fb.acquisition_requested", "1")
ADOPTION_REQUESTED = _ContractRef("sui.fb.adoption_requested", "1")

# 窓口が成立を確かめた論理の出来事 (Observed / MEMBRANE / FACT)
WORK_TERMINAL = _ContractRef("sui.fb.work_terminal", "1")
DRAW_UNKNOWN = _ContractRef("sui.fb.draw_unknown", "1")
SEGMENT_BINDING = _ContractRef("sui.fb.segment_binding", "1")
PREPARED = _ContractRef("sui.fb.prepared", "1")
EVALUATED = _ContractRef("sui.fb.evaluated", "1")
STALE = _ContractRef("sui.fb.stale", "1")
CONFLICT = _ContractRef("sui.fb.conflict", "1")
WAITING = _ContractRef("sui.fb.waiting", "1")

# 内側の値契約 (独立 Body なし)
CANDIDATE_GENERATION = _ContractRef("sui.fb.candidate_generation", "1")

# 段 2 (§6-9): 最初の候補の生成方法 (H9)、評価の準備と、くじからの評価の実行の操作 (H8、名前だけの仮定)
MODEL_OPERATIONS = _ContractRef("sui.fb.model_operations", "1")
EVALUATION_PREPARE = _ContractRef("sui.fb.evaluation_prepare", "1")
EVALUATE_FROM_DRAW = _ContractRef("sui.fb.evaluate_from_draw", "1")
# 選択のくじの生成器 (§6-10 K35、H4): 法則 uniform_bits/1 のくじ U の続きのかたまりを、OS の暗号用の乱数から
# B ビットずつ返す。B (1 回に読むかたまりの大きさ。目盛りではない) はここだけに置き、本体の係 UniformDraw と
# registry の保証の宣言はここから読む。別の B が欲しい時は別の生成器 (名前か版) を足して起動の宣言で指す
OS_UNIFORM_BITS = _ContractRef("sui.fb.os_uniform_bits", "1")
OS_UNIFORM_BITS_BLOCK = 128
DRAW_GUARANTEE = _ContractRef("sui.fb.draw_guarantee", "2")   # 生成器の保証の範囲 (H4・K35 決定 11) の値の契約

# finite_update/2 とその周り (§2-5-19、段 3 で新しい registry へ)
FINITE_UPDATE_2 = _ContractRef("sui.f.finite_update", "2")
OBSERVATION_PLAN_2 = _ContractRef("sui.f.observation_plan", "2")
FINITE_SEGMENT_PROJECTION = _ContractRef("sui.fb.finite_segment_projection", "1")
FINITE_JOINT_COUNT_LAW = _ContractRef("sui.fb.finite_joint_count_law", "1")
NO_ARRIVAL = _ContractRef("sui.fb.no_arrival", "1")
COUNT_EXACTLY_ONE = _ContractRef("sui.fb.count_exactly_one", "1")
# 測り方の契約 (§6-10 K25): 1 標本 = ホストが仲立ちした 1 回の取得の結果 (taken・empty・unavailable)。
# Frame はホストが acquire の中で出す。件数や区切りそのものを Frame の値とは呼ばない
ACQUISITION_RESULT_SAMPLING = _ContractRef("sui.fb.acquisition_result_sampling", "1")
# 取りに行き方 (§6-10 K27): 前の取りに行きが決着したら (結果によらず) 止める合図を確かめて次を取りに行く。
# 待ち・周期・回数の上限を置かない。args は {}。人が置く最初の方式 (差し替えの口、P9 ①)。実行は本体の
# SourceMeasurer が担う (能力の呼出しの規約からは呼ばない)
ACQUISITION_REPEAT_WHEN_DONE = _ContractRef("sui.fb.acquisition_repeat_when_done", "1")
BOOTSTRAP_GENERATION = _ContractRef("sui.fb.bootstrap_generation", "1")
SEGMENT_VALUE_ONLY = _ContractRef("sui.fb.segment_value_only", "1")
# 入口 U (§6-3): 一次事実から計算して IssuedUpdate を発行する。結果 R* は既存の
# `sui.f.finite_update_result/1` の値で保存する (§2-5-19-8)。v0.25 で証明・認証の名札
# (finite_update_statement/2・finite_update_replay/2・finite_update_target_check/1・
# target_update_certificate/1・sui.fb.verification・proof_output・verification_response) を外した
FINITE_UPDATE_COMPUTE = _ContractRef("sui.f.finite_update_compute", "1")

# 段 3 の最初の輪の記録と値の契約 (§6-10 J4・J5、名前だけの仮定)
UPDATE_RESPONSE = _ContractRef("sui.fb.update_response", "1")  # Wu の返答の三枝 {kind: issued / rejected / insufficient, value}
UPDATE_RESULT = _ContractRef("sui.fb.update_result", "1")      # R*: 発行物の正準な説明 (J5)
BELIEF_ADOPTED = _ContractRef("sui.fb.belief_adopted", "1")    # A*: 採用 (J5)

# 取得の列を読む本 (§6-10 K26・K26-a)。読み口 `fb.read_acquisition_sequence` だけが使う (F-a の読み口には登録しない)
ACQUISITION_OBSERVATION_MODEL = _ContractRef("sui.fb.acquisition_observation_model", "1")  # 観測モデルの記録 (Prediction / MODEL)
ACQUISITION_RESULT_PROJECTION = _ContractRef("sui.fb.acquisition_result_projection", "1")  # 取得の Frame → {result, source_called}
ACQUISITION_CONTROL_TABLE = _ContractRef("sui.fb.acquisition_control_table", "1")          # 記録された履歴 → 制御 u の候補
STATE_INDEPENDENT_CONTROL_SELECTION = _ContractRef("sui.fb.state_independent_control_selection", "1")  # 選び方が状態に依存しない根拠

# 見立てへ通す本 (§6-10 K28・K28-a)。家の人が acquire で残した取りに行きの列を、1 回ずつの核で順に予想へ
SAVED_ACQUISITION_UPDATE = _ContractRef("sui.fb.saved_acquisition_update", "1")   # δ: 取りに行きの Frame の B ごとに義務 1 つ
STATE_CORRESPONDENCE = _ContractRef("sui.fb.state_correspondence", "1")           # 物語の対応の記録 (Prediction / MODEL)
ACQUISITION_SEQUENCE_PROJECTION = _ContractRef("sui.fb.acquisition_sequence_projection", "1")  # 読み方: 列の i 番目を核で
ACQUISITION_GENERATION = _ContractRef("sui.fb.acquisition_generation", "1")       # 生成: その Frame は acquire が k・route の中で作った
