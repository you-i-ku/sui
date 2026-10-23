"""試験の土台: xdist の並列の数を `tools/run_tests.py` の auto の上限で切る (ゆう 2026-10-23「rules に書いてあるのに間違えるのを
防止するには？」)。`pytest -n 14` と直に打っても、`-n auto` でも、起動の瞬間の min(コア − 4, 空きメモリ ÷ 1.2 GB, 8) まで。
Claude にも Codex の試験の係にも効く (規則を読ませず、入口で塞ぐ)。上限は xdist の --maxprocesses に入れる (既に小さい指定は保つ)。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from run_tests import auto_workers  # noqa: E402


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config):
    if not getattr(config.option, "numprocesses", None):
        return None   # 並列でない回し方 (xdist なし・-n 0) は触らない
    cap, _cores, _free = auto_workers()
    given = config.option.maxprocesses
    if given is None or given > cap:
        config.option.maxprocesses = cap
    return None
