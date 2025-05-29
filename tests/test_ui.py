import os
import sys
# tests/ のひとつ上のフォルダ（プロジェクトルート）を検索パスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import requests
from unittest.mock import Mock
import streamlit as st
import datetime

import ui
from ui import (
    merge_violations,
    merge_same_ng_violations,
    submit_ad_text,
    get_ng_words,
)

# --- submit_ad_text のテスト ---
def test_submit_ad_text_success(monkeypatch):
    called = {}
    def fake_post(url, data, headers):
        called['url'] = url
        called['data'] = data
        called['headers'] = headers
        return Mock(status_code=200)
    monkeypatch.setattr(requests, 'post', fake_post)

    # 呼び出し時に例外が発生しないことを確認
    submit_ad_text('テスト広告文')
    assert called['url'] == ui.AD_FORM_URL
    assert called['data'] == {ui.AD_ENTRY_ID: 'テスト広告文'}

# Exception 発生時にも例外を投げない

def test_submit_ad_text_exception(monkeypatch):
    def fake_post(url, data, headers):
        raise requests.exceptions.ConnectionError
    monkeypatch.setattr(requests, 'post', fake_post)
    # 例外が内包され、何も起きない
    submit_ad_text('広告文')  # should not raise

# --- merge_violations のテスト ---
def test_merge_violations_combines_overlaps():
    violations = [
        {'開始位置': 0, '終了位置': 5},
        {'開始位置': 3, '終了位置': 8},
        {'開始位置': 10, '終了位置': 15},
    ]
    merged = merge_violations(violations, tolerance=2)
    # 最初の2件は重複または近接で統合され、結果は2件となる
    assert len(merged) == 3
    starts = [v['開始位置'] for v in merged]
    assert starts == [0, 3, 10]

# --- merge_same_ng_violations のテスト ---
def test_merge_same_ng_violations_counts():
    violations = [
        {'表現': 'NG', '開始位置': 0, '終了位置': 2},
        {'表現': 'NG', '開始位置': 5, '終了位置': 7},
        {'表現': 'OK', '開始位置': 10, '終了位置': 12},
    ]
    merged = merge_same_ng_violations(violations)
    # 同一ワードは大文字のまま集約される
    counts = {v['表現']: v['count'] for v in merged}
    assert counts['NG'] == 2
    assert counts['OK'] == 1

# --- get_ng_words のテスト ---
def test_get_ng_words(monkeypatch, placeholder_values):
    # モックする関数
    fake_data = {'global_categories': [{'name': '化粧品等', 'subcategories': []}],}
    monkeypatch.setattr(ui, 'load_json', lambda _: fake_data)
    monkeypatch.setattr(ui, 'extract_ng_data_by_subcategory', lambda data: {'共通': [], '一般化粧品': []})
    monkeypatch.setattr(ui, 'extract_ng_data_from_subcategories', lambda subs, u, p, c: {'key':'value'})
    result = get_ng_words('一般化粧品', 'スキンケア', '化粧水')
    assert result['ng_dict'] == {'key':'value'}
    assert 'subcategories' in result

# --- Streamlit 関連のモック例 ---
def test_render_sidebar_default(monkeypatch):
    # Streamlit のセッションステートや UI をモック
    monkeypatch.setattr(st, 'sidebar', st)
    monkeypatch.setattr(st, 'radio', lambda *args, **kwargs: '一般化粧品')
    monkeypatch.setattr(st, 'selectbox', lambda *args, **kwargs: 'スキンケア')
    monkeypatch.setattr(st, 'text_area', lambda *args, **kwargs: 'テキスト')
    monkeypatch.setattr(st, 'button', lambda *args, **kwargs: False)
    # 実行時に例外にならず、返り値のタプルを得る
    selected_category, selected_usage, selected_product = ui.render_sidebar()
    assert selected_category == '一般化粧品'
    assert selected_usage == 'スキンケア'

# --- submit_feedback のテスト ---
@pytest.fixture(autouse=True)
def reset_session_state(monkeypatch):
    # 各テスト毎にセッションステートをリセット
    st.session_state.clear()
    yield
    st.session_state.clear()

def test_submit_feedback_empty(monkeypatch):
    # feedback_area が空文字 or whitespace のとき
    st.session_state.feedback_area = "   "
    ui.submit_feedback()
    assert st.session_state.feedback_message == "入力してから送信してください。"

@pytest.mark.parametrize("status, expected_msg", [
    (200, "フィードバックありがとうございました！"),
    (302, "フィードバックありがとうございました！"),
    (500, "送信に失敗しました。"),
])
def test_submit_feedback_status_codes(monkeypatch, status, expected_msg):
    # 有効な入力をセット
    st.session_state.feedback_area = "ありがと"
    # requests.post をモックしてステータスを返す
    fake_resp = Mock(status_code=status)
    monkeypatch.setattr(requests, "post", lambda url, data: fake_resp)

    ui.submit_feedback()
    assert st.session_state.feedback_message == expected_msg
    if status in (200, 302):
        # 成功時は入力欄クリア
        assert st.session_state.feedback_area == ""
    else:
        # 失敗時は入力はそのまま
        assert st.session_state.feedback_area == "ありがと"

def test_submit_feedback_exception(monkeypatch):
    st.session_state.feedback_area = "問題報告"
    # post が例外を投げる
    def raise_error(url, data):
        raise requests.exceptions.ConnectionError
    monkeypatch.setattr(requests, "post", raise_error)

    ui.submit_feedback()
    assert st.session_state.feedback_message == "送信中にエラーが発生しました。"

@pytest.fixture(autouse=True)
def reset_session_and_mocks(request, monkeypatch):
    # セッションステートクリア
    st.session_state.clear()
    # render_sidebar は "test_render_sidebar_" 系のテストでは本物を呼ぶ
    if not request.node.name.startswith("test_render_sidebar_"):
        monkeypatch.setattr(ui, 'render_sidebar', lambda: ("一般化粧品", "スキンケア", "化粧水"))
    # フォーム送信は無視
    monkeypatch.setattr(ui, 'submit_ad_text', lambda text: None)
    # load_json はレンダリング／main テスト以外ではスキップしない
    monkeypatch.setattr(ui, 'load_json', lambda path: {})
    # get_ng_words のスタブは get_ng_words 系テストでは外す
    if not request.node.name.startswith("test_get_ng_words"):
        monkeypatch.setattr(ui, 'get_ng_words', lambda a, b, c: {"ng_dict": {}})
    # highlight_prohibited_phrases はシンプルHTMLを返す
    monkeypatch.setattr(ui, 'highlight_prohibited_phrases', lambda text, vio: "<b>HIGHLIGHT</b>")
    # チェック関数もあとで上書き
    yield
    st.session_state.clear()

def stub_st_methods(monkeypatch, text_area_return, button_return):
    """
    st の代表的メソッドをスタブし、呼び出しを記録する dict を返す。
    """
    calls = []
    monkeypatch.setattr(st, 'title',       lambda txt: calls.append(('title', txt)))
    monkeypatch.setattr(st, 'markdown',    lambda txt, **kw: calls.append(('markdown', txt)))
    monkeypatch.setattr(st, 'write',       lambda *args, **kw: calls.append(('write', args, kw)))
    monkeypatch.setattr(st, 'warning',     lambda msg: calls.append(('warning', msg)))
    monkeypatch.setattr(st, 'success',     lambda msg: calls.append(('success', msg)))
    monkeypatch.setattr(st, 'subheader',   lambda txt: calls.append(('subheader', txt)))
    monkeypatch.setattr(st, 'text_area',   lambda label, height=None: text_area_return)
    monkeypatch.setattr(st, 'button',      lambda label: button_return)
    return calls

def test_render_main_no_input(monkeypatch):
    # テキスト空、ボタン押下
    calls = stub_st_methods(monkeypatch, text_area_return="", button_return=True)
    # check_advertisement... を空リスト返す stub
    monkeypatch.setattr(ui, 'check_advertisement_with_categories_masking', lambda text, d: [])
    ui.render_main()
    # 警告が一度だけ呼ばれる
    assert ('warning', "広告文を入力してください。") in calls
    # メッセージ後に早期 return するため success や write は呼ばれない
    assert all(c[0] != 'success' for c in calls)

def test_render_main_no_violations(monkeypatch):
    # テキストあり、ボタン押下
    calls = stub_st_methods(monkeypatch, text_area_return="広告文", button_return=True)
    monkeypatch.setattr(ui, 'check_advertisement_with_categories_masking', lambda text, d: [])
    ui.render_main()
    # NGなしなので success が呼ばれる
    assert ('success', "✅ 問題のある表現は見つかりませんでした。") in calls
    # 警告ではなく成功メッセージ
    assert all(c[0] != 'warning' or "広告文を入力してください" not in c[1] for c in calls)

def test_render_main_with_violations(monkeypatch):
    # テキストあり、ボタン押下
    calls = stub_st_methods(monkeypatch, text_area_return="広告文", button_return=True)
    # １件の違反を返す stub
    fake_vio = {
        "表現": "NGワード",
        "開始位置": 0,
        "終了位置": 3,
        "カテゴリ": "test",
        "指摘事項": "問題です",
        "改善提案": ["提案1"],
        "適正表現例": ["例1"],
        "関連法令等": ["法令A"],
    }
    monkeypatch.setattr(ui, 'check_advertisement_with_categories_masking', lambda text, d: [fake_vio])
    # merge 系はそのまま返す
    monkeypatch.setattr(ui, 'merge_violations', lambda v: v)
    monkeypatch.setattr(ui, 'merge_same_ng_violations', lambda v: v)
    
    ui.render_main()

    # まず警告メッセージに「1件」と入っていること
    assert any(c[0]=='warning' and "1 件" in c[1] for c in calls)

    # highlight_prohibited_phrases の出力が write されていること
    assert ('write', ("<b>HIGHLIGHT</b>",), {'unsafe_allow_html': True}) in calls

    # 改善提案・適正表現例用のサブヘッダが呼ばれている
    assert ('subheader', "👩‍🏫 改善提案・適正表現例と関連情報") in calls

    # 個別の markdown で「提案1」や「例1」「法令A」が出ていること
    assert any(c[0]=='markdown' and "提案1" in c[1] for c in calls)
    assert any(c[0]=='markdown' and "例1" in c[1] for c in calls)
    assert any(c[0]=='markdown' and "法令A" in c[1] for c in calls)

# --- USE_USAGE_FILTER = False 時の render_sidebar ---
def test_render_sidebar_usage_filter_off(monkeypatch):
    # ■ 用途フィルターOFF時の動作検証
    # USE_USAGE_FILTER を False にセット
    monkeypatch.setattr(ui, 'USE_USAGE_FILTER', False)
    # Streamlit UI をモック
    monkeypatch.setattr(st, 'sidebar', st)
    monkeypatch.setattr(st, 'radio', lambda *args, **kwargs: '一般化粧品')
    # 製品選択用の selectbox は何でも返す
    monkeypatch.setattr(st, 'selectbox', lambda label, options, **kwargs: 'ダミー製品')
    monkeypatch.setattr(st, 'text_area', lambda *args, **kwargs: 'テキスト')
    monkeypatch.setattr(st, 'button', lambda *args, **kwargs: False)

    selected_category, selected_usage, selected_product = ui.render_sidebar()
    assert selected_category == '一般化粧品'
    assert selected_usage == ''  # フィルタOFFなので必ず空文字
    assert selected_product == 'ダミー製品'

# --- merge_violations の境界値テスト ---
def test_merge_violations_contains_and_boundary():
    violations = [
        {'開始位置': 0, '終了位置': 10},
        {'開始位置': 2, '終了位置': 8},    # 完全包含 → 除外される
        {'開始位置': 12, '終了位置': 14},  # 差 = tolerance(2) → 残る
    ]
    merged = ui.merge_violations(violations, tolerance=2)
    # 完全包含の2番目は除外されるが、境界の3番目は残るので長さは2
    assert len(merged) == 2
    starts = sorted(v['開始位置'] for v in merged)
    assert starts == [0, 12]

# --- merge_same_ng_violations の ingredient 優先テスト ---
def test_merge_same_ng_violations_ingredient_priority():
    violations = [
        {'ingredient': '成分A', '表現': 'A', '開始位置': 0, '終了位置': 1},
        {'表現': '成分A',       '開始位置': 2, '終了位置': 3},
        {'ingredient': '成分A', '表現': 'A', '開始位置': 4, '終了位置': 5},
    ]
    merged = ui.merge_same_ng_violations(violations)
     # normalize_text('成分A') をキーとして 3 件がまとめられ、count が3になる
    key = ui.normalize_text('成分A')
    result = {ui.normalize_text(v.get('ingredient') or v.get('表現')): v['count'] for v in merged}
    assert result[key] == 3

def test_get_ng_words_idempotent():
    """同じ引数で２回呼んでも、必ず同じ結果（キャッシュが効いている）になることを検証"""
    r1 = ui.get_ng_words('一般化粧品', 'スキンケア', '化粧水')
    r2 = ui.get_ng_words('一般化粧品', 'スキンケア', '化粧水')
    # まったく同じ辞書が返ってくること
    assert r1 == r2
    # 必須キーは揃っていること
    assert set(r1.keys()) == {'ng_dict', 'subcategories'}

def test_get_ng_words_medicated_branch(monkeypatch):
    # 医薬部外品（薬用化粧品）ブランチのテスト
    fake_data = {}
    monkeypatch.setattr(ui, 'load_json', lambda _: fake_data)
    monkeypatch.setattr(ui, 'extract_ng_data_by_subcategory', lambda data: {'共通': ['c1'], '薬用化粧品': ['c2']})
    monkeypatch.setattr(ui, 'extract_ng_data_from_subcategories', lambda subs, u, p, c: {'x': 1})

    result = ui.get_ng_words('医薬部外品（薬用化粧品）', 'ヘアケア', 'シャンプー')
    assert result['ng_dict'] == {'x': 1}
    assert result['subcategories'] == ['c1', 'c2']

# --- render_sidebar の「更新」ボタン押下フローテスト ---
def test_render_sidebar_update_flow(monkeypatch):
    st.session_state.clear()
    # ── モック準備 ──
    # ラジオ／セレクトボックス等の基本返値
    monkeypatch.setattr(st, 'sidebar', st)
    monkeypatch.setattr(st, 'radio', lambda *args, **kwargs: "一般化粧品")
    monkeypatch.setattr(st, 'selectbox', lambda *args, **kwargs: "スキンケア")
    monkeypatch.setattr(st, 'text_area', lambda *args, **kwargs: "テキスト")
    # 「更新」ボタン押下をシミュレート
    monkeypatch.setattr(st.sidebar, 'button', lambda label, **kwargs: True)
    # キャッシュクリア／rerun の呼ばれたことを記録するフラグ
    flags = {"cleared": False, "rerun": False}
    # st.cache_data を DummyCache に差し替え
    class DummyCache:
        @staticmethod
        def clear():
            flags["cleared"] = True
    monkeypatch.setattr(st, 'cache_data', DummyCache)
    # experimental_rerun は存在しない属性なので raising=False で用意
    monkeypatch.setattr(st, 'experimental_rerun',
                        lambda: (_ for _ in ()).throw(AttributeError()),
                        raising=False)
    # rerun も同様に置き換え
    monkeypatch.setattr(st, 'rerun',
                        lambda: flags.__setitem__("rerun", True),
                        raising=False)
    # ── １回目呼び出し：更新フローが動く ──
    ui.render_sidebar()
    assert flags["cleared"], "キャッシュクリアが呼ばれていない"
    assert flags["rerun"], "st.rerun() が呼ばれていない"
    assert st.session_state.just_updated is True
    assert "last_update" in st.session_state

    # ── ２回目呼び出し：フラッシュメッセージが出て just_updated がリセットされる ──
    msgs = []
    monkeypatch.setattr(st.sidebar, 'success', lambda msg: msgs.append(msg))
    # 更新ボタンは押さない
    monkeypatch.setattr(st.sidebar, 'button', lambda label, **kwargs: False)
    ui.render_sidebar()
    # 先ほどの last_update タイムスタンプを含むメッセージが出る
    assert any("データを更新しました！" in m for m in msgs)
    assert st.session_state.just_updated is False

# --- render_sidebar の用途リスト動的切り替えテスト ---
@pytest.mark.parametrize(
    "category, expected_len",
    [
        ("一般化粧品", 7),
        ("医薬部外品（薬用化粧品）", 4),
    ],
)
def test_render_sidebar_usage_options(monkeypatch, category, expected_len):
    st.session_state.clear()
    # ラジオでカテゴリを返す
    monkeypatch.setattr(st, 'sidebar', st)
    monkeypatch.setattr(st, 'radio', lambda *args, **kwargs: category)
    # 用途選択 (label に “用途選択” が含まれる) のときだけキャプチャ
    captured = {}
    def fake_selectbox(label, options, **kwargs):
        if "用途を選択" in label:
            captured['options'] = options
            return options[0]
        # 製品選択時はダミーで何か返す
        return options[0] if options else None
    monkeypatch.setattr(st, 'selectbox', fake_selectbox)
    # 他の st.sidebar ウィジェットはダミー
    monkeypatch.setattr(st, 'text_area', lambda *args, **kwargs: "テキスト")
    monkeypatch.setattr(st, 'button', lambda *args, **kwargs: False)

    # 実行
    ui.render_sidebar()
    assert 'options' in captured, "用途選択の options がキャプチャされていません"
    assert len(captured['options']) == expected_len, f"{category} の用途リスト長が期待と異なる"
