import os
import sys

# pytest 実行時に、この conftest.py のあるフォルダ（プロジェクトルート）を
# モジュール検索パスに追加
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import pytest
from data_processing import (
    expand_placeholders,
    normalize_text_for_matching,
    normalize_text,
    convert_to_hiragana_preserving_katakana,
    convert_to_katakana,
    extract_ng_data_by_subcategory,
    extract_ng_data_from_subcategories,
)
from config import PLACEHOLDER_VALUES

@pytest.fixture
def placeholder_values():
    """config.PLACEHOLDER_VALUES をそのまま返すフィクスチャ"""
    return PLACEHOLDER_VALUES

@pytest.fixture
def sample_ng_json():
    """テスト用の最小限の NGword.json サンプル"""
    return {
        "version": "1.0.0",
        "global_categories": [
            {
                "id": "CAT001",
                "name": "化粧品等",
                "subcategories": [
                    {
                        "id": "SUB_E01",
                        "parent_id": "CAT001",
                        "name": "E01_共通_「肌の疲れ」等の表現",
                        "NGワードと禁止理由": [
                            {
                                "グループ": "肌の疲労回復的表現",
                                "用途区分": ["スキンケア"],
                                "製品名": ["化粧水"],
                                "対象ワード": ["肌{TUKARE}", "{TUKARE}顔"],
                                "除外表現": [],
                                "理由": {"一般": "疲労回復的な表現は…", "薬用": ""},
                                "改善提案": {"一般": "…", "薬用": ""},
                                "適正表現例": {"一般": ["例文"], "薬用": []}
                            }
                        ],
                        "関連法令等": ["適正広告ガイドライン E1"]
                    }
                ]
            }
        ]
    }

@pytest.fixture
def subcategory_data(sample_ng_json):
    """extract_ng_data_by_subcategory の結果"""
    return extract_ng_data_by_subcategory(sample_ng_json)

@pytest.fixture
def ng_word_map(subcategory_data):
    """extract_ng_data_from_subcategories の結果"""
    return extract_ng_data_from_subcategories(
        {"共通": subcategory_data["共通"]},
        selected_usage="スキンケア",
        selected_product="化粧水",
    )
