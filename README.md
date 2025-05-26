# yakkiho-checker
薬機法チェックアプリ

**　アプリソフト　**
    1.data_processing.py（NGワード処理ロジックプロンプト）
    2.ui.py（UI（ユーザーインターフェース）処理プロンプト）
    3.NGword.json（NGワードチェック用JSONファイル）
    4.config.py（プレースホルダー）
    5.debug.log（デバッグ用ログ）


【 管理用テキストデータ 】
    → NGword.jsonの元となる全ての情報が入ったデータ。

【 NGword_output.xlsx 】
    → 管理用テキストデータに対し、以下のことができるマスタファイル
        ・グループ追加
        ・対象ワード追加（考える余地あり、本当にここでやるのがベスト？？）
        ・理由・改善提案・適正表現例の設定　
        ・用途区分・製品名フラグの設定と追加

【 text_to_NGword.py 】
    → 管理用テキストからNGワードJSONを作成するスクリプト


――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

# 【 insert_flags.py 】　

## 概要

`insert_flags.py` は、既存のテキストファイル内にある「用途区分」「製品名」のフラグ情報を、Excel ファイルの最新情報に置き換えるバッチスクリプトです。GUI ダイアログで入出力フォルダと Excel ファイルを選択し、ログを出力しながら一括処理を行います。

**主な処理フロー**

1. GUI ダイアログで以下を選択

   * 処理対象のテキスト格納フォルダ
   * フラグ定義の Excel ファイル
   * 出力先フォルダ
2. Excel を読み込み、(サブカテゴリ, グループ)→フラグ文字列 のキャッシュを生成
3. 各テキストファイルを

   * 「### x.x サブカテゴリ: YYY」ごとに分割
   * 各「【グループi: Z】」ブロックをキャッシュ情報で置換
4. 処理結果を出力フォルダへ書き出し、ログに記録

---

## 必要環境

* Python 3.7 以上
* pip
* ライブラリ

  ```bash
  pip install pandas openpyxl
  ```
* GUI ライブラリ: 標準で同梱されている `tkinter`

---

## ファイル構成

```
project/
├── insert_flags.py          # メインスクリプト
├── insert_flags.log         # 実行ログ (INFO, ERROR)
├── test_insert_flags.py     # pytest テストコード
├── examples/                # サンプルデータ（任意）
│   ├── texts/               # 入力用 .txt ファイル
│   └── data.xlsx            # フラグ定義 Excel
└── README.md                # 本ドキュメント
```

---

## 実行方法 (GUI)

```bash
python insert_flags.py
```

1. **新形式テキスト格納フォルダを選択**: 置換対象の `.txt` ファイルが入ったフォルダを指定
2. **Excelファイルを選択**: 用途区分／製品名フラグ定義を持つ `.xlsx`/`.xls` ファイルを指定
3. **出力先フォルダを選択**: 更新後ファイルを書き出すフォルダを指定
4. 処理終了後、コンソールと `insert_flags.log` を確認

---

## 実行方法 (CLI)

将来的に CLI モードで実行したい場合、以下のようにオプションを指定できます。※現バージョンは GUI モード推奨

```bash
python insert_flags.py \
  -i <入力フォルダ> \
  -e <Excelファイル> \
  -o <出力フォルダ> \
  [-l <ログファイル名>] \
  [-v <ログレベル>]
```

オプション名:

* `-i` / `--input`: テキスト格納フォルダ (必須)
* `-e` / `--excel`: Excel ファイルパス (必須)
* `-o` / `--output`: 出力フォルダ (必須)
* `-l` / `--log`: ログファイル名 (デフォルト `insert_flags.log`)
* `-v` / `--loglevel`: `DEBUG`/`INFO`/`WARNING`/`ERROR` (デフォルト `INFO`)

---

## ログ

* **ファイル出力**: `insert_flags.log` に INFO レベル以上を記録
* **コンソール**: ERROR レベル以上を表示

```text
2025-05-15 14:23:01 INFO: ✔ test1.txt -> output/test1.txt
2025-05-15 14:23:02 ERROR: test2.txt: フラグ取得失敗: サブカテゴリ='A', グループ='X'
```

---

## カスタマイズ

* `usage_set` に新用途カテゴリ（Excel の列名）を追加
* `fixed_cols` に不要/追加された列名を調整
* 正規表現パターンは `parse_sections()` / `replace_flags()` 内で変更可

---

## テスト

ユニットテストは pytest で実行します。

```bash
pytest -q
```

* **対象関数**: `build_excel_cache()`, `parse_sections()`, `replace_flags()`, `process_file()`, `process_all()`
* テストファイル: `test_insert_flags.py`

---

## CI (GitHub Actions)

`.github/workflows/python-tests.yml` を用意して、`feature/*` ブランチへの push および pull\_request 時に自動でテストを実行します。

```yaml
on:
  push:
    branches: ['feature/*']
  pull_request:
    branches: ['feature/*']
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: |
          pip install pytest pandas openpyxl
      - run: pytest -q
```

---

## 今後の拡張

* CLI 完全対応（`argparse` モードの強化）
* 正規表現のさらなる堅牢化・フォーマット対応
* テストカバレッジの拡充（Tkinter 部分のモック化など）

---

## ライセンス

MIT

――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

