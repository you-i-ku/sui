"""Ledger-backed identity for F boundaries, separate from reference lookup.

A Ref selects records. A binding authenticates their CID and canonical bytes.
Only immutable readers of checked headers, seals and contents are accepted here.
"""
from dataclasses import dataclass

from . import f as core


@dataclass(frozen=True)
class RecordBinding:
    ref: object
    cid: str
    digest: str


def reader_for(ledger):
    from ._f_world import freeze_world_ledger
    return freeze_world_ledger(ledger)


def require_reader(resources):
    core._require(resources, core.FResources)
    reader = resources.preference_ledger
    if reader is None:
        raise core.FReplayUnavailable('missing_input', 'ledger', '/ledger')
    return reader


def point(reader, cid):
    from ._f_world import _UnreadLedgerRecord
    if reader is None or cid not in reader._entries:
        raise core.FReplayUnavailable('missing_input', cid, '/ledger')
    value = reader._records[cid]
    if isinstance(value, _UnreadLedgerRecord):
        if value.missing:
            raise core.FReplayUnavailable('missing_input', cid, '/ledger')
        raise core.FReplayMismatch('result_mismatch', fields=('/ledger',))
    return reader._entries[cid], value, RecordBinding(value.id, cid, core._digest(value))


def bind_record(reader, record, *, parents=None, cids=None):
    if reader is None or record.id not in reader._by_id:
        raise core.FReplayUnavailable('missing_input', str(record.id), '/ledger')
    selected = reader._by_id[record.id] if cids is None else cids
    if parents is not None:
        selected = tuple(cid for cid in selected if reader._entries[cid].parents == parents)
        if not selected:
            raise core.FReplayMismatch('result_mismatch', fields=('/parents',))
    if not selected:
        raise core.FReplayUnavailable('missing_input', str(record.id), '/ledger')
    expected = core._digest(record)
    bindings = []
    for cid in sorted(selected):
        entry, actual, binding = point(reader, cid)
        if entry.id != record.id or binding.digest != expected:
            raise core.FReplayMismatch('result_mismatch', fields=('/records',))
        bindings.append(binding)
    return tuple(bindings)


def resource_record(resources, ref, *, parents=None):
    core._require(resources, core.FResources)
    record = next((r for r in resources.records if r.id == ref), None)
    if record is None:
        raise core.FReplayUnavailable('missing_input', str(ref), '/records')
    return record, bind_record(require_reader(resources), record, parents=parents)


def resource_bindings(resources, refs=(), *, parents=()):
    bindings = []
    for ref in sorted(set(refs), key=str):
        _, values = resource_record(resources, ref)
        bindings.extend(values)
    if parents:
        reader = require_reader(resources)
        for cid in sorted(parents):
            _, _, binding = point(reader, cid)
            bindings.append(binding)
    return unique_bindings(bindings)


def unique_bindings(bindings):
    return tuple(sorted(set(bindings), key=lambda b:(b.cid, str(b.ref), b.digest)))


def check_bindings(reader, bindings):
    for expected in bindings:
        if reader is None:
            raise core.FReplayUnavailable('missing_input', 'ledger', '/ledger')
        if expected.cid not in reader._entries and expected.ref in reader._by_id:
            raise core.FReplayMismatch('result_mismatch', fields=('/dependencies',))
        _, _, actual = point(reader, expected.cid)
        if actual != expected:
            raise core.FReplayMismatch('result_mismatch', fields=('/dependencies',))
