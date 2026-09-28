"""本体を読むだけで開き、点の集合を蓄積する外部の係。"""

from dataclasses import dataclass
from os import PathLike

from sui.ledger import Ledger, RandomSalts
from sui.store import SqliteStore


@dataclass(frozen=True)
class SyncReport:
    added: int
    models: int


def sync(source: str | PathLike, target: str | PathLike) -> SyncReport:
    with SqliteStore.open(source, readonly=True) as src:
        with SqliteStore.open(target, create=True) as dst:
            source_ledger = Ledger(salts=RandomSalts(), entries=src.entries, contents=src.contents)
            refs = src.models.refs() - dst.models.refs()
            for ref in sorted(refs):
                dst.models.put(src.models.get(ref))
            target_ledger = Ledger(salts=RandomSalts(), entries=dst.entries, contents=dst.contents)
            before = len(target_ledger.entries())
            target_ledger.merge(source_ledger)
            report = SyncReport(added=len(target_ledger.entries()) - before, models=len(refs))
    return report
