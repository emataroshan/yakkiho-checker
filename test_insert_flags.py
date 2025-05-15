# test_insert_flags.py
# "insert_flags.py"の主な３つの処理（build_excel_cache／parse_sections／replace_flags）それぞれに対応する pytest テスト

# test_insert_flags.py

import os
import pandas as pd
import pytest
import logging

from insert_flags import (
    build_excel_cache,
    parse_sections,
    replace_flags,
    process_file,
    process_all,
    FlagReplaceError,
)

# --- ダミーデータ作成ユーティリティ ---
def make_dummy_df():
    data = {
        'サブカテゴリ': ['A', 'A', 'B'],
        'グループ':     ['X', 'Y', 'Z'],
        'スキンケア':  ['〇', '',  '〇'],
        'ヘアケア':    ['',  '〇',  ''],
        '製品1':       ['',  '〇',  '〇'],
    }
    return pd.DataFrame(data)

DUMMY_TEXT = """\
### 1.1 サブカテゴリ: A
ここは前文。
【グループ1: X】
--- 旧フラグ ---
- 用途区分: ダミー
- 製品名: ダミー

### 1.2 サブカテゴリ: B
【グループ1: Z】
"""

# --- テスト: build_excel_cache ---
def test_build_excel_cache(tmp_path):
    df = make_dummy_df()
    excel_file = tmp_path / "dummy.xlsx"
    df.to_excel(excel_file, index=False)

    fixed_cols = {'サブカテゴリ', 'グループ'}
    usage_set = {'スキンケア', 'ヘアケア'}

    cache = build_excel_cache(str(excel_file), fixed_cols, usage_set)

    # エントリ数は3件
    assert len(cache) == 3

    # A–X は「スキンケア」だけ
    assert cache[('A', 'X')] == "- 用途区分: スキンケア\n- 製品名: \n"

    # A–Y は「ヘアケア」と「製品1」
    assert cache[('A', 'Y')] == "- 用途区分: ヘアケア\n- 製品名: 製品1\n"

# --- テスト: parse_sections ---
def test_parse_sections():
    sections = parse_sections(DUMMY_TEXT)
    # サブカテゴリ A と B の2つセクション
    assert len(sections) == 2
    assert sections[0]['name'] == 'A'
    assert 'ここは前文。' in sections[0]['body']
    assert sections[1]['name'] == 'B'

# --- テスト: replace_flags ---
def test_replace_flags_success():
    # まずキャッシュを手作り
    excel_cache = {
        ('A','X'): "- 用途区分: スキンケア\n- 製品名: \n",
        ('B','Z'): "- 用途区分: \n- 製品名: 製品1\n",
    }
    sections = parse_sections(DUMMY_TEXT)
    out1 = replace_flags(sections[0], excel_cache)
    # 置換後には古い「ダミー」が残らず、正しい行が入る
    assert "- 用途区分: スキンケア" in out1
    assert "ダミー" not in out1

    out2 = replace_flags(sections[1], excel_cache)
    assert "- 製品名: 製品1" in out2

def test_replace_flags_missing_key():
    # キャッシュに存在しない組み合わせだと例外
    excel_cache = {}
    sections = parse_sections(DUMMY_TEXT)
    with pytest.raises(FlagReplaceError):
        replace_flags(sections[0], excel_cache)

# --- fixtures ---
@pytest.fixture
def excel_file(tmp_path):
    df = make_dummy_df()
    path = tmp_path / "dummy.xlsx"
    df.to_excel(path, index=False)
    return str(path)

@pytest.fixture
def excel_cache(excel_file):
    fixed_cols = {
        'サブカテゴリ', 'グループ', '対象ワード',
        '理由_一般','理由_薬用','改善提案_一般','改善提案_薬用',
        '適正表現例_一般','適正表現例_薬用'
    }
    usage_set = {'スキンケア','ヘアケア'}
    return build_excel_cache(excel_file, fixed_cols, usage_set)

@pytest.fixture
def logger():
    # ログは出力しない NullHandler だけつける
    lg = logging.getLogger("test_logger")
    lg.setLevel(logging.DEBUG)
    lg.addHandler(logging.NullHandler())
    return lg

def write_txt(tmp_path, content, name="in.txt"):
    p = tmp_path / name
    p.write_text(content, encoding='utf-8')
    return str(p)

# --- テスト: process_file tests ---
def test_process_file_success(tmp_path, excel_cache, logger):
    # 入力ファイル準備
    in_file = write_txt(tmp_path, DUMMY_TEXT, "test1.txt")
    out_file = tmp_path / "out1.txt"

    errors = process_file(in_file, str(out_file), excel_cache, logger)
    # エラーなし
    assert errors == []

    # 出力ファイルの内容チェック
    out = out_file.read_text(encoding='utf-8')
    assert "ダミー" not in out
    assert "- 用途区分: スキンケア" in out  # キャッシュから置換

def test_process_file_missing_key(tmp_path, excel_cache, logger):
    # キャッシュにキーがないように空にする
    in_file = write_txt(tmp_path, DUMMY_TEXT, "test2.txt")
    out_file = tmp_path / "out2.txt"

    errors = process_file(in_file, str(out_file), {}, logger)
    # セクションが2つなので2件のエラー
    assert len(errors) == 2
    assert all("フラグ取得失敗" in e for e in errors)

    # 出力ファイルは作成され、少なくともヘッダーは書かれている
    out = out_file.read_text(encoding='utf-8')
    assert out.startswith("## 2. サブカテゴリ別広告表現ルール")

# --- テスト: process_all tests ---
def test_process_all_mixed(tmp_path, excel_cache, logger):
    # ディレクトリ構成
    in_dir = tmp_path / "in"; in_dir.mkdir()
    out_dir = tmp_path / "out"; out_dir.mkdir()

    # good.txt x 2
    write_txt(in_dir, DUMMY_TEXT, "good1.txt")
    write_txt(in_dir, DUMMY_TEXT, "good2.txt")

    # process_all の呼び出し
    errors = process_all(str(in_dir), str(out_dir), excel_cache, logger)

    # 正常系なのでエラーなし
    assert errors == []

    # 出力ファイルが2つ作成されている
    outs = sorted(os.listdir(out_dir))
    assert outs == ["good1.txt", "good2.txt"]

# --- テスト: process_all (異常系：キャッシュ空) ---
def test_process_all_all_missing(tmp_path, logger):
    in_dir = tmp_path / "in"; in_dir.mkdir()
    out_dir = tmp_path / "out"; out_dir.mkdir()

    # セクション数２のファイルを１つ用意
    write_txt(in_dir, DUMMY_TEXT, "bad.txt")

    # キャッシュを空で渡す
    errors = process_all(str(in_dir), str(out_dir), {}, logger)

    # sec が2つなので2件のエラー
    assert len(errors) == 2
    assert all("フラグ取得失敗" in e for e in errors)

    # 出力ファイルは作成されている
    assert os.listdir(out_dir) == ["bad.txt"]
