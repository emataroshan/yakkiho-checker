##########
# insert_flags.py
# テキスト内の「用途区分」「製品名」フラグを Excel 情報で更新するバッチスクリプト
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
    """フラグ置換エラー"""
    pass

# ===== ロギング設定 =====
def setup_logger(log_path: str, level: str = 'INFO') -> logging.Logger:
    """
    ロガーを生成し、ファイルおよびコンソール出力を設定
    :param log_path: ログファイルパス
    :param level: ログレベル (DEBUG, INFO, WARNING, ERROR)
    """
    logger = logging.getLogger('insert_flags')
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # ファイル出力ハンドラ
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(getattr(logging, level.upper(), logging.INFO))

    # コンソール出力ハンドラ（INFO以上）
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fmt = '%(asctime)s %(levelname)s: %(message)s'
    datefmt = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt, datefmt)
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(fh)
    logger.addHandler(ch)
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
                      usage_set: set,
                      logger: logging.Logger) -> dict:
    """
    Excelファイルを読み込み、(サブカテゴリ, グループ)毎のフラグ文字列を構築して辞書化
    """
    try:
        df = pd.read_excel(path, dtype=str).fillna("")
    except Exception as e:
        logger.error(f'Excel読み込み失敗: {e}')
        sys.exit(1)
    df = df.drop_duplicates(subset=["サブカテゴリ", "グループ"], keep="first")

    cache = {}
    for _, row in df.iterrows():
        key = (row['サブカテゴリ'], row['グループ'])
        usages   = [col for col in row.index if col not in fixed_cols and col in usage_set and row[col] == "〇"]
        products = [col for col in row.index if col not in fixed_cols and col not in usage_set and row[col] == "〇"]
        cache[key] = (
            f"- 用途区分: {', '.join(usages)}\n"
            f"- 製品名: {', '.join(products)}\n"
        )
    return cache

# ===== テキスト分割 =====
def parse_sections(text: str) -> list:
    """
    複数のセクションに分割して返す
    ヘッダー例: ### 1.1 サブカテゴリ: XXX
    """
    header_pat = re.compile(
        r'^(?P<header>###\s*\d+\.\d+\s*サブカテゴリ\s*[:：]\s*(?P<name>.+?))\s*$',
        re.MULTILINE
    )
    sections = []
    matches = list(header_pat.finditer(text))
    for idx, m in enumerate(matches):
        name = m.group('name').strip()
        start = m.end() + 1
        end = matches[idx+1].start() if idx+1 < len(matches) else len(text)
        body = text[start:end]
        sections.append({'header': m.group('header'), 'name': name, 'body': body})
    return sections

# ===== フラグ置換 =====
def replace_flags(section: dict, excel_cache: dict) -> str:
    """
    セクション情報を受け取り、キャッシュ辞書からフラグを取得・置換して返す
    """
    subcat = section['name']
    header = section['header']
    body   = section['body']

    grp_pat = re.compile(r'【グループ(?P<idx>\d+)[：:]\s*(?P<group>.+?)】')

    def repl(m):
        i = m.group('idx')
        group = m.group('group').strip()
        key = (subcat, group)
        if key not in excel_cache:
            raise FlagReplaceError(f"フラグ取得失敗: サブカテゴリ='{subcat}', グループ='{group}'")
        return f"【グループ{i}: {group}】\n" + excel_cache[key]

    cleaned = re.sub(
        r'^(【グループ\d+[:：].*?】\n)(?:- 用途区分:.*?\n)?(?:- 製品名:.*?\n)?',
        r'\1', header + '\n' + body,
        flags=re.MULTILINE
    )
    return re.sub(grp_pat, repl, cleaned)

# ===== ファイル処理 =====
def process_file(input_path: str,
                 output_path: str,
                 excel_cache: dict,
                 logger: logging.Logger) -> list:
    errors = []
    try:
        text = open(input_path, 'r', encoding='utf-8').read()
        sections = parse_sections(text)
        out = "## 2. サブカテゴリ別広告表現ルール\n\n"
        for sec in sections:
            try:
                out += replace_flags(sec, excel_cache)
            except FlagReplaceError as e:
                logger.error(f"{os.path.basename(input_path)}: {e}")
                errors.append(f"{os.path.basename(input_path)}: {e}")
                out += sec['header'] + '\n'
        open(output_path, 'w', encoding='utf-8').write(out)
        logger.info(f"✔ {os.path.basename(input_path)} -> {output_path}")
    except Exception as e:
        logger.exception(f"{os.path.basename(input_path)} の処理中に例外発生")
        errors.append(f"{os.path.basename(input_path)}: {e}")
    return errors

# ===== ディレクトリ一括処理 =====
def process_all(in_dir: str,
                out_dir: str,
                excel_cache: dict,
                logger: logging.Logger) -> list:
    all_errors = []
    files = [f for f in os.listdir(in_dir) if f.lower().endswith('.txt')]
    for fn in files:
        in_p = os.path.join(in_dir, fn)
        out_p = os.path.join(out_dir, fn)
        errs = process_file(in_p, out_p, excel_cache, logger)
        all_errors.extend(errs)
    return all_errors

# ===== メイン =====
def main():
    # ログ設定
    logger = setup_logger('insert_flags.log')
    logger.info('処理開始')

    # ダイアログでフォルダ／ファイル選択
    in_dir  = select_directory('新形式テキスト格納フォルダを選択')
    excel_p = select_file('Excelファイルを選択', [("Excel files","*.xlsx;*.xls")])
    out_dir = select_directory('出力先フォルダを選択')
    if not (in_dir and excel_p and out_dir):
        logger.error('入力が選択されていません。処理を中止します。')
        sys.exit(1)

    # 定義セット
    usage_set = {"スキンケア","ヘアケア","メイクアップ","ボディケア","ネイルケア","オーラルケア"}
    fixed_cols = {"サブカテゴリ","グループ","対象ワード",
                  "理由_一般","理由_薬用","改善提案_一般","改善提案_薬用",
                  "適正表現例_一般","適正表現例_薬用"}

    # Excel→キャッシュ
    cache = build_excel_cache(excel_p, fixed_cols, usage_set, logger)

    # 一括処理
    errors = process_all(in_dir, out_dir, cache, logger)
    if errors:
        logger.warning(f"処理完了: {len(errors)} 件のエラーが発生しました。詳細はログを参照してください。")
        sys.exit(1)
    logger.info('すべての処理が正常に完了しました。')

if __name__ == '__main__':
    main()