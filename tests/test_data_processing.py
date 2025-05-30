import json
import pytest

from data_processing import (
    _basic_normalize_char,
    expand_placeholders,
    normalize_text,
    normalize_text_for_matching,
    convert_to_hiragana_preserving_katakana,
    convert_to_katakana,
    compile_ng_word,
    extract_ng_data_by_subcategory,
    extract_ng_data_from_subcategories,
    get_ng_word_data,
    mask_safe_expressions,
    check_advertisement_with_categories_masking,
    highlight_prohibited_phrases,
    check_ingredient_context,
    load_json,
)

# --- 文字列正規化系 ---
def test_basic_normalize_char_fullwidth_to_halfwidth_and_lower():
    # 全角英字→半角小文字、全角記号→半角
    assert _basic_normalize_char('Ａ') == 'a'
    assert _basic_normalize_char('．') == '.'

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello　WORLD  TEST", "hello world test"),
        ("ＡＢ Ｃ", "ab c"),
        ("スペース ２つ", "スペース 2つ"),
    ]
)
def test_normalize_text_various_inputs(text, expected):
    assert normalize_text(text) == expected

@pytest.mark.parametrize(
    "input_text,expected_norm,expected_map",
    [
        ("たった１日 で", "たった1日で", [0, 1, 2, 3, 4, 6]),
        ("あＢ C", "あbc", [0, 1, 3]),
    ]
)
def test_normalize_text_for_matching_mapping(input_text, expected_norm, expected_map):
    norm, mapping = normalize_text_for_matching(input_text)
    assert norm == expected_norm
    assert mapping == expected_map

# --- 文字種変換系 ---
def test_convert_hiragana_and_katakana():
    src = "アイウあいう"
    # ひらがな保持・カタカナ保持の動作確認
    assert convert_to_hiragana_preserving_katakana(src) == "あいうあいう"
    assert convert_to_katakana(src) == "アイウアイウ"

# --- プレースホルダー展開 ---
def test_expand_placeholders_single():
    results = expand_placeholders("肌{TUKARE}に", {"TUKARE": ["疲れ", "に出た疲れ"]})
    assert "肌疲れに" in results
    assert "肌に出た疲れに" in results

def test_expand_placeholders_with_config(placeholder_values):
    results = expand_placeholders("肌{TUKARE}", placeholder_values)
    assert len(results) >= len(placeholder_values["TUKARE"])

@pytest.mark.parametrize(
    "template,values,expected_contains",
    [
        (
            "{SEIBUN}配合で{MOKUTEKI}",
            {"SEIBUN": ["ヒアルロン酸"], "MOKUTEKI": ["保湿"]},
            ["ヒアルロン酸配合で保湿"]
        ),
        (
            "{TUKARE}肌に",
            {"TUKARE": ["疲れ", "の疲れ"]},
            ["疲れ肌に", "の疲れ肌に"]
        ),
    ]
)
def test_expand_placeholders_multi(template, values, expected_contains):
    results = expand_placeholders(template, values)
    for expect in expected_contains:
        assert expect in results

# --- compile_ng_word / 抽出関連 ---
def test_compile_ng_word_matches():
    pattern = compile_ng_word(r"たった\d+日で")
    assert pattern.search("たった100日で")

def test_compile_ng_word_invalid_regex_fallback():
    bad = "["
    pat = compile_ng_word(bad)
    assert pat.search(bad)

# --- NGワードデータ処理 ---
def test_extract_and_filter_ng_data(sample_ng_json):
    sub = extract_ng_data_by_subcategory(sample_ng_json)
    ng_map = extract_ng_data_from_subcategories(
        {"共通": sub["共通"]}, "スキンケア", "化粧水"
    )
    assert any("肌" in k for k in ng_map)

def test_get_ng_word_data(tmp_path, sample_ng_json):
    p = tmp_path / 'ng.json'
    p.write_text(json.dumps(sample_ng_json), encoding='utf-8')
    ng_map = get_ng_word_data(str(p))
    assert isinstance(ng_map, dict)

# --- マスク & 検出 & ハイライト ---
def test_full_flow_mask_and_detect(ng_word_map):
    text = "化粧水で肌疲れケア"
    violations = check_advertisement_with_categories_masking(text, ng_word_map)
    assert violations and violations[0]["表現"] == '肌疲れ'
    html = highlight_prohibited_phrases(text, violations)
    assert '<span' in html and '肌疲れ' in html

# --- 文脈チェック ---
def test_check_ingredient_context_basic():
    vio = check_ingredient_context("ヒアルロン酸使用", '{SEIBUN}', '{MOKUTEKI}')
    assert vio and '配合目的を記載' in vio[0]["message"]

def test_check_ingredient_context_with_exclusion():
    vio = check_ingredient_context(
        "テスト", 'ヒアルロン酸', '保湿', 'ヒアルロン酸'
    )
    assert vio == []

# --- load_json のテスト ---
def test_load_json_success(tmp_path):
    data = {"a": 1}
    file = tmp_path / "sample.json"
    file.write_text(json.dumps(data), encoding='utf-8')
    assert load_json(str(file)) == data

def test_load_json_not_found():
    with pytest.raises(FileNotFoundError):
        load_json("nonexistent.json")

@pytest.mark.parametrize(
    "content,exc",
    [("not a json", Exception), ("{'a':1}", json.JSONDecodeError)]
)
def test_load_json_invalid(tmp_path, content, exc):
    file = tmp_path / "invalid.json"
    file.write_text(content, encoding='utf-8')
    with pytest.raises(exc):
        load_json(str(file))

# --- mask_safe_expressions のテスト ---
def test_mask_safe_expressions_basic():
    text = "許可された表現とNG表現"
    ng_map = {"NG表現::化粧品等": {"除外表現": ["許可された"]}}
    masked = mask_safe_expressions(text, ng_map)
    assert "許可された" not in masked
    assert masked.startswith("□" * len("許可された"))
