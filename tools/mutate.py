"""S0 検品用: sui を作業用のコピーに写し、誤実装を 1 つずつ入れて pytest が落ちるか確かめる。

使い方: iku/sui で  .venv/Scripts/python tools/mutate.py tools/mutants.json
(S0〜S1c の変異。仕様書の §6 の変異の表から作った。コードを変えて old の文字列が見つからない変異は SETUP_ERROR と出るので、表と一緒に直す)
終了コード: 変異を入れる前のテストがすべて通り、すべての変異が KILLED の時だけ 0。それ以外は 1 (S1c)
mutations.json: [{"id": "M1", "file": "src/sui/ids.py", "old": "...", "new": "...", "expect": ["i1"]}, ...]
- old は file の中にちょうど 1 回だけ現れること (違えば SETUP_ERROR)
- expect はテスト関数名の接頭辞 (test_<id>_) の <id>。そのどれかが落ちれば KILLED
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# .pyc は大きさと秒単位の時刻で使い回されるので、同じ文字数の変異が前の変異の .pyc を拾う。作らせない
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
SUI = Path(__file__).resolve().parents[1]
PY = SUI / ".venv" / "Scripts" / "python.exe"


def run(mut: dict, work: Path) -> tuple[str, str]:
    target = work / mut["file"]
    text = target.read_text(encoding="utf-8")
    mutated = text
    for old, new in mut.get("edits") or [(mut["old"], mut["new"])]:
        if mutated.count(old) != 1:
            return "SETUP_ERROR", f"old appears {mutated.count(old)} times: {old[:40]!r}"
        mutated = mutated.replace(old, new)
    target.write_text(mutated, encoding="utf-8")
    try:
        r = subprocess.run(
            [str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf"],
            cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, env=ENV,
        )
    finally:
        target.write_text(text, encoding="utf-8")
    failed = [l.split("::")[-1].split(" ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    errors = [l for l in r.stdout.splitlines() if l.startswith("ERROR")]
    hit = [f for f in failed if any(f.startswith(f"test_{e}_") for e in mut["expect"])]
    if hit:
        return "KILLED", ", ".join(hit)
    if failed or errors:
        return "KILLED_ELSEWHERE", ", ".join(failed[:5] + errors[:3])
    return "SURVIVED", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def main() -> int:
    muts = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as d:
        work = Path(d) / "sui"
        shutil.copytree(SUI / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(SUI / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(SUI / "pyproject.toml", work / "pyproject.toml")
        shutil.copy(SUI / "requirements.txt", work / "requirements.txt")
        base = subprocess.run([str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                              cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
        print("BASELINE:", base.stdout.strip().splitlines()[-1] if base.stdout.strip() else base.stderr.strip())
        ok = base.returncode == 0
        for m in muts:
            status, detail = run(m, work)
            print(f"{m['id']:4} {status:16} expect={m['expect']} {detail}")
            ok = ok and status == "KILLED"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
