# data_processing.py
#######################
#  NGワード処理ロジックスクリプト
#######################

import json
import re
import logging
import functools
import unicodedata
from typing import (
    Any, 
    Dict, 
    List, 
    Tuple, 
    Optional,
    Pattern,
    Set,
    Union,
    TypedDict, 
)


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # DEBUGレベルでログ出力（開発時）
# コンソール用
console_handler = logging.StreamHandler()
# ファイル用
file_handler = logging.FileHandler("debug.log", encoding="utf-8")

formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# --- TypedDict 定義 ---
class NGWordDetail(TypedDict):
    original: str
    pattern: Pattern[str]
    category: str
    指摘事項: str
    改善提案: Union[str, List[str]]
    適正表現例: List[str]
    関連法令等: List[str]
    共通禁止事項: List[str]
    注意点: List[str]
    除外表現: List[str]
    用途区分: List[str]

class ViolationItem(TypedDict, total=False):
    カテゴリ: str
    表現: str
    開始位置: int
    終了位置: int
    指摘事項: str
    改善提案: Union[str, List[str]]
    適正表現例: List[str]
    関連法令等: List[str]
    共通禁止事項: List[str]
    注意点: List[str]
    # 文脈チェック用の optional フィールド
    ingredient: str
    context: str
    message: str

from config import PLACEHOLDER_VALUES

# ───────────────────────────────────────────────────────────────────────
# ★ 共通：全角→半角変換テーブル 
FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
FW_UPPER  = str.maketrans("ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
FW_LOWER  = str.maketrans("ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ", "abcdefghijklmnopqrstuvwxyz")
# 全角記号＋全角スペースマッピング
FW_PUNCT  = str.maketrans({
    "．": ".",
    "，": ",",
    "％": "%",
    "　": " ",
    # 必要なら他の記号も追加
})

def _basic_normalize_char(ch: str) -> str:
    """
    1文字に対して NFC正規化 → 全角→半角（数字・英字・記号）→小文字化 を実施。
    """
    # 1) NFC 正規化
    ch = unicodedata.normalize("NFC", ch)
    # 2) 全角→半角（数字・英字・記号・全角スペース）
    ch = ch.translate(FW_DIGITS).translate(FW_UPPER).translate(FW_LOWER).translate(FW_PUNCT)
    # 3) ASCIIなら小文字化
    if ch.isascii():
        ch = ch.lower()
    return ch
# ───────────────────────────────────────────────────────────────────────

# ロガーの初期設定（必要に応じて出力先やレベルを調整）
logging.basicConfig(level=logging.INFO)

# ───────────────────────────────────────────────────────────────────────
# JSON読み込み
def load_json(file_path: str) -> Dict[str, Any]:
    
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as e:
        raise
    except Exception as e:
        raise Exception(f"JSON ファイルの読み込みに失敗しました: {e}")

# プレースホルダー展開
def expand_placeholders(
    text: str, 
    placeholders: Dict[str, List[str]],
) -> List[str]:
    """
    文字列内のプレースホルダを指定された値リストで展開し、すべての組み合わせを返します。

    Args:
        text (str): プレースホルダ（例: "{KEY}"）を含む元の文字列。
        placeholders (Dict[str, List[str]]): 
            キーをプレースホルダ名、値をその置換候補文字列リストとする辞書。

    Returns:
        List[str]: プレースホルダを置換した結果の文字列リスト。  
            プレースホルダが含まれない場合は [text] を返します。

    Examples:
        >>> expand_placeholders("肌{TUKARE}に", {"TUKARE": ["の疲れ", "に出た疲れ"]})
        ["肌の疲れに", "肌に出た疲れに"]
        >>> expand_placeholders("そのままの文", {"X": ["A", "B"]})
        ["そのままの文"]
    """
    results: List[str] = [text]
    for ph, values in placeholders.items():
        token = f"{{{ph}}}"
        new_results: List[str] = []
        for item in results:
            if token in item:
                for value in values:
                    new_results.append(item.replace(token, value))
            else:
                new_results.append(item)
        results = new_results
    return results

# --- 文字正規化・変換系 ---
def normalize_text(text: str) -> str:
    """
    広告文を正規化します。

    Args:
        text (str): 元の広告文。

    Returns:
        str: 以下の処理を行った正規化済テキスト。
            - Unicode NFC 正規化
            - 全角数字・英字・記号・スペースを半角化
            - ASCII文字を小文字化
            - 連続スペースを単一スペースにまとめる

    Examples:
        >>> normalize_text("Hello　　WORLD  TEST")
        "hello world test"
    """
    normalized = ''.join(_basic_normalize_char(ch) for ch in text)
    # 連続した ASCII スペースを単一スペースにまとめる
    normalized = re.sub(r'(?<=\S) +(?=\S)', ' ', normalized)
    return normalized

# --- 内部マッチング用正規化＆マッピング作成 ---
def normalize_text_for_matching(
    text: str,
) -> Tuple[str, List[int]]:
    """
    マッチング用にテキストを正規化し、元テキスト上の位置対応を返します。

    正規化の処理内容:
      1. Unicode NFC 正規化
      2. 全角数字・英字・記号・スペースを半角化
      3. カタカナをひらがなに変換
      4. 空白文字をすべて除去

    Args:
        text (str): 元の入力テキスト（広告文など）。

    Returns:
        Tuple[str, List[int]]:
            - normalized_text (str):
                正規化＆空白除去済みのテキスト。  
            - mapping (List[int]):
                normalized_text[i] が元テキストのどのインデックスに対応するかを示すリスト。
                長さは len(normalized_text) と一致します。

    Examples:
        >>> normalize_text_for_matching("たった１日 で") 
        ("たった1日で", [0, 1, 2, 3, 4, 6])
        >>> normalize_text_for_matching("ＡＢ Ｃ")
        ("ab c", [0, 1, 3])
    """
    normalized_chars: List[str] = []
    mapping: List[int] = []
    for orig_idx, ch in enumerate(text):
        ch_norm = _basic_normalize_char(ch)
        # カタカナ→ひらがな
        if 'ァ' <= ch_norm <= 'ン':
            ch_norm = chr(ord(ch_norm) - 0x60)
        # 空白は除去
        if ch_norm.isspace():
            continue
        # 文字と対応元インデックスを追加
        normalized_chars.append(ch_norm)
        mapping.append(orig_idx)

    normalized_text = ''.join(normalized_chars)
    return normalized_text, mapping

def convert_to_hiragana_preserving_katakana(text: str) -> str:
    """
    文字列中のカタカナをすべてひらがなに変換し、既存のひらがなはそのまま保持します。

    Args:
        text (str): 入力文字列。

    Returns:
        str: ひらがながカタカナに変換され、元のカタカナは変更されない文字列。

    Examples:
        >>> convert_to_hiragana_preserving_katakana("あいうアイウ")
        "アイウアイウ"
    """
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in text
    )

def convert_to_katakana(text: str) -> str:
    """
    入力文字列中のひらがなをすべてカタカナに変換します。

    Args:
        text (str): ひらがなを含む入力文字列。

    Returns:
        str: ひらがながカタカナに変換された文字列。元のカタカナやその他の文字はそのまま保持します。

    Examples:
        >>> convert_to_katakana("あいうえおアイウ")
        "アイウエオアイウ"
    """
    # ひらがな(U+3041–U+3096)を対応するカタカナ(U+30A1–U+30F6)に変換
    return text.translate(str.maketrans("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞ\
ただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽ\
まみむめもやゃゆゅよょらりるれろわゐゑをんゔゕゖ",
                                         "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾ\
タダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポ\
マミムメモヤャユュヨョラリルレロワヰヱヲンヴヵヶ"))

@functools.lru_cache(maxsize=128)
def compile_ng_word(phrase: str) -> Pattern[str]:
    """
    指定されたNGワードを正規化し、正規表現パターンにコンパイルして返します。
    同じフレーズはキャッシュされるため、2回目以降は高速に返却されます。

    Args:
        phrase (str):
            NGワード文字列。たとえば "たった\\d+日で" のように
            正規表現のメタ文字を含んでもOKです。

    Returns:
        Pattern[str]:
            大文字小文字を区別しない (re.IGNORECASE) フラグ付きの
            コンパイル済み正規表現オブジェクト。

    Examples:
        >>> pattern = compile_ng_word("たった\\d+日で")
        >>> bool(pattern.search("たった100日で"))
        True
    """
    # NGワードを内部マッチング用に正規化する
    phrase_normalized, _ = normalize_text_for_matching(phrase)
    
    # 数字部分やひらがなをパターン化
    pattern_str = re.sub(r'\\d\+', r"[0-9０-９]+", phrase_normalized)
    pattern_str = re.sub(
        r'[ぁ-ん]',
        lambda m: f"[{m.group(0)}{chr(ord(m.group(0)) + 0x60)}]",
        pattern_str
    )
    pattern_str = re.sub(r'\s+', r'\\s*', pattern_str)

    try:
        return re.compile(pattern_str, re.IGNORECASE)
    except re.error as e:
        # エラーログを残してフォールバック
        logging.warning(
            "Regex compilation failed for pattern '%s': %s. Falling back to escaped phrase.",
            pattern_str, e
        )
        # フォールバック：特殊文字をエスケープして再コンパイル
        return re.compile(re.escape(phrase_normalized), re.IGNORECASE)

# --- サブカテゴリ分け用定数 ---
GLOBAL_CATEGORY_NAME: str = "化粧品等"
COMMON_SUBCATEGORIES: List[str] = ["共通"]
GENERAL_SUBCATEGORIES: List[str] = ["一般"]
MEDICINAL_SUBCATEGORIES: List[str] = ["薬用"]

def extract_ng_data_by_subcategory(
    data: Dict[str, Any]
) -> Dict[str, List[Dict[str, Any]]]:
    
    common_data: List[Dict[str, Any]] = []
    general_data: List[Dict[str, Any]] = []
    medicinal_data: List[Dict[str, Any]] = []
    
    for global_cat in data.get("global_categories", []):
        if global_cat.get("name") == GLOBAL_CATEGORY_NAME:
            for sub_cat in global_cat.get("subcategories", []):
                sub_cat_name = sub_cat.get("name", "")
                if any(keyword in sub_cat_name for keyword in COMMON_SUBCATEGORIES):
                    common_data.append(sub_cat)
                elif any(keyword in sub_cat_name for keyword in GENERAL_SUBCATEGORIES):
                    general_data.append(sub_cat)
                elif any(keyword in sub_cat_name for keyword in MEDICINAL_SUBCATEGORIES):
                    medicinal_data.append(sub_cat)
                else:
                    common_data.append(sub_cat)
                    
    return {
        "共通": common_data,
        "一般化粧品": general_data,
        "薬用化粧品": medicinal_data
    }

def extract_ng_data_from_subcategories(
    subcategory_data: Dict[str, List[Dict[str, Any]]],
    selected_usage: Optional[str] = None,
    selected_product: Optional[str] = None,
    # JSONの「一般」か「薬用」を選択
    category_type: str = "一般",
) -> Dict[str, NGWordDetail]:
    
    # デバッグ出力
    logger.debug(f"selected_usage={selected_usage}, selected_product={selected_product}")

    ng_words: Dict[str, NGWordDetail] = {}
    for group_name, subcategories in subcategory_data.items():
        for sub_cat in subcategories:
            sub_cat_name = sub_cat.get("name", "")
            category_str = f"{GLOBAL_CATEGORY_NAME} > {sub_cat_name}"
            usage_list = sub_cat.get("用途区分", [])  # サブカテゴリ自体の用途（使わないことが多い）
            common_guidelines = sub_cat.get("関連法令等", [])
            common_notes = sub_cat.get("共通禁止事項", [])
            common_attention = sub_cat.get("注意点", [])

            for item in sub_cat.get("NGワードと禁止理由", []):
                # ✅ 用途区分フィルタ
                item_usages = item.get("用途区分", [])
                if selected_usage and item_usages and selected_usage not in item_usages:
                    continue
                # ✅ 製品名フィルタ
                prod_list = item.get("製品名", [])
                if not prod_list or selected_product not in prod_list:
                    continue

                # 「理由」を抽出し、薬用が空なら一般をフォールバック
                raw_reason = item.get("理由", "")
                if isinstance(raw_reason, dict):
                    reason = raw_reason.get(category_type, "").strip()
                    if category_type == "薬用" and not reason:
                        reason = raw_reason.get("一般", "").strip()
                else:
                    reason = raw_reason

                # 「改善提案」を抽出し、薬用が空なら一般をフォールバック
                raw_suggestion = item.get("改善提案", "")
                if isinstance(raw_suggestion, dict):
                    suggestion = raw_suggestion.get(category_type, "").strip()
                    if category_type == "薬用" and not suggestion:
                        suggestion = raw_suggestion.get("一般", "").strip()
                else:
                    suggestion = raw_suggestion

                # 「適正表現例」を抽出し、薬用が空リストなら一般をフォールバック
                raw_examples = item.get("適正表現例", [])
                if isinstance(raw_examples, dict):
                    appropriate_examples = raw_examples.get(category_type, []) or []
                    if category_type == "薬用" and not appropriate_examples:
                        appropriate_examples = raw_examples.get("一般", []) or []
                else:
                    appropriate_examples = raw_examples or []

                exclusion_list = item.get("除外表現", [])

                for word in item.get("対象ワード", []):
                    for final_word in expand_placeholders(word, PLACEHOLDER_VALUES):
                        ng_key = f"{final_word}::{category_str}"
                        if not final_word or ng_key in ng_words:
                            continue
                        pattern = compile_ng_word(final_word)
                        ng_words[ng_key] = {
                            "original": final_word,
                            "pattern": pattern,
                            "category": category_str,
                            "指摘事項": reason,
                            "改善提案": suggestion,
                            "適正表現例": appropriate_examples,
                            "関連法令等": common_guidelines,
                            "共通禁止事項": common_notes,
                            "注意点": common_attention,
                            "除外表現": exclusion_list,
                            "用途区分": item_usages,
                        }

    return ng_words

# NGワード抽出のキャッシュ化
def get_ng_word_data(file_path: str) -> Dict[str, NGWordDetail]:
    
    data = load_json(file_path)
    subcategory_data = extract_ng_data_by_subcategory(data)
    # ここでは「共通」キーのみを対象に NG ワードマッピングを構築
    return extract_ng_data_from_subcategories({"共通": subcategory_data["共通"]})

def mask_safe_expressions(
    ad_text: str, 
    ng_words: Dict[str, NGWordDetail],
) -> str:
    
    masked_text: str = ad_text
    processed_exclusions: Set[str] = set()
    for details in ng_words.values():
        # 除外表現リストを取得
        exclusion_list: List[str] = details.get("除外表現", [])
        # 各除外表現に対して、プレースホルダー展開を行う
        for safe_expr in exclusion_list:
            expanded_safe_exprs = expand_placeholders(safe_expr, PLACEHOLDER_VALUES)
            for expr in expanded_safe_exprs:
                # 同じ表現を複数回処理しないようにチェック
                if expr in processed_exclusions:
                    continue
                processed_exclusions.add(expr)
                # 除外表現を正規表現としてコンパイルする（re.escapeを使わない）
                try:
                    pattern = re.compile(expr, re.IGNORECASE)
                except re.error:
                    # もしコンパイルエラーが発生したら、リテラルとして扱う
                    pattern = re.compile(re.escape(expr), re.IGNORECASE)
                # マッチした部分の文字数に合わせて「□」を生成する
                masked_text = pattern.sub(lambda m: "□" * len(m.group()), masked_text)
    return masked_text


def check_advertisement_with_categories_masking(
    ad_text: str, 
    ng_words: Dict[str, NGWordDetail],
) -> List[ViolationItem]:
    
    # 1) 正規化＆マッピング
    normalized_text, mapping = normalize_text_for_matching(ad_text)

    #st.write("正規化後のテキスト:", ad_text_normalized)  # デバッグ出力

    # 2) 除外表現をマスク
    masked_text = mask_safe_expressions(normalized_text, ng_words)

    #st.write("マスク済みのテキスト:", masked_text)  # ここを追加して確認

    detected_violations: List[ViolationItem] = []
    matched_positions: Set[Tuple[int, int]] = set()

    # 3) 長いワードから順にNGワードパターンを検索
    sorted_ng_words = sorted(ng_words.items(), key=lambda x: -len(x[0]))
    for _, details in sorted_ng_words:
        # pattern がなければ original からコンパイルしてフォールバック
        if "pattern" in details and isinstance(details["pattern"], re.Pattern):
            phrase_pattern = details["pattern"]
        else:
            phrase_pattern = compile_ng_word(details["original"])  
        for match in phrase_pattern.finditer(masked_text):
            start, end = match.start(), match.end()
            # 重複或いは重なりを避ける
            if any(start < e and end > s for s, e in matched_positions):
                continue
            matched_positions.add((start, end))

            # 4) マッピングで元テキスト上の位置に変換
            orig_start = mapping[start]
            orig_end   = mapping[end - 1] + 1

            detected_violations.append({
                "カテゴリ": details["category"],
                "表現": ad_text[orig_start:orig_end],
                "開始位置": orig_start,
                "終了位置": orig_end,
                "指摘事項": details.get("指摘事項", ""),
                "改善提案": details.get("改善提案", ""),
                "適正表現例": details.get("適正表現例", []),
                "関連法令等": details.get("関連法令等", []),
                "共通禁止事項": details.get("共通禁止事項", []),
                "注意点": details.get("注意点", []),
            })
            
    detected_violations.sort(key=lambda x: x["開始位置"])
    return detected_violations

def highlight_prohibited_phrases(
    ad_text: str, 
    violations: List[ViolationItem],
) -> str:
    
    highlighted_text: str = ""
    last_end: int = 0
    for violation in sorted(violations, key=lambda x: x['開始位置']):
        start, end = violation['開始位置'], violation['終了位置']
        highlighted_text += ad_text[last_end:start]
        highlighted_text += (
            f"<span style='background-color:#FFCCCC; color:red; font-weight:bold;'>"
            f"{ad_text[start:end]}</span>"
        )
        last_end = end
    highlighted_text += ad_text[last_end:]
    return highlighted_text

# チェック対象成分の文脈を検証する関数（特定成分の配合目的の記載確認用）
def check_ingredient_context(
    ad_text: str,
    ingredient_placeholder: str,
    effect_placeholder: str,
    exclusion_placeholder: Optional[str] = None,
    window: int = 80
) -> List[ViolationItem]:
    
    # プレースホルダーの対象成分と効果表現のバリエーションを取得
    ingredient_variants = expand_placeholders(ingredient_placeholder, PLACEHOLDER_VALUES)
    effect_variants = expand_placeholders(effect_placeholder, PLACEHOLDER_VALUES)
    
    # 正規化バージョンを準備
    normalized_ingredient_variants = [normalize_text_for_matching(ing)[0] for ing in ingredient_variants]
    normalized_effect_variants = [normalize_text_for_matching(eff)[0] for eff in effect_variants]
    
    # 除外表現が指定されている場合は展開
    exclusion_variants: List[str] = []
    if exclusion_placeholder is not None:
        exclusion_variants = expand_placeholders(exclusion_placeholder, PLACEHOLDER_VALUES)
    
    violations_list: List[ViolationItem] = []
    normalized_text, mapping = normalize_text_for_matching(ad_text)
    
    # 元の成分と正規化した成分のペアでループ
    for orig_ing, norm_ing in zip(ingredient_variants, normalized_ingredient_variants):
        for match in re.finditer(re.escape(norm_ing), normalized_text, re.IGNORECASE):
            start, end = match.start(), match.end()
            window_start = max(0, start - window)
            window_end = min(len(normalized_text), end + window)
            context = normalized_text[window_start:window_end]
            
            # 除外判定：対象成分の一致が、入力文中のいずれかの除外表現に完全に含まれているか
            excluded = False
            for excl in exclusion_variants:
                for m_excl in re.finditer(re.escape(excl), normalized_text, re.IGNORECASE):
                    if m_excl.start() <= start and m_excl.end() >= end:
                        excluded = True
                        break
                    if excluded:
                        break
            if excluded:
                continue  # 除外対象なのでチェックしない
            
            # 効果表現のチェック（こちらも正規化済みのものを使用）
            if not any(re.search(re.escape(norm_eff), context, re.IGNORECASE) for norm_eff in normalized_effect_variants):
                orig_start = mapping[start]
                orig_end = mapping[end - 1] + 1
                violations_list.append({
                    "ingredient": orig_ing,
                    "context": context,
                    "開始位置": orig_start,
                    "終了位置": orig_end,
                    "message": f"'{orig_ing}' を特記成分として表記している場合は配合目的を記載してください。",
                    "改善提案": "配合目的を明確に記載する。",
                    "適正表現例": ["肌にうるおいを与え、乾燥を防ぐ。（ヒアルロン酸配合）"],
                    "関連法令等": ["適正広告ガイドライン F5"]
                })
    return violations_list