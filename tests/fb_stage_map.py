"""FBS0-01 / v0.24: independent stage allocation, restart draft 3.

Current checkpoint is RESTART_SESSION_NOTE below. The first round's historical
notes/results are retained below and are NOT this restart's verification.

The grouping policies below are explicit decisions from §5-2, not inference from
contract != NA or a keyword classifier. Original TARGETS and IDs are never edited.
Every expanded row preserves the original obligation and its contrast pair.
Family decisions were reviewed against §2-4/§2-5/§4/§5, with per-ID exceptions
for REF/CMP/PATH and older paper-line IDs. Field/branch rows inherit the uses of
their explicitly listed declaration, not the meaning of the contract NA label.
The broad public math group includes old-bundle compatibility at stages 2/3;
it does not assert that every F-a type is a new F-b production event.
Assigning an owner never establishes runtime coverage or discrimination.
Review granularity is the explicit policy/declaration family plus exceptions;
the structural audit does not independently prove every row's semantic uses.

Session note (2026-10-18, tool=codex, project=sui): restricted to four new files;
no commit. Vault Session/Project/Heat writes are outside this task's explicit
write scope, so NOT reflected. Reused knowledge: none for expected results;
only the allowed specification/public declarations/target data were used.
The initial common-rule Home/Heat/shared-rule read was garbled and was not used
as technical evidence. No other agent conversation was read. No external source.
Public-declaration excerpt output included private-name declarations in nearby
context; no method bodies from f.py or other prohibited implementation files
were inspected. The narrow read boundary was not perfectly maintained.
Codex conversation/session path was not established within the allowed inputs.

Handoff: FBS0-01 has 3,729 allocated IDs and structural checks; the policies
still need the specified comparison with Claude's independent allocation.
FBS0-02 has nine named interface/material gaps. FBS0-03 scenarios cannot enter
the production host until CG-ENV is resolved; per-row execution/contrast is
not connected. Never treat either a raised gap or a passed DTO construction
as execution/discrimination evidence. The input-scope extension is pending;
only the current four-file write scope is authorized. No artifact copied to
the vault. New reusable Knowledge: none; next action is public declarations
for real stores/clock/registry, followed by real adapter and row-level pairs.
Final dry-run command (2026-10-18): .venv/Scripts/python.exe -B -m pytest
--noconftest -p no:cacheprovider -q tests/test_fb_stage_map.py
tests/test_fb_skeleton.py tests/test_fb_stage1.py (PYTEST_ADDOPTS=--tb=no).
Observed: exit 1; 57 passed, 21 failed, 34 errors (112 cases). Stage map:
20 passed. Skeleton: 37 passed / 9 ContractGap. Stage 1: 39 CG-ENV (34 setup
errors + 5 failures), 7 TestConnectionGap; zero NotImplementedError/TypeError.
Behavioral assertions and all 1,272 required stage-1 rows: not_run/unconnected.
No skip/xfail. Failure classes are not success evidence for the product.
"""

from fb_targets import TARGETS

RESTART_SESSION_NOTE = """2026-10-18 / project=sui / tool=codex / tags=sui,F-b,試験
[[Projects/sui]]
Topic: F-b stage-0 public skeleton, restart after sui-fb-stage0-test was interrupted.
Current Codex session ID/path: not established. Predecessor/Claude transcripts:
not read; only the user's handoff was used. Their actual transcript paths are unconfirmed.

Decisions and artifacts (implemented, uncommitted): only tests/fb_stage_map.py,
tests/test_fb_stage_map.py, tests/test_fb_skeleton.py, tests/test_fb_stage1.py.
Original 3,729 IDs retained. The predecessor's already-written scope decisions
were checked independently: 47 unadopted I-5 predicate rows are R2 extensions,
not old F-a compatibility work; 12 Run/RunException rows are excluded by paper:3247.
Thus owner counts are 1=1260, 2=1560, 3=777, D7=1, outside=131; stage 1 requires
1260 rows, not the handoff's 1272. This restart does not further move any owner.

Prepared row links: 213 raw-field, 72 raw-branch, 63 record-field integrity,
13 exact scenario bundles = 361. Remaining 899 are explicit TestConnectionGap:
boot=45/common=456/generation=39/measure=166/review_common=193; receipt/legacy=0.
These are preparation counts, never executed behavioral conformance counts.
All execution states remain not_run because the host/prepare stub prevents
reaching behavioral assertions. Same-name/case-family proximity is not proof.

Original nine gap replacements and the two issued-handle additions are tested
as public construction/signature/constructor behavior. New CG-LAUNCH-CUT has
paper reasons at 316-318,3193,3239,3256: no supplied public control/observation
for a failure before worker entry. An injected launcher protocol is a proposal,
not an implemented API or a user's decision. Stage 0 is not closed.

Test-side fixes: independent wire oracle now honors rational pairs, SlotValue's
declaration wrapper, FixedView.environment, reading/outcome/segment tags and
Frame's nested unions. Stored-header hash checking handles the sha256: notation.
Constructor-side invalid-value rejection is separated from FWindow rejection;
the same legal constructor call is first checked. Ledger-only probes do not
construct an unrelated stub host. Audit also detects wrong owners, changed
original obligations, lost deferred obligations, unknown uses and broken focus.
Actual collected pytest node IDs are checked for all per-row references.

Read depth: relevant paper sections (not both papers in full), allowed public
signature/docstring excerpts and public fields, the four test files, TARGETS data.
The initial tests/fb_targets.py:1-90 output also included its local target-building
helper definitions at 23-82. Public excerpts also displayed private type aliases.
No product function/method body, private product module, forbidden model/test,
or other agent transcript was read. Perfect no-helper-body isolation is not claimed.
External sources: none. Reused knowledge: no prior product result was promoted;
the shared recording rule was read, but expected results came from the paper.

Recording: Obsidian Session/Project/Knowledge/Heat NOT updated. This task permits
writes to exactly four tests and execution of only the designated pytest command;
this note is the pending vault log. No vault artifact copy and no commit.
Next: resolve the public launch-cut contract; connect the remaining 899 original
obligations to exact positive/negative public paths. Do not replace them with
family labels or call a stub exception a stage-1 behavioral pass.

Verification actually performed in this restart: designated pytest command only,
eight runs while correcting/assembling tests. First run: 72 passed, 15 failed,
47 errors (4.40s). Final run: 86 passed, 86 failed, 334 errors = 506 cases (8.20s),
exit 1. Final red classes: NotImplementedError=414 (host=339, Ledger.prepare=75),
ContractGap=1 (CG-LAUNCH-CUT), TestConnectionGap=5 (899 rows); other error classes=0.
Map: 29 pass; skeleton: 51 pass/1 gap; stage 1: 6 auxiliary/bookkeeping pass,
414 stub outcomes/5 connection gaps. No skip/xfail; no behavioral completion claim.
Final reporting settings: PYTHONIOENCODING=utf-8, PYTEST_ADDOPTS='--tb=line -s',
FB_STAGE0_INVENTORY=1. Traceback source bodies were suppressed. No other suite,
golden, model or mutant execution. Git status of these four files: all untracked.
The final post-run change was this session-note text only.
"""

LAUNCH_SESSION_NOTE = """2026-10-18 / project=sui / tool=codex / tags=sui,F-b,試験
[[Projects/sui]]
Topic: third-turn CG-LAUNCH-CUT only; supersedes the preceding note's next action.
Current session ID/path: not established; no other conversation was read.
The user's latest scope places the remaining 899 row connections at stage-1
closure, not this stage-0 launch-cut check. All allocations and links are unchanged.

Implemented, uncommitted: public FLauncher/LaunchResult/optional launcher signature
checks; test-owned WitnessLauncher for not_started/unknown/exception/launched;
four real-host scenarios built with actual stores/Ledger/FakeClock/registry and
WitnessWorkers. The callback is deferred independently of the launch return.
Definite non-start has the same-WorkId successful retry as its legal comparison;
unknown/exception must retain the declared one-seat need and not retry, including
after rebuild and independently saved Received. Launched alone is not entry;
only the real worker's ctx.enter supplies the entry witness. No FStatus-derived
expectation, product edit, monkeypatch, skip, xfail, or new semantic default.

Evidence read: F-b paper 300-326 and 3189-3199 this turn (relevant parts only);
fb.py public launcher declarations 605-616 and host signature 651-652; allowed
test files. Declaration extraction overran once to fb.py:626's stub raise line.
That body line was displayed, so perfect no-body isolation is not claimed;
it supplied no expected result or implementation logic. Other product bodies,
private modules, prohibited tests/models and conversations were not read.
External sources: none. Reused knowledge: prior conclusions were not promoted
to observations; current signature/construction checks are rerun independently.

Recording: pending vault log here only. Obsidian Session/Project/Knowledge/Heat
are not updated under the four-file write and designated-command execution scope.
No new Knowledge artifact or owner decision; no message to Claude, no commit.
Validation actually performed: only the designated three-file pytest command,
four runs this turn. First: 90 passed / 89 failed / 334 errors. A stronger
callback annotation check then failed on alias/None annotation representation
in runs two and three (89 passed / 90 failed / 334 errors); normalize only the
equivalent no-argument/None-return spellings, not the launch semantics.
Final: 90 passed / 89 failed / 334 errors, 513 cases, 8.18s, exit 1.
Final red classes, counted once from pytest E lines: NotImplementedError=418,
TestConnectionGap=5 (unchanged 899 rows), ContractGap=0, TypeError=0, other=0.
All four new real-host cases reach the expected stub exception; none of their
behavioral assertions has executed. Public construction checks pass, but this
does not establish launch/entry/occupancy implementation conformance.
Current CG-LAUNCH-CUT work: completed. Stage-1 behavior and the 899 connections
remain incomplete for stage 1, as explicitly deferred by the latest user scope.
No additional missing public shape was found within this launch-cut review.
Final post-run edits are session-note text only; allocation/connection counts
remain 3729 IDs, owners 1260/1560/777/D7=1/outside=131, prepared 361, unconnected899.
"""

REVIEW_SESSION_NOTE = """2026-10-18 / project=sui / tool=codex / tags=sui,F-b,試験
[[Projects/sui]]
Topic: fourth-turn precommit review R01-R05; supersedes earlier current counts.
Current session ID/path: not established. No other agent transcript was read.
Implemented only in the four authorized test/map files; the fourth is now
scratchpad/stage1_hold/test_fb_stage1.py, per the user's explicit relocation.
It was NOT returned to tests/. No product edit, commit, or message to Claude.

R01: new observation DTOs and read/monitored signatures are checked. Three local
stage-3 input contrasts hold raw Started/Ended/Claim and target/call fixed:
full-window monitoring vs a hole, actual work-mouth envelope vs a different
report path with the same WorkId, acquisition-before-use vs use-before-acquisition.
These prove representability and independent input distinction, NOT successful
target verification or an assembled, saved Q/R/P/Cq dataset. The reader adapter
has all five public FReader methods and wraps actual Ledger/MemoryContents.

R02: no CapabilityImplementation.implementation call remains. Need declaration
has kind=method, input=NEED_INPUT, output=SEATS, with exact names/versions checked.
CG-NEED-STRUCTURAL is intentionally red: the supplied public contract places
F-a structural acceptance at stage 1 (fb_contracts.py:19-22; F-a paper:114).
F-a accepting/rejecting this new contract was NOT independently executed here.

R03: Ledger.prepare/write exception DOCSTRINGS only were read (ledger.py:338-357).
Two broad assert_host_fault uses around tampered Ledger.write are replaced with
pytest.raises(CorruptEntry), before/after an existing point; existing exact
CorruptEntry assertions retain the same declared contract. I/O is not recast
as CorruptEntry. Runtime rejection assertions remain not_run behind prepare stub.

R04: handwritten paper/public-declaration manifests compare exact field sets,
one-layer resolved annotations, nullable/union/literal branches and exported names.
Recursive JSON aliases are checked separately; get_type_hints expansion depth
is not substituted for a field contract. Public private-alias SPELLINGS in type
annotations are bound to their documented public types; no private alias value
or implementation is accessed. Envelope reuses the old public object event
annotation (paper:468/3231), with accepted FEvent branches checked separately.
Two IN-MEMORY temporary public declaration copies (nullable Received.data and
an extra FEvent branch) fail the same checker, and their nearest legal copies
pass. Original module/class identities are checked unchanged. No source copied
or mutated, and no extra suite or Python command was executed for these probes.

R05: CapabilityKind@661 and branches 6(method)/9(measurement)/15(generator) now
require stage 1 and retain stages 2/3. Owners move four rows from 2 to 1.
All 185 catalogue alias rows and public capability families were reviewed; the
other listed aliases are NoDecision/FMath call/claim types for stages 2/3.
Independent paper-derived lower bounds now guard stage-1 public values,
measurement DTOs, capability declarations, wire core types and these four rows.
Six coherent wrong-policy copies (allocation AND policy changed together) are
detected. The structural policy checks still are not a proof of every row's
semantic assignment; that limitation is explicit, not promoted to full coverage.

Final allocation: 3729 IDs; owner 1=1264,2=1556,3=777,D7=1,outside=131;
stage-1 required=1264. Prepared links remain361, unconnected903 (=899+new4):
boot45/common460/generation39/measure166/review_common193. No obligation deleted.
Stage-1 node references follow the held file, including collected-node selfcheck.

Verification: the designated pytest only, with third path changed to the held
file as explicitly requested, -B/--noconftest/-p no:cacheprovider/-q unchanged.
PYTHONIOENCODING=utf-8, PYTEST_ADDOPTS='--tb=line -s', FB_STAGE0_INVENTORY=1.
Seven executions this turn. Test-construction failures corrected: recursive JSON
annotation unfolding/forward-reference representation, public alias spellings,
and old collected-node paths after relocation. Final: 206 passed,90 failed,
334 errors =630 cases,8.41s,exit1. Once-per-case E-line classification:
NotImplementedError418, ContractGap1(CG-NEED-STRUCTURAL), TestConnectionGap5,
TypeError0, other0. No skip/xfail; stage-1 behavior remains not_run.

Read depth: relevant parts of F-b paper §2-4/§2-5/§5 and F-a V-11, public
signatures/docstrings/fields and allowed catalogue data/test files. Not full papers.
Initial f_update2.py:1-245 output also displayed its two stub body lines, and
fb.py:646-665 extraction included its constructor's stub body line. Thus strict
no-body-display isolation was imperfect; these stubs supplied no expected result.
Other product logic/private modules/prohibited tests/models/conversations unread.
External sources:none. Reused knowledge: current claims rerun, no prior result
promoted to independent evidence; no new reusable Knowledge artifact.

Recording: this is the pending vault Session/Project note. Obsidian/Heat were NOT
written/run under the current restricted write/command scope. Latest task work
R01-R05 completed; next is stage-1 implementation/Need structural dispatch and
903 row connections, plus stage-3 behavioral verification of the prepared pairs.
This session-note text is the only post-final-run change.
"""

PAPER = "specs/関所F_Fb_今の約束.md"
NEED_MOVE_SESSION_NOTE = """2026-10-18 / project=sui / tool=codex / tags=sui,F-b,試験
[[Projects/sui]] Fifth turn: CG-NEED-STRUCTURAL failing test moved from stage-0
CG-METHOD to held stage-1 test_need_structural_contract_gap. Stage 0 retains
only passing NEED_INPUT/SEATS declaration construction; no skip or red deletion.
One designated three-file pytest run (held third path), --tb=line -rA to count
outcomes: stage0=201 passed/0 red; total207 passed/90 failed/334 errors,8.27s,exit1.
Red classes unchanged: NotImplementedError418/ContractGap1/TestConnectionGap5.
No product/source bodies or external material read this turn; test files only.
Session ID/path unknown; no other conversation read. No commit. Reused knowledge:
prior red counts independently rerun. Vault Session/Project/Heat still unreflected
under the restricted scope; this is the pending record. Allocation unchanged.
"""
REPORT_LINK_SESSION_NOTE = """2026-10-18 / project=sui / tool=codex / tags=sui,F-b,試験
[[Projects/sui]] Sixth turn, review2 R01/R02 follow-up. ReportObservation exact
fields/nullable type and ExecutionObservation.reports tuple added to manifest.
Provenance contrast now keeps work-mouth envelope/r identical, with target raw
report Point present only in the legal execution's reports. A different saved
duplicate has the same WorkId/body; the target in an external observation does
not grant worker provenance. point=None also cannot establish that membership.
All are construction inputs, not actual saves or a completed verifier run.
Need declaration output changed to QUANTITY_VALUE; SEATS remains QuantityValue's
quantity contract. Stage-1 named gap retained with corrected contract names.
Only allowed test files edited; stage 1 still held. Allocation unchanged.
One designated three-file pytest run: stage0=202 passed/0 red; total208 passed,
90 failed,334 errors,8.78s,exit1. Red classes NotImplementedError418/ContractGap1/
TestConnectionGap5, other0. New exact ReportObservation, point provenance contrast
and stage0 CG-METHOD cases explicitly passed. No skips, product edits or commit.
Read depth: allowed test files and public f_update2.py:159-181 / fb_contracts.py:18-23
DTO/comment declarations only; no method body, private value, other conversation,
or external material read this turn. Session ID/path unknown. Reused knowledge:
reran current checks rather than treating prior results as evidence. Vault
Session/Project/Heat not reflected under restricted scope; this is pending log.
"""
STAGES = ("1", "2", "3", "D7の後", "範囲外")
SOURCE_ID_SHA256 = "5a915e78fcb288d01c8e42b2913f2df9c1293117cd2e31e4593a356d5bad323f"
WORK_USES = {
    "measure_segment": "1", "candidate_generation": "2",
    "belief_result": "3", "belief_proof": "3", "verification": "3",
    "evaluation_prepare": "2", "selection_draw": "2", "evaluation": "2",
}
ENTRY_USES = {"I-1": "1", "I-2": "1", "I-6": "1", "I-7": "1", "I-3": "2", "I-8": "2"}


def policy(owner, uses, basis, *, destination=None, review=False):
    return dict(owner_stage=owner, uses=uses, scope_basis=basis,
                destination=destination, review_required=review)


POLICIES = {
    "common": policy("1", {
        **{entry: (stage,) for entry, stage in ENTRY_USES.items()},
        **{use: (stage,) for use, stage in WORK_USES.items()},
    }, (f"{PAPER}:3245", f"{PAPER}:3258"), destination="2/3:追加入口・用途で共通義務を再検証"),
    "receipt": policy("1", {"I-1": ("1", "2", "3")},
                      (f"{PAPER}:200", f"{PAPER}:3187", f"{PAPER}:3189", f"{PAPER}:3193"),
                      destination="2/3:計算中も未知bytesの受信保存を継続"),
    "boot": policy("1", {"boot_and_initial_slots": ("1",)}, (f"{PAPER}:3239",)),
    "measure": policy("1", {"raw_segment_and_binding": ("1",), "measurement_use_in_update": ("3",)},
                      (f"{PAPER}:3239", f"{PAPER}:3241"), destination="3:数値使用と取得の再確認"),
    "generation": policy("1", {"origin_Qgen_saved_Wg_owned": ("1",), "candidate_generation": ("2",)},
                         (f"{PAPER}:3239", f"{PAPER}:3240"), destination="2:Wgの実行とCG以降"),
    "compute": policy("2", {u: (s,) for u, s in WORK_USES.items()
                            if u not in ("measure_segment", "selection_draw")},
                      (f"{PAPER}:258", f"{PAPER}:3240", f"{PAPER}:3241"), destination="3:Wr/Wp/Wv"),
    "math": policy("2", {"evaluation_prepare": ("2",), "selection_draw": ("2",),
                          "evaluation": ("2",), "updated_belief_in_next_evaluation": ("3",)},
                   (f"{PAPER}:3240", f"{PAPER}:3241"), destination="3:更新後の評価・旧道の再確認"),
    "update": policy("3", {"belief_result": ("3",), "belief_proof": ("3",), "verification": ("3",),
                            "acquire_adopt_replay": ("3",)}, (f"{PAPER}:3241",), destination="3:§19全閉じる条件"),
    "draw": policy("2", {"I-8": ("2",), "selection_draw": ("2",)}, (f"{PAPER}:3240",), destination="2:I-8と選択"),
    "legacy": policy("1", {"unchanged_measurement_contracts": ("1", "2", "3")},
                     ("specs/関所F_今の約束.md:69-70", f"{PAPER}:3256"),
                     destination="各段:旧 measurement_requested/job の型と対応を維持。新しい F-b 要求と混同しない"),
    "external": policy("範囲外", {"external_extension": ("範囲外",)},
                       (f"{PAPER}:265", f"{PAPER}:3112-3121", f"{PAPER}:3209"),
                       destination="§3:R1-R10を足す時。S5/S13/W-45/D6の既決範囲を維持"),
    "predicate_extension": policy("範囲外", {"I-5_predicate_extension": ("範囲外",)},
                       (f"{PAPER}:265", f"{PAPER}:3113", "specs/関所F_今の約束.md:297"),
                       destination="R2/I-5追加時:各行の対象・欄・枝の原義務。旧F-a述語の不変は別の既存契約行と§5-3(d)で確認"),
    "run_extension": policy("範囲外", {"Run_codec_when_added": ("範囲外",)},
                       (f"{PAPER}:3247",), destination="Runを報告形式に足す時:codecとFrameへの厳密展開を宣言・検証"),
    "display": policy("D7の後", {"toy_world_initial_present_and_none": ("D7の後",)},
                      (f"{PAPER}:24", f"{PAPER}:3243"), destination="段3後:D7の小表示と短い実走"),
    # Reviewed cross-cutting source/terminology rules: must be reapplied as new
    # entry points and work purposes join the vertical path (B:3245/3258).
    "review_common": policy("1", {
        **{entry: (stage,) for entry, stage in ENTRY_USES.items()},
        **{use: (stage,) for use, stage in WORK_USES.items()},
    }, (f"{PAPER}:3245", f"{PAPER}:3258"), destination="2/3:横断する対象ごとの用途照合を継続"),
    "review_math": policy("2", {"evaluation_prepare": ("2",), "evaluation": ("2",),
                                 "updated_belief_in_next_evaluation": ("3",)},
                          (f"{PAPER}:3240", f"{PAPER}:3241", f"{PAPER}:486-491"),
                          destination="2/3:数学の入力・結果・artifactの全枝と旧bundleを再検証"),
}

# Each family is listed deliberately; unlisted families are errors, never defaulted.
FAMILY_GROUPS = {
    "common": "body record instant producer state_ref payload contract_ref contract_declaration ref role category envelope reading clock_reading unavailable contract_value dependency_ref terminal conflict waiting descriptor generation fwork work_phase prepared_entry ledger_entry purpose_part status receipt_sequence",
    "boot": "boot_event boot_decl boot_fact resource_scope clock_declared clock_source",
    "receipt": "received",
    "measure": "segment_report measurement_id interval frame claim gap measurement_unavailable unproved coverage route_config route_applied segment segment_binding measurement_run",
    "generation": "initial model origin qgen",
    "compute": "work_finished all_work_stages",
    "draw": "draw_returned draw_fact draw_unknown",
    "math": "candidate candidate_generation eq prepared evaluated selection context facts_request scope artifact artifact1 model_document model_document1 action_decl kernel policy capability capability_implementation artifact_preflight artifact_bridge artifact_limit dependencies capability_context predicate predicate_args predicate_result predicate_snapshot style old_style quantity limit world preparation math_problem math_root missing",
    "update": "plan old_binding acquired request result proof completed adopted finite_update1 finite_result finite_statement finite_replay finite_update2 target_certificate verification stale registry_old registry_new v23",
    "legacy": "measurement_requested measurement_job",
    "external": "at when reservation_due generation_draw_request generation_draw_unknown external",
    "review_common": "rel vocab entry usage paper",
    "review_math": "public decl",
}
FAMILY_POLICY = {name: p for p, names in FAMILY_GROUPS.items() for name in names.split()}

WIRE_TYPE_GROUPS = {
    "common": "ContractRef ContractValue MethodCall SlotValue<T> SlotValue SlottedMethod BootSlot FixedView Trigger Stage Desc<Args> ClockReading Unavailable ReadingEvidence GenerationPair FailureInfo UnknownInfo TerminalReturned TerminalBasis Projection<T> Projection SavedKeyValue SavedKeyField SavedCondition Part SavedPurpose SavedTarget MissingTarget SavedOwner WaitingPayload ConflictRule WorkTerminal Conflict RecordEnvelope Instant Producer ProducerState ObservedEnvelope DecidedEnvelope PredictionEnvelope",
    "boot": "QuantityValue Seats ResourceScope Allocation BootstrapRoute Environment BootDeclaration Received ExistingBoot ExistingClockSource",
    "measure": "SegmentArgs SegmentReport SegmentItem MeasurementFrame Gap MeasurementUnavailable CoverageClaim CoverageUnproved MeasurementInterval MeasurementId BindingGeneration SegmentRequested SegmentBinding ExistingRouteApplied ExistingClockReading RouteConfig",
    "generation": "InitialProcess CandidateArgs CandidateRequest ExistingOrigin",
    "compute": "WorkOutcome WorkReport WorkRequested",
    "draw": "DrawOutcome DrawArgs DrawReport DrawRequested DrawUnknown ExistingDrawFact DrawRequest",
    "math": "CandidateGeneration EvaluationPrepareArgs EvaluationArgs EvaluationRequested Prepared Evaluated Selection ExistingMathArtifact2 FCandidateDeclaration FCandidateGeneration FContinuation ContinuationAfter CandidateMeasureRef PolicyRef FFactsRequest EvaluationScope",
    "update": "ReceivedUpdateArgs ResultArgs ProofArgs VerificationArgs ProofOutput VerificationResponse Verification AcquisitionRequested AdoptionRequested Stale ExistingQ ExistingResult ExistingProof ExistingCompletion ExistingAcquisition ExistingAdoption ProofRef",
}
WIRE_TYPE_POLICY = {name: p for p, names in WIRE_TYPE_GROUPS.items() for name in names.split()}
WIRE_CONTRACT_GROUPS = {
    "boot": "received boot_declaration seats resource_scope allocation bootstrap_route initial_process environment",
    "measure": "segment_report segment_requested segment_binding",
    "generation": "candidate_request",
    "compute": "work_report work_requested",
    "draw": "draw_report draw_requested draw_unknown",
    "common": "work_terminal conflict waiting",
    "math": "evaluation_requested prepared evaluated selection candidate_generation",
    "update": "verification acquisition_requested adoption_requested stale received_update proof_output verification_response",
    "external": "generation_draw_requested generation_draw_unknown",
}
WIRE_CONTRACT_POLICY = {name: p for p, names in WIRE_CONTRACT_GROUPS.items() for name in names.split()}

PUBLIC_MEASUREMENT = set("MeasurementId ClockReading MeasurementInterval Gap MeasurementUnavailable CoverageUnproved CoverageClaim MeasurementFrame RouteConfig Run RunException".split())
PUBLIC_COMMON = set("Unavailable ContractValue".split())

# Per-ID exceptions inspected against the paper. Numeric suffixes are original IDs,
# not line numbers in v0.24 (the catalogue retains older IDs).
EXACT_POLICY = {
    # R05: these declaration rows are consumed by stage-1 Need/measurement/Qgen.
    "T.decl.alias.CapabilityKind@661": "common",
    "T.decl.alias.CapabilityKind@661.branch.6": "common",   # method
    "T.decl.alias.CapabilityKind@661.branch.9": "common",   # measurement
    "T.decl.alias.CapabilityKind@661.branch.15": "common",  # generator
    **{f"T.entry.I-{i}": "external" for i in (4, 5)},
    "T.d7.perception": "measure", "T.d7.two_starts": "math", "T.d7.display": "display",
    **{f"T.paper.{i}": "external" for i in (
        *range(2021, 2031), *range(2064, 2076), 2048, 2052, 2053, 2054, 2056, 140, 2117, 2119)},
    **{f"T.paper.{i}": "generation" for i in (1931, 1932, 1933)},
    **{f"T.paper.{i}": "boot" for i in (469, 470, 471, 1925, 1927)},
    **{f"T.paper.{i}": "update" for i in (475, 479, 480, 481, 482, 483, 484, 485, 150)},
    **{f"T.paper.{i}": "compute" for i in (473, 1972)},
    **{f"T.paper.{i}": "draw" for i in (474, 1968, 1970)},
    **{f"T.usage.B{i}": "math" for i in (5, 7)},
    **{f"T.usage.B{i}": "update" for i in (3, 4)},
    "T.usage.B1": "boot", "T.usage.B2": "measure", "T.usage.B6": "compute",
    **{f"T.rel.{n}": "update" for n in ("declared_derive", "update_stages", "acquisition", "verify", "stale", "numeric_update2", "registry_versions")},
    **{f"T.rel.{n}": "measure" for n in ("coverage", "measurement", "segment_end")},
    "T.rel.initial_none": "boot", "T.rel.generation": "generation",
    "T.rel.draw": "draw", "T.rel.selection": "math",
    "T.rel.invariance": "math", "T.rel.terminal": "compute",
    "T.entry.I-1": "receipt", "T.entry.I-2": "measure", "T.entry.I-3": "compute",
    "T.entry.I-6": "generation", "T.entry.I-7": "boot", "T.entry.I-8": "draw",
    **{f"T.vocab.W-{i:02}": "external" for i in (42, 43, 44, 45)},
    **{f"T.vocab.W-{i:02}": "update" for i in (21, 22, 23, 24)},
    **{f"T.vocab.W-{i:02}": "measure" for i in (1, 3, 4)},
    **{f"T.vocab.W-{i:02}": "math" for i in (33, 34, 36, 37, 41)},
    "T.vocab.W-20": "generation",
    # Reference/use/CMP/PATH rows were read individually, then assigned by the
    # operation that actually consumes that reference, not by contract presence.
    **{f"T.wire.logical.REF-{i}": "update" for i in (
        1027, 1028, 1029, 1030, 1031, *range(1033, 1045))},
    **{f"T.wire.logical.REF-{i}": "measure" for i in (1026, *range(1054, 1060))},
    **{f"T.wire.logical.REF-{i}": "math" for i in (1032, 1045, 1049, 1050, 1060)},
    **{f"T.wire.logical.REF-{i}": "draw" for i in (1046, 1047, 1048)},
    "T.wire.logical.REF-1025": "generation",
    **{f"T.wire.logical.CMP-{i:02}": "measure" for i in (*range(3, 10), 23)},
    **{f"T.wire.logical.CMP-{i:02}": "update" for i in range(11, 17)},
    **{f"T.wire.logical.CMP-{i:02}": "math" for i in (17, 19, 20)},
    "T.wire.logical.CMP-18": "draw", "T.wire.logical.CMP-02": "generation",
    **{f"T.wire.logical.PATH-{n}": "update" for n in (
        "RESULT", "STATEMENT", "CHECKER", "Q0", "QPREV", "QOBS", "R-OUTER", "P-OUTER",
        "COMPLETE", "ACQUIRE", "ADOPT", "LINK-ACQUISITION")},
    "T.wire.logical.PATH-REPORT-EVIDENCE": "measure",
    **{f"T.wire.logical.PATH-{n}": "math" for n in (
        "ARTIFACT-INPUT", "ARTIFACT-DRAW", "ARTIFACT-NONPOINT")},
    **{f"T.wire.text.{i}": "update" for i in (2085, 2336, 2352, 2353, 2357, 2524, 2558, 2559, 2581, 2583)},
    **{f"T.wire.text.{i}": "measure" for i in (2093, 2231, 2354, 2534, 2566)},
    **{f"T.wire.text.{i}": "math" for i in (2349, 2350, 2351, 2536)},
    **{f"T.wire.text.{i}": "draw" for i in (2204, 2545)},
    **{f"T.wire.text.{i}": "external" for i in (2499, 2500)},
    **{f"T.wire.text.{i}": "boot" for i in (2112, 2127, 2129, 2523, 2526, 2527, 2533, 2542)},
    "T.wire.text.2532": "receipt",
    **{f"T.paper.{i}": "math" for i in (1934, 1935, 1936, 1937, 1938,
        *range(1942, 1949), *range(1952, 1959), *range(1960, 1965))},
    **{f"T.wire.existing.sui.f.{n}/1": "update" for n in (
        "computation_requested", "computation_result", "computation_proof",
        "computation_completed", "content_acquired", "knowledge_adopted")},
    "T.wire.existing.sui.s4.boot/1": "boot",
    "T.wire.existing.sui.clock.source/1": "boot",
    "T.wire.existing.sui.f.route_config/1": "measure",
    "T.wire.existing.sui.f.knowledge_origin/1": "generation",
    "T.wire.existing.sui.f.clock_reading/1": "common",
    "T.wire.existing.sui.f.candidate_declaration/1": "math",
    "T.wire.existing.sui.f.draw_fact/1": "draw",
    "T.wire.existing.sui.f.math_artifact/2": "math",
}

# Round 2 review: exactly these I-5 families (47 rows), not every 'unadopted'
# label. Their use/consumer is R2, NOT the old F-a predicate API. Preserve every
# row's field/branch obligation in deferred_obligation below. T.public.* old
# predicate declarations retain their separate compatibility assignments.
PREDICATE_EXTENSION_FAMILIES = frozenset(("predicate", "predicate_args", "predicate_result", "predicate_snapshot"))
RUN_EXTENSION_IDS = frozenset(("T.measurement_run", "T.public.Run", "T.public.RunException"))


def select_policy(row):
    rid = row["id"]
    parts = rid.split(".")
    if parts[1] in PREDICATE_EXTENSION_FAMILIES:
        return "predicate_extension"
    if any(rid == base or rid.startswith(base + ".") for base in RUN_EXTENSION_IDS):
        return "run_extension"
    if rid in EXACT_POLICY:
        return EXACT_POLICY[rid]
    parts = rid.split(".")
    if parts[1] == "wire":
        layer = parts[2]
        if layer == "type":
            return WIRE_TYPE_POLICY[parts[3]]
        if layer == "contract":
            return WIRE_CONTRACT_POLICY[parts[3]]
        if layer == "purpose":
            return {"measure_segment": "measure", "candidate_generation": "generation",
                    "selection_draw": "draw", "evaluation_prepare": "math", "evaluation": "math",
                    "belief_result": "update", "belief_proof": "update", "verification": "update"}[parts[3]]
        if layer == "unresolved":
            return "update"
        if layer == "artifact_input":
            return "math"
        if layer in ("logical", "text", "existing", "no_ninth_body"):
            return "review_common"
        raise ValueError(f"Unknown wire layer: {rid}")
    if parts[1] == "public" and parts[2] in PUBLIC_MEASUREMENT:
        return "measure"
    if parts[1] == "public" and parts[2] in PUBLIC_COMMON:
        return "common"
    if parts[1] == "public" and parts[2] in (
            "CapabilityDeclaration", "CapabilityImplementation", "CapabilityCallable", "CapabilityContext", "FRegistry"):
        return "common"  # stage 1 needs declared methods; no implicit Need=1
    return FAMILY_POLICY[parts[1]]


# Stage-1 case bundles are paper-derived operation/observation paths. They are
# not inferred from a passing FStatus. A bundle checks whole stored projections
# (so each field/branch row keeps its original obligation), plus the nearest
# legal/illegal transition pairs. Other-stage uses remain separate in the map.
STAGE1_CASES = {
    "receipt": ("custody", "shape", "same_envelope", "distinct_envelopes", "receive_clock", "raw_received"),
    "boot": ("raw_boot", "raw_clock", "boot_slots", "boot_preconditions", "initial_none", "initial_plan", "initial_retry"),
    "generation": ("initial_plan", "initial_retry", "boot_slots", "initial_none"),
    "measure": ("raw_segments", "descriptor", "forged_boundary", "ended_stop", "wrong_terminal", "initial_none"),
    "storage": ("ledger_write", "ledger_tamper", "write_retry", "raw_received"),
    "status": ("receipt_status", "readonly", "ended_stop", "boot_preconditions", "rebuild"),
    "work": ("descriptor", "entry_ticket", "ended_stop", "initial_plan", "readonly"),
    "ownership": ("write_retry", "initial_retry", "boot_preconditions", "entry_ticket", "ended_stop", "rebuild"),
    "legacy": ("legacy_request", "legacy_job"),
    "common": ("raw_received", "raw_clock", "raw_boot", "ledger_tamper", "descriptor", "rebuild"),
}
STAGE1_REACH = {
    "receipt": "原本全欄/rの一致、同封再試行と別受信、外形拒否と未知の合法原文",
    "boot": "Boot二slot・時計・初期記録一式・Qgen保存と未開始Wg、前提不足との対照",
    "generation": "実在model/origin/Qgenと同じ初期計画、途中故障からの復帰、initial=Noneとの対照",
    "measure": "8枝の原報告保存・要求とDesc対応・実入場/報告/停止、原文だけの偽対応との対照",
    "storage": "実C/Eの本文/header/seal/CID、prepare無書込み、固定準備と改変/応答喪失との対照",
    "status": "独立の宣言/封筒/実C/E/EWと表示の照合、照会による消費なし",
    "work": "保存要求全欄と宣言、入場札一回、停止前占有、列挙/作り直しとの区別",
    "ownership": "保存/初期計画/入場/停止の継続を故障と作り直しの前後で実観測",
    "legacy": "旧measurement_requested/jobの全本文と外側の対応、同じ準備と単一改変の対照",
    "common": "当該段の全受信入口の原文/保存の全欄、固定記述と同プロセス復帰",
}


def stage1_binding(row, key):
    """Explicit case-family assignment; NOT a claim of executed discrimination."""
    category = {"receipt": "receipt", "boot": "boot", "generation": "generation",
                "measure": "measure", "legacy": "legacy", "common": "common",
                "review_common": "common"}[key]
    family = row["id"].split(".")[1]
    subject = row["subject"]
    if family in ("prepared_entry", "ledger_entry"):
        category = "storage"
    elif family in ("status",):
        category = "status"
    elif family in ("descriptor", "fwork", "work_phase", "generation"):
        category = "work"
    elif family in ("purpose_part", "waiting", "conflict", "terminal"):
        category = "ownership"
    elif subject in ("Desc<Args>", "Stage", "Trigger", "BootSlot", "SegmentArgs", "FixedView"):
        category = "work"
    elif subject in ("SavedCondition", "SavedPurpose", "SavedOwner", "WaitingPayload", "Part",
                     "SavedKeyValue", "SavedKeyField", "SavedTarget", "MissingTarget", "Projection<T>", "Projection.held"):
        category = "ownership"
    overrides = {
        "T.rel.receipt": "receipt", "T.rel.shape": "receipt", "T.rel.storage": "storage",
        "T.rel.rebuild": "ownership", "T.rel.owner": "ownership", "T.rel.transfer": "ownership",
        "T.rel.frozen": "work", "T.rel.conflict_use": "ownership", "T.rel.resource": "work",
        "T.rel.independence": "ownership", "T.rel.initial_none": "boot",
        **{f"T.paper.{n}": "status" for n in range(1911, 1922)},
    }
    category = overrides.get(row["id"], category)
    return dict(category=category, cases=STAGE1_CASES[category],
        subject=row["subject"], field=row["field"], branch=row["branch"],
        obligation=row["use"], negative=row["negative"], nearest_legal=row["nearest_legal"],
        required_reach=STAGE1_REACH[category], connection="candidate_bundle_not_row_proof", execution="not_run")


def allocate(row):
    key = select_policy(row)
    p = POLICIES[key]
    uses = tuple(dict(use=name, stages=stages, obligation=row["use"],
                      negative=row["negative"], nearest_legal=row["nearest_legal"])
                 for name, stages in p["uses"].items())
    required = tuple(s for s in STAGES if any(s in u["stages"] for u in uses))
    refs = tuple(dict(stage=s,
        reference=("scratchpad/stage1_hold/test_fb_stage1.py::test_stage1_obligation_connection[" + key + "]")
                  if s == "1" else f"{PAPER}:3240" if s == "2" else f"{PAPER}:3241" if s == "3"
                  else f"{PAPER}:3243" if s == "D7の後" else f"{PAPER}:3112-3121",
        state="not_run", kind="test" if s == "1" else "remaining_verification") for s in required)
    return dict(id=row["id"], owner_stage=p["owner_stage"], required_uses=uses,
                required_stages=required, close_stage=required[-1], scope_basis=p["scope_basis"],
                verification_refs=refs, destination=p["destination"], policy=key,
                review_required=p["review_required"], original_sources=row["sources"],
                original_consumer=row["consumer"], original_rules=row["rules"],
                deferred_obligation=(dict(subject=row["subject"], field=row["field"], branch=row["branch"],
                    use=row["use"], negative=row["negative"], nearest_legal=row["nearest_legal"],
                    reason="R2/I-5の未採用の運用。旧F-aの検査を新運用の証拠にしない" if key == "predicate_extension"
                        else "紙:3247のRun非使用。Frameを使えることをcodecの検証にしない")
                    if key in ("predicate_extension", "run_extension") else None),
                review_level="explicit_policy_and_exceptions",
                subject=row["subject"], field=row["field"], branch=row["branch"],
                stage1_binding=stage1_binding(row, key) if "1" in required else None,
                execution="not_run")


STAGE_MAP = tuple(allocate(row) for row in TARGETS)
STAGE_BY_ID = {row["id"]: row for row in STAGE_MAP}


def audit(rows, targets=TARGETS):
    """Structural audit; deliberately separate from semantic row review."""
    from collections import Counter
    errors = []
    ids = Counter(r["id"] for r in rows)
    known = {r["id"] for r in targets}
    originals = {r["id"]: r for r in targets}
    errors += [f"missing:{i}" for i in sorted(known - ids.keys())]
    errors += [f"unknown:{i}" for i in sorted(ids.keys() - known)]
    errors += [f"duplicate:{i}" for i, n in ids.items() if n != 1]
    for row in rows:
        rid = row["id"]
        if row["owner_stage"] not in STAGES:
            errors.append(f"owner:{rid}")
        if rid in originals and row["policy"] != select_policy(originals[rid]):
            errors.append(f"policy:{rid}")
        # Independent semantic obligation, deliberately NOT select_policy or
        # POLICIES: a coherent but wrong allocation policy must still fail.
        # B:2121/2165/3239 + public FThreadHost's method/measurement/generator
        # resolution require these exact catalogue declarations at stage 1.
        declared_stage1 = rid in {
            "T.decl.alias.CapabilityKind@661",
            "T.decl.alias.CapabilityKind@661.branch.6",
            "T.decl.alias.CapabilityKind@661.branch.9",
            "T.decl.alias.CapabilityKind@661.branch.15",
        }
        # Independently enumerated public input/declaration dependencies of
        # stage 1, from B:2103-2133,2161-2235,3239. Do not share the allocation
        # FAMILY/WIRE/PUBLIC policy tables: those tables are what this guards.
        parts = rid.split(".")
        if len(parts) > 2 and parts[1] == "public" and parts[2] in {
            "Unavailable", "ContractValue", "ClockReading", "MeasurementInterval",
            "MeasurementId", "MeasurementFrame", "Gap", "MeasurementUnavailable",
            "CoverageClaim", "CoverageUnproved", "RouteConfig", "CapabilityDeclaration",
            "CapabilityImplementation", "CapabilityCallable", "CapabilityContext", "FRegistry",
        }:
            declared_stage1 = True
        if len(parts) > 3 and parts[1:3] == ["wire", "type"] and parts[3] in {
            "ContractRef", "ContractValue", "MethodCall", "SlotValue<T>", "SlotValue",
            "SlottedMethod", "BootSlot", "FixedView", "QuantityValue", "Seats", "ResourceScope",
            "Allocation", "BootstrapRoute", "Environment", "BootDeclaration", "InitialProcess",
            "Trigger", "Stage", "Desc<Args>", "ReadingEvidence", "ClockReading", "Unavailable",
            "GenerationPair", "FailureInfo", "UnknownInfo", "SegmentArgs", "CandidateArgs",
            "SegmentReport", "SegmentItem", "MeasurementFrame", "MeasurementInterval", "MeasurementId",
            "Gap", "MeasurementUnavailable", "CoverageClaim", "CoverageUnproved", "RouteConfig", "Received",
        }:
            declared_stage1 = True
        if declared_stage1 and "1" not in row["required_stages"]:
            errors.append(f"semantic-stage1:{rid}")
        if row["policy"] not in POLICIES:
            errors.append(f"unknown-policy:{rid}")
            continue
        if row["owner_stage"] != POLICIES[row["policy"]]["owner_stage"]:
            errors.append(f"owner-policy:{rid}")
        expected = POLICIES[row["policy"]]["uses"]
        actual = {u["use"]: u for u in row["required_uses"]}
        if len(actual) != len(row["required_uses"]):
            errors.append(f"duplicate-use:{rid}")
        for name, stages in expected.items():
            if name not in actual or not set(stages) <= set(actual[name]["stages"]):
                errors.append(f"missing-use:{rid}:{name}")
        for use in row["required_uses"]:
            if use["use"] not in expected:
                errors.append(f"unknown-use:{rid}:{use['use']}")
            elif set(use["stages"]) != set(expected[use["use"]]):
                errors.append(f"use-stages:{rid}:{use['use']}")
            if not use["negative"] or not use["nearest_legal"]:
                errors.append(f"contrast:{rid}:{use['use']}")
            if rid in originals:
                for name, original_name in (("obligation", "use"), ("negative", "negative"), ("nearest_legal", "nearest_legal")):
                    if use[name] != originals[rid][original_name]:
                        errors.append(f"original-obligation:{rid}:{name}")
        stages = {s for u in row["required_uses"] for s in u["stages"]}
        if stages != set(row["required_stages"]) or not stages <= set(STAGES):
            errors.append(f"stages:{rid}")
        valid_stages = stages <= set(STAGES)
        if (row["close_stage"] not in stages or not valid_stages
                or (stages and row["close_stage"] != max(stages, key=STAGES.index))):
            errors.append(f"close:{rid}")
        if row["owner_stage"] not in stages:
            errors.append(f"owner-stage:{rid}")
        if (row["owner_stage"] in ("範囲外", "D7の後") or row["close_stage"] != row["owner_stage"]):
            if not row["scope_basis"]:
                errors.append(f"basis:{rid}")
            if not row["destination"]:
                errors.append(f"destination:{rid}")
        if {r["stage"] for r in row["verification_refs"]} != stages:
            errors.append(f"verification:{rid}")
        if rid in originals and row["policy"] in ("predicate_extension", "run_extension"):
            deferred = row.get("deferred_obligation")
            if not deferred:
                errors.append(f"deferred:{rid}")
            else:
                for name in ("subject", "field", "branch", "use", "negative", "nearest_legal"):
                    if deferred.get(name) != originals[rid][name]:
                        errors.append(f"deferred:{rid}:{name}")
        if "1" in stages:
            binding = row.get("stage1_binding")
            if not binding or not binding["cases"] or not binding["required_reach"]:
                errors.append(f"stage1-connection:{rid}")
            elif rid in originals:
                for name in ("subject", "field", "branch", "negative", "nearest_legal"):
                    if binding[name] != originals[rid][name]:
                        errors.append(f"stage1-focus:{rid}:{name}")
    return errors
