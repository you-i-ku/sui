"""導出 (DERIVATIONS) の実装 — 規則の表の名前 1 つに関数 1 つ (規則の正本 `src/sui/fb_rules.md` の DERIVATIONS、紙 F-b v0.35 Z28)。

ここは「世界の中身」(何が時計で、何が取得か) で、文法 (`_fb_a1.py`) ではない。各関数は値を返すだけで、落とさない・分類しない
(比べて分類するのは表の原子)。読めなければ `Missing`。名前は生成物 `_fb_rules.DERIVATIONS` の 75 名に閉じ、ここに無い名前は
評価器が「未接続 = 不足」にする (成功や空集合に落とさない)。接続した名前の一覧が、構造の検査の分母 (`a1.DERIVATIONS` の鍵)。

引数は評価器が解いた値 (記録の欄なら文書そのもの、Point、観測の列)。記録の Point が要る導出は `env.point_of(document)` で
文書から元の Point を取る (`point_of`・`entry` だけがその対応を取得する、表記規約)。
"""

from ._fb_a1 import Missing, derivation


def _work_id(env, request):
    """要求 (Point か文書) の desc.work_id。"""
    document = request
    if isinstance(request, str):
        if env.reader is None:
            return Missing("via: no reader to read the request")
        _contract, document = env.reader.document(request)
    try:
        return document["desc"]["work_id"]
    except (KeyError, TypeError):
        return Missing("request has no desc.work_id")


@derivation("via")
def via(env, rule_id, source):
    """(T-REF ID, source) → その行で一意に認証した到達先の Point。source は出発の記録の文書 (SELF: など)。
    欄・条件・用途・認証の失敗を再使用し、未処理の行を名前だけで呼ばない (`_fb_uses._via_target` がそれ)。"""
    from . import _fb_uses as uses
    if env.reader is None:
        return Missing("via: no reader")
    try:
        if isinstance(source, str):   # 入れ子の via が返した到達先の Point: その記録の文書から辿る
            point, (_contract, source) = source, env.reader.document(source)
        else:
            point = env.point_of(source)
        return uses._via_target(env.reader, rule_id, point, source, None)
    except (uses.Unresolved, uses.Malformed) as exc:
        return Missing(f"via {rule_id}: {exc}")


@derivation("point_of")
def point_of(env, record):
    """(束縛された記録 1 件) → その Point。Point そのものが来ればそれ。文書には元の記録の対応を保持している (Env)。"""
    found = env.point_of(record)
    return Missing("point_of: the value is not a bound record") if found is None else found


@derivation("set")
def set_(env, *operands):
    """(operand を 0 個以上) → 型付き集合 (正準の形で重複を除き、整列した列)。宣言された集合の比較にだけ使う。"""
    from ._fb_a1 import _canon, _json
    seen = {}
    for value in operands:
        seen.setdefault(_canon(value), _json(value))
    return [seen[key] for key in sorted(seen)]


@derivation("first_report")
def first_report(env, request, executions, reports):
    """(要求, EW:, EH:) → 最初の保存済み原報告の Point。要求の work_id の実行 (入場済み) の reports を
    (received_ns, envelope) の順に見て最初の 1 件。その point が null (保存を照合できていない) なら MISSING で、後の保存済みの
    報告へ飛ばない。envelope は Post の封筒番号 (Receipt.index ではない)。"""
    work_id = _work_id(env, request)
    if isinstance(work_id, Missing):
        return work_id
    runs = [e for e in executions if e.get("work_id") == work_id]
    if len(runs) != 1:
        return Missing(f"first_report: {len(runs)} executions observed for {work_id}")
    run = runs[0]
    if run.get("entered", 0) < 1:
        return Missing(f"first_report: the work {work_id} was not observed entering")
    ordered = sorted(run.get("reports", ()), key=lambda r: (r["received_ns"], r["envelope"]))
    if not ordered:
        return Missing(f"first_report: no report received from {work_id}")
    first = ordered[0]
    if first.get("point") is None:
        return Missing(f"first_report: the first report of {work_id} is not yet matched to a saved record")
    return first["point"]


# ---------------------------------------------------------------- 効果・一覧表を読む補助

@derivation("effect")
def effect(env, name, *records):
    """(name, 対象 record 0 個以上) → 実行の場所で捕捉した実値 (`Env.effects[(name, Point)]`)。表の期待値・done の印・自己申告から
    作らない。捕捉が無ければ MISSING (= 不足)。name は EFFECTS に閉じる。"""
    from . import _fb_rules as rules
    if name not in rules.EFFECTS:
        return Missing(f"effect {name!r} is not in EFFECTS")
    point = env.point_of(records[0]) if records else None
    if records and point is None:
        return Missing(f"effect {name}: the record is not bound to a point")
    found = env.effects.get((name, point))
    return Missing(f"effect {name} not captured for {point}") if found is None else found


@derivation("enumeration_source")
def enumeration_source(env, name, *args):
    """(名前, 引数…) → ENUMERATION_SOURCES に閉じた 1 つの値の読取り。名前ごとの接続 (下の _SOURCES) が要り、未接続は MISSING。"""
    from . import _fb_rules as rules
    if name not in rules.ENUMERATION_SOURCES:
        return Missing(f"enumeration_source {name!r} is not declared")
    fn = _SOURCES.get(name)
    if fn is None:
        return Missing(f"enumeration_source {name} is not connected")
    return fn(env, *args)


def _work_events(env, request):
    """(Q*) → 実行の場所で捕捉した仕事の出来事の列 [{kind, domain?}] (BUDGET_EVENT_KINDS.capture = work_events)。EFFECTS の名ではなく
    列挙表が宣言した捕捉名なので、effect() を通さずに同じ捕捉の置き場 (Env.effects) から読む。"""
    point = env.point_of(request)
    found = env.effects.get(("work_events", point))
    return Missing(f"work_events not captured for {point}") if found is None else found


_SOURCES = {"work_events": _work_events}


@derivation("contract_ref")
def contract_ref(env, name):
    """(正式契約名/版の literal) → 既存 ContractRef の保存形 {name, version}。版の文字列をそのまま (数値へ推測変換しない)。"""
    if not isinstance(name, str) or "/" not in name:
        return Missing(f"contract_ref: {name!r} is not name/version")
    contract, version = name.rsplit("/", 1)
    return {"name": contract, "version": version}


# 一覧を消費する導出の作り方 (どの一次の事実をどう組むか、原子の被演算子の文法で)。導出は自分の作り方をここに持ち、規則の正本の
# ENUMERATIONS を読まない (ゆう 2026-10-23 の方向: 一覧の原子は導出の戻り値を外から照らす係 = 本番の原子は世界の関係、試験の原子は
# 施工の確認。紙 F-b Z30 で型枠を外す時に、ここをふつうのコードへ訳す)。中身は 2026-10-22 の正本 v1.2 の一覧と同じ被演算子
# (計算を変えずに表の形から切り離すため。値の答え合わせは段 1〜3 の試験)
_SPECS = {'BUDGET_RULES': {'mode': 'cases',
                  'items': [{'id': 'COUNT-FINITE-UPDATE-1',
                             'when': {'method': 'sui.f.finite_update_compute/1'},
                             'template': {'method': {'derive': 'contract_ref',
                                                     'args': [{'literal': 'sui.f.finite_update_compute/1'}]},
                                          'unit': {'literal': 'logical_work/1'}}}]},
 'BUDGET_EVENT_KINDS': {'mode': 'event_kinds',
                        'items': [{'id': 'WORK-HEADER_READ', 'kind': 'header_read', 'unit': 1, 'when': True},
                                  {'id': 'WORK-BODY_READ', 'kind': 'body_read', 'unit': 1, 'when': True},
                                  {'id': 'WORK-REFERENCE_COMPARE',
                                   'kind': 'reference_compare',
                                   'unit': 1,
                                   'when': True},
                                  {'id': 'WORK-PROJECTION_INPUT',
                                   'kind': 'projection_input',
                                   'unit': 1,
                                   'when': True},
                                  {'id': 'WORK-INTEGER_EXTENSION',
                                   'kind': 'integer_extension',
                                   'unit': 1,
                                   'when': True},
                                  {'id': 'WORK-EXACT_ADD', 'kind': 'exact_add', 'unit': 1, 'when': True},
                                  {'id': 'WORK-EXACT_SUBTRACT', 'kind': 'exact_subtract', 'unit': 1, 'when': True},
                                  {'id': 'WORK-EXACT_MULTIPLY', 'kind': 'exact_multiply', 'unit': 1, 'when': True},
                                  {'id': 'WORK-EXACT_DIVIDE', 'kind': 'exact_divide', 'unit': 1, 'when': True},
                                  {'id': 'WORK-EXACT_COMPARE', 'kind': 'exact_compare', 'unit': 1, 'when': True}],
                        'unit': 'logical_work/1'},
 'CLOCK_PAIRS': {'mode': 'pairs',
                 'items': [{'id': 'CLK-INLINE-SAVED',
                            'kind': 'equal',
                            'left': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'item_field'}, {'literal': '/inline'}]},
                            'right': {'derive': 'enumeration_source',
                                      'args': [{'literal': 'item_field'}, {'literal': '/saved'}]},
                            'when': True,
                            'each': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'same_event_clock_links'},
                                              'B:',
                                              'Reading:',
                                              'Claim:',
                                              'K:']}},
                           {'id': 'CLK-ENTRY-STARTED',
                            'kind': 'le',
                            'left': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'event_reading'},
                                              {'literal': 'work_entered'},
                                              'K:',
                                              'EW:',
                                              'EH:',
                                              'EA:']},
                            'right': {'derive': 'boundary_reading', 'args': ['Started:']},
                            'when': {'nonnull': 'B:/generation/started?'}},
                           {'id': 'CLK-STARTED-RECEIVED',
                            'kind': 'le',
                            'left': {'derive': 'boundary_reading', 'args': ['Started:']},
                            'right': {'derive': 'enumeration_source',
                                      'args': [{'literal': 'event_reading'},
                                               {'literal': 'report_received'},
                                               'Started:',
                                               'EW:',
                                               'EH:',
                                               'EA:']},
                            'when': {'nonnull': 'B:/generation/started?'}},
                           {'id': 'CLK-ENDED-RECEIVED',
                            'kind': 'le',
                            'left': {'derive': 'boundary_reading', 'args': ['Ended:']},
                            'right': {'derive': 'enumeration_source',
                                      'args': [{'literal': 'event_reading'},
                                               {'literal': 'report_received'},
                                               'Ended:',
                                               'EW:',
                                               'EH:',
                                               'EA:']},
                            'when': {'nonnull': 'B:/generation/ended?'}},
                           {'id': 'CLK-CLAIM-END-RECEIVED',
                            'kind': 'le',
                            'left': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'clock_at'},
                                              {'derive': 'enumeration_source',
                                               'args': [{'literal': 'claim_window'}, 'Claim:'],
                                               'path': '/clock'},
                                              {'derive': 'enumeration_source',
                                               'args': [{'literal': 'claim_window'}, 'Claim:'],
                                               'path': '/end_ns'},
                                              'Claim:',
                                              'EW:',
                                              'EH:']},
                            'right': {'derive': 'enumeration_source',
                                      'args': [{'literal': 'event_reading'},
                                               {'literal': 'report_received'},
                                               'Claim:',
                                               'EW:',
                                               'EH:',
                                               'EA:']},
                            'when': {'item_kind': 'claim'}},
                           {'id': 'CLK-ROUTE-WINDOW-START',
                            'kind': 'le',
                            'left': 'Route:/effective_from[kind=clock]/value',
                            'right': {'derive': 'enumeration_source',
                                      'args': [{'literal': 'clock_at'},
                                               {'derive': 'enumeration_source',
                                                'args': [{'literal': 'claim_window'}, 'Claim:'],
                                                'path': '/clock'},
                                               {'derive': 'enumeration_source',
                                                'args': [{'literal': 'claim_window'}, 'Claim:'],
                                                'path': '/start_ns'},
                                               'Claim:',
                                               'EW:',
                                               'EH:']},
                            'when': {'item_kind': 'claim'}},
                           {'id': 'CLK-VERSIONED-RELATIONS',
                            'when': True,
                            'each': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'generation_clock_links'},
                                              'Reading:',
                                              'B:',
                                              'Claim:',
                                              'K:']},
                            'kind': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'item_field'}, {'literal': '/kind'}]},
                            'left': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'item_field'}, {'literal': '/left'}]},
                            'right': {'derive': 'enumeration_source',
                                      'args': [{'literal': 'item_field'}, {'literal': '/right'}]}}]},
 'MODEL_LINKS': {'mode': 'pairs',
                 'items': [{'id': 'MODEL-ORIGIN',
                            'kind': 'equal',
                            'left': 'Origin:/model',
                            'right': 'Q*:/desc/args/model',
                            'when': True},
                           {'id': 'MODEL-PRIOR-MODEL',
                            'kind': 'equal',
                            'left': {'derive': 'via', 'args': [{'literal': 'REF-Q-PRIOR'}, 'Q*:'], 'path': '/model'},
                            'right': 'Q*:/desc/args/model',
                            'when': {'nonnull': 'Q*:/desc/args/prior?'}},
                           {'id': 'MODEL-PRIOR-ORIGIN',
                            'kind': 'equal',
                            'left': {'derive': 'via', 'args': [{'literal': 'REF-Q-PRIOR'}, 'Q*:'], 'path': '/origin'},
                            'right': 'Q*:/desc/reader?',
                            'when': {'nonnull': 'Q*:/desc/args/prior?'}},
                           {'id': 'MODEL-COMPILER-MODEL',
                            'kind': 'equal',
                            'left': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'compiler_field'}, 'Q*:', {'literal': '/model'}]},
                            'right': 'Q*:/desc/args/model',
                            'when': {'stage': '評価の頭'}},
                           {'id': 'MODEL-COMPILER-ORIGIN',
                            'kind': 'equal',
                            'left': {'derive': 'enumeration_source',
                                     'args': [{'literal': 'compiler_field'}, 'Q*:', {'literal': '/origin'}]},
                            'right': 'Q*:/desc/reader?',
                            'when': {'stage': '評価の頭'}}]},
 'INPUT_ACQUISITIONS': {'mode': 'records',
                        'items': [{'id': 'INPUT-ACQUIRED-ORIGIN',
                                   'path': '/acquired_origin',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'acquisition_for_use'}, 'Q*:', 'EA:', 'EW:'],
                                             'path': '/origin'},
                                   'when': True},
                                  {'id': 'INPUT-USED-ORIGIN',
                                   'path': '/used_origin',
                                   'value': 'Q*:/desc/reader?',
                                   'when': True},
                                  {'id': 'INPUT-ACQUIRED-POINT',
                                   'path': '/acquired_point',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'acquired_point'},
                                                      {'derive': 'enumeration_source',
                                                       'args': [{'literal': 'acquisition_for_use'},
                                                                'Q*:',
                                                                'EA:',
                                                                'EW:']},
                                                      {'derive': 'enumeration_source',
                                                       'args': [{'literal': 'item_field'}, {'literal': '/point'}]}]},
                                   'when': True},
                                  {'id': 'INPUT-USED-POINT',
                                   'path': '/used_point',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'item_field'}, {'literal': '/point'}]},
                                   'when': True},
                                  {'id': 'INPUT-ACQUIRED-RUN',
                                   'path': '/acquired_run',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'observation_run'},
                                                      {'literal': 'acquisition'},
                                                      {'derive': 'enumeration_source',
                                                       'args': [{'literal': 'acquisition_for_use'},
                                                                'Q*:',
                                                                'EA:',
                                                                'EW:']},
                                                      'EW:',
                                                      'EA:']},
                                   'when': True},
                                  {'id': 'INPUT-USED-RUN',
                                   'path': '/used_run',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'observation_run'},
                                                      {'literal': 'use'},
                                                      {'derive': 'enumeration_source',
                                                       'args': [{'literal': 'item_field'}, {'literal': ''}]},
                                                      'EW:',
                                                      'EA:']},
                                   'when': True},
                                  {'id': 'INPUT-ACQUIRED-NS',
                                   'path': '/acquired_ns',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'acquisition_for_use'}, 'Q*:', 'EA:', 'EW:'],
                                             'path': '/acquired_ns'},
                                   'when': True},
                                  {'id': 'INPUT-USED-NS',
                                   'path': '/used_ns',
                                   'value': {'derive': 'enumeration_source',
                                             'args': [{'literal': 'item_field'}, {'literal': '/used_ns'}]},
                                   'when': True}],
                        'each': {'derive': 'enumeration_source',
                                 'args': [{'literal': 'input_use_obligations'}, 'Q*:', 'EW:']}},
 'HISTORICAL_USES': {'mode': 'records',
                     'items': [{'id': 'HISTORY-ACQUIRED-RUN',
                                'path': '/acquired_run',
                                'value': {'derive': 'enumeration_source',
                                          'args': [{'literal': 'observation_run'},
                                                   {'literal': 'acquisition'},
                                                   {'derive': 'history_acquisition',
                                                    'args': ['A*:', 'G:', 'R*:', 'EA:']},
                                                   'EW:',
                                                   'EA:']},
                                'when': True},
                               {'id': 'HISTORY-USED-RUN',
                                'path': '/used_run',
                                'value': {'derive': 'enumeration_source',
                                          'args': [{'literal': 'observation_run'},
                                                   {'literal': 'use'},
                                                   {'derive': 'enumeration_source',
                                                    'args': [{'literal': 'item_field'}, {'literal': ''}]},
                                                   'EW:',
                                                   'EA:']},
                                'when': True},
                               {'id': 'HISTORY-ACQUIRED-NS',
                                'path': '/acquired_ns',
                                'value': {'derive': 'history_acquisition',
                                          'args': ['A*:', 'G:', 'R*:', 'EA:'],
                                          'path': '/acquired_ns'},
                                'when': True},
                               {'id': 'HISTORY-USED-NS',
                                'path': '/used_ns',
                                'value': {'derive': 'enumeration_source',
                                          'args': [{'literal': 'item_field'}, {'literal': '/used_ns'}]},
                                'when': True}],
                     'each': {'from': 'uses',
                              'where': {'/point': {'derive': 'point_of', 'args': ['R*:']}},
                              'select': 'all',
                              'path': ''}},
 'FUTURE_RECORD_ROLES': {'mode': 'record',
                         'items': [{'id': 'FUTURE-SELF',
                                    'when': True,
                                    'value': {'derive': 'enumeration_source',
                                              'args': [{'literal': 'future_record'}, 'Q*:', {'literal': 'self'}]},
                                    'path': '/self'},
                                   {'id': 'FUTURE-RESULT',
                                    'when': True,
                                    'value': {'derive': 'enumeration_source',
                                              'args': [{'literal': 'future_record'}, 'Q*:', {'literal': 'result'}]},
                                    'path': '/result'},
                                   {'id': 'FUTURE-ACQUISITION',
                                    'when': True,
                                    'value': {'derive': 'enumeration_source',
                                              'args': [{'literal': 'future_record'},
                                                       'Q*:',
                                                       {'literal': 'acquisition'}]},
                                    'path': '/acquisition'},
                                   {'id': 'FUTURE-ADOPTION',
                                    'when': True,
                                    'value': {'derive': 'enumeration_source',
                                              'args': [{'literal': 'future_record'}, 'Q*:', {'literal': 'adoption'}]},
                                    'path': '/adoption'}]},
 'ADOPTION_TIMES': {'mode': 'record',
                    'items': [{'id': 'ADOPT-G',
                               'path': '/g',
                               'value': {'derive': 'enumeration_source',
                                         'args': [{'literal': 'event_reading'},
                                                  {'literal': 'result_generated'},
                                                  'R*:',
                                                  'EW:',
                                                  'EH:',
                                                  'EA:'],
                                         'path': '/time_ns'},
                               'when': True},
                              {'id': 'ADOPT-A',
                               'path': '/a',
                               'value': {'derive': 'history_acquisition',
                                         'args': ['A*:', 'G:', 'R*:', 'EA:'],
                                         'path': '/acquired_ns'},
                               'when': True},
                              {'id': 'ADOPT-R',
                               'path': '/r',
                               'value': {'derive': 'enumeration_source',
                                         'args': [{'literal': 'record_metadata'},
                                                  'G:',
                                                  {'literal': '/body/received_ns'}]},
                               'when': True},
                              {'id': 'ADOPT-AT',
                               'path': '/adopted',
                               'value': {'derive': 'enumeration_source',
                                         'args': [{'literal': 'record_metadata'}, 'A*:', {'literal': '/at/mono_ns'}]},
                               'when': True},
                              {'id': 'ADOPT-RUNS',
                               'path': '/runs',
                               'value': {'derive': 'tuple',
                                         'args': [{'derive': 'enumeration_source',
                                                   'args': [{'literal': 'event_reading'},
                                                            {'literal': 'result_generated'},
                                                            'R*:',
                                                            'EW:',
                                                            'EH:',
                                                            'EA:'],
                                                   'path': '/run'},
                                                  {'derive': 'enumeration_source',
                                                   'args': [{'literal': 'event_reading'},
                                                            {'literal': 'content_acquired'},
                                                            'G:',
                                                            'EW:',
                                                            'EH:',
                                                            'EA:'],
                                                   'path': '/run'},
                                                  {'derive': 'enumeration_source',
                                                   'args': [{'literal': 'record_metadata'},
                                                            'G:',
                                                            {'literal': '/at/run'}]},
                                                  {'derive': 'enumeration_source',
                                                   'args': [{'literal': 'record_metadata'},
                                                            'A*:',
                                                            {'literal': '/at/run'}]}]},
                               'when': True},
                              {'id': 'ADOPT-EXPECTED-RUNS',
                               'path': '/expected_runs',
                               'value': {'derive': 'tuple',
                                         'args': [{'derive': 'enumeration_source',
                                                   'args': [{'literal': 'comparison_run'},
                                                            'R*:',
                                                            'G:',
                                                            'A*:',
                                                            'EW:',
                                                            'EH:',
                                                            'EA:']},
                                                  {'derive': 'enumeration_source',
                                                   'args': [{'literal': 'comparison_run'},
                                                            'R*:',
                                                            'G:',
                                                            'A*:',
                                                            'EW:',
                                                            'EH:',
                                                            'EA:']},
                                                  {'derive': 'enumeration_source',
                                                   'args': [{'literal': 'comparison_run'},
                                                            'R*:',
                                                            'G:',
                                                            'A*:',
                                                            'EW:',
                                                            'EH:',
                                                            'EA:']},
                                                  {'derive': 'enumeration_source',
                                                   'args': [{'literal': 'comparison_run'},
                                                            'R*:',
                                                            'G:',
                                                            'A*:',
                                                            'EW:',
                                                            'EH:',
                                                            'EA:']}]},
                               'when': True}]},
 'HISTORY_DEPENDENCIES': {'mode': 'union',
                          'items': [{'id': 'HISTORY-RESULT', 'value': 'A*:/result', 'when': True},
                                    {'id': 'HISTORY-ACQUISITION', 'value': 'A*:/acquisition', 'when': True},
                                    {'id': 'HISTORY-PREVIOUS',
                                     'value': 'A*:/previous?',
                                     'when': {'nonnull': 'A*:/previous?'}}]}}


def _items(block):
    return _SPECS[block]["items"]


@derivation("counting_rule")
def counting_rule(env, method, budget):
    """(method, budget) → {method, unit}。BUDGET_RULES の場合 (when.method) を読み、合う 1 件の template を解く。
    合う場合が無ければ MISSING (missing_contract)。budget は単位を決めない (RateBudget は上限と誤差)。"""
    from ._fb_a1 import resolve
    from ._fb_uses import contract_name
    try:
        name = contract_name(method)
    except (KeyError, TypeError, AttributeError):
        return Missing("counting_rule: method is not a ContractRef")
    for item in _items("BUDGET_RULES"):
        when = item.get("when", True)
        if when is True or (hasattr(when, "items") and when.get("method") == name):
            return {key: resolve(env, operand) for key, operand in item["template"].items()}
    return Missing(f"counting_rule: no rule for {name} (missing_contract)")


@derivation("budget_events")
def budget_events(env, request):
    """(Q) → 実際の仕事の出来事の順序列 (種類)。BUDGET_EVENT_KINDS の capture (work_events) を読む。表に無い種類は MISSING。"""
    events = _work_events(env, request)
    if isinstance(events, Missing):
        return events
    kinds = {item["kind"] for item in _items("BUDGET_EVENT_KINDS")}
    events = [event["kind"] for event in events]
    unknown = [kind for kind in events if kind not in kinds]
    if unknown:
        return Missing(f"budget_events: unknown event kind {unknown[0]!r} (missing_contract)")
    return events


@derivation("unit_charges")
def unit_charges(env, rule, events):
    """(counting_rule, events) → 順序を保った各出来事の仕事量 (BUDGET_EVENT_KINDS の unit)。規則の単位が表の単位と違えば MISSING。"""
    block = _SPECS["BUDGET_EVENT_KINDS"]
    if not (hasattr(rule, "items") and rule.get("unit") == block["unit"]):
        return Missing("unit_charges: the counting rule's unit is not the table's unit")
    units = {item["kind"]: item["unit"] for item in block["items"]}
    out = []
    for kind in events:
        if kind not in units:
            return Missing(f"unit_charges: unknown event kind {kind!r}")
        out.append(units[kind])
    return out


# ---------------------------------------------------------------- 一覧表の each (量化) と時計

def enumerate_block(env, block_name):
    """一覧表 (ENUMERATIONS) の 1 ブロックを、原子の文法だけで読む: 各 item の when (nonnull / item_kind / generation) が
    真なら、`each` があればその出現ごとに Item を束縛して、kind・left・right (operand か literal) を解く。
    返すのは [{id, kind, left, right}] (出現の順)。読めない所は Missing を値として残す (落とさない)。
    これは「原子 + each」の読み方そのもので、12 モードの通訳ではない (紙 v0.35 Z28、表の係 8 通目)。"""
    from ._fb_a1 import Env, Missing as _Missing, Unknown, _applies, resolve
    out = []
    for item in _SPECS[block_name]["items"]:
        try:
            applies = _applies(env, _when(item.get("when", True)))
        except Unknown as exc:
            missing = _Missing(str(exc))
            out.append({"id": item["id"], "kind": missing, "left": missing, "right": missing})
            continue
        if not applies:
            continue
        if "each" in item:
            elements = resolve(env, item["each"])
            if isinstance(elements, _Missing):
                out.append({"id": item["id"], "kind": elements, "left": elements, "right": elements})
                continue
            scopes = [Env({**env.records, "Item": (None, element)}, evidence=env.evidence, reader=env.reader,
                          effects=env.effects) for element in elements]
        else:
            scopes = [env]
        for scope in scopes:
            out.append({"id": item["id"], **{key: _value(scope, item.get(key)) for key in ("kind", "left", "right")}})
    return out


def _when(when):
    """一覧表の when: item_kind は Claim の枝 (表記規約 → Claim:/item/kind の一致)。他は原子の when と同じ語。"""
    if when is True or when is None:
        return True
    if "item_kind" in when:
        rest = {k: v for k, v in when.items() if k != "item_kind"}
        return {"claim_kind": when["item_kind"], **rest}
    return when


def _value(env, operand):
    from ._fb_a1 import resolve
    if operand is None:
        return None
    if isinstance(operand, str) and ":" not in operand:
        return operand   # literal の文字列 (kind: "equal" / "le")
    return resolve(env, operand)


def _current_item(env):
    """今の each の出現 (ATOM_PROTOCOL v3 の字句の名前 ITEM、導出の作り方 `_SPECS` の中では Item)。"""
    found = env.document("ITEM")
    return env.document("Item") if found is None else found


def _item_field(env, pointer):
    from ._fb_a1 import _at, Missing as _Missing
    item = _current_item(env)
    if item is None:
        return _Missing("item_field outside an each")
    if isinstance(item, _Missing):
        return item   # 読めなかった出現 (必要な使用の観測が無い等) は理由ごと運ぶ
    return item if pointer == "" else _at(item, pointer)


def _clock_reading(run, time_ns):
    return {"run": run, "time_ns": time_ns}


def _event_reading(env, event, record, *_evidence):
    """EVENT_SOURCES の出来事 1 つの時計の読み (ClockReading {run, time_ns})。run が観測に無ければ MISSING (補わない)。"""
    if env.evidence is None:
        return Missing("event_reading: no independent observations")
    if event == "work_entered":
        execution = _execution_of(env, record)
        if isinstance(execution, Missing):
            return execution
        if len(execution.entered_ns) != 1:
            # 実際の入場は 1 回のはず (重複の入場も落とさず残っている = どれかを都合よく選ばない)
            return Missing(f"event_reading(work_entered): {len(execution.entered_ns)} entries observed")
        if execution.run is None or execution.clock_source is None:
            return Missing("event_reading(work_entered): the host run / clock source of the entry is not recorded")
        return _clock_reading(execution.run, execution.entered_ns[0])
    if event == "route_applied":
        application = _route_application_of(env, record)
        if isinstance(application, Missing):
            return application
        reading = application.reading
        from .f import ClockReading
        if not isinstance(reading, ClockReading):
            return Missing("event_reading(route_applied): the boundary clock was unavailable at the application")
        return _clock_reading(reading.run, reading.time_ns)
    if event == "report_received":
        point = env.point_of(record)
        if point is None:
            return Missing("event_reading(report_received): the record is not bound to a point")
        found = [r for e in env.evidence.executions for r in e.reports if r.point == point]
        if len(found) != 1:
            return Missing(f"event_reading(report_received): {len(found)} receipts observed for {point}")
        if found[0].run is None:
            return Missing("event_reading(report_received): the host run of the receipt is not recorded")
        return _clock_reading(found[0].run, found[0].received_ns)
    return Missing(f"event_reading: event {event!r} is not connected")


def _execution_of(env, record):
    """(K の文書) → その要求を実際に実行した ExecutionObservation 1 件 (工場の実行の札が 1 つ、要求の Point が一致)。
    WorkId は絞り込みの名札で、同一性の証明にしない (紙 :2171、正本 v1.3.7 execution_observation_extension)。"""
    point = env.point_of(record)
    if isinstance(record, str):   # 束縛の外の要求は Point で渡す (宣言の側の組み立て)
        record = _doc(env, record)
        if isinstance(record, Missing):
            return record
    if point is None:
        return Missing("execution: the request is not bound to a point")
    try:
        work_id = record["desc"]["work_id"]
    except (KeyError, TypeError):
        return Missing("execution: the record is not a request")
    found = [e for e in env.evidence.executions if e.work_id == work_id and e.request == point]
    if len(found) != 1:
        return Missing(f"execution: {len(found)} actual executions of {point}")
    return found[0]


def _route_application_of(env, record):
    """(K の文書) → その実行が使った route の実適用 (EW.route_operation → 保持した RouteApplicationObservation)。
    保存した route_config や K.args.route から推測しない。"""
    execution = _execution_of(env, record)
    if isinstance(execution, Missing):
        return execution
    if execution.route_operation is None:
        return Missing("route application: the execution has no route operation")
    found = [a for a in env.evidence.route_applications if a.operation is execution.route_operation]
    if len(found) != 1:
        return Missing(f"route application: {len(found)} retained applications for the execution")
    if found[0].publication is None:
        return Missing("route application: the route_config of the application is not confirmed")
    return found[0]


def _event_route(env, event, record, *_evidence):
    """event_route (正本 ENUMERATION_SOURCES): 出来事の実操作がたどる route の確定した Point。K.args.route・B.route とは
    呼んだ側が独立に比べる (ここで期待値から選ばない)。"""
    if env.evidence is None:
        return Missing("event_route: no independent observations")
    if event in ("route_applied", "work_entered"):
        application = _route_application_of(env, record)
        return application if isinstance(application, Missing) else application.publication
    if event == "report_received":
        point = env.point_of(record)
        if point is None:
            return Missing("event_route(report_received): the record is not bound to a point")
        owners = [e for e in env.evidence.executions if any(r.point == point for r in e.reports)]
        if len(owners) != 1:
            return Missing(f"event_route(report_received): {len(owners)} executions received {point}")
        if owners[0].route_operation is None:
            return Missing("event_route(report_received): the receiving execution has no route operation")
        found = [a for a in env.evidence.route_applications if a.operation is owners[0].route_operation]
        if len(found) != 1 or found[0].publication is None:
            return Missing("event_route(report_received): the route application is not retained")
        return found[0].publication
    return Missing(f"event_route: event {event!r} is not connected")


def _clock_at(env, clock, ns, record, *_evidence):
    """(時計の Ref, ns, record) → ClockReading。時計の宣言 (sui.clock.source/1) が読み手の中に 1 つ無ければ MISSING。"""
    from . import _fb_uses as uses
    if not isinstance(clock, str):
        return Missing("clock_at: clock is not a Ref")
    if env.reader is None:
        return Missing("clock_at: no reader")
    try:
        env.reader.clock_source(clock)
    except uses.Unresolved as exc:
        return Missing(f"clock_at: {exc}")
    if not isinstance(ns, int) or isinstance(ns, bool):
        return Missing("clock_at: ns is not an integer")
    return _clock_reading(clock, ns)


def _claim_window(env, claim):
    from ._fb_a1 import _at
    return _at(claim, "/item[kind=claim]/value/interval")


def _same_event_clock_links(env, *records):
    """型付きの時計参照 (inline の reading と保存した clock_reading の対) を全深さ走査して列挙する。保存した読みが
    sui.f.clock_reading/1 の記録でなければ (時計の宣言 clock.source を指す inline の読みだけなら) 対は無い = 空 (記録で決まる)。"""
    from . import _fb_uses as uses
    out = []

    def walk(node, path):
        if hasattr(node, "items"):
            if set(node) == {"reading", "source"} and isinstance(node.get("source"), str) and env.reader is not None:
                try:
                    contract, saved = env.reader.document(node["source"])
                except uses.Unresolved:
                    out.append({"inline": node["reading"], "saved": Missing(f"{path}: source not readable")})
                    return
                if contract == "sui.f.clock_reading/1":
                    out.append({"inline": node["reading"], "saved": saved.get("reading", Missing("no reading"))})
                return
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}/{i}")
    for record in records:
        if hasattr(record, "items"):
            walk(record, "")
    return out


def _generation_clock_links(env, reading, *_records):
    """Reading の生成・射影・時刻射影の版の組を VERSIONED_CLOCK_EXTENSIONS に完全一致させ、その extra_pairs。未登録の組は MISSING。"""
    from . import _fb_rules as rules
    from ._fb_uses import contract_name
    try:
        key = (contract_name(reading["generation"]["contract"]), contract_name(reading["projection"]["contract"]),
               contract_name(reading["projection"]["args"]["time_projection"]["contract"]))
    except (KeyError, TypeError):
        return Missing("generation_clock_links: the reading has no generation/projection/time_projection contracts")
    for ext in rules.VERSIONED_CLOCK_EXTENSIONS:
        if (ext["generation"], ext["projection"], ext["time_projection"]) == key:
            return list(ext["extra_pairs"])
    return Missing(f"generation_clock_links: the versions {key} are not registered (missing_contract)")


_SOURCES.update({
    "item_field": _item_field, "event_reading": _event_reading, "clock_at": _clock_at, "claim_window": _claim_window,
    "same_event_clock_links": _same_event_clock_links, "generation_clock_links": _generation_clock_links,
})


@derivation("boundary_reading")
def boundary_reading(env, boundary):
    """(Started または Ended) → ClockReading。/item/value/reading[kind=clock]/value/reading。unavailable は MISSING。
    先に枝を確かめる (正本 v1.3.10 boundary_authentication): 読めた境目でない記録 (Claim など) は不適合で、時計の不足にしない。"""
    from ._fb_a1 import Mismatch, _at
    kind = _at(boundary, "/item/kind")
    if isinstance(kind, Missing):
        return kind
    if kind not in ("started", "ended"):
        return Mismatch(f"boundary_reading: the record is a {kind!r} report, not a boundary",
                        code="observation_binding_mismatch")
    found = _at(boundary, "/item/value/reading[kind=clock]/value/reading")
    if isinstance(found, Missing):
        return Missing("boundary_reading: the boundary has no clock reading (unavailable)")
    return found


@derivation("clock_pairs")
def clock_pairs(env, b, reading, claim, k, *_evidence):
    """(B, Reading, Claim, K, EW, EH, EA) → [{kind: equal|le, left: ClockReading, right: ClockReading}]。
    CLOCK_PAIRS の宣言を原子 + each で読む (enumerate_block)。対の種類は表、件数は記録で決まる。"""
    return [{"id": pair["id"], "kind": pair["kind"], "left": pair["left"], "right": pair["right"]}
            for pair in enumerate_block(env, "CLOCK_PAIRS")]


@derivation("history_acquisition")
def history_acquisition(env, a, g, r, acquisitions):
    """(A*, G, R*, EA) → AcquisitionObservation {origin, contents, acquired_ns}。origin と contents が G と同じで、G.clock
    (保存した clock_reading) が証す取得時刻と acquired_ns が一致する観測。別の観測の origin/contents/時刻を合成しない。
    対応する観測が無ければ MISSING。G.clock が読めなければ MISSING (時刻を数値だけで合わせない)。"""
    from . import _fb_uses as uses
    from ._fb_a1 import _at
    try:
        origin, contents, clock = g["origin"], sorted(g["contents"]), g["clock"]
    except (KeyError, TypeError):
        return Missing("history_acquisition: G is not a content_acquired record")
    if env.reader is None:
        return Missing("history_acquisition: no reader for G.clock")
    try:
        contract, reading_record = env.reader.document(clock)
    except uses.Unresolved as exc:
        return Missing(f"history_acquisition: G.clock is not readable ({exc})")
    if contract != "sui.f.clock_reading/1":
        return Missing(f"history_acquisition: G.clock is {contract}, not a clock_reading")
    time_ns = _at(reading_record, "/reading/time_ns")
    if isinstance(time_ns, Missing):
        return time_ns
    # 同じ G に対応する観測 = origin と contents が同じもの (取得の同一性)。時刻の前後の照合は別の原子 (ADOPTION_TIMES・
    # A1-HISTORY-ACQUIRE-BEFORE-ADOPT) が持つので、ここで時刻の不一致を「無い」にしない (読取りの欠落と確定した不一致を分ける)。
    # 合法な再取得が複数あれば G.clock の時刻と同じものを選び、無ければ最も早いもの (別の観測の値を合成しない)
    found = [x for x in acquisitions if x.get("origin") == origin and sorted(x.get("contents", ())) == contents]
    if not found:
        return Missing("history_acquisition: no acquisition observation matches G (origin, contents)")
    same = [x for x in found if x.get("acquired_ns") == time_ns]
    chosen = same[0] if same else min(found, key=lambda x: x.get("acquired_ns", 0))
    return {"origin": chosen["origin"], "contents": sorted(chosen["contents"]), "acquired_ns": chosen["acquired_ns"],
            "run": chosen.get("run")}


# ---------------------------------------------------------------- 一覧表の records モード (each の出現ごとに成分を組む)

def enumerate_records(env, block_name):
    """一覧表の records モード: ブロックの `each` の各出現を Item に束縛し、各 item の path に value (operand) を解いて
    1 件の記録 {成分: 値} を組む。[記録] (出現の順)。each が読めなければ Missing。これも「原子 + each」の読み方。"""
    from ._fb_a1 import Env, Missing as _Missing, Quantified, resolve
    block = _SPECS[block_name]
    elements = resolve(env, block["each"])
    if isinstance(elements, _Missing):
        return elements
    if isinstance(elements, Quantified):
        elements = list(elements.values)
    out = []
    for element in elements:
        if isinstance(element, _Missing):
            # each の出現そのものが読めない (必要な使用の観測が無い等): 全成分をその理由の Missing にして残す (消さない)
            out.append({item["path"].lstrip("/"): element for item in block["items"]})
            continue
        scope = Env({**env.records, "Item": (None, element)}, evidence=env.evidence, reader=env.reader,
                    effects=env.effects, stages=env.stages, registry=env.registry, compiler=env.compiler)
        record = {}
        for item in block["items"]:
            if item.get("when", True) is not True:
                return _Missing(f"{block_name}: conditional component {item['id']} is not connected")
            record[item["path"].lstrip("/")] = resolve(scope, item["value"])
        out.append(record)
    return out


_ACQUISITION_OBLIGATION_ROWS = {   # 取得を要する観測の入力 (正本 ENUMERATION_SOURCES.input_use_obligations、K5 :3497 の 5 種)
    "sui.fb.work_requested/1": ("REF-Q-BINDING", "REF-Q-READING"),
    "sui.fb.segment_binding/1": ("REF-B-REPORT", "REF-B-SUPPORT"),
    "sui.f.observation_plan/2": ("REF-READING-LAW",),
}


def _input_use_obligations(env, q, *_evidence):
    """(Q, EW) → 取得を要する観測の入力 (Q の observations から REF-Q-BINDING・REF-Q-READING、その B の REF-B-REPORT・必要な
    REF-B-SUPPORT、その Reading の REF-READING-LAW を解いて先に導く) ごとに、当該 Wu の実使用 (UseObservation) の全出現。
    必要な対象の使用の観測が無ければ MISSING の出現として残す (空列にしない)。C 全体・uses 全件・input_points は分母にしない。"""
    from . import _fb_uses as uses
    from ._fb_a1 import _json
    if env.evidence is None or env.reader is None:
        return Missing("input_use_obligations: no independent observations or reader")
    try:
        work_id = q["desc"]["work_id"]
    except (KeyError, TypeError):
        return Missing("input_use_obligations: the record is not a request")
    targets, queue = [], [(env.point_of(q), "sui.fb.work_requested/1", q)]
    while queue:
        start, contract, document = queue.pop(0)
        for row_id in _ACQUISITION_OBLIGATION_ROWS.get(contract, ()):
            row = uses._REF_BY_ID[row_id]
            try:
                obligations = uses._row_obligations(env.reader, row, start, document, _context_for(env, row, start))
            except uses.Unresolved as exc:
                return Missing(f"input_use_obligations: {row_id} does not resolve ({exc})")
            except uses.Unsupported as exc:
                return Missing(f"input_use_obligations: {row_id} is not supported ({exc})", code="algorithm_unavailable")
            for ob in obligations:
                if ob.target is None:
                    continue
                targets.append(ob.target)
                target_contract = env.reader.contract_of(ob.target)
                if target_contract in _ACQUISITION_OBLIGATION_ROWS:
                    queue.append((ob.target, target_contract, env.reader.document(ob.target)[1]))
    out = [m for m in _support_targets(env, q, work_id) if isinstance(m, Missing)]
    targets += [m for m in _support_targets(env, q, work_id) if not isinstance(m, Missing)]
    for target in dict.fromkeys(targets):
        found = [_json(u) for u in env.evidence.uses if u.work_id == work_id and u.point == target]
        out += found if found else [Missing(f"input_use_obligations: no use of {target} by {work_id} is observed")]
    return out


def _support_targets(env, q, work_id):
    """Support (監視の記録 monitor_span) の取得義務: B.evidence には無く、固定像の中から同じ segment・route・clock で原 Claim の
    窓を覆う monitor_span を選ぶ (紙 §19-5 whole_window、K4/K5 :3496-3497、表の係 13 通目 (イ))。覆う記録のうち当該 Wu が
    実際に使ったものが取得義務の対象。覆う記録があるのに Wu が使っていなければ MISSING の出現 (消さない)。"""
    from . import _fb_uses as uses
    from ._fb_a1 import _at
    image = _parent_image(env)
    if image is None or env.reader is None:
        return []
    used = {u.point for u in env.evidence.uses if u.work_id == work_id}
    out = []
    for use in q.get("desc", {}).get("args", {}).get("observations", ()):
        try:
            b = env.reader.document(use["binding"])[1]
            claim = env.reader.document(b["report"])[1]
            window = _at(claim, "/item[kind=claim]/value/interval")
            route = env.reader.document(b["route"])[1]
        except (uses.Unresolved, KeyError, TypeError):
            continue
        if isinstance(window, Missing):
            continue
        effective = _at(route, "/effective_from[kind=clock]/value/time_ns")
        covering = []
        for entry in getattr(image, "all_entries", image.entries)():
            try:
                if env.reader.contract_of(entry.cid) != "sui.fb.monitor_span/1":
                    continue
                _c, m = env.reader.document(entry.cid)
            except uses.Unresolved:
                continue
            if m.get("segment") != b.get("segment") or m.get("route") != b.get("route") or [m.get("clock")] != list(b.get("clock", ())):
                continue
            if not isinstance(effective, Missing) and effective <= window["start_ns"]                     and m.get("entered_ns", 0) <= window["start_ns"] and window["end_ns"] <= m.get("observed_ns", -1):
                covering.append(entry.cid)
        chosen = [p for p in covering if p in used]
        out += chosen if chosen or not covering else [Missing(f"input_use_obligations: no covering monitor record of {b.get('report')} was used by {work_id}")]
    return out


def _context_for(env, row, b_point):
    """REF-B-SUPPORT の条件 support_required は B の読み方 (Reading の生成の契約) から。他の行は文脈なし。"""
    if row["id"] != "REF-B-SUPPORT":
        return None
    reading = _reading_of(env, b_point)
    if reading is None:
        return None
    from ._fb_uses import contract_name
    generation = contract_name(reading["generation"]["contract"])
    return {"generation": generation, "support_required": generation == "sui.fb.bootstrap_generation/1"}


def _reading_of(env, b_point):
    """B (segment_binding) に対応する Reading: Q* の observations で同じ binding を持つ対の reading。"""
    q = env.document("Q*")
    if q is None:
        return None
    for use in q.get("desc", {}).get("args", {}).get("observations", ()):
        if use.get("binding") == b_point:
            try:
                return env.reader.document(use["reading"])[1]
            except Exception:   # noqa: BLE001
                return None
    return None


def _acquisition_for_use(env, q, *_evidence):
    """(Q, EA, EW) → 当該 each の実使用 (Item) の point を Q.reader が同じ run 上で acquired_ns ≤ used_ns に取得した EA (any)。
    別の証人の origin/contents/時刻を合成しない。無ければ MISSING。"""
    from ._fb_a1 import _json
    use = _current_item(env)
    if isinstance(use, Missing):
        return use   # 必要な使用の観測が無い出現 (消さずに残した MISSING) は理由ごと運ぶ
    if use is None or env.evidence is None:
        return Missing("acquisition_for_use: outside an each or no observations")
    try:
        origin = q["desc"]["reader"]
    except (KeyError, TypeError):
        return Missing("acquisition_for_use: the request has no reader")
    if use.get("run") is None:
        return Missing("acquisition_for_use: the host run of the use is not recorded")
    for x in env.evidence.acquisitions:
        if x.origin == origin and use["point"] in x.contents and x.run is not None and _json(x.run) == _json(use["run"]) \
                and x.acquired_ns <= use["used_ns"]:
            return _json(x)
    return Missing(f"acquisition_for_use: no acquisition of {use['point']} by {origin} before its use on the same run")


def _acquired_point(env, acquisition, point):
    """(AcquisitionObservation, Point) → contents への実所属を確かめた同じ Point。非所属・未読は MISSING。"""
    if not hasattr(acquisition, "items") or not isinstance(point, str):
        return Missing("acquired_point: not an acquisition and a point")
    if point not in acquisition.get("contents", ()):
        return Missing(f"acquired_point: {point} is not in the acquisition's contents")
    return point


def _observation_run(env, kind, observation, *_evidence):
    """(kind, observation, EW, EA) → その独立観測を作った host/run。DTO に無ければ MISSING (時刻の整数から補わない)。"""
    if not hasattr(observation, "items"):
        return Missing(f"observation_run({kind}): no observation")
    run = observation.get("run")
    return Missing(f"observation_run({kind}): the host run is not recorded") if run is None else run


def _compiler_field(env, q, pointer):
    """(Q*, Pointer) → 評価の頭の compiler の欄 (/model = source、/origin = origin_point)。入口 U では無い (MISSING)。"""
    if env.compiler is None:
        return Missing("compiler_field: no compiler (not the evaluation head)")
    if pointer == "/model":
        return env.compiler.source
    if pointer == "/origin":
        return env.compiler.origin_point
    return Missing(f"compiler_field: {pointer} is not a compiler field")


def _support_used_records(env, q, *_records):
    """(Q*, B, Reading, Claim, Xnum, EW) → 固定像の中の被覆の候補 (同じ segment・route・clock で原 Claim の窓を覆う monitor_span)
    のうち当該 Wu が実際に使った記録の Point の列。候補があるのに使っていなければ MISSING の出現 (表の係 14 通目、SUPPORT-POINTS)。"""
    try:
        work_id = q["desc"]["work_id"]
    except (KeyError, TypeError):
        return Missing("support_used_records: the record is not a request")
    return _support_targets(env, q, work_id)


_SOURCES.update({"support_used_records": _support_used_records})
_SOURCES.update({"input_use_obligations": _input_use_obligations, "acquisition_for_use": _acquisition_for_use,
                 "acquired_point": _acquired_point, "observation_run": _observation_run, "compiler_field": _compiler_field})


@derivation("input_acquisitions")
def input_acquisitions(env, q, *_evidence):
    """(Q, EA, EW) → [{acquired_origin, used_origin, acquired_point, used_point, acquired_run, used_run, acquired_ns, used_ns}]
    (INPUT_ACQUISITIONS を原子 + each で)。実使用 1 件ごとに 1 記録。"""
    return enumerate_records(env, "INPUT_ACQUISITIONS")


@derivation("historical_uses")
def historical_uses(env, a, r, *_evidence):
    """(A*, R*, EA, EW) → [{acquired_run, used_run, acquired_ns, used_ns}] (HISTORICAL_USES: R* の実使用ごと)。"""
    return enumerate_records(env, "HISTORICAL_USES")


@derivation("model_links")
def model_links(env, q):
    """(Q) → [{actual, expected}] (MODEL_LINKS を原子 + each で。output_fields: left = actual、right = expected)。"""
    return [{"id": pair["id"], "actual": pair["left"], "expected": pair["right"]} for pair in enumerate_block(env, "MODEL_LINKS")]


@derivation("registry")
def registry(env, key):
    """(保存した registry_key) → {declarations, implementations} = 今の registry の全宣言と実装の識別。保存 key が今の registry の
    identity と違えば MISSING (未知の版を今の registry に置き換えない、§19-10。不足 = algorithm_unavailable / replay)。"""
    from ._f_world import registry_view_key
    from ._fb_a1 import _json
    if env.registry is None:
        return Missing("registry: no registry in this evaluation")
    if key != registry_view_key(env.registry):
        return Missing("registry: the request's registry is not this registry", code="algorithm_unavailable",
                       need={"kind": "capability", "value": {"contract": {"name": "sui.f.finite_update_compute", "version": "1"},
                                                              "purpose": "replay"}})
    return {"declarations": [{"kind": d.kind, "ref": _json(d.ref)} for d in env.registry.declarations],
            "implementations": [{"kind": i.kind, "ref": _json(i.ref), "identity": i.identity} for i in env.registry.implementations]}


@derivation("shape_of")
def shape_of(env, value, type_name=None):
    """(value, 宣言型名) → 版付き構造宣言との相違の列 (正常は空列)。型名は fb の DTO の名前 (UpdateArgs など)。
    記録全体 (型名なし、A1-SHAPE) はまだ接続していない (MISSING = 不足)。"""
    if type_name is None:
        return _record_shape(env, value)
    from . import fb as _fb
    from .f import FInputError, _decode
    typ = getattr(_fb, type_name, None)
    if typ is None:
        return Missing(f"shape_of: unknown declared type {type_name!r} (missing_contract)")
    try:
        _decode(value, typ)
    except FInputError as exc:
        # 違反の kind は F-a A-20/A-21 の構造検査の型付き reason (schema / shape / noncanonical / rational / unit / unknown_version /
        # normalization、DERIVED_FIELDS FIELD-SHAPE_OF-KIND)。他の種類の reason は shape に含めない (未知 = そのまま残す)
        return [{"kind": getattr(exc, "reason", "shape"), "field": getattr(exc, "field", None), "detail": str(exc)}]
    except (TypeError, KeyError, ValueError, AttributeError) as exc:
        return [{"kind": "shape", "field": None, "detail": f"{type_name}: {exc}"}]
    return []


# ---------------------------------------------------------------- 像 (固定像・部分像・鍵) と未来の記録

def _parent_image(env):
    """Q* を読んだ親の像 (Env の読み手の像)。無ければ None。"""
    return getattr(env.reader, "_image", None) if env.reader is not None else None


@derivation("parent_view")
def parent_view(env, q):
    """(Q) → 直上の再構成 Q の Xnum、最外だけ許された入口の親側像 (= Q* を読んだ像)。再帰で最初の広い base に戻らない。"""
    image = _parent_image(env)
    return Missing("parent_view: no parent image") if image is None else image


@derivation("numerical_view")
def numerical_view(env, q):
    """(Q) → Q.numerical_view.boundary から親側で実構成した Xnum (捕捉した像 `_Sub` + capture_reader、保存した予算で)。
    保存 view_key は照合の相手で、構成の正解にしない。Q が束ねた Q* なら親は Q* を読んだ像。Q が Point (via で辿った前の系列の
    要求) なら、親はすぐ上の Q* の Xnum (CLOSURE_TERMS の recursive_parent: 子の像は直上の像の中で作る、最初の広い像に戻らない)。"""
    from ._f_world import capture_reader
    from .f import FIncomplete, FReplayUnavailable, _decode
    from .f_update2 import _Sub
    from .f_update2 import UpdateBudget
    if isinstance(q, str):
        upper = env.document("Q*")
        if upper is None or q == env.point("Q*"):
            return Missing("numerical_view: no request above the given point")
        image = numerical_view(env, upper)
        if isinstance(image, Missing):
            return image
        try:
            _contract, q = _Reader(image).document(q)
        except Exception as exc:   # noqa: BLE001 — 直上の像の外 = その中で作れない
            return Missing(f"numerical_view: the request is outside the upper view: {exc}")
    else:
        image = _parent_image(env)
    if image is None:
        return Missing("numerical_view: no parent image")
    try:
        boundary = frozenset(q["desc"]["numerical_view"]["boundary"])
        budget = _decode(q["desc"]["args"]["budget"], UpdateBudget).numerical
    except (KeyError, TypeError, Exception):   # noqa: BLE001 — 形の不正は A1-SHAPE の行が別に落とす
        return Missing("numerical_view: the request has no readable numerical_view / budget")
    try:
        return capture_reader(_Sub(image, boundary), budget)
    except (KeyError, FReplayUnavailable):
        return Missing("numerical_view: the boundary is outside the reader")
    except FIncomplete:
        return Missing("numerical_view: the reader budget is exhausted", code="budget_exhausted",
                       need={"kind": "budget", "value": {"phase": "reader"}})


def _Reader(image):
    from ._fb_uses import Reader
    return Reader(image)


@derivation("points")
def points(env, view):
    """(view) → 許可された像の Point の集合 (header で範囲を確定。本文は読まない)。整列した列。"""
    if isinstance(view, Missing):
        return view
    entries = getattr(view, "all_entries", None) or getattr(view, "entries", None)   # 像の全部 (出来事だけでなく派生物も、header で)
    if entries is None:
        return Missing("points: not an image")
    return sorted(e.cid for e in entries())


@derivation("view_key")
def view_key(env, view):
    """(実構成 view) → F-a E-06 の像の鍵 (CID/header/body の有無と bytes)。保存 key から逆算しない。"""
    if isinstance(view, Missing):
        return view
    key = getattr(view, "view_key", None)
    return Missing("view_key: the image has no view key") if key is None else key


@derivation("intersection")
def intersection(env, a, b):
    """(setA, setB) → 型を保った共通部分 (正準の形で比べる)。"""
    from ._fb_a1 import _canon
    pool = {_canon(v) for v in (b or ())}
    return [v for v in (a or ()) if _canon(v) in pool]


def _future_record(env, q, role):
    """(Q, role) → 役割の対象の Point の集合 (整列した列、ENUMERATION_SOURCES.future_record の形): self は [Q]、result /
    acquisition / adoption は同じ Q に対応する既存の未来側の記録 (親の像の中、契約で絞って本文を読む)。独立に確認した未作成は
    空の集合、読めなければ Missing。仮の CID は作らない。"""
    from . import _fb_uses as uses
    point = env.point_of(q)
    if role == "self":
        return [point] if point is not None else Missing("future_record(self): Q is not bound")
    image = _parent_image(env)
    if image is None or point is None:
        return Missing(f"future_record({role}): no parent image")
    wanted = {"result": "sui.fb.update_result/1", "acquisition": "sui.f.content_acquired/1", "adoption": "sui.fb.belief_adopted/1"}.get(role)
    if wanted is None:
        return Missing(f"future_record: unknown role {role!r} (missing_contract)")
    reader = env.reader
    results = None
    for entry in getattr(image, "all_entries", image.entries)():
        try:
            if reader.contract_of(entry.cid) != wanted:
                continue
            _c, document = reader.document(entry.cid)
        except uses.Unresolved:
            return Missing(f"future_record({role}): a {wanted} record is not readable")
        if role == "result" and document.get("request") == point:
            return [entry.cid]
        if role == "adoption" and document.get("request") == point:
            return [entry.cid]
        if role == "acquisition":
            if results is None:
                results = {r for r in _results_of(env, image, point)}
            if any(p in results for p in document.get("contents", ())):
                return [entry.cid]
    return []


def _results_of(env, image, point):
    from . import _fb_uses as uses
    reader = env.reader
    for entry in getattr(image, "all_entries", image.entries)():
        try:
            if reader.contract_of(entry.cid) == "sui.fb.update_result/1" and reader.document(entry.cid)[1].get("request") == point:
                yield entry.cid
        except uses.Unresolved:
            continue


_SOURCES["future_record"] = _future_record


@derivation("future_records")
def future_records(env, q):
    """(Q) → {self, result, acquisition, adoption}: Q 自身と、Q の将来の R / G / A に当たる既存の点を役割別に保った集合 (各役割は
    列。独立に確認した未作成だけ空列、読めなければ MISSING)。FUTURE_RECORD_ROLES を record モードで読む (表の係 14 通目: 4 成分、
    和は旧の 1 集合と同じ)。"""
    from ._fb_a1 import resolve
    out = {}
    for item in _SPECS["FUTURE_RECORD_ROLES"]["items"]:
        value = resolve(env, item["value"])
        if isinstance(value, Missing):
            return value
        out[item["path"].lstrip("/")] = list(value)
    return out


# ---------------------------------------------------------------- 採用の時刻 (ADOPTION_TIMES) と祖先

def _record_metadata(env, record, pointer):
    """(record, Pointer) → 記録の header の値 (/at/mono_ns・/at/run) か本文の外側の欄 (/body/received_ns)。読み手の像の entry から。"""
    from . import _fb_uses as uses
    point = env.point_of(record)
    image = _parent_image(env)
    if point is None or image is None:
        return Missing("record_metadata: the record is not bound or no image")
    try:
        entry = image.entry(point)
    except (KeyError, LookupError):
        return Missing(f"record_metadata: {point} has no entry in the image")
    if pointer == "/at/mono_ns":
        return entry.at.mono_ns
    if pointer == "/at/run":
        from ._fb_a1 import _json
        return _json(entry.at.run)
    if pointer == "/body/received_ns":
        try:
            value = image.record(point).body.received_ns
        except (KeyError, LookupError, AttributeError):
            return Missing(f"record_metadata: {point} has no body.received_ns")
        return value if value is not None else Missing(f"record_metadata: {point}.received_ns is null")
    return Missing(f"record_metadata: {pointer} is not a metadata field")


def _comparison_run(env, r, g, a, *_evidence):
    """(R*, G, A*, EW, EH, EA) → 生成・実取得・採用の時計の run が独立の対応で全部同じならその run。1 つでも読めない・違えば MISSING。"""
    from ._fb_a1 import _json
    runs = []
    generated = _event_reading(env, "result_generated", r)
    acquired = _event_reading(env, "content_acquired", g)
    for value in (generated, acquired):
        if isinstance(value, Missing):
            return value
        runs.append(_json(value["run"]))
    for record in (g, a):
        run = _record_metadata(env, record, "/at/run")
        if isinstance(run, Missing):
            return run
        runs.append(_json(run))
    if len({str(x) for x in runs}) != 1:
        return Missing(f"comparison_run: the runs differ {runs}")
    return runs[0]


_SOURCES.update({"record_metadata": _record_metadata, "comparison_run": _comparison_run})


def _event_reading_extended(env, event, record, *evidence):
    """event_reading の続き: result_generated (R* の生成 = Q* の仕事の最初の返答 (issued) の EH の受信) と content_acquired (G に
    対応する EA の acquired_ns)。他は元の _event_reading。"""
    if event == "result_generated":
        if env.evidence is None:
            return Missing("event_reading(result_generated): no independent observations")
        q = env.document("Q*")
        if q is None:
            return Missing("event_reading(result_generated): Q* is not bound")
        try:
            work_id = q["desc"]["work_id"]
        except (KeyError, TypeError):
            return Missing("event_reading(result_generated): Q* has no work_id")
        from . import _fb_uses as uses
        try:
            basis = env.reader.points(record.get("basis", ())) if hasattr(record, "items") and env.reader is not None else ()
        except uses.Unresolved as exc:
            return Missing(f"event_reading(result_generated): R*.basis does not resolve ({exc})")
        q_point = env.point_of(q)
        ends = [p for p in basis if p != q_point]
        found = [rep for e in env.evidence.executions if e.work_id == work_id for rep in e.reports if rep.point in ends]
        if not found:
            return Missing("event_reading(result_generated): the first end of R* was not received from the update work")
        first = min(found, key=lambda rep: (rep.received_ns, rep.envelope))
        if first.run is None:
            return Missing("event_reading(result_generated): the host run of the receipt is not recorded")
        return _clock_reading(first.run, first.received_ns)
    if event == "content_acquired":
        a_doc = env.document("A*")
        r_doc = env.document("R*")
        acq = history_acquisition(env, a_doc, record, r_doc, [_json_obs(x) for x in env.evidence.acquisitions]) \
            if env.evidence is not None else Missing("no observations")
        if isinstance(acq, Missing):
            return acq
        if acq.get("run") is None:
            return Missing("event_reading(content_acquired): the host run of the acquisition is not recorded")
        return _clock_reading(acq["run"], acq["acquired_ns"])
    return _event_reading_base(env, event, record, *evidence)


def _json_obs(x):
    from ._fb_a1 import _json
    return _json(x)


_event_reading_base = _event_reading
_event_reading = _event_reading_extended
_SOURCES["event_reading"] = _event_reading
_SOURCES["event_route"] = _event_route


@derivation("tuple")
def tuple_(env, *operands):
    """(operand…) → 順序と重複を保った列。MISSING の要素は保持する (present が拾う)。"""
    return list(operands)


@derivation("ancestors")
def ancestors(env, record):
    """(record) → Entry の実親を推移展開した Point の集合 (整列した列)。候補は準備済みの実親から (仮の CID は作らない)。"""
    point = env.point_of(record)
    image = _parent_image(env)
    if point is None or image is None:
        return Missing("ancestors: the record is not bound or no image")
    try:
        return sorted(image.ancestors(frozenset({point})))
    except (KeyError, LookupError):
        return Missing(f"ancestors: {point} is not in the image")


@derivation("adoption_times")
def adoption_times(env, a, r, g, *_evidence):
    """(A*, R*, G, EA, EW, EH) → {g, a, r, adopted, runs, expected_runs} (ADOPTION_TIMES を record モードで: 各成分を解く)。"""
    from ._fb_a1 import resolve
    out = {}
    for item in _SPECS["ADOPTION_TIMES"]["items"]:
        out[item["path"].lstrip("/")] = resolve(env, item["value"])
    return out


# ---------------------------------------------------------------- 能力 (registry と使用する契約)

def _capability_identity(kind, ref):
    from ._fb_a1 import _json
    return {"kind": kind, "ref": _json(ref)}


@derivation("capabilities")
def capabilities(env, q, view):
    """(Q, Xnum) → この Q* の再構成が使う能力 (kind と ContractRef の組) の集合。T-REF と一次本文から導く (呼出し側の一覧を正解に
    しない): Q.desc.method (method)、各観測の Reading の契約 (method)・生成 (generation)・射影 (projection)・時刻射影 (clock)、
    原 Claim の意味 (projection)、Law の契約 (generation)。読めない所は MISSING。"""
    from . import _fb_uses as uses
    from ._fb_a1 import _at
    if env.reader is None:
        return Missing("capabilities: no reader")
    out, seen = [], set()

    def add(kind, ref):
        if isinstance(ref, Missing):
            return ref
        item = _capability_identity(kind, ref)
        key = (kind, str(item["ref"]))
        if key not in seen:
            seen.add(key)
            out.append(item)
        return None

    missing = add("method", _at(q, "/desc/method"))
    if missing:
        return missing
    for use in q.get("desc", {}).get("args", {}).get("observations", ()):
        try:
            reading_contract, reading = env.reader.document(use["reading"])
            _c, b = env.reader.document(use["binding"])
            _c2, claim = env.reader.document(b["report"])
        except (uses.Unresolved, KeyError, TypeError) as exc:
            return Missing(f"capabilities: an observation record is not readable ({exc})")
        name, version = reading_contract.rsplit("/", 1)
        for kind, value in (("method", {"name": name, "version": version}),
                            ("generation", _at(reading, "/generation/contract")),
                            ("projection", _at(reading, "/projection/contract")),
                            ("clock", _at(reading, "/projection/args/time_projection/contract")),
                            ("projection", _at(claim, "/item[kind=claim]/value/contract"))):
            missing = add(kind, value)
            if missing:
                return missing
        for entry in reading.get("projection", {}).get("args", {}).get("claims", ()):
            try:
                law_contract, _law = env.reader.document(entry["law"])
            except (uses.Unresolved, KeyError, TypeError) as exc:
                return Missing(f"capabilities: the law is not readable ({exc})")
            name, version = law_contract.rsplit("/", 1)
            add("generation", {"name": name, "version": version})
    return out


@derivation("implementations")
def implementations(env, registry_view, caps):
    """(registry, capabilities) → 各能力に対応する明示の実装の identity の列 (能力の順)。1 つでも未提供なら MISSING。"""
    if isinstance(registry_view, Missing) or isinstance(caps, Missing):
        return registry_view if isinstance(registry_view, Missing) else caps
    from ._fb_a1 import _canon
    by_key = {(i["kind"], _canon(i["ref"])): i["identity"] for i in registry_view.get("implementations", ())}
    out = []
    for cap in caps:
        identity = by_key.get((cap["kind"], _canon(cap["ref"])))
        if identity is None:
            # 宣言はあるが実装が無い = 能力の不足 (A4: Insufficient / algorithm_unavailable。宣言が無いのは別の原子の missing_contract)
            return Missing(f"implementations: no implementation of {cap['kind']} {cap['ref']} in this registry",
                           code="algorithm_unavailable", need={"kind": "capability", "value": {"contract": cap["ref"], "purpose": "computation"}})
        out.append(identity)
    return out


@derivation("count")
def count(env, collection):
    """(collection) → 要素数 (重複を除かない)。列でなければ MISSING。"""
    if isinstance(collection, Missing):
        return collection
    if isinstance(collection, (list, tuple)):
        return len(collection)
    return Missing("count: not a collection")


# ---------------------------------------------------------------- 記録の同一性 (scope records: 閉包と全 I で読む各 record)

def _payload_json(payload):
    """Payload を比べられる JSON の形に (media_type と bytes の base64)。"""
    import base64
    return {"media_type": payload.media_type, "data": base64.b64encode(payload.data).decode("ascii")}


@derivation("entry")
def entry(env, record):
    """(Record) → 実 Entry の値 {cid, header, seal, parents, salt, payload}。payload は実際に保存された本文の bytes、header・seal は
    実 Entry の値 (保存契約に仮想の欄を足すのではない)。Point の対応は束縛した文書から (point_of)。本文が無ければ Missing。"""
    point = env.point_of(record)
    image = _parent_image(env)
    if point is None or image is None:
        return Missing("entry: the value is not a bound record")
    try:
        found = image.entry(point)
        salt, payload = image.sealed_content(point)
    except LookupError as exc:   # KeyError (像の外)・FReplayUnavailable (本文が読めない)
        return Missing(f"entry: {point} is not readable: {exc}")
    return {"cid": found.cid, "header": found.header.decode("utf-8"), "seal": found.seal,
            "parents": sorted(found.parents), "salt": salt.hex(), "payload": _payload_json(payload)}


@derivation("seal_of")
def seal_of(env, found):
    """(entry) → F-a A-01 の塩・本文から再計算した seal (保存した seal を返すのではない)。"""
    import base64
    from .ledger import seal
    from .records import Payload
    try:
        payload = Payload(found["payload"]["media_type"], base64.b64decode(found["payload"]["data"]))
        return seal(payload, bytes.fromhex(found["salt"]))
    except (KeyError, TypeError, ValueError) as exc:
        return Missing(f"seal_of: {exc}")


@derivation("cid_of")
def cid_of(env, found):
    """(entry) → header・seal・正準本文から再計算した CID: 保存した header と本文を復号し、再計算した seal で header を
    正準に組み直してその digest。保存した CID を返すだけの関数ではない。復号できなければ確定した不一致の印 (CID にならない値)。"""
    import base64
    import json
    from .ledger import _digest, decode_record, encode_header
    from .records import Payload
    recomputed = seal_of(env, found)
    if isinstance(recomputed, Missing):
        return recomputed
    try:
        payload = Payload(found["payload"]["media_type"], base64.b64decode(found["payload"]["data"]))
        header = found["header"].encode("utf-8")
        parents = frozenset(json.loads(header)["parents"])
        return _digest(encode_header(decode_record(header, payload), recomputed, parents))
    except Exception as exc:   # noqa: BLE001 — 壊れた header・本文は CID にならない (比較が不適合で落とす)
        return {"undecodable": f"{type(exc).__name__}: {exc}"}


@derivation("canonical_bytes")
def canonical_bytes(env, record):
    """(Record) → 版つき保存契約の正準 bytes (JSON は鍵を整列した UTF-8 の正準形、テキストは UTF-8)。保存した bytes を
    そのまま返さず、本文の値から組み直す。未知の media_type は Missing (正準形を推測しない)。"""
    import json
    from .records import Payload
    point = env.point_of(record)
    image = _parent_image(env)
    if point is None or image is None:
        return Missing("canonical_bytes: the value is not a bound record")
    try:
        payload = image.record(point).body.content
    except LookupError as exc:
        return Missing(f"canonical_bytes: {point} is not readable: {exc}")
    try:
        if payload.media_type == "application/json":
            return _payload_json(Payload.json(json.loads(payload.data)))
        if payload.media_type == "text/plain; charset=utf-8":
            return _payload_json(Payload.text(payload.data.decode("utf-8")))
    except (ValueError, UnicodeError) as exc:
        return {"undecodable": f"{type(exc).__name__}: {exc}"}
    return Missing(f"canonical_bytes: no canonical form for {payload.media_type!r}")


# ---------------------------------------------------------------- 参照の解決と I

def _resolve_one(view, ref):
    """保存した Ref 1 つ → {point, ref, bytes, causal} (許可された像の中で 1 つの CID、全 bytes、実因果 = 実親)。
    1 つに解決しない・本文が読めない時は Missing (その要素だけ。他の要素を消さない)。"""
    from ._fb_uses import Reader, Unresolved
    try:
        point = Reader(view).point(ref)
        found = view.entry(point)
        _salt, payload = view.sealed_content(point)
    except (Unresolved, LookupError) as exc:
        return Missing(f"resolved_refs: {ref} does not resolve in the view: {exc}")
    return {"point": point, "ref": str(ref), "bytes": _payload_json(payload), "causal": sorted(found.parents)}


@derivation("resolved_refs")
def resolved_refs(env, refs, view):
    """(保存した Ref の列、または参照義務の列, view) → 各参照の [{point, ref, bytes, causal}] (順と重複を保つ)。Ref を像の外の
    読み手で解かない。参照義務 (REFERENCE_OBLIGATION_PROTOCOL の型) は reference_kind が Point / Ref のものだけを解き
    (値だけの欄の認証義務に Point を捏造しない)、Point はそのまま、Ref は像の中で 1 つの CID に解く。"""
    if isinstance(view, Missing):
        return view
    if isinstance(refs, Missing):
        return refs
    if not isinstance(refs, (list, tuple)):
        return Missing("resolved_refs: not a list of references")
    out = []
    for ref in refs:
        if hasattr(ref, "items") and "reference_kind" in ref:
            if ref["reference_kind"] == "Point":
                out.append(_resolve_point(view, ref["reference"]))
            elif ref["reference_kind"] == "Ref":
                out.append(_resolve_one(view, ref["reference"]))
            continue
        out.append(_resolve_one(view, ref))
    return out


def _resolve_point(view, point):
    """Point 1 つ → {point, ref, bytes, causal} (像の中に在ること、全 bytes、実親)。無ければ Missing。"""
    try:
        found = view.entry(point)
        _salt, payload = view.sealed_content(point)
    except (LookupError, TypeError) as exc:
        return Missing(f"resolved_refs: {point} is not in the view: {exc}")
    return {"point": point, "ref": str(found.id), "bytes": _payload_json(payload), "causal": sorted(found.parents)}


@derivation("input_availability")
def input_availability(env, resolved, q):
    """(解決した I, Q) → 各 I の利用能力 {point, readable}: 余分な I も本文を読めること (存在・内容の認証) を確かめる。
    読めない I は Missing (その要素)。観測の追加や無関係な Q の再生は起こさない。"""
    view = numerical_view(env, q)
    if isinstance(view, Missing):
        return view
    out = []
    for item in resolved:
        try:
            view.record(item["point"])
            out.append({"point": item["point"], "readable": True})
        except LookupError as exc:
            out.append(Missing(f"input_availability: {item['point']} is not readable: {exc}"))
    return out


# ---------------------------------------------------------------- 必須閉包 C

@derivation("closure_keys")
def closure_keys(env, q, view):
    """(Q, Xnum) → 必須閉包 C の Point の集合 (整列した列): T-A2 / T-REF から Local(Q) ∪ History(prior) ∪ C(prior.request) ∪
    Resolve(I(prior.request)) を再帰に導く (`_fb_uses.required`、出発の Q には Local・History だけ = 保存した I を C の
    生成器にしない)。用途ごとの義務を保ってから集合にする。"""
    from . import _fb_uses as uses
    from .f_update2 import _c
    if isinstance(view, Missing):
        return view
    point = env.point_of(q)
    if point is None:
        return Missing("closure_keys: the request is not a bound record")
    if isinstance(q, str):   # via で辿った前の系列の要求の Point: 読み手 (直上の像を含む) で本文を読む
        try:
            q = env.reader.document(point)[1]
        except Exception as exc:   # noqa: BLE001
            return Missing(f"closure_keys: {point} is not readable: {exc}")
    try:
        found = uses.required(uses.Reader(view), point, uses.contract_name(_c().WORK_REQUESTED), "update", q,
                              groups=uses.A2_GROUPS, start_groups=("Local", "History"))
    except (uses.Unresolved, uses.Unsupported, uses.Malformed) as exc:
        return Missing(f"closure_keys: {type(exc).__name__}: {exc}")
    return sorted(uses.points_of(found))


@derivation("ref_projection")
def ref_projection(env, points_, view):
    """(Points, view) → 各 Point の認証した Record.id (保存した Ref の表記) の集合。像の外の Point は Missing (その要素)。"""
    if isinstance(view, Missing):
        return view
    out = {}
    for point in points_:
        try:
            out.setdefault(str(view.entry(point).id), None)
        except LookupError as exc:
            return Missing(f"ref_projection: {point} is outside the view: {exc}")
    return sorted(out)


# ---------------------------------------------------------------- 再計算 (数値の再構成)

@derivation("replay_result")
def replay_result(env, q, view):
    """(Q, Xnum) → {result: {joint, evidence_mass}, application_digest}: 認証済みの一次モデル・順の観測・保存した予算から、
    prior も再帰に再計算した値 (`f_update2._Replay` がその Q* を認証した時に計算したもの)。保存した R* からは写さない。
    その Q* をまだ再計算していなければ Missing (未計算を保存値で補わない)。数学の中身は golden・誤実装の別の検査の対象。"""
    if isinstance(view, Missing):
        return view
    point = env.point_of(q)
    found = env.replays.get(point) if point is not None else None
    return Missing(f"replay_result: {point} has not been recomputed") if found is None else found


# ---------------------------------------------------------------- 採用の系列 (scope history)

@derivation("use_view")
def use_view(env):
    """() → 当該操作の固定根 Xuse (入口 U は今の Q* の数値の像、評価の準備は compiler の見える範囲)。過去の Q の Xnum で代用しない。"""
    return Missing("use_view: the operation has no fixed root") if env.use_view is None else env.use_view


def _adoption(reader, point):
    """採用の記録 1 件の本文 (契約が採用でなければ Missing)。"""
    from ._fb_uses import Unresolved, contract_name
    from .f_update2 import _c
    try:
        name, document = reader.document(point)
    except Unresolved as exc:
        return Missing(f"adoption {point} is not readable: {exc}")
    if name != contract_name(_c().BELIEF_ADOPTED):
        return Missing(f"{point} is not an adoption ({name})")
    return document


@derivation("adoption_chain")
def adoption_chain(env, a):
    """(A) → {points, terminal}: A から previous を実際に読んでたどった全 Point の列。null を読んだ実の節点で
    terminal = {kind: root, point}、既出の Point への辺を読んだらその Point を points の末尾にも残して {kind: cycle, point}。
    読めない記録で止まれば terminal は Missing (短い列を完了にしない)。"""
    point = env.point_of(a)
    if point is None or env.reader is None:
        return Missing("adoption_chain: the adoption is not bound")
    points, seen = [], set()
    while True:
        points.append(point)
        if point in seen:
            return {"points": points, "terminal": {"kind": "cycle", "point": point}}
        seen.add(point)
        document = _adoption(env.reader, point)
        if isinstance(document, Missing):
            return {"points": points, "terminal": document}
        previous = document.get("previous")
        if previous is None:
            return {"points": points, "terminal": {"kind": "root", "point": point}}
        point = previous


@derivation("adoption_heads")
def adoption_heads(env, origin, model, view):
    """(origin, model, Xuse) → 固定根の中の同じ系列 (origin・model) の採用のうち、他の採用の previous になっていない頭の列。
    同じ系列の採用の本文が 1 つでも読めなければ Missing (0 件や複数の頭に置き換えない)。"""
    from ._fb_uses import Reader, contract_name
    from .f_update2 import _c
    if isinstance(view, Missing):
        return view
    reader, adoption = Reader(view), contract_name(_c().BELIEF_ADOPTED)
    entries = getattr(view, "all_entries", None) or view.entries
    series = {}
    for found in entries():
        try:
            if reader.contract_of(found.cid) != adoption:
                continue
        except Exception as exc:   # noqa: BLE001 — 契約の読めない記録は系列の確認ができない
            return Missing(f"adoption_heads: {found.cid} is not readable: {exc}")
        document = _adoption(reader, found.cid)
        if isinstance(document, Missing):
            return document
        if document.get("origin") == origin and document.get("model") == model:
            series[found.cid] = document.get("previous")
    followed = set(series.values())
    return sorted(p for p in series if p not in followed)


@derivation("history_dependencies")
def history_dependencies(env, a):
    """(A) → A の R・G・previous など紙が実因果を要求する点 (一覧表 HISTORY_DEPENDENCIES の各 item の値) を、ブロックの変換
    「Ev then Front」で出来事に写した Point の集合 (整列した列): 出来事はそれ自身、派生物 (Prediction) はその実親 (前線の出来事)。
    Prediction は出来事の親ではない。型つきの参照一般を実祖先へ昇格させない。読めない item は Missing。"""
    from ._fb_a1 import _applies, resolve
    image = _parent_image(env)
    if image is None:
        return Missing("history_dependencies: no image")
    out = set()
    for item in _SPECS["HISTORY_DEPENDENCIES"]["items"]:
        if not _applies(env, _when(item.get("when", True))):
            continue
        value = resolve(env, item["value"])
        if isinstance(value, Missing):
            return value
        try:
            found = image.entry(value)
        except (KeyError, LookupError, TypeError):
            return Missing(f"history_dependencies: {item['id']} {value} is not in the image")
        out |= {value} if found.is_event else set(found.parents)
    return sorted(out)


# ---------------------------------------------------------------- 観測の意味と channel (scope observations)

def _claim_entries(reading, law, claim):
    """Reading.projection.args.claims のうち、この Claim の意味の契約と Law の Point に当たる要素の列。"""
    from ._fb_a1 import _canon
    meaning = claim["item"]["value"]["contract"]
    return [e for e in reading["projection"]["args"]["claims"]
            if _canon(e["meaning"]) == _canon(meaning) and e["law"] == law]


@derivation("matching_channels")
def matching_channels(env, law, k, route, reading):
    """(Law, K, Route, Reading) → 法則の channels のうち、route が route_configs にあり、過程が K の過程と同じものの全部
    (法則の順)。選んだ channel の id で先に絞らない。★ domain の時計・区間の照合は版つき法則の規則が未接続 (表の係へ)。"""
    route_point = env.point_of(route)
    if route_point is None:
        return Missing("matching_channels: the route is not bound")
    try:
        process = k["desc"]["process"]
        return [ch for ch in law["channels"] if route_point in ch["route_configs"] and ch["process"] == process]
    except (KeyError, TypeError) as exc:
        return Missing(f"matching_channels: {exc}")


@derivation("selected_channel")
def selected_channel(env, reading, law, claim):
    """(Reading, Law, Claim) → Reading.projection.args.claims の、この Claim の意味と Law に当たる要素の channel。
    matching_channels の結果は写さない。当たる要素がちょうど 1 つでなければ Missing (複数は Multiple)。"""
    from ._fb_a1 import Multiple
    law_point = env.point_of(law)
    try:
        found = _claim_entries(reading, law_point, claim)
    except (KeyError, TypeError) as exc:
        return Missing(f"selected_channel: {exc}")
    if len(found) > 1:
        return Multiple(f"selected_channel: {len(found)} projection entries match the claim")
    return Missing("selected_channel: no projection entry for the claim") if not found else found[0]["channel"]


@derivation("claim_signature")
def claim_signature(env, claim):
    """(Claim) → {kind, contract}: 原 Claim の本文 (item.value) が名乗る kind と意味の契約。"""
    try:
        value = claim["item"]["value"]
        return {"kind": value["kind"], "contract": value["contract"]}
    except (KeyError, TypeError) as exc:
        return Missing(f"claim_signature: {exc}")


@derivation("projection_signature")
def projection_signature(env, reading, law, claim):
    """(Reading, Law, Claim) → 射影の宣言がこの Claim に要求する {kind, contract}: 宣言の要素の意味の契約と、その契約に
    初回に定めた kind (§19-1 の表、`f_update2._meanings`)。意味が未宣言なら Missing (missing_contract)。"""
    from .f_update2 import _meanings
    try:
        found = _claim_entries(reading, env.point_of(law), claim)
    except (KeyError, TypeError) as exc:
        return Missing(f"projection_signature: {exc}")
    if len(found) != 1:
        return Missing(f"projection_signature: {len(found)} projection entries for the claim")
    contract = found[0]["meaning"]
    meaning = _meanings().get((contract.get("name"), contract.get("version")))
    if meaning is None:
        return Missing(f"projection_signature: no meaning is declared for {contract}", code="missing_contract")
    return {"kind": meaning[0], "contract": contract}


@derivation("reported_bytes")
def reported_bytes(env, raw, request, executions, reports):
    """(raw, 要求, EW, EH) → 要求の仕事の口から実際に受け取った封筒に対応して保存した raw の bytes (ReportObservation.point
    との保存の対応から読む。raw の中の WorkId から観測を逆に作らない)。その口の報告に raw が無ければ Missing。"""
    from ._fb_a1 import Multiple
    point = env.point_of(raw)
    image = _parent_image(env)
    if point is None or image is None:
        return Missing("reported_bytes: the raw report is not bound")
    work_id = _work_id(env, request)
    if isinstance(work_id, Missing):
        return work_id
    runs = [e for e in executions if e.get("work_id") == work_id]
    if len(runs) > 1:
        return Multiple(f"reported_bytes: {len(runs)} executions of {work_id}")
    received = [r for r in (runs[0].get("reports", ()) if runs else ()) if r.get("point") == point]
    if not received:
        return Missing(f"reported_bytes: {point} was not received from the port of {work_id}")
    try:
        _salt, payload = image.sealed_content(point)
    except LookupError as exc:
        return Missing(f"reported_bytes: {point} is not readable: {exc}")
    return _payload_json(payload)


# ---------------------------------------------------------------- ATOM_PROTOCOL v3 で本番の原子が使う補助 (2026-10-23)

@derivation("project")
def project(env, value, selector, *_bindings):
    """(value, Pointer) → その欄 (型と欠落を保つ)。(derivation_return の捕捉, {block, case, component}, BINDINGS) の形は
    戻り値の照合 = 試験の側 (phase: test) だけが使うので、本番では読まない (Missing)。"""
    from ._fb_a1 import _at
    if isinstance(value, Missing):
        return value
    if not isinstance(selector, str):
        return Missing("project: the capture projection is test-only (phase: test)")
    return value if selector == "" else _at(value, selector)


@derivation("set_from")
def set_from(env, collection):
    """(collection) → 同じ型の集合 (正準の形で重複を除き整列した列)。読めない要素があれば Missing (捨てない)。"""
    from ._fb_a1 import _canon, _json
    if isinstance(collection, Missing):
        return collection
    if not isinstance(collection, (list, tuple)):
        return Missing("set_from: not a collection")
    if any(isinstance(v, Missing) for v in collection):
        return next(v for v in collection if isinstance(v, Missing))
    seen = {}
    for value in collection:
        seen.setdefault(_canon(value), _json(value))
    return [seen[key] for key in sorted(seen)]


@derivation("interval_set")
def interval_set(env, interval):
    """(MeasurementInterval の値 {clock, start_ns, end_ns, closure}) → 時計と開閉端を保った区間集合
    {"interval_set": {...}}。subset_of は同じ時計の上の区間の包含 (`_f_count.Span.covers`、両端だけの点集合にしない)。"""
    if isinstance(interval, Missing):
        return interval
    try:
        clock, start, end, closure = interval["clock"], interval["start_ns"], interval["end_ns"], interval["closure"]
    except (KeyError, TypeError):
        return Missing("interval_set: not a measurement interval")
    if closure not in ("[start,end)", "(start,end]", "[start,end]", "(start,end)") or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in (start, end)):
        return Missing("interval_set: malformed interval (shape)")
    return {"interval_set": {"clock": clock, "start_ns": start, "end_ns": end, "closure": closure}}


def _report_branches():
    """SegmentItem の八枝の名前 (保存の形 `_fb_wire.segment_item` の kind: started・ended・route_applied と _SEGMENT_TAGS の枝)。"""
    from ._fb_wire import _SEGMENT_TAGS
    return {"started", "ended", "route_applied", *_SEGMENT_TAGS.values()}


@derivation("supported_report_branch")
def supported_report_branch(env, claim, reading):
    """(Claim, Reading) → 既知の報告の枝の名前。報告の契約と、Reading の射影がこの用途 (Claim を読む有限の区間の射影) に
    対応することを先に解く。未知の枝・射影の契約が未宣言なら missing_contract の Missing (kind != claim を対応違反に潰さない)。"""
    from ._fb_uses import contract_name
    from .f_update2 import _c
    point = env.point_of(claim)
    if point is None or env.reader is None:
        return Missing("supported_report_branch: the claim is not bound")
    if env.reader.contract_of(point) != contract_name(_c().SEGMENT_REPORT):
        return Missing("supported_report_branch: not a segment report", code="missing_contract")
    try:
        projection = contract_name(reading["projection"]["contract"])
        kind = claim["item"]["kind"]
    except (KeyError, TypeError):
        return Missing("supported_report_branch: the reading or the report has no branch")
    if projection != contract_name(_c().FINITE_SEGMENT_PROJECTION):
        return Missing(f"supported_report_branch: projection {projection} is not declared", code="missing_contract")
    if kind not in _report_branches():
        return Missing(f"supported_report_branch: unknown branch {kind!r}", code="missing_contract")
    return kind


def _causal_contribution(env, value):
    """(記録の Point) → 実因果の点 (Ev/Front: 出来事はそれ自身、派生物 (Prediction) はその実親)。像の外なら Missing。"""
    image = _parent_image(env)
    if isinstance(value, Missing):
        return value
    if image is None or not isinstance(value, str):
        return Missing("causal_contribution: not a point in the image")
    try:
        found = image.entry(value)
    except (KeyError, LookupError):
        return Missing(f"causal_contribution: {value} is not in the image")
    return [value] if found.is_event else sorted(found.parents)


def _table_inputs(env, group, q, view):
    """(T-A2 区分, Q, Xnum) → その区分の全 T-A2 行と各行の T-REF 展開で導いた Point の集合 (保存した I を正解にしない)。"""
    from . import _fb_uses as uses
    from .f_update2 import _c
    if isinstance(view, Missing):
        return view
    point = env.point_of(q)
    if point is None:
        return Missing("table_inputs: the request is not bound")
    try:
        found = uses.required(uses.Reader(view), point, uses.contract_name(_c().WORK_REQUESTED), "update", q,
                              groups=(group,), start_groups=(group,))
    except (uses.Unresolved, uses.Unsupported, uses.Malformed) as exc:
        return Missing(f"table_inputs({group}): {type(exc).__name__}: {exc}")
    return sorted(uses.points_of(found))


def _closure_contribution(env, consumer, case_id, value, *_scope):
    """(consumer, 場合の ID, 値, Q, Xnum) → 1 つの寄与の認証済みの集合 (closure_keys なら Point の集合: Point の列はそのまま、
    解決した参照の列 [{point, ...}] は point を射影)。authenticated_references の義務の射影はまだ接続していない (Missing)。"""
    if isinstance(value, Missing):
        return value
    if consumer not in ("closure_keys", "authenticated_references"):
        return Missing(f"closure_contribution: {consumer} is not connected")
    # 本番の原子はこの寄与が読めること (present) だけを見る。authenticated_references の用途・位置ごとの義務への射影は
    # 戻り値の照合 (phase: test) の側
    if not isinstance(value, (list, tuple)):
        return Missing(f"closure_contribution({case_id}): not a collection")
    out = set()
    for element in value:
        if isinstance(element, Missing):
            return element
        out.add(element["point"] if hasattr(element, "items") else element)
    return sorted(out)


def _event_domain(env, event):
    """(仕事の出来事 1 つ) → 実際の演算の場所で捕捉した値域 (integer / rational)。捕捉が無ければ Missing (推測しない)。"""
    if not hasattr(event, "items") or "domain" not in event:
        return Missing("event_domain: the event has no captured domain")
    return event["domain"]


_SOURCES.update({"causal_contribution": _causal_contribution, "table_inputs": _table_inputs,
                 "closure_contribution": _closure_contribution, "event_domain": _event_domain})



# ---------------------------------------------------------------- 採用した結果と実返答 (A1-HISTORY-RETURN)

@derivation("result_value")
def result_value(env, result):
    """(R) → {request, result, application_digest, numerical_view, registry_key} の全内容 (保存した R* の本文から。
    IssuedUpdate の形はまだ接続していない)。読めなければ Missing。"""
    if not hasattr(result, "items"):
        return Missing("result_value: not a stored result")
    try:
        return {key: result[key] for key in ("request", "result", "application_digest", "numerical_view", "registry_key")}
    except KeyError as exc:
        return Missing(f"result_value: the stored result has no {exc}")


@derivation("returned_value")
def returned_value(env, report, request, executions, reports):
    """(原報告の Point, 要求, EW, EH) → {result: finite_update_result/1 の全値}: 要求の仕事が実際に入場し、その口から受け取った
    報告 (EH) で、outputs の `sui.fb.update_response/1` の issued の値 (joint と evidence_mass) 全体。failure・unknown・
    rejected・insufficient は issued ではない (Missing)。R* にしか無い 4 欄 (request 等) は補わない。"""
    from ._fb_uses import Unresolved, contract_name
    from .fb_contracts import UPDATE_RESPONSE, WORK_REPORT
    work_id = _work_id(env, request)
    if isinstance(work_id, Missing):
        return work_id
    if not isinstance(report, str) or env.reader is None:
        return Missing("returned_value: the report is not a point")
    runs = [e for e in executions if e.get("work_id") == work_id]
    if len(runs) != 1 or runs[0].get("entered", 0) < 1:
        return Missing(f"returned_value: the work {work_id} was not observed entering once")
    if not any(r.get("point") == report for r in runs[0].get("reports", ())):
        return Missing(f"returned_value: {report} was not received from the port of {work_id}")
    try:
        name, document = env.reader.document(report)
    except Unresolved as exc:
        return Missing(f"returned_value: {report} is not readable: {exc}")
    if name != contract_name(WORK_REPORT):
        return Missing(f"returned_value: {report} is {name}, not a work report")
    try:
        outcome = document["outcome"]
        if outcome.get("kind") != "outputs":
            return Missing(f"returned_value: the outcome is {outcome.get('kind')}, not outputs")
        value = outcome["value"]
        if contract_name(value["contract"]) != contract_name(UPDATE_RESPONSE):
            return Missing("returned_value: the outputs are not an update response", code="missing_contract")
        response = value["value"]
    except (KeyError, TypeError) as exc:
        return Missing(f"returned_value: the report has no update response ({exc})")
    if response.get("kind") != "issued":
        return Missing(f"returned_value: the response is {response.get('kind')}, not issued")
    return {"result": response["value"]}



# ---------------------------------------------------------------- 直の参照 (A1-DIRECT-REFS、REFERENCE_OBLIGATION_PROTOCOL)

def obligation_record(ob, contract):
    """`_fb_uses.Obligation` → 正本の義務の型 {source, source_purpose, rule, path, reference_kind, reference, target_contract,
    target_purpose, role} (REFERENCE_OBLIGATION_PROTOCOL)。reference は解決前の元の Point / Ref のまま。"""
    from ._fb_a1 import _json
    from ._fb_uses import field_type
    kind = field_type(contract, ob.field)
    return {"source": ob.start, "source_purpose": ob.purpose, "rule": ob.rule, "path": ob.path,
            "reference_kind": {"point": "Point", "ref": "Ref"}.get(kind, kind),
            "reference": _json(ob.value) if not isinstance(ob.value, str) else ob.value,
            "target_contract": None if ob.target_contract in ("-", None) else ob.target_contract,
            "target_purpose": None if ob.target_purpose in ("-", None) else ob.target_purpose, "role": ob.role}


def direct_obligations(reader, point, document):
    """Q (Point と文書) の契約 × 用途の T-REF の行を直接当てた参照義務の列 (正本の型、出現の順)。同じ Point を指す別の欄も
    別の義務。値だけの欄・ignored は義務にしない (`_fb_uses.obligations` の分母のとおり)。"""
    from . import _fb_uses as uses
    from .f_update2 import _c
    contract = uses.contract_name(_c().WORK_REQUESTED)
    return [obligation_record(ob, contract) for ob in uses.obligations(reader, point, contract, "update", document)]


@derivation("reference_obligations")
def reference_obligations(env, q, view):
    """(Q, Xnum) → T-REF の欄 / 用途 / 配列位置 / 枝ごとの型つきの直の参照義務の列 (Xnum の読み手で、Q の本文から独立に導く)。"""
    from . import _fb_uses as uses
    if isinstance(view, Missing):
        return view
    point = env.point_of(q)
    if point is None:
        return Missing("reference_obligations: the request is not bound")
    if isinstance(q, str):
        try:
            q = env.reader.document(point)[1]
        except Exception as exc:   # noqa: BLE001
            return Missing(f"reference_obligations: {point} is not readable: {exc}")
    try:
        return direct_obligations(uses.Reader(view), point, q)
    except uses.Unsupported as exc:
        return Missing(f"reference_obligations: {exc}", code="algorithm_unavailable")
    except (uses.Unresolved, uses.Malformed) as exc:
        return Missing(f"reference_obligations: {type(exc).__name__}: {exc}")



# ---------------------------------------------------------------- 参照の解決の一意性・本文・因果 (A1-REF-RESOLUTION)

@derivation("resolution_groups")
def resolution_groups(env, q, view):
    """(Q, view) → 直の参照義務ごとの {cid_count, unique_point, body_pairs}。cid_count は許された像の header から得た候補 CID
    の数 (Point の参照は 1)、unique_point は 1 つに証明できた候補 (候補が 1 つ、または Point の参照そのもの。複数の CID を
    辞書順で選ばない、未証明は Missing)、body_pairs は同じ Ref に当たる全ての異なる CID の非順序の対の正準 bytes。
    義務の分母は reference_obligations から (解けた Ref だけに縮めない)。値だけの欄は参照ではないので含めない。"""
    from ._fb_uses import as_ref
    obligations = reference_obligations(env, q, view)
    if isinstance(obligations, Missing):
        return obligations
    by_ref = {}
    for found in (getattr(view, "all_entries", None) or view.entries)():
        by_ref.setdefault(str(found.id), []).append(found.cid)
    out = []
    for ob in obligations:
        if ob["reference_kind"] == "Point":
            out.append({"cid_count": 1, "unique_point": ob["reference"], "body_pairs": []})
            continue
        if ob["reference_kind"] != "Ref":
            continue
        ref = ob["reference"]
        parsed = as_ref(ref) if isinstance(ref, str) else None
        candidates = sorted(by_ref.get(str(parsed if parsed is not None else ref), ()))
        pairs = []
        for i, left in enumerate(candidates):
            for right in candidates[i + 1:]:
                pairs.append({"left": _canonical_at(view, left), "right": _canonical_at(view, right)})
        out.append({"cid_count": len(candidates),
                    "unique_point": candidates[0] if len(candidates) == 1 else Missing(
                        f"resolution_groups: {ref} has {len(candidates)} candidate CIDs (not proven unique)"),
                    "body_pairs": pairs})
    return out


def _canonical_at(view, point):
    """候補 1 つの認証済みの記録全体の正準 bytes (読めなければ Missing、対から消さない)。"""
    try:
        _salt, payload = view.sealed_content(point)
    except LookupError as exc:
        return Missing(f"resolution_groups: {point} is not readable: {exc}")
    return _payload_json(payload)


@derivation("required_causal_dependencies")
def required_causal_dependencies(env, q, view):
    """(Q, view) → Q の参照が要求する実因果の点: T-A2 / T-REF の必須の義務のうち、実際に使う役割 (U・UE) の到達先を Ev/Front で
    出来事に写したもの (F-a A-03「実際に使用した出来事は使用側の台帳上の実祖先」。存在だけの E の参照 (宣言した input_points
    など) と余分な I は認証するが使用しないので実祖先を要求しない。Prediction を出来事の親に昇格させない)。読めなければ Missing。"""
    from . import _fb_uses as uses
    from .f_update2 import _c
    if isinstance(view, Missing):
        return view
    point = env.point_of(q)
    if point is None or not hasattr(q, "items"):
        return Missing("required_causal_dependencies: the request is not bound")
    try:
        found = uses.required(uses.Reader(view), point, uses.contract_name(_c().WORK_REQUESTED), "update", q,
                              groups=uses.A2_GROUPS, start_groups=("Local", "History"))
    except (uses.Unresolved, uses.Unsupported, uses.Malformed) as exc:
        return Missing(f"required_causal_dependencies: {type(exc).__name__}: {exc}")
    used = sorted({ob.target for ob in found if ob.target is not None and ob.role in ("U", "UE")})
    out = set()
    for point in used:
        try:
            entry_ = view.entry(point)
        except LookupError as exc:
            return Missing(f"required_causal_dependencies: {exc}")
        out |= {point} if entry_.is_event else set(entry_.parents)
    return sorted(out)



@derivation("authenticated_references")
def authenticated_references(env, q, view):
    """(Q, Xnum) → 認証済みの参照の列: T-A2 の Local・History・前の C・前の I の各義務 (`_fb_uses.required`、出発の Q には
    Local・History) を正本の義務の型 (REFERENCE_OBLIGATION_PROTOCOL) で、用途と出現位置を保って。列挙しただけで認証済みに
    しない = 解決できない義務があれば Missing。"""
    from . import _fb_uses as uses
    from .f_update2 import _c
    if isinstance(view, Missing):
        return view
    point = env.point_of(q)
    if point is None:
        return Missing("authenticated_references: the request is not bound")
    if isinstance(q, str):
        try:
            q = env.reader.document(point)[1]
        except Exception as exc:   # noqa: BLE001
            return Missing(f"authenticated_references: {point} is not readable: {exc}")
    try:
        found = uses.required(uses.Reader(view), point, uses.contract_name(_c().WORK_REQUESTED), "update", q,
                              groups=uses.A2_GROUPS, start_groups=("Local", "History"))
    except (uses.Unresolved, uses.Unsupported, uses.Malformed) as exc:
        return Missing(f"authenticated_references: {type(exc).__name__}: {exc}")
    return [obligation_record(ob, ob.contract) for ob in found]


# ---------------------------------------------------------------- 生成の独立の観測と Support (正本 v1.3.7、Z33 ①)
# 手書きだった A1-GENERATION-* と A1-SUPPORT を表の行で回すための導出と読取り。独立の観測はホストの工場の捕捉
# (RouteApplicationObservation・HostMonitorObservation・ExecutionObservation の実行の札) だけから読み、保存した B・
# monitor_span・Route から写さない。

@derivation("independent_event")
def independent_event(env, k, event, *_evidence):
    """(K, applied|started|ended, EW, EH, EI) → {route, reading: ClockReading} (INDEPENDENT_EVENTS)。applied は K の実行が使った
    route の実適用、started は K の実行の入場 (EW の entered_ns)、ended は Ended の原報告を K の口から受け取った EH。"""
    if isinstance(k, Missing):
        return k
    if event == "applied":
        source_event, record = "route_applied", k
    elif event == "started":
        source_event, record = "work_entered", k
    elif event == "ended":
        record = env.document("Ended")
        if record is None:
            return Missing("independent_event(ended): Ended is not bound")
        source_event = "report_received"
    else:
        return Missing(f"independent_event: unknown event {event!r} (missing_contract)")
    route = _event_route(env, source_event, record)
    reading = _event_reading(env, source_event, record)
    for value in (route, reading):
        if isinstance(value, Missing):
            return value
    return {"route": route, "reading": reading}


def _generation_contract(reading):
    from ._fb_uses import contract_name
    try:
        return contract_name(reading["generation"]["contract"])
    except (KeyError, TypeError):
        return None


@derivation("generation_boundary")
def generation_boundary(env, b, reading, kind):
    """(B, Reading, started|ended) → 生成の契約が要る境界記録の Point、または合法の null (GENERATION_BOUNDARIES)。
    bootstrap_generation/1 は started が要り、ended は測り続ける要求では null でよい。未知の契約は missing_contract。"""
    for value in (b, reading):
        if isinstance(value, Missing):
            return value
    if _generation_contract(reading) != "sui.fb.bootstrap_generation/1":
        return Missing("generation_boundary: unknown generation contract (missing_contract)", code="missing_contract")
    if kind not in ("started", "ended"):
        return Missing(f"generation_boundary: unknown boundary {kind!r} (missing_contract)", code="missing_contract")
    value = (b.get("generation") or {}).get(kind)
    if kind == "started" and value is None:
        return Missing("generation_boundary: generation.started is required by bootstrap_generation/1")
    if value is not None:   # 要求した枝の境目として確かめてから返す (正本 v1.3.10 boundary_authentication)
        branch = _boundary_branch(env, value)
        if isinstance(branch, Missing):
            return branch
        if branch != kind:
            from ._fb_a1 import Mismatch
            return Mismatch(f"generation_boundary: generation.{kind} points to a {branch!r} report",
                            code="observation_binding_mismatch")
    return value


def _boundary_branch(env, point):
    """境目の参照の契約と /item/kind (読めなければ元の不足)。区間の報告でない記録は、その契約の名前を枝として返す。"""
    from . import _fb_uses as uses
    from ._fb_a1 import _at
    if env.reader is None:
        return Missing("generation_boundary: no reader for the boundary")
    try:
        contract, document = env.reader.document(point)
    except uses.Unresolved as exc:
        return Missing(f"generation_boundary: the boundary is not readable ({exc})")
    if contract != "sui.fb.segment_report/1":
        return contract
    return _at(document, "/item/kind")


@derivation("generation_evidence")
def generation_evidence(env, b, reading, *_rest):
    """(B, Reading, Xnum, EW, EH, EI) → 生成の契約の名前 (GENERATION_EVIDENCE の項目の原子が、その契約が要る独立の観測と保存の
    対応を 1 つずつ照らす)。未知の契約は missing_contract。"""
    for value in (b, reading):
        if isinstance(value, Missing):
            return value
    name = _generation_contract(reading)
    if name != "sui.fb.bootstrap_generation/1":
        return Missing("generation_evidence: unknown generation contract (missing_contract)", code="missing_contract")
    return {"contract": name}


@derivation("support_requirement")
def support_requirement(env, b, reading, claim):
    """(B, Reading, Claim) → この生成の契約が固定像の中の Support を要るか (bootstrap_generation/1 の whole_window は要る)。"""
    if isinstance(reading, Missing):
        return reading
    name = _generation_contract(reading)
    if name is None:
        return Missing("support_requirement: the reading has no generation contract (missing_contract)",
                       code="missing_contract")
    return name == "sui.fb.bootstrap_generation/1"


def _support_witness(env, b, claim):
    """固定像の中の monitor_span のうち、同じ segment・route・clock で原 Claim の窓を全部覆う 1 件 (Point と文書)。短い候補だけで
    後の完全な証人を退けない。覆う記録が無ければ MISSING (Claim を切り詰めない、部分しか覆わなければ不足)。"""
    from . import _fb_uses as uses
    from ._fb_a1 import _at
    image = _parent_image(env)
    if image is None or env.reader is None:
        return Missing("support: no fixed view")
    window = _at(claim, "/item[kind=claim]/value/interval")
    if isinstance(window, Missing):
        return window
    for entry in sorted(getattr(image, "all_entries", image.entries)(), key=lambda e: e.cid):
        try:
            if env.reader.contract_of(entry.cid) != "sui.fb.monitor_span/1":
                continue
            m = env.reader.document(entry.cid)[1]
        except uses.Unresolved:
            continue
        if m.get("segment") != b.get("segment") or m.get("route") != b.get("route") \
                or m.get("clock") not in list(b.get("clock", ())):
            continue
        entered, observed = m.get("entered_ns"), m.get("observed_ns")
        if isinstance(entered, int) and isinstance(observed, int) \
                and entered <= window["start_ns"] and window["end_ns"] <= observed:
            return entry.cid, m
    return Missing("support: no host monitoring record in the fixed view covers the claim")


def _support_observed(env, witness_point):
    """保存した証人に対応するホストの監視の実観測 (同じ操作から保存した Point = publication) と、その入場の EW。"""
    if env.evidence is None:
        return Missing("support: no independent observations")
    found = [m for m in env.evidence.host_monitors if m.publication == witness_point]
    if len(found) != 1:
        return Missing(f"support: {len(found)} host monitor observations for the saved monitoring record")
    monitor = found[0]
    runs = [e for e in env.evidence.executions if e.execution_occurrence is monitor.execution_occurrence]
    if len(runs) != 1 or not 0 <= monitor.entry_index < len(runs[0].entered_ns):
        return Missing("support: the monitored execution entry is not observed")
    return monitor, runs[0]


def _support_records(env, b, reading, claim, *_rest):
    """support_records (正本 ENUMERATION_SOURCES): 固定像の中の、この B の測る要求 (segment) を型つきで指す monitor_span の全候補の
    Point (CID の順)。被覆の判定はここでしない (SUPPORT_CHECKS が候補ごとに、SUPPORT_EVENT_FIELDS が全候補の保存と実観測を照らす)。"""
    from . import _fb_uses as uses
    image = _parent_image(env)
    if image is None or env.reader is None:
        return Missing("support_records: no fixed view")
    out = []
    for entry in sorted(getattr(image, "all_entries", image.entries)(), key=lambda e: e.cid):
        try:
            if env.reader.contract_of(entry.cid) != "sui.fb.monitor_span/1":
                continue
            if env.reader.document(entry.cid)[1].get("segment") == b.get("segment"):
                out.append(entry.cid)
        except uses.Unresolved as exc:
            return Missing(f"support_records: {exc}")
    return out


def _support_item(env, b, claim):
    """support_field が読む候補: each が束ねた ITEM (monitor_span の Point) があればそれ、無ければ窓を覆う証人。"""
    item = env.document("ITEM")
    if isinstance(item, str):
        saved = _doc(env, item)
        return saved if isinstance(saved, Missing) else (item, saved)
    return _support_witness(env, b, claim)


def _support_field(env, side, path, b, reading, claim, *_evidence):
    """support_field (正本 ENUMERATION_SOURCES): 候補の保存の 1 欄 (saved) か、その実観測の射影 (observed、HOST_MONITOR_BINDING:
    segment・work・route は工場の控え、clock は時計の源、entered_ns は EW の入場、observed_ns は監視の時の読み)。"""
    witness = _support_item(env, b, claim)
    if isinstance(witness, Missing):
        return witness
    point, saved = witness
    key = path.lstrip("/")
    if side == "saved":
        return saved.get(key, Missing(f"support_field: the saved monitoring record has no {path}"))
    observed = _support_observed(env, point)
    if isinstance(observed, Missing):
        return observed
    monitor, run = observed
    values = {"segment": monitor.segment, "work": monitor.work, "route": monitor.route, "clock": monitor.clock_source,
              "entered_ns": run.entered_ns[monitor.entry_index], "observed_ns": monitor.observed_reading.time_ns}
    return values.get(key, Missing(f"support_field: unknown field {path}"))


def _support_events(env, side, b, reading, claim, *_rest):
    fields = ("segment", "work", "route", "clock", "entered_ns", "observed_ns")
    event = {name: _support_field(env, side, "/" + name, b, reading, claim) for name in fields}
    missing = next((v for v in event.values() if isinstance(v, Missing)), None)
    return missing if missing is not None else [event]


def _support_covered(env, b, reading, claim, *_rest):
    """証人の実観測が覆う区間 (ホストの run 上で入場から監視の読みまで、両端を含む)。保存した値からは作らない。"""
    witness = _support_witness(env, b, claim)
    if isinstance(witness, Missing):
        return witness
    observed = _support_observed(env, witness[0])
    if isinstance(observed, Missing):
        return observed
    monitor, run = observed
    if run.run is None or monitor.observed_reading.run != run.run:
        return Missing("support: the entry and the monitoring reading are not on one host run")
    return {"interval_set": {"clock": run.run, "start_ns": run.entered_ns[monitor.entry_index],
                             "end_ns": monitor.observed_reading.time_ns, "closure": "[start,end]"}}


def _record_points(env, records, *_rest):
    if isinstance(records, Missing):
        return records
    return list(records)


@derivation("support")
def support(env, b, reading, claim, view, *_rest):
    """(B, Reading, Claim, Xnum, EW, EI, Q) → {points, covered, saved_events, observed_events} (SUPPORT_COMPONENTS)。"""
    q = env.document("Q*")
    points = _record_points(env, _support_used_records(env, q)) if q is not None else Missing("support: Q* is not bound")
    out = {"points": points, "covered": _support_covered(env, b, reading, claim),
           "saved_events": _support_events(env, "saved", b, reading, claim),
           "observed_events": _support_events(env, "observed", b, reading, claim)}
    missing = next((v for v in out.values() if isinstance(v, Missing)), None)
    return missing if missing is not None else out


def _clock_sources(env, b, reading, claim, k, *_evidence):
    """clock_sources: K の実行の入場と route の実適用で実際に使った時計の源 (独立の対応から)。B.clock の写しにしない。"""
    if env.evidence is None:
        return Missing("clock_sources: no independent observations")
    execution = _execution_of(env, k)
    if isinstance(execution, Missing):
        return execution
    application = _route_application_of(env, k)
    if isinstance(application, Missing):
        return application
    found = {p for p in (execution.clock_source, application.clock_source) if p is not None}
    if not found:
        return Missing("clock_sources: no clock source observed")
    return sorted(found)


def _required_generation_scope(env, reading, claim, *_rest):
    """required_generation_scope: Claim の版つきの meaning が要る生成の範囲 (no_arrival/1・count_exactly_one/1 は whole_window)。"""
    from ._fb_a1 import _at
    from ._fb_uses import contract_name
    meaning = _at(claim, "/item[kind=claim]/value/contract")
    if isinstance(meaning, Missing):
        return meaning
    name = contract_name(meaning)
    if name in ("sui.fb.no_arrival/1", "sui.fb.count_exactly_one/1"):
        return "whole_window"
    return Missing(f"required_generation_scope: {name} has no declared scope (missing_contract)", code="missing_contract")


_SOURCES.update({"support_field": _support_field, "support_events": _support_events, "support_covered": _support_covered,
                 "support_records": _support_records,
                 "record_points": _record_points, "clock_sources": _clock_sources,
                 "required_generation_scope": _required_generation_scope})


def _ended_required(env, b, reading, k, *_rest):
    """ended_required: 生成の契約と K の要求の形から Ended の境界が要るか。bootstrap_generation/1 で続けて測る要求 (requested の
    ongoing 枝、§6-5 G1) は Ended を要らない (合法の null)、有限の区間 (finite 枝) は要る。未知の契約・枝は missing_contract。"""
    for value in (b, reading, k):
        if isinstance(value, Missing):
            return value
    if _generation_contract(reading) != "sui.fb.bootstrap_generation/1":
        return Missing("ended_required: unknown generation contract (missing_contract)", code="missing_contract")
    try:
        branch = k["desc"]["args"]["requested"]["kind"]
    except (KeyError, TypeError):
        return Missing("ended_required: K has no requested branch")
    if branch not in ("finite", "ongoing"):
        return Missing(f"ended_required: unknown requested branch {branch!r} (missing_contract)", code="missing_contract")
    return branch == "finite"


_SOURCES["ended_required"] = _ended_required


# ---------------------------------------------------------------- 宣言と許可 (A1-DECLARATION、正本 v1.3.7 PERMISSION_BINDINGS)
# 許可は {対象, 用途, 方法, 範囲, 割当} の 5 成分の組。要求の側 (Q* の Desc) と宣言の側 (Boot・δ・台帳から導いた origin・
# 実際に受け取った原報告) をそれぞれ独立に組み、組の集合の包含で比べる (成分ごとに別の許可から寄せ集めない)。

def _doc(env, point):
    from . import _fb_uses as uses
    if not isinstance(point, str) or env.reader is None:
        return Missing(f"declaration: {point!r} is not a readable point")
    try:
        return env.reader.document(point)[1]
    except uses.Unresolved as exc:
        return Missing(f"declaration: {exc}")


def _boot_slot(boot, slot):
    """Boot の宣言の中で slot 名の位置を一意に解く: 一番上の SlotValue (scope・initial・environment・routes[*])、その中の入れ子の
    SlotValue / SlottedMethod (allocation・derivation)、過程の名札 (initial・routes[*] の process_slot)。0 件・2 件以上は Missing
    (名前だけで照合を終えない: 返すのはその位置の値全体)。"""
    found = []

    def visit(top):
        if not hasattr(top, "items"):
            return
        if top.get("slot") == slot:
            found.append(top)
        value = (top.get("declaration") or {}).get("value") if hasattr(top.get("declaration"), "items") else None
        if not hasattr(value, "items"):
            return
        for key in ("allocation", "derivation"):
            nested = value.get(key)
            if hasattr(nested, "items") and nested.get("slot") == slot:
                found.append(nested)
        if value.get("process_slot") == slot:
            found.append({"process_slot": slot, "declared_by": top.get("slot"), "declaration": top.get("declaration")})

    for key in ("scope", "initial", "environment"):
        visit(boot.get(key))
    for route in boot.get("routes", ()):
        visit(route)
    if len(found) != 1:
        return Missing(f"declaration: slot {slot!r} resolves to {len(found)} positions in the boot declaration")
    return found[0]


def _authenticated_slot(env, slot_value, q, *_rest):
    """authenticated_slot (正本 ENUMERATION_SOURCES): BootSlot {declaration, slot} → 保存した Boot の宣言の中の一意の位置の値全体。"""
    if not hasattr(slot_value, "items"):
        return Missing("authenticated_slot: not a BootSlot")
    boot = _doc(env, slot_value.get("declaration"))
    if isinstance(boot, Missing):
        return boot
    if env.reader.contract_of(slot_value["declaration"]) != "sui.fb.boot_declaration/1":
        return Missing("authenticated_slot: the declaration is not a boot declaration (reference_kind)")
    found = _boot_slot(boot, slot_value.get("slot"))
    if isinstance(found, Missing):
        return found
    return {"declaration": slot_value["declaration"], "slot": slot_value["slot"], "value": found}


@derivation("declaration_slots")
def declaration_slots(env, q, view):
    """(Q, Xnum) → process・allocation・permissions の各 BootSlot が指す宣言全体と一意な slot の値 (DECLARATION_SLOTS)。"""
    if not hasattr(q, "items"):
        return Missing("declaration_slots: Q is not readable")
    desc = q.get("desc", {})
    out = [_authenticated_slot(env, desc.get("process"), q), _authenticated_slot(env, desc.get("allocation"), q),
           *(_authenticated_slot(env, s, q) for s in desc.get("permissions", ()))]
    missing = next((v for v in out if isinstance(v, Missing)), None)
    return missing if missing is not None else out


def _declared_origin(env, boot_point, initial, q):
    """台帳から導く origin (ledger_origin_binding): 候補の範囲 (U・履歴では resolution_scope(Q, numerical_view(Q)) = 親の像を
    Q の境界の祖先の閉包に限ったもの) の knowledge_origin/1 の全候補のうち、model が initial.model で、Boot を因果の祖先に
    持つもの。1 件ならその Point、0 件は Missing、2 件以上は全候補の列 (どれも選ばない = 照合で不適合)。"""
    from .f_update2 import _Sub
    parent = _parent_image(env)
    if parent is None:
        return Missing("declared origin: no fixed view")
    try:
        image = _Sub(parent, frozenset(q["desc"]["numerical_view"]["boundary"]))
    except Exception:   # noqa: BLE001 — 境界の読めない Q は候補の範囲を持たない (形は A1-SHAPE の行が落とす)
        return Missing("declared origin: the request has no readable numerical_view boundary")
    candidates = []
    for entry in sorted(getattr(image, "all_entries", image.entries)(), key=lambda e: e.cid):
        try:
            if env.reader.contract_of(entry.cid) != "sui.f.knowledge_origin/1":
                continue
        except Exception:   # noqa: BLE001 — 読めない記録は候補の外 (下の数え方で不足になる)
            continue
        origin = _doc(env, entry.cid)
        if isinstance(origin, Missing) or origin.get("model") != initial.get("model"):
            continue
        if boot_point in image.ancestors(frozenset({entry.cid})):
            candidates.append(entry.cid)
    if not candidates:
        return Missing("declared origin: no knowledge_origin of the boot's initial model in the view")
    return candidates[0] if len(candidates) == 1 else {"ambiguous": candidates}


def _route_entry(boot, slot):
    found = [r for r in boot.get("routes", ()) if r.get("slot") == slot]
    return found[0] if len(found) == 1 else Missing(f"declaration: route slot {slot!r} is not unique")


def _scope_of(boot, initial):
    allocation = (initial.get("allocation") or {}).get("declaration") or {}
    scope_slot = (allocation.get("value") or {}).get("scope_slot")
    scope = boot.get("scope")
    if not hasattr(scope, "items") or scope.get("slot") != scope_slot:
        return Missing("declaration: the allocation's scope slot does not resolve")
    return scope


def _initial_of(env, boot_point):
    boot = _doc(env, boot_point)
    if isinstance(boot, Missing):
        return boot, boot
    initial = ((boot.get("initial") or {}).get("declaration") or {}).get("value")
    if not hasattr(initial, "items"):
        return boot, Missing("declaration: the boot declaration has no initial process")
    return boot, initial


def _requested_instances(env, q):
    desc = q.get("desc", {})
    args = desc.get("args", {})
    boot_point = (desc.get("process") or {}).get("declaration")
    boot, initial = _initial_of(env, boot_point)
    alloc_boot_point = (desc.get("allocation") or {}).get("declaration")
    alloc_boot, alloc_initial = _initial_of(env, alloc_boot_point)
    for value in (boot, initial, alloc_boot, alloc_initial):
        if isinstance(value, Missing):
            return value
    declared_origin = _declared_origin(env, boot_point, initial, q)
    by_report = {}
    for use in args.get("observations", ()):
        b = _doc(env, use.get("binding"))
        if not isinstance(b, Missing):
            by_report.setdefault(b.get("report"), []).append(b)
    out = []
    for trigger in desc.get("trigger", ()):
        bindings = by_report.get(trigger.get("point"), [])
        if len(bindings) != 1:
            return Missing(f"requested permission: the trigger {trigger.get('point')} has {len(bindings)} bindings")
        b = bindings[0]
        application = _route_application_of(env, b.get("segment"))
        if isinstance(application, Missing):
            return application
        app_boot = _doc(env, application.boot)
        if isinstance(app_boot, Missing):
            return app_boot
        entry = _route_entry(app_boot, application.route_slot)
        if isinstance(entry, Missing):
            return entry
        reader_slot = initial.get("reader_slot") if desc.get("reader") == declared_origin \
            else {"unassociated_reader": desc.get("reader")}
        out.append({
            "対象": {"process": desc.get("process"), "reader_slot": reader_slot, "origin": desc.get("reader"),
                   "model": args.get("model"),
                   "route": {"declaration": application.boot, "slot": application.route_slot,
                             "process": {"declaration": application.boot,
                                         "slot": entry["declaration"]["value"]["process_slot"]},
                             "applied": b.get("route")},
                   "trigger": {"point": trigger.get("point"), "slot": trigger.get("slot")}},
            "用途": desc.get("purpose"),
            "方法": {"contract": desc.get("method"), "output_contract": desc.get("output_contract"), "args": args},
            "範囲": _scope_of(alloc_boot, alloc_initial),
            "割当": (alloc_initial.get("allocation") or {}).get("declaration")})
    return out


def _declared_instances(env, q):
    """宣言の側: Boot の initial・δ (derivation) と台帳から導いた origin、Q の観測の B が指す原報告のうち K の口から実際に
    受け取った (EH) もの (DeclaredTriggerOccurrence の history の読み)。"""
    from ._fb_uses import contract_name
    desc = q.get("desc", {})
    args = desc.get("args", {})
    boot_point = (desc.get("process") or {}).get("declaration")
    boot, initial = _initial_of(env, boot_point)
    for value in (boot, initial):
        if isinstance(value, Missing):
            return value
    delta = (initial.get("derivation") or {}).get("method") or {}
    delta_args = delta.get("args") or {}
    route_slot = delta_args.get("route")
    entry = _route_entry(boot, route_slot)
    if isinstance(entry, Missing):
        return entry
    meanings = [contract_name(c["meaning"]) for c in delta_args.get("claims", ()) if hasattr(c, "items")]
    declared_origin = _declared_origin(env, boot_point, initial, q)
    if isinstance(declared_origin, Missing):
        return declared_origin
    observations, triggers = [], []
    for use in args.get("observations", ()):
        b = _doc(env, use.get("binding"))
        reading = _doc(env, use.get("reading"))
        for value in (b, reading):
            if isinstance(value, Missing):
                return value
        claim = _doc(env, b.get("report"))
        if isinstance(claim, Missing):
            return claim
        execution = _execution_of(env, b.get("segment"))
        application = _route_application_of(env, b.get("segment"))
        for value in (execution, application):
            if isinstance(value, Missing):
                return value
        if not any(r.point == b.get("report") for r in execution.reports):
            return Missing("declared permission: the raw report was not received from its measuring work")
        item = claim.get("item", {})
        if item.get("kind") != "claim" or contract_name(item["value"]["contract"]) not in meanings:
            return Missing("declared permission: the report is not a claim of the delta's meanings", code="missing_contract")
        if application.boot != boot_point or application.route_slot != route_slot:
            return Missing("declared permission: the claim did not come through the delta's route")
        if reading.get("model") != initial.get("model"):
            return Missing("declared permission: the reading is not of the boot's model")
        observations.append({"binding": use.get("binding"), "reading": use.get("reading")})
        triggers.append((b, application))
    prior = args.get("prior")
    if prior is not None:
        adopted = _doc(env, prior)
        if isinstance(adopted, Missing):
            return adopted
        if adopted.get("origin") != declared_origin or adopted.get("model") != initial.get("model"):
            prior = {"foreign_prior": prior}   # 別の origin・モデルの採用は宣言の側の prior にならない (照合で不適合)
    method_args = _declared_method_args(boot, q, {"prior": prior, "observations": observations})
    if isinstance(method_args, Missing):
        return method_args
    out = []
    for b, application in triggers:
        out.append({
            "対象": {"process": {"declaration": boot_point, "slot": initial.get("process_slot")},
                   "reader_slot": initial.get("reader_slot"), "origin": declared_origin, "model": initial.get("model"),
                   "route": {"declaration": boot_point, "slot": route_slot,
                             "process": {"declaration": boot_point,
                                         "slot": entry["declaration"]["value"]["process_slot"]},
                             "applied": application.publication},
                   "trigger": {"point": b.get("report"), "slot": "trigger"}},
            "用途": "belief_update",
            "方法": {"contract": {"name": "sui.f.finite_update_compute", "version": "1"},
                   "output_contract": {"name": "sui.fb.update_response", "version": "1"}, "args": method_args},
            "範囲": _scope_of(boot, initial),
            "割当": (initial.get("allocation") or {}).get("declaration")})
    return out


def _declared_method_args(boot, q, derived):
    """宣言の側の方法の args: 正本 PERMISSION_BINDINGS の束縛 (Boot・Q* の Pointer) を読む。DeclaredDeltaInputs から組む欄
    (prior・observations) は derived。予算は Q* の保存した予算 (v1.3.9、紙 A3・Z7: Boot の update_budget との一致は要らない)。"""
    from . import _fb_rules as rules
    from ._fb_a1 import _instances, _walk
    spec = rules.PERMISSION_BINDINGS["bindings"][0]["components"]["方法"]["declared"]["args"]
    records = {"Boot": boot, "Q*": q}
    out = {}
    for key, binding in spec.items():
        if key in derived:
            out[key] = derived[key]
            continue
        record = records.get(binding.get("record"))
        if record is None or "pointer" not in binding:
            return Missing(f"declared permission: method arg {key!r} has no readable binding (missing_contract)",
                           code="missing_contract")
        value = _instances(_walk(record, binding["pointer"]), binding["pointer"])
        if isinstance(value, Missing):
            return value
        out[key] = value
    if set(out) != set(spec) | set(derived):
        return Missing("declared permission: method args outside the binding (missing_contract)", code="missing_contract")
    return out


def _permission_required_slots(env, q, *_rest):
    """permission_required_slots (正本 v1.3.10 ENUMERATION_SOURCES): Boot の initial の δ と割当の役割から、Q* の permissions が
    覆うべき BootSlot の集合を独立に作る (Q*:/desc/permissions を走査しない)。型の雛形は PB-PERMISSION-SLOTS.required_slots。"""
    from . import _fb_rules as rules
    from ._fb_a1 import _instances, _walk
    if not hasattr(q, "items"):
        return Missing("permission_required_slots: Q is not readable")
    boot_point = ((q.get("desc") or {}).get("process") or {}).get("declaration")
    boot, initial = _initial_of(env, boot_point)
    for value in (boot, initial):
        if isinstance(value, Missing):
            return value
    spec = rules.PERMISSION_BINDINGS["bindings"][0]["authentication"]["PB-PERMISSION-SLOTS"]["required_slots"]
    out = []
    for template in spec["templates"]:
        binding = template["value"]["slot"]
        if binding.get("record") != "Boot" or "pointer" not in binding:
            return Missing(f"permission_required_slots: role {template['role']!r} has no readable binding (missing_contract)",
                           code="missing_contract")
        slot = _instances(_walk(boot, binding["pointer"]), binding["pointer"])
        if isinstance(slot, Missing):
            return slot
        out.append({"declaration": boot_point, "slot": slot})
    return out


_SOURCES["permission_required_slots"] = _permission_required_slots


def _instances_or_missing(instances):
    if isinstance(instances, Missing):
        return instances
    for instance in instances:
        for value in instance.values():
            if isinstance(value, Missing):
                return value
    return instances


@derivation("requested_permissions")
def requested_permissions(env, q):
    """(Q) → 実 Desc とその用途が要る {対象, 用途, 方法, 範囲, 割当} の組の列 (原報告の出現ごと)。permissions の自己申告を正解にしない。"""
    if not hasattr(q, "items"):
        return Missing("requested_permissions: Q is not readable")
    return _instances_or_missing(_requested_instances(env, q))


@derivation("declared_permissions")
def declared_permissions(env, q, view):
    """(Q, Xnum) → 宣言が許す {対象, 用途, 方法, 範囲, 割当} の組の列 (Boot の版つきの意味から、出現ごと)。"""
    if not hasattr(q, "items"):
        return Missing("declared_permissions: Q is not readable")
    return _instances_or_missing(_declared_instances(env, q))


def _side_instances(env, q):
    """呼んだ導出の側 (CALL の consumer: declared_permissions / requested_permissions) の組の列。"""
    call = env.document("CALL")
    consumer = call.get("consumer") if hasattr(call, "items") else None
    if consumer == "declared_permissions":
        return _instances_or_missing(_declared_instances(env, q))
    if consumer == "requested_permissions":
        return _instances_or_missing(_requested_instances(env, q))
    return Missing(f"permission_instances: unknown side for {consumer!r} (missing_contract)", code="missing_contract")


def _permission_instances(env, q, *_rest):
    """permission_instances (正本 ENUMERATION_SOURCES): その側の 5 成分の組の列 (原報告の出現ごと)。"""
    return _side_instances(env, q)


def _permission_component(env, component, q, *_rest):
    """permission_component (正本 ENUMERATION_SOURCES): each が束ねた組 (ITEM) の 1 成分。組の外では読まない。"""
    item = env.document("ITEM")
    if not hasattr(item, "items"):
        return Missing("permission_component: no permission instance is bound")
    value = item.get(component)
    return Missing(f"permission_component: the instance has no {component}") if value is None else value


_SOURCES.update({"authenticated_slot": _authenticated_slot, "permission_component": _permission_component,
                 "permission_instances": _permission_instances})



# ---------------------------------------------------------------- 予算の合計 (A1-BUDGET-TOTAL、Z34 (a) C)

def _budget_effect(env, name, q):
    point = env.point_of(q) if q is not None else env.point("Q*")
    found = env.effects.get((name, point))
    return Missing(f"{name} not captured for {point}") if found is None else found


def _budget_frame_instances(env, q, *_rest):
    """budget_frame_instances: その Q* の区切りでの実 active の親鎖の各枠と outer_global の {identity, budget} (実呼出しの位置)。"""
    return _budget_effect(env, "budget_frames", q)


def _active_frames(env, q, *_rest):
    found = _budget_effect(env, "budget_frames", q)
    return found if isinstance(found, Missing) else [f["identity"] for f in found if f["identity"] != "outer_global"]


def _frame_budget(env, frame, *_rest):
    found = _budget_effect(env, "budget_frames", None)
    if isinstance(found, Missing):
        return found
    matches = [f["budget"] for f in found if f["identity"] == frame]
    return matches[0] if len(matches) == 1 else Missing(f"frame_budget: {len(matches)} frames {frame!r}")


def _dimension_charge(env, frame, dimension, q, *_rest):
    """dimension_charge: 枠の窓の出来事を、宣言した adapter (10 種 → /logical_limit 各 1) で独立に数え直す。計装の計数は読まない。"""
    from . import _fb_rules as rules
    identity = frame.get("identity") if hasattr(frame, "items") else frame
    windows = _budget_effect(env, "frame_events", q)
    if isinstance(windows, Missing):
        return windows
    if identity not in windows:
        return Missing(f"dimension_charge: no event window for {identity!r}")
    table = rules.ENUMERATIONS["BUDGET_DIMENSIONS"]["data"]["adapter"]["event_to_dimension"]
    total = 0
    for kind in windows[identity]:
        if kind not in table:
            return Missing(f"dimension_charge: event {kind!r} has no declared charge (missing_contract)",
                           code="missing_contract")
        total += table[kind].get(dimension, 0)
    return total


@derivation("budget_charges")
def budget_charges(env, q, events):
    """(Q, events) → [{frame, dimension, used, limit}] (BUDGET_FRAMES × BUDGET_DIMENSIONS)。used は窓の出来事の数え直し、limit は
    その枠の UpdateBudget の /logical_limit。"""
    if isinstance(events, Missing):
        return events
    frames = _budget_frame_instances(env, q)
    if isinstance(frames, Missing):
        return frames
    out = []
    for frame in frames:
        used = _dimension_charge(env, frame, "/logical_limit", q)
        if isinstance(used, Missing):
            return used
        out.append({"frame": frame["identity"], "dimension": "/logical_limit", "used": used,
                    "limit": frame["budget"]["logical_limit"]})
    return out


@derivation("rule_data")
def rule_data(env, path):
    """(dot path) → 正本の宣言の値 (`ENUMERATIONS.<ブロック>.items` は宣言の順の全項目の {id, data})。記録や実返却を読まない。"""
    from . import _fb_rules as rules
    parts = path.split(".") if isinstance(path, str) else []
    if len(parts) == 3 and parts[0] == "ENUMERATIONS" and parts[2] == "items" and parts[1] in rules.ENUMERATIONS:
        return [{"id": item["id"], "data": item.get("data", {})} for item in rules.ENUMERATIONS[parts[1]]["items"]]
    return Missing(f"rule_data: unknown path {path!r} (shape)")


_SOURCES.update({"budget_frame_instances": _budget_frame_instances, "active_frames": _active_frames,
                 "frame_budget": _frame_budget, "dimension_charge": _dimension_charge})



def _record_shape(env, value):
    """shape_of(記録): その記録の契約の形の違反の列 (`_fb_shapes`、Z33 ③ (c))。本体は表を読まない。知らない契約の余分な I は
    外側の形だけ (正本 CSB outer_structure.unknown_content)。"""
    from ._fb_shapes import shape_of_record
    point = env.point_of(value)
    if point is None or env.reader is None:
        return Missing("shape_of: the record is not bound to a point")
    try:
        record = env.reader._image.record(point)   # 本文と外側 (Body・役割) を持つ Record そのもの
        name = env.reader.contract_of(point)
    except Exception as exc:   # noqa: BLE001 — 読めない記録は A1-BODY-MISSING の側
        return Missing(f"shape_of: {exc}")
    found = shape_of_record(name, record, record.body.content.as_json())
    return [] if found is None else found
