##########
# insert_flags.py
# 既存のテキストファイル内にある「用途区分」「製品名」のフラグ情報を、Excel ファイルの最新情報に置き換えるバッチスクリプト
##########

import os
import re
import sys
import logging
import pandas as pd
import tkinter as tk
from tkinter import filedialog

# カスタム例外
class FlagReplaceError(Exception):
    """フラグ置換時の例外"""
    pass

# ===== ロギング設定 =====
def setup_logger(log_path: str) -> logging.Logger:
    """Logger を生成して返す"""
    logger = logging.getLogger('insert_flags')
    logger.setLevel(logging.INFO)

    # ファイルハンドラ
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.INFO)

    # コンソールハンドラ
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)

    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

# ===== ファイル・フォルダ選択 =====
def select_directory(title: str) -> str:
    root = tk.Tk(); root.withdraw()
    path = filedialog.askdirectory(title=title)
    root.destroy()
    return path

def select_file(title: str, filetypes) -> str:
    root = tk.Tk(); root.withdraw()
    path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return path

# ===== Excel 読み込み & キャッシュ化 =====
def build_excel_cache(path: str,
                      fixed_cols: set,
                      usage_set: set) -> dict:
    """
    Excel からサブカテゴリ・グループごとのフラグ文字列を構築し、辞書を返す
    key: (サブカテゴリ, グループ), value: フラグ文字列
    """
    df = pd.read_excel(path, dtype=str).fillna("")
    df = df.drop_duplicates(subset=["サブカテゴリ", "グループ"], keep="first")

    cache = {}
    for _, row in df.iterrows():
        key = (row['サブカテゴリ'], row['グループ'])
        usages   = [c for c in row.index if c not in fixed_cols and row[c] == "〇" and c in usage_set]
        products = [c for c in row.index if c not in fixed_cols and row[c] == "〇" and c not in usage_set]
        flag_lines = (
            f"- 用途区分: {', '.join(usages)}\n"
            f"- 製品名: {', '.join(products)}\n"
        )
        cache[key] = flag_lines
    return cache

# ===== テキスト分割 =====
def parse_sections(text: str) -> list:
    """
    テキストをサブカテゴリ単位で分割し、リストを返す
    各要素は dict(header, name, body)
    """
    header_pat = re.compile(r'^(###\s*\d+\.\d+\s*サブカテゴリ:\s*(.+))$', re.MULTILINE)
    headers = list(header_pat.finditer(text))
    sections = []
    for i, m in enumerate(headers):
        header_line = m.group(1)
        name = m.group(2).strip()
        start = m.end() + 1
        end = headers[i+1].start() if i+1 < len(headers) else len(text)
        body = text[start:end]
        sections.append({"header": header_line, "name": name, "body": body})
    return sections

# ===== フラグ置換 =====
def replace_flags(section: dict, excel_cache: dict) -> str:
    """
    セクション dict を受け取り、キャッシュからフラグを取得して置換した文字列を返す
    """
    subcat = section['name']
    header = section['header']
    body   = section['body']

    # グループ行と古いフラグ行をまとめて取得
    lines = (header + '\n' + body).splitlines(True)
    cleaned_lines = []
    for line in lines:
        # フラグ行を削除
        if re.match(r'- 用途区分:.*', line) or re.match(r'- 製品名:.*', line):
            continue
        cleaned_lines.append(line)
    cleaned = ''.join(cleaned_lines)

    grp_pat = re.compile(r'【グループ(\d+):\s*(.+?)】')
    def repl(match):
        idx, group = match.group(1), match.group(2).strip()
        key = (subcat, group)
        if key not in excel_cache:
            raise FlagReplaceError(f"フラグ取得失敗: サブカテゴリ='{subcat}', グループ='{group}'")
        # キャッシュから新フラグを挿入
        return f"【グループ{idx}: {group}】\n" + excel_cache[key]

    return re.sub(grp_pat, repl, cleaned)

# ===== ファイル処理 =====
def process_file(input_path: str,
                 output_path: str,
                 excel_cache: dict,
                 logger: logging.Logger) -> list:
    """
    単一テキストファイルを処理し、エラー発生時はメッセージを返す
    """
    errors = []
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        sections = parse_sections(content)
        out_txt = "## 2. サブカテゴリ別広告表現ルール\n\n"
        for sec in sections:
            try:
                out_txt += replace_flags(sec, excel_cache)
            except FlagReplaceError as fe:
                logger.error(f"{os.path.basename(input_path)}: {fe}")
                errors.append(f"{os.path.basename(input_path)}: {fe}")
                out_txt += sec['header'] + '\n'
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(out_txt)
        logger.info(f"✔ {os.path.basename(input_path)} を更新 -> {output_path}")
    except Exception as e:
        logger.exception(f"{os.path.basename(input_path)} の処理中にエラー発生")
        errors.append(f"{os.path.basename(input_path)}: {e}")
    return errors

# ===== 全体処理 =====
def process_all(in_dir: str,
                out_dir: str,
                excel_cache: dict,
                logger: logging.Logger) -> list:
    """ディレクトリ内の全テキストファイルを処理し、エラー一覧を返す"""
    errors = []
    for fn in os.listdir(in_dir):
        if not fn.lower().endswith('.txt'):
            continue
        in_p = os.path.join(in_dir, fn)
        out_p = os.path.join(out_dir, fn)
        errors.extend(process_file(in_p, out_p, excel_cache, logger))
    return errors

# ===== メイン =====
def main():
    # 選択ダイアログ
    in_dir  = select_directory("新形式テキスト格納フォルダを選択")
    excel_p = select_file("Excelを選択", [("Excel files","*.xlsx;*.xls")])
    out_dir = select_directory("出力先フォルダを選択")
    if not (in_dir and excel_p and out_dir):
        print("入力が選択されていません。処理を中止します。")
        sys.exit(1)

    # ロガー
    logger = setup_logger('insert_flags.log')

    # 定義セット
    usage_set = {"スキンケア","ヘアケア","メイクアップ","ボディケア","ネイルケア","オーラルケア"}
    fixed_cols = {
        "サブカテゴリ","グループ","対象ワード",
        "理由_一般","理由_薬用","改善提案_一般","改善提案_薬用",
        "適正表現例_一般","適正表現例_薬用"
    }

    # Excel キャッシュ生成
    excel_cache = build_excel_cache(excel_p, fixed_cols, usage_set)

    # ファイル一括処理
    errors = process_all(in_dir, out_dir, excel_cache, logger)

    # 結果出力
    if errors:
        logger.warning("処理完了。エラーが発生したファイルがあります。詳細はログをご確認ください。")
        print("⚠ エラーが発生しました。詳細は insert_flags.log をご確認ください。")
    else:
        print("✔ 全ファイルの処理が完了しました。")

if __name__ == '__main__':
    main()
