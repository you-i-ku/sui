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

# New contracts are separately registered; the legacy declarations stay byte
# for byte as they were. Registration is not an assertion of runtime fitness.
RATE_REPORT = _ContractRef("sui.s4b.rate_report", "1")
RATE_ARRIVAL = _ContractRef("sui.s4b.rate_arrival", "1")
RATE_BELIEF = _ContractRef("sui.s4b.rate_belief", "1")
RATE_DECISION = _ContractRef("sui.s4b.rate_decision", "1")
RATE_JOB = _ContractRef("sui.s4b.rate_job", "1")
RATE_REFINEMENT = _ContractRef("sui.s4b.rate_refinement", "1")
RATE_DECLARATIONS: tuple[_Contract, ...] = (
    _Contract(ref=RATE_REPORT,
        meaning='Observed content={channel,experiment,window_start_ns,window_end_ns,arrival_count,outcome,completion_ns}. model.9 resolves the joint count/probe or constant-completion kernel. null is unobserved, not zero. One physical report has one source_id.',
        unit='Clock readings integer ns; count exact nonnegative or at_least declared cap; finite-record-counting/1 likelihood is dimensionless mass',
        state_owner='sui.membrane', persistence='Keep raw payload and attempt/clock/receipt provenance in the ledger; reconstruct from model.9 and frozen facts',
        failure='Malformed input RateInputError; missing semantics RateSpecificationMissing; proved contradictory event/clock RateModelFalsified; unavailable computation RateIncomplete',
        cancel='none', redelivery='Same source_id and physical content is one event; conflicting content is a contradiction'),
    _Contract(ref=RATE_ARRIVAL,
        meaning='Observed content={process,mark,event_ns}. Physical marked-arrival/1 inside declared exact-arrival/1 coverage; mark=null marginalizes contents and preserves the arrival event. Never convert to a count report.',
        unit='event_ns integer run clock ns; marked-arrival-density/1 is density on ordered event times, with declared time unit raised to minus the number of arrivals',
        state_owner='sui.membrane', persistence='Keep raw ordered event times, process, mark, source_id, clock provenance and receipt independently',
        failure='Unknown kernels or measure stop; event contradiction is proved only; latent clocks and unsupported tied-time subspaces remain incomplete',
        cancel='none', redelivery='Same physical source is idempotent; a new Record alone does not create another physical arrival'),
)

RATE_DECLARATIONS += (
    _Contract(ref=RATE_BELIEF,
        meaning='Prediction target=belief. content={model,states,status,reason,context,derivation_budget,evidence,state_marginal,parameter_moments,structure_weights,unread}. derivation_budget={tolerance,max_cells,max_terms,max_refinements} is saved even before an evidence certificate exists. Certified quantities retain their axes; uncomputed fields are null.',
        unit='Exact rational enclosures; mass dimensionless, time raw run ns, moments in declared units',
        state_owner='sui.agent', persistence='Derived leaf only; verify with the saved derivation budget from model bytes and parent raw records, never from summary means; restored execution retains its current budget',
        failure='prior/complete/incomplete/unexplained/no_axis distinguish missing computation and proved contradiction',
        cancel='none', redelivery='Canonical reconstruction from the same frozen parent evidence'),
    _Contract(ref=RATE_DECISION,
        meaning='Decided content={root,candidates,u,values,display,selection,intent,certificate}. True softmax is enclosed; choose only previous.upper <= u < current.lower. Root freezes model, belief, parents, facts, context and preferences.',
        unit='Information nat; q_star and cumulative probabilities; u exact rational; clock raw run ns',
        state_owner='sui.agent', persistence='Reexecute the saved version and trace; proof validity and canonical byte regeneration are separate checks',
        failure='Unavailable reference/version RateReplayUnavailable; false proof/root/intent/inputs RateReplayMismatch; exhausted computation RateIncomplete',
        cancel='none', redelivery='Same Commit keeps the same u, full command, intent and reservation'),
    _Contract(ref=RATE_JOB,
        meaning='JobOpened step=0 content is the full {choice,action,reservation_rule,execution,effect} of the certified decision intent.',
        unit='Planned start in declared physical time, with causal stage and position',
        state_owner='sui.agent', persistence='Saved after all validation and after Decided; decision refers to its Record.id',
        failure='Command, reservation or decision mismatch rejects before saving; unverified runtime stops',
        cancel='No invented execution or cancellation law', redelivery='Retry the same job identity and command'),
    _Contract(ref=RATE_REFINEMENT,
        meaning='Prediction target=decision_refinement content={decision,problem_key,values,certificate}. A derived refinement sheet; intersect only after verifying both enclosures of the same quantities.',
        unit='Same units and targets as the original decision',
        state_owner='sui.agent', persistence='Original decision/u/selection/command stay immutable; this leaf is not a raw observation',
        failure='Nonintersecting or false enclosures RateReplayMismatch; unavailable replay and budget exhaustion remain distinct',
        cancel='No automatic refinement driver', redelivery='Repeated verification does not add an observation'),
)
