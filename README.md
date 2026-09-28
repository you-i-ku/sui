# sui

sui は、ゆうの理想「何にも縛られない、自由な AI」のための新しい核です。
事実・予測・解釈を分けて記録し、有限の世界で観測・推論・選択・学習の一周をつなぎます。
S1c では観測の回数だけを学んで持ち、状態が時間で変わらない前提で、信念と仮説ごとの帳面を回数から計算します。

テストは、用意した `.venv` から実行します。

```powershell
.venv\Scripts\python -m pytest -q -W error
```

記録の約束の意味は、コードの [`src/sui/s1_contracts.py`](src/sui/s1_contracts.py) が正です。
今後増える `*_contracts.py` も、対応する記録の約束を宣言します。
設計の文書 (`.md`) は方針により git に載らず、この README だけを載せます。
