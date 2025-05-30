#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
json_export_script.py
NGword マスター (MergedMaster シート) と Markdown ファイルから JSON を生成するスクリプト
Markdownファイルの不足 → エラー
"""
import os
import json
import re
from datetime import datetime, timezone, timedelta
import pandas as pd

# 定数・設定
EXCEL_FILE      = 'NGwordマスタ.xlsm'
SHEET_TABLE     = 'MergedMaster'
MD_DIR          = './markdown_texts/'
OUTPUT_JSON     = 'NGword.json'
PARENT_CAT_ID   = 'CAT001'
PARENT_CAT_NAME = '化粧品等'


def parse_markdown(subcat_id: str, subcat_name: str) -> dict:
    """
    Markdown ファイルから以下セクションをパースして辞書で返す:
      - 概要
      - 共通禁止事項
      - 関連法令等
      - 注意点
    NGワード部分は build_ng_list で構築
    """
    filename = f"{subcat_name}.md"
    path = os.path.join(MD_DIR, filename)
    sections = {}
    current = None
    if not os.path.exists(path):
        print(f"Warning: Markdown file not found: {path}")
        return {'概要':'', 'common_ng':[], 'laws':[], 'notes':[]}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            header = re.match(r'^###\s+(.*)', line)
            if header:
                current = header.group(1).strip()
                sections[current] = []
            else:
                if current:
                    sections[current].append(line.rstrip('\n'))
    # ヘッダー名に合わせてキーを抽出
    def parse_list(lines):
        items = []
        for l in lines:
            if l.strip().startswith(('-', '・')):
                item = re.sub(r'^[\-\u30FB]\s*', '', l.strip())
                if item:
                    items.append(item)
        return items

    result = {
        '概要':   '\n'.join(sections.get('概要', [])).strip(),
        'common_ng': parse_list(sections.get('共通禁止事項', [])),
        'laws':      parse_list(sections.get('関連法令等', [])),
        'notes':     parse_list(sections.get('注意点', [])),
    }
    return result


def parse_cell_list(cell):
    """
    セルの文字列やリストを Python リストに正規化
    """
    if pd.isna(cell):
        return []
    if isinstance(cell, list):
        return cell
    if isinstance(cell, str):
        # JSON 形式リストの可能性
        try:
            val = json.loads(cell)
            if isinstance(val, list):
                return val
        except:
            pass
        # 改行または区切り文字で分割
        lines = [l.strip() for l in cell.splitlines() if l.strip()]
        items = []
        for l in lines:
            parts = re.split(r'[,;；]', l)
            for p in parts:
                p2 = p.strip()
                if p2:
                    items.append(p2)
        # 重複を排除
        seen = set()
        unique = []
        for i in items:
            if i not in seen:
                seen.add(i)
                unique.append(i)
        return unique
    return [cell]


def build_ng_list(df_grp: pd.DataFrame, subcat_id: str) -> list:
    """
    MergedMaster のサブカテゴリ DataFrame を受け取り、
    グループ単位で NGワードと禁止理由を辞書化してリストで返す
    用途と製品は「用途_*」「製品_*」の列で〇をチェックして抽出
    対象ワードは「対象ワード」列をすべて収集
    """
    ng_list = []
    for group_id, grp in df_grp.groupby('グループID'):
        group_name = grp['グループ名'].iloc[0]
        # 用途列を動的に検出
        usage_cols = [c for c in grp.columns if c.startswith('用途_')]
        usage = [c.replace('用途_', '') for c in usage_cols if str(grp[c].iloc[0]).strip() == '〇']
        # 製品列を動的に検出
        product_cols = [c for c in grp.columns if c.startswith('製品_')]
        products = [c.replace('製品_', '') for c in product_cols if str(grp[c].iloc[0]).strip() == '〇']
        # 対象ワード列を動的に検出
        target_cols = [c for c in grp.columns if c.startswith('対象ワード')]
        targets = []
        for col in target_cols:
            for cell in grp[col]:
                targets.extend(parse_cell_list(cell))
        seen = set()
        targets = [x for x in targets if not (x in seen or seen.add(x))]
        # 除外表現
        excludes = []
        if '除外表現' in grp:
            for cell in grp['除外表現']:
                excludes.extend(parse_cell_list(cell))
            seen2 = set()
            excludes = [x for x in excludes if not (x in seen2 or seen2.add(x))]
        # 理由
        cell_reason_general   = grp['理由_一般'].iloc[0] if '理由_一般' in grp.columns else ''
        cell_reason_medicinal = grp['理由_薬用'].iloc[0] if '理由_薬用' in grp.columns else ''
        reason_general   = '' if pd.isna(cell_reason_general) else cell_reason_general
        reason_medicinal = '' if pd.isna(cell_reason_medicinal) else cell_reason_medicinal
        # 改善提案
        cell_proposal_general   = grp['改善提案_一般'].iloc[0] if '改善提案_一般' in grp.columns else ''
        cell_proposal_medicinal = grp['改善提案_薬用'].iloc[0] if '改善提案_薬用' in grp.columns else ''
        proposal_general   = '' if pd.isna(cell_proposal_general) else cell_proposal_general
        proposal_medicinal = '' if pd.isna(cell_proposal_medicinal) else cell_proposal_medicinal
        # 適正表現例
        example_general   = parse_cell_list(grp['適正表現例_一般'].iloc[0]) if '適正表現例_一般' in grp.columns else []
        example_medicinal = parse_cell_list(grp['適正表現例_薬用'].iloc[0]) if '適正表現例_薬用' in grp.columns else []

        ng_item = {
            'グループ':       group_name,
            '用途区分':       usage,
            '製品名':         products,
            '対象ワード':     targets,
            '除外表現':       excludes,
            '理由': {
                '一般': reason_general,
                '薬用': reason_medicinal
            },
            '改善提案': {
                '一般': proposal_general,
                '薬用': proposal_medicinal
            },
            '適正表現例': {
                '一般': example_general,
                '薬用': example_medicinal
            }
        }
        ng_list.append(ng_item)
    return ng_list


def main():
    # MergedMaster シート読み込み
    df_master = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_TABLE)

    # サブカテゴリごとに JSON オブジェクトを生成
    subcats = []
    for subcat_id, df_grp in df_master.groupby('サブカテゴリID'):
        subcat_name = df_grp['サブカテゴリ名'].iloc[0]
        text = parse_markdown(subcat_id, subcat_name)
        ng_list = build_ng_list(df_grp, subcat_id)
        subcats.append({
            'id':                f'SUB_{subcat_id}',
            'parent_id':         PARENT_CAT_ID,
            'name':              subcat_name,
            # '概要':              text['概要'],  ←現時点で使用予定なし
            'NGワードと禁止理由': ng_list,
            # '共通禁止事項':        text['common_ng'],  ←現時点で使用予定なし
            '関連法令等':          text['laws'],
            # '注意点':             text['notes'],  ←現時点で使用予定なし
        })

    # グローバルカテゴリ構造を組み立て
    global_categories = [{
        'id':             PARENT_CAT_ID,
        'name':           PARENT_CAT_NAME,
        # '概要':           '',  ←現時点で使用予定なし
        'subcategories':  subcats
    }]

    # 最終 JSON 出力
    output = {
        'version':           '1.0.0',
        'last_updated':      datetime.now(timezone(timedelta(hours=+9))).isoformat(),
        'global_categories': global_categories
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"→ {OUTPUT_JSON} を出力しました")


if __name__ == '__main__':
    main()
