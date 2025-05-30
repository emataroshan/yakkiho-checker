import json
import re
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

# --- 1. _basic_normalize_char ---
@pytest.mark.parametrize("inp,expected", [
    ("Ａ", "a"),     # 全角英字→半角小文字
    ("．", "."),     # 全角句点→半角
    ("５", "5"),     # 全角数字→半角
    ("％", "%"),     # 全角記号→半角
    ("　", " "),     # 全角スペース→半角
])
def test_basic_normalize_char_various(inp, expected):
    assert _basic_normalize_char(inp) == expected

# --- 2. normalize_text / normalize_text_for_matching ---
@pytest.mark.parametrize("text,expected", [
    ("Hello　WORLD  TEST", "hello world test"),
    ("ＡＢ Ｃ", "ab c"),
    ("スペース ２つ", "スペース 2つ"),
    (" テスト  ", " テスト  "),       # 先頭・末尾のスペースはそのまま
])
def test_normalize_text(text, expected):
    assert normalize_text(text) == expected

@pytest.mark.parametrize("orig,expected_norm,expected_map", [
    ("たった１日 で", "たった1日で", [0,1,2,3,4,6]),
    ("あＢ C", "あbc", [0,1,3]),
    ("アイウ カタ", "あいうかた", [0,1,2,4,5]),  # カタカナ→ひらがな、空白除去
])
def test_normalize_text_for_matching(orig, expected_norm, expected_map):
    norm, mapping = normalize_text_for_matching(orig)
    assert norm == expected_norm
    assert mapping == expected_map

# --- 3. 文字種変換系 ---
@pytest.mark.parametrize("func,src,expected", [
    (convert_to_hiragana_preserving_katakana, "アイウあいう", "あいうあいう"),  # 混在変換
    (convert_to_hiragana_preserving_katakana, "あいう", "あいう"),      # ひらがなのみ
    (convert_to_hiragana_preserving_katakana, "アイウ", "あいう"),      # カタカナのみ
    (convert_to_katakana, "あいうえおアイ", "アイウエオアイ"),  # 混在変換
    (convert_to_katakana, "ABCかき", "ABCカキ"),        # ASCII保持
])
def test_char_type_conversions(func, src, expected):
    assert func(src) == expected

# --- 4. プレースホルダー展開 ---
@pytest.mark.parametrize("text,placeholders,expected_contains", [
    ("肌{TUKARE}に", {"TUKARE": ["疲れ","に出た疲れ"]}, ["肌疲れに","肌に出た疲れに"]),
    ("そのままの文",   {"X": ["A","B"]}, ["そのままの文"]),
])
def test_expand_placeholders(text, placeholders, expected_contains):
    results = expand_placeholders(text, placeholders)
    for exp in expected_contains:
        assert exp in results

# --- 5. compile_ng_word ---
@pytest.mark.parametrize("phrase,test_str,should_find", [
    (r"たった\d+日で", "たった100日で", True),     # 正常マッチ
    ("[", "[", True),     # 無効→フォールバック
    ("１日", "２日", False),     # 全角数字対応
])
def test_compile_ng_word_patterns(phrase, test_str, should_find):
    pat = compile_ng_word(phrase)
    assert bool(pat.search(test_str)) == should_find

# --- 6. NGワードデータ抽出 ---
def test_extract_ng_data_by_subcategory_default_branch():
    data = {"global_categories": [
        {"name": "化粧品等", "subcategories": [
            {"name": "その他", "用途区分": [], "関連法令等": [], "共通禁止事項": [], "注意点": [], "NGワードと禁止理由": []}
        ]}
    ]}
    out = extract_ng_data_by_subcategory(data)
    assert out["共通"] and out["一般化粧品"] == [] and out["薬用化粧品"] == []

@pytest.fixture
def sample_subcategory():
    return {"共通": [{
        "name": "テスト", "用途区分": ["A"], "関連法令等": [], "共通禁止事項": [], "注意点": [],
        "NGワードと禁止理由": [{
            "用途区分": ["A"], "製品名": ["P"],
            "理由": {"一般": "reason1", "薬用": ""},
            "改善提案": {"一般": "suggest1", "薬用": ""},
            "適正表現例": {"一般": ["OK"], "薬用": []},
            "除外表現": [], "対象ワード": ["ワード"]
        }]
    }]} 

def test_extract_ng_data_from_subcategories_fallback(sample_subcategory):
    ng = extract_ng_data_from_subcategories(sample_subcategory, selected_usage="A", selected_product="P", category_type="薬用")
    detail = next(iter(ng.values()))
    assert detail["指摘事項"] == "reason1"
    assert detail["改善提案"] == "suggest1"
    assert detail["適正表現例"] == ["OK"]


# --- 7. get_ng_word_data ---
def test_get_ng_word_data(tmp_path, sample_ng_json):
    p = tmp_path / 'ng.json'
    p.write_text(json.dumps(sample_ng_json), encoding='utf-8')
    ng_map = get_ng_word_data(str(p))
    assert isinstance(ng_map, dict)

# --- 8. mask_safe_expressions ---
def test_mask_safe_expressions_invalid_and_dedup():
    text = "foo[bar] foo[bar]"
    ng_map = {"X": {"除外表現": ["[bar]"]}}
    masked = mask_safe_expressions(text, ng_map)
    assert masked == "foo[□□□] foo[□□□]"

# --- 9. check_advertisement_with_categories_masking / highlight ---
def test_check_and_highlight_flow(ng_word_map):
    text = "化粧水で肌疲れケア"
    violations = check_advertisement_with_categories_masking(text, ng_word_map)
    assert violations and violations[0]["表現"] == '肌疲れ'
    html = highlight_prohibited_phrases(text, violations)
    assert '<span' in html and '肌疲れ' in html

# --- 10. check_ingredient_context ---
@pytest.mark.parametrize("text,ing,eff,excl,expected_count", [
    ("ヒアルロン酸使用", '{SEIBUN}', '{MOKUTEKI}', None, 1),
    ("テスト", 'ヒアルロン酸', '保湿', 'ヒアルロン酸', 0),
    ("ヒアルロン酸は保湿効果", 'ヒアルロン酸', '保湿', None, 0),
])
def test_check_ingredient_context(text, ing, eff, excl, expected_count):
    vio = check_ingredient_context(text, ing, eff, excl)
    assert len(vio) == expected_count

# --- 11. load_json ---
def test_load_json_success(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"x":1}', encoding="utf-8")
    assert load_json(str(p)) == {"x":1}

@pytest.mark.parametrize("fname,content,exc", [
    ("no.json", None, FileNotFoundError),
    ("bad.json", "not json", json.JSONDecodeError),
])
def test_load_json_file_errors(tmp_path, fname, content, exc):
    f = tmp_path / fname
    if content is not None:
        f.write_text(content, encoding="utf-8")
    with pytest.raises(exc):
        load_json(str(f))

def test_load_json_permission_error(tmp_path, monkeypatch):
    f = tmp_path / "a.json"
    f.write_text("{}", encoding="utf-8")
    # open による読み込み時に PermissionError を発生させる
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    # load_json は PermissionError をキャッチして Exception をラップして投げる
    with pytest.raises(Exception) as excinfo:
        load_json(str(f))
    assert "JSON ファイルの読み込みに失敗しました" in str(excinfo.value)
