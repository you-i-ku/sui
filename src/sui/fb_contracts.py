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
BOOTSTRAP_ROUTE = _ContractRef("sui.fb.bootstrap_route", "1")
INITIAL_PROCESS = _ContractRef("sui.fb.initial_process", "1")
ENVIRONMENT = _ContractRef("sui.fb.environment", "1")
# δ の契約 (§2-5-4)。v0.25 §6-4 で火種を受信だけから保存済みの事実へ広げた。名前と入力の形は段 3 で決める
RECEIVED_UPDATE = _ContractRef("sui.fb.received_update", "1")
# Need の呼出しの構造契約 (FBS0-R02)。入力 NEED_INPUT = {"work": Desc の正準 JSON, "scope": ResourceScope の
# 正準 JSON}。出力 QUANTITY_VALUE = QuantityValue の正準 JSON {"contract": 量の契約, "value": その契約の値}
# (この版の量の契約は SEATS = 非負整数一つで、SEATS 自身の意味は変えない)。F-a の能力の呼出しの構造検査が
# この 2 つの契約を受け付けるようにするのは段 1。名前は段 0 で決めた (紙に無い名前だけの仮定)。
NEED_INPUT = _ContractRef("sui.fb.need_input", "1")
QUANTITY_VALUE = _ContractRef("sui.fb.quantity_value", "1")

# 原報告 (Observed / MEMBRANE / FACT、§2-5-9)
RECEIVED = _ContractRef("sui.fb.received", "1")
BOOT_DECLARATION = _ContractRef("sui.fb.boot_declaration", "1")
SEGMENT_REPORT = _ContractRef("sui.fb.segment_report", "1")
WORK_REPORT = _ContractRef("sui.fb.work_report", "1")
DRAW_REPORT = _ContractRef("sui.fb.draw_report", "1")

# sui の要求・選択・採用の確定 (Decided / MODEL / FACT)
SEGMENT_REQUESTED = _ContractRef("sui.fb.segment_requested", "1")
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

# finite_update/2 とその周り (§2-5-19、段 3 で新しい registry へ)
FINITE_UPDATE_2 = _ContractRef("sui.f.finite_update", "2")
OBSERVATION_PLAN_2 = _ContractRef("sui.f.observation_plan", "2")
FINITE_SEGMENT_PROJECTION = _ContractRef("sui.fb.finite_segment_projection", "1")
FINITE_JOINT_COUNT_LAW = _ContractRef("sui.fb.finite_joint_count_law", "1")
NO_ARRIVAL = _ContractRef("sui.fb.no_arrival", "1")
COUNT_EXACTLY_ONE = _ContractRef("sui.fb.count_exactly_one", "1")
BOOTSTRAP_GENERATION = _ContractRef("sui.fb.bootstrap_generation", "1")
SEGMENT_VALUE_ONLY = _ContractRef("sui.fb.segment_value_only", "1")
# 入口 U (§6-3): 一次事実から計算して IssuedUpdate を発行する。結果 R* は既存の
# `sui.f.finite_update_result/1` の値で保存する (§2-5-19-8)。v0.25 で証明・認証の名札
# (finite_update_statement/2・finite_update_replay/2・finite_update_target_check/1・
# target_update_certificate/1・sui.fb.verification・proof_output・verification_response) を外した
FINITE_UPDATE_COMPUTE = _ContractRef("sui.f.finite_update_compute", "1")
