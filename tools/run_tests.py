"""検品の試験を、いつも同じ回し方で回して、短い要約だけを画面に出す (関所 F の後、開発フロー F5)。

使い方: iku/sui で  .venv/Scripts/python -B tools/run_tests.py [all | <pytest に渡す場所 …>] [-n 並列] [--timeout 秒]
- all (既定): ① tests を並列 (時間に敏感な 3 ファイルを除く) ② その 3 ファイルを 1 本ずつ ③ backup
- 場所を渡すと、その場所だけを 1 回 (例: tests/test_gate_f_facts.py)
- 画面には部ごとの件数・落ちた試験の名前・最初の数行だけ。全部の出力は --log の場所 (既定は一時フォルダ) のファイルへ
終了コード: 全部の部が通った時だけ 0
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUI = Path(__file__).resolve().parents[1]
PY = SUI / ".venv" / "Scripts" / "python.exe"
# 負荷で揺れる既存の試験 (HANDOFF §F)。並列の部から外して 1 本ずつ回す
SERIAL = ["tests/test_runtime.py", "tests/test_store.py", "tests/test_s4b_action_integration.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}


def part(name, args, log_dir, timeout, show):
    log = log_dir / f"{name}.txt"
    cmd = [str(PY), "-B", "-m", "pytest", "-q", "-W", "error", "-p", "no:cacheprovider", "--tb=line", "-rf",
           f"--basetemp={log_dir / ('tmp_' + name)}", *args]
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=SUI, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=ENV)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = e.stdout or "", "timeout"
        if isinstance(out, bytes):  # text=True でも時間切れの時は bytes で返ることがある
            out = out.decode("utf-8", "replace")
    log.write_text(out, encoding="utf-8")
    lines = out.splitlines()
    summary = next((l for l in reversed(lines) if " passed" in l or " failed" in l or " error" in l),
                   next((l for l in reversed(lines) if l.strip()), "(出力なし)"))
    failed = [l for l in lines if l.startswith(("FAILED", "ERROR"))]
    print(f"[{name}] {summary.strip('= ')}  ({time.monotonic() - start:.0f} 秒、終了 {code})  log: {log}")
    for l in failed[:show]:
        print("   ", l[:300])
    if len(failed) > show:
        print(f"    … ほか {len(failed) - show} 件 (log を見る)")
    return code == 0


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp932 の画面でも Codex の取り込みでも同じ文字に
    ap = argparse.ArgumentParser()
    ap.add_argument("where", nargs="*", default=["all"])
    ap.add_argument("-n", default="2", help="並列の数 (PC のメモリが少ないので既定 2)")
    ap.add_argument("--timeout", type=int, default=3600, help="部ごとの時間の上限 (秒)")
    ap.add_argument("--log", default=None, help="全部の出力を置くフォルダ")
    ap.add_argument("--show", type=int, default=20, help="画面に出す落ちた試験の数")
    a = ap.parse_args()
    log_dir = Path(a.log) if a.log else Path(tempfile.mkdtemp(prefix="sui_tests_"))
    log_dir.mkdir(parents=True, exist_ok=True)
    if a.where == ["all"]:
        ignore = [f"--ignore={p}" for p in SERIAL]
        ok = part("1_parallel", ["-n", a.n, "tests", *ignore], log_dir, a.timeout, a.show)
        ok = part("2_serial", SERIAL, log_dir, a.timeout, a.show) and ok
        ok = part("3_backup", ["backup"], log_dir, a.timeout, a.show) and ok
    else:
        ok = part("only", ["-n", a.n, *a.where], log_dir, a.timeout, a.show)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
