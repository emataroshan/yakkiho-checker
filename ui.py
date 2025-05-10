# ui.py
##################################
#  UI（ユーザーインターフェース）処理プロンプト
##################################

import streamlit as st
import requests
import pandas as pd
from typing import Any, List, Dict
from data_processing import ViolationItem
import time 
import os

# ===== 用途区分フィルタの on/off =====
# Comment out the next line to disable usage-based filtering
USE_USAGE_FILTER = True  # True -> ON, False -> OFF
# ================================

# 以下、データ処理モジュールから主要な関数をインポート
from data_processing import (
    load_json,
    extract_ng_data_by_subcategory,
    extract_ng_data_from_subcategories,
    check_advertisement_with_categories_masking, 
    # check_ingredient_context_negative,  # 文脈チェック用（必要に応じて有効化）
    highlight_prohibited_phrases,
    normalize_text,
)
import pandas as pd

# ─────────────────────────────────────────────────
# ★ Googleフォーム連携設定
# ユーザーがチェックした広告文をバックグラウンドで記録する
AD_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSc_Y8CjcT5LP-K_nCXZmcFuP9qOm3AJkcWNilJlDjBHbHXmYA/formResponse"
AD_ENTRY_ID = "entry.981221194"

def submit_ad_text(ad_text: str):
    """
   広告文を Google フォームに送信し、利用状況を記録。
   失敗しても処理を中断しない（ログ不要と判断）。

    Args:
        ad_text (str): ユーザー入力の広告文
    """
    try:
        # フォームにPOSTリクエスト送信
        requests.post(
            AD_FORM_URL,
            data={AD_ENTRY_ID: ad_text},
            headers={"User-Agent": "Mozilla/5.0", "Referer": AD_FORM_URL}
        )
    except Exception:
        # ネットワークエラー等は無視
        pass
# ─────────────────────────────────────────────────

# ---------------------------
# 重複マージ用ユーティリティ
# UI モジュールで必要な場合にローカル定義
# ---------------------------
def merge_violations(
    violations: List[ViolationItem],
    tolerance: int = 2
) -> List[ViolationItem]:
    """
    検出された違反リストから、位置が重複または近接するものを統合。

    Args:
        violations (List[ViolationItem]): 元の違反リスト
        tolerance (int): 開始・終了位置の許容差
    Returns:
        List[ViolationItem]: 重複除去後の違反リスト
    """
    merged: List[ViolationItem] = []
    for v in violations:
        dup = False
        for m in merged:
            # 完全包含またはほぼ同一位置とみなしたら重複扱い
            if (v["開始位置"] >= m["開始位置"] and v["終了位置"] <= m["終了位置"]) or \
               (abs(v["開始位置"] - m["開始位置"]) < tolerance and abs(v["終了位置"] - m["終了位置"]) < tolerance):
                dup = True
                break
        if not dup:
            merged.append(v)
    return merged


def merge_same_ng_violations(
    violations: List[ViolationItem]
) -> List[ViolationItem]:
    """
    同じNGワードに対する複数の違反をまとめ、発生回数を 'count' フィールドに格納。

    Args:
        violations (List[ViolationItem]): 元の違反リスト
    Returns:
        List[ViolationItem]: 重複マージ後、各ワードごと1レコードに集約
    """
    merged: Dict[str, ViolationItem] = {}
    for v in violations:
        # ingredient フィールド優先、なければ 表現 フィールドをキーに
        raw_key = v.get("ingredient") or v.get("表現")
        key = normalize_text(raw_key) if raw_key else ""
        if key in merged:
            # 既存レコードにカウントを加算
            merged[key]["count"] = merged[key].get("count", 1) + 1
        else:
            # 新規登録時に初期カウントを1に設定
            v["count"] = 1
            merged[key] = v
    return list(merged.values())
# ---------------------------

@st.cache_data(show_spinner=False)
def get_ng_words(
    selected_category: str,
    selected_usage: str,
    selected_product: str
) -> Dict[str, Any]:
    
    option_map = {
        "一般化粧品": "一般化粧品",
        "医薬部外品（薬用化粧品）": "薬用化粧品"
    }
    # JSONファイルのロード
    data = load_json("NGword.json")
    # グローバルカテゴリ"化粧品等"からサブカテゴリを抽出
    subcats = extract_ng_data_by_subcategory(data)
       
    ng_dict = extract_ng_data_from_subcategories({
        "共通": subcats["共通"],
        option_map[selected_category]: subcats[option_map[selected_category]]
    }, selected_usage, selected_product)

    return {
        "ng_dict": ng_dict,
        "subcategories": subcats["共通"] + subcats[option_map[selected_category]]
    }


# ---------------------------
# サイドバー処理：大区分・用途区分・フィードバックなどを集約
# ---------------------------
def render_sidebar():
 
    """
    サイドバーに以下を表示・選択させる:
      1. 大区分（一般化粧品 / 医薬部外品）
      2. 用途区分（selectboxで1つ選択）
      3. フィードバック入力欄
      4. 注意事項

    Returns:
        selected_display (str): 選択された大区分
        selected_usage (str): 選択された用途区分
    """
# 更新ボタン押下後に表示するフラッシュメッセージ用フラグ
    if "just_updated" in st.session_state and st.session_state.just_updated:
        st.sidebar.success(f"データを更新しました！ ({st.session_state.last_update})")
        # フラグリセット
        st.session_state.just_updated = False

# ===== 開発用：手動更新ボタン =====
# ※開発中だけ有効化したい場合は、次のコメントを外してください
    if st.sidebar.button("🔄 更新"):
        # キャッシュをクリアして JSON などを再読み込みさせる
        try:
            st.cache_data.clear()
        except AttributeError:
            pass
        # 更新完了時刻を記録
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.last_update = now
        st.session_state.just_updated = True
        # UI再実行
        try:
            st.experimental_rerun()
        except AttributeError:
            st.rerun()
# =================================

    # 1) 大区分選択ラジオ
    st.sidebar.title("💊 カテゴリを選択")
    selected_category = st.sidebar.radio(
        "💊 カテゴリを選択",
        options=["一般化粧品", "医薬部外品（薬用化粧品）"],
        index=0,
    )   
    # 2) 用途区分の候補を固定順序で用意
    if USE_USAGE_FILTER:
        # 用途の候補はカテゴリ別に変わる
        all_usages = (
            ["スキンケア","ヘアケア","メイクアップ","ボディケア","フレグランス","ネイルケア","オーラルケア"]
            if selected_category == "一般化粧品"
            else ["スキンケア","ヘアケア","ボディケア","オーラルケア"]
        )
        selected_usage = st.sidebar.selectbox("🎯 用途を選択", all_usages)
    else:
        # フィルタOFF時は空文字を返す
        selected_usage = ""

    # ③ JSON からサブカテゴリを取得して絞り込み
    data    = load_json("NGword.json")
    subcats = extract_ng_data_by_subcategory(data)
    option_map = {"一般化粧品": "一般化粧品", "医薬部外品（薬用化粧品）": "薬用化粧品"}
    raw_list = subcats["共通"] + subcats[option_map[selected_category]]

#    # ★ デバッグ: フィルタ後のサブカテゴリ名を確認
#    st.sidebar.write("🎯 フィルタ後サブカテゴリ:", [sub.get("name") for sub in filtered])

    # ④ フィルタ後の JSON 定義から製品名一覧を収集
    product_set = set()
    for sub in raw_list:
#        # ★ デバッグ: 各サブカテゴリの中身を確認
#        st.sidebar.write(f"— サブカテゴリ {sub.get('name')}")

        for group in sub.get("NGワードと禁止理由", []):
            # 用途フィルタONなら、ここで弾く
            if USE_USAGE_FILTER and selected_usage not in group.get("用途区分", []):
                continue
            for p in group.get("製品名", []):
                product_set.add(p)
    product_list = sorted(product_set)

#    st.sidebar.write("🔍 JSONを読み込んでいるパス:", os.path.abspath("NGword.json"))
#    st.sidebar.write("🔍 製品候補:", product_list)

    # 製品選択ドロップダウン
    selected_product = st.sidebar.selectbox("🧴 製品を選択", product_list)

    # 区切り線
    st.sidebar.markdown("---")
    # 3) フィードバック入力欄
    st.sidebar.title("💬 フィードバック")
    if "feedback_area" not in st.session_state:
        st.session_state.feedback_area = ""
    if "feedback_message" not in st.session_state:
        st.session_state.feedback_message = ""
    st.sidebar.text_area("ご意見・ご要望をお聞かせください", key="feedback_area", height=100)
    st.sidebar.button("送信", on_click=submit_feedback)
    if st.session_state.feedback_message:
        st.sidebar.success(st.session_state.feedback_message)
    st.sidebar.markdown("---")
    # 4) 注意事項
    st.sidebar.title("ℹ️ 注意事項")
    st.sidebar.markdown("このツールは参考情報です。最終判断は専門家にご相談ください。")
    return selected_category, selected_usage, selected_product
# ---------------------------
# フィードバック送信処理（UI側ローカル定義）
# ---------------------------
def submit_feedback():
    """
    サイドバーのフィードバック入力内容を Google フォームに送信。
    空入力時や失敗時は st.session_state.feedback_message で通知。
    """
    if st.session_state.feedback_area.strip():
        FEEDBACK_FORM_URL = "https://docs.google.com/forms/..."
        FEEDBACK_ENTRY_ID = "entry.745635231"
        try:
            resp = requests.post(FEEDBACK_FORM_URL, data={FEEDBACK_ENTRY_ID: st.session_state.feedback_area})
            if resp.status_code in (200,302):
                st.session_state.feedback_message = "フィードバックありがとうございました！"
                st.session_state.feedback_area = ""
            else:
                st.session_state.feedback_message = "送信に失敗しました。"
        except:
            st.session_state.feedback_message = "送信中にエラーが発生しました。"
    else:
        st.session_state.feedback_message = "入力してから送信してください。"

# ---------------------------
# メイン画面の処理
# ---------------------------
def render_main():
    """
    メイン画面を描画し、ユーザー入力→NGチェック→結果表示を制御。
    """
    st.title("💊 薬機法表現チェックアプリ")

    # サイドバーからカテゴリ・用途・製品名を取得
    selected_category, selected_usage, selected_product = render_sidebar()

    data = load_json("NGword.json")# 🔧 get_ng_words によるフィルタ付き NGワード取得
    ng_data = get_ng_words(selected_category, selected_usage, selected_product)
    ng_dict = ng_data["ng_dict"]




# 📊 デバッグ出力：選択情報と NG ワード数
    st.markdown("### 🧪 デバッグ情報")
    st.write(f"📌 選択カテゴリ: {selected_category}")
    st.write(f"📌 選択用途区分: {selected_usage}")
    st.write(f"📌 選択製品名: {selected_product}")
    st.write(f"📌 登録NGワード数: {len(ng_dict)}")

    # 展開済みNGワードを確認
    st.markdown("### 🧪 展開済みNGワード一覧（最大5件）")
    for word, detail in list(ng_dict.items())[:5]:
        st.write(f"🔹 {word} → カテゴリ: {detail['category']}")




    # 広告文入力エリア
    ad_text = st.text_area("カテゴリ選択後、広告文を入力してください", height=200).strip()
    if st.button("チェック開始"):
        if not ad_text:
            st.warning("広告文を入力してください。")
            return

        # フォームに記録
        submit_ad_text(ad_text)

        # NGチェック実行
        violations = check_advertisement_with_categories_masking(ad_text, ng_dict) or []



        # NG検出結果表示（デバッグ用）
        st.markdown("### 🔍 検出された NG ワード（デバッグ）")
        if violations:
            for v in violations:
                st.write(f"✅ '{v['表現']}'（位置: {v['開始位置']}〜{v['終了位置']}） - カテゴリ: {v['カテゴリ']}")
        else:
            st.write("（検出なし）")
        
        # 重複統合＆同語統合
        all_violations = merge_violations(violations)
        all_violations = merge_same_ng_violations(all_violations)
        all_violations.sort(key=lambda x: x["開始位置"])


        # 結果の視覚表示
        if all_violations:
            st.warning(f"⚠️ 気になる表現が {len(all_violations)} 件見つかりました！")
            st.write(highlight_prohibited_phrases(ad_text, all_violations), unsafe_allow_html=True)
            st.subheader("👩‍🏫 改善提案・適正表現例と関連情報")
            for v in all_violations:
                label = v.get("ingredient") or v.get("表現")
                st.markdown(f"**<span style='color:red'>{label}</span>**", unsafe_allow_html=True)
                st.write(v.get("指摘事項") or v.get("message"))
                impr = v.get("改善提案") or []
                if isinstance(impr, str): impr = [impr]
                if impr:
                    st.markdown(f"<span style='color:#FF8C00;font-weight:bold'>💡 改善提案:</span> {'、'.join(impr)}", unsafe_allow_html=True)
                ex = v.get("適正表現例") or []
                if ex:
                    st.markdown(f"<span style='color:#FF8C00;font-weight:bold'>🔧 適正表現例:</span> {'、'.join(ex)}", unsafe_allow_html=True)
                laws = v.get("関連法令等") or []
                if laws:
                    st.markdown(f"<span style='color:#FF8C00;font-weight:bold'>📄 関連法令等:</span> {'、'.join(laws)}", unsafe_allow_html=True)
                st.markdown("---")
        else:
            st.success("✅ 問題のある表現は見つかりませんでした。")

# エントリポイント
if __name__ == '__main__':
    render_main()