# data_processing.py
#######################
#  NGワード処理ロジックプロンプト
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
    """
    JSON ファイルを読み込んで Python の辞書オブジェクトとして返します。

    Args:
        file_path (str): 読み込む JSON ファイルのパス。

    Returns:
        Dict[str, Any]: パースされた JSON データ。

    Raises:
        FileNotFoundError: 指定したファイルが存在しない場合。
        json.JSONDecodeError: JSON のパースに失敗した場合。
        Exception: その他の I/O エラーが発生した場合。
    """
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
            プレースホルダが含まれない場合は `[text]` を返します。

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
            NGワード文字列。たとえば `"たった\\d+日で"` のように
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
GENERAL_SUBCATEGORIES: List[str] = ["一般化粧品"]
MEDICINAL_SUBCATEGORIES: List[str] = ["薬用化粧品"]

def extract_ng_data_by_subcategory(
    data: Dict[str, Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    JSON データからグローバルカテゴリ「化粧品等」に該当するサブカテゴリを抽出し、
    “共通”、“一般化粧品”、“薬用化粧品” の 3 つに分類して返します。

    Args:
        data (Dict[str, Any]):
            全体の JSON データ。少なくともキー "global_categories" を含む構造を前提とします。

    Returns:
        Dict[str, List[Dict[str, Any]]]:
            サブカテゴリ分類結果を格納した辞書。キーは以下の通りです。
            - "共通": 共通サブカテゴリのリスト
            - "一般化粧品": 一般化粧品サブカテゴリのリスト
            - "薬用化粧品": 薬用化粧品サブカテゴリのリスト

    Examples:
        >>> sample = {
        ...     "global_categories": [
        ...         {"name": "化粧品等", "subcategories": [
        ...             {"name": "共通A", "id": "1"},
        ...             {"name": "一般化粧品B", "id": "2"},
        ...             {"name": "薬用化粧品C", "id": "3"},
        ...         ]}
        ...     ]
        ... }
        >>> r = extract_ng_data_by_subcategory(sample)
        >>> [c["id"] for c in r["共通"]]
        ['1']
        >>> [c["id"] for c in r["一般化粧品"]]
        ['2']
        >>> [c["id"] for c in r["薬用化粧品"]]
        ['3']
    """
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
) -> Dict[str, NGWordDetail]:
    """
    サブカテゴリごとのデータから、NGワードと関連情報のマッピング辞書を作成します。

    Args:
        subcategory_data (Dict[str, List[Dict[str, Any]]]):
            extract_ng_data_by_subcategory で分類されたサブカテゴリの辞書。
            キーは "common", "general", "medicinal" などのグループ名、
            値は各サブカテゴリのリストです。
            各サブカテゴリには、"id", "name", "NGワードと禁止理由" といったキーを含む必要があります。

    Returns:
        Dict[str, NGWordDetail]:
            NGワードをキーに、詳細情報を値とするマッピング辞書。
            各値（Dict[str, Any]）には少なくとも以下のキーが含まれます:
            - "original": 元の NG ワード文字列
            - "pattern": コンパイル済み正規表現オブジェクト
            - "category": グローバルカテゴリ > サブカテゴリ名 の文字列
            - "指摘事項", "改善提案", "適正表現例", "関連法令等", "共通禁止事項", "注意点", "除外表現"

    Examples:
        >>> sample_subcats = {
        ...     "common": [
        ...         {
        ...             "name": "共通A",
        ...             "関連法令等": ["法令1"],
        ...             "共通禁止事項": [],
        ...             "注意点": [],
        ...             "NGワードと禁止理由": [
        ...                 {
        ...                     "理由": "禁止の理由",
        ...                     "改善提案": "改善案",
        ...                     "適正表現例": ["例1"],
        ...                     "除外表現": [],
        ...                     "対象ワード": ["ワードA"]
        ...                 }
        ...             ]
        ...         }
        ...     ]
        ... }
        >>> ng_map = extract_ng_data_from_subcategories(sample_subcats)
        >>> "ワードA" in ng_map
        True
        >>> ng_map["ワードA"]["category"]
        '化粧品等 > 共通A'
    """
    ng_words: Dict[str, NGWordDetail] = {}
    for group_name, subcategories in subcategory_data.items():
        for sub_cat in subcategories:
            sub_cat_name = sub_cat.get("name", "")
            # カテゴリ文字列に用途は含めずとも、用途区分を別フィールドで持たせる
            category_str = f"{GLOBAL_CATEGORY_NAME} > {sub_cat_name}"
            usage_list = sub_cat.get("用途区分", [])  # JSONの用途区分を取得
            common_guidelines = sub_cat.get("関連法令等", ["該当するガイドラインはありません。"])
            common_notes = sub_cat.get("共通禁止事項", [])
            common_attention = sub_cat.get("注意点", [])
            for item in sub_cat.get("NGワードと禁止理由", []):
                reason = item.get("理由", "指摘事項が設定されていません。")
                suggestion = item.get("改善提案", "適切な表現を検討してください。")
                appropriate_examples = item.get("適正表現例", [])
                exclusion_list = item.get("除外表現", [])
                for word in item.get("対象ワード", []):
                    expanded_words = expand_placeholders(word, PLACEHOLDER_VALUES)
                    for final_word in expanded_words:
                        # もし final_word が空文字なら登録しない
                        if not final_word:
                            continue
                        # 重複しないよう、オリジナルのみキーとする
                        if final_word not in ng_words:
                            # ここで一度だけ正規表現パターンを構築・コンパイルして保持
                            pattern = compile_ng_word(final_word)
                            ng_words[final_word] = {
                                "original": final_word,
                                "pattern": pattern,        # ← 追加
                                "category": category_str,
                                "指摘事項": reason,
                                "改善提案": suggestion,
                                "適正表現例": appropriate_examples,
                                "関連法令等": common_guidelines,
                                "共通禁止事項": common_notes,
                                "注意点": common_attention,
                                "除外表現": exclusion_list,
                                "用途区分": usage_list
                            }
    return ng_words

# NGワード抽出のキャッシュ化
def get_ng_word_data(file_path: str) -> Dict[str, NGWordDetail]:
    """
    指定した JSON ファイルを読み込み、「共通」サブカテゴリに含まれる NG ワード辞書を返します。

    Args:
        file_path (str):
            NG ワード定義が書かれた JSON ファイルのパス。

    Returns:
        Dict[str, NGWordDetail]:
            NG ワード文字列をキーに、詳細情報（正規表現パターン、指摘事項、改善提案など）を
            値とする辞書。

    Examples:
        >>> # JSON ファイルに共通サブカテゴリの NG ワード定義があるとする
        >>> ng_map = get_ng_word_data("checkword_phrases.json")
        >>> isinstance(ng_map, dict)
        True
        >>> # キーのひとつとして、定義に含まれるワードが存在する
        >>> "くすみ" in ng_map
        True
        >>> # 値の中にはコンパイル済み Pattern オブジェクトが含まれる
        >>> import re
        >>> hasattr(ng_map["くすみ"]["pattern"], "search")
        True
    """
    data = load_json(file_path)
    subcategory_data = extract_ng_data_by_subcategory(data)
    # ここでは「共通」キーのみを対象に NG ワードマッピングを構築
    return extract_ng_data_from_subcategories({"共通": subcategory_data["共通"]})

def mask_safe_expressions(
    ad_text: str, 
    ng_words: Dict[str, NGWordDetail],
) -> str:
    """
    広告テキスト中の「除外表現」を同じ長さのマスク文字「□」で置換します。

    Args:
        ad_text (str):
            マスク対象の広告文テキスト。
        ng_words (Dict[str, NGWordDetail]):
            extract_ng_data_from_subcategories で生成された NG ワード辞書。
            各値にキー "除外表現"（List[str]）を含む必要があります。

    Returns:
        str:
            除外表現が「□」でマスクされたテキスト。
            マスク文字は元表現と同じ文字数になります。

    Examples:
        >>> ng_dict = {
        ...     "特別オファー": {
        ...         "除外表現": ["特別オファー"],
        ...         "pattern": None,  # 無視
        ...     }
        ... }
        >>> text = "今なら特別オファーをお届け！"
        >>> mask_safe_expressions(text, ng_dict)
        '今なら□□□□□□をお届け！'
    """
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
    """
    マスク処理を適用した上で、NGワードを検出し、検出情報のリストを返します。

    Args:
        ad_text (str):
            ユーザーが入力した広告文テキスト。
        ng_words (Dict[str, NGWordDetail]):
            extract_ng_data_from_subcategories で生成された NG ワード辞書。
            キーは NG ワード文字列、値は詳細情報を含む辞書であり、
            各値に "pattern" (Pattern[str]) が含まれている必要があります。

    Returns:
        List[ViolationItem]:
            検出された各違反についての情報リスト。各要素は以下をキーに持つ辞書:
            - "カテゴリ" (str): NG ワードのカテゴリ名
            - "表現" (str): 元テキストから抽出した違反表現
            - "開始位置" (int): 元テキスト内での開始インデックス
            - "終了位置" (int): 元テキスト内での終了インデックス
            - "指摘事項" (str)
            - "改善提案" (str or List[str])
            - "適正表現例" (List[str])
            - "関連法令等" (List[str])
            - "共通禁止事項" (List[str])
            - "注意点" (List[str])

    Raises:
        IndexError:
            normalized_text と mapping の長さ不整合でマッピングに失敗した場合。

    Examples:
        >>> ng_dict = {
        ...     "くすみ": {"pattern": re.compile("くすみ", re.IGNORECASE), "category": "共通"}
        ... }
        >>> check_advertisement_with_categories_masking("肌のくすみを改善", ng_dict)
        [{
            "カテゴリ": "共通",
            "表現": "くすみ",
            "開始位置": 3,
            "終了位置": 5,
            "指摘事項": "...",
            "改善提案": "...",
            "適正表現例": [...],
            "関連法令等": [...],
            "共通禁止事項": [...],
            "注意点": [...]
        }]
    """
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
    """
    元の広告文テキストに対し、検出された違反表現箇所を HTML の <span> タグで強調表示します。

    Args:
        ad_text (str):
            ユーザーが入力した元の広告文テキスト。
        violations (List[ViolationItem]):
            check_advertisement_with_categories_masking などで取得した違反情報リスト。
            各要素にキー "開始位置" (int) と "終了位置" (int) が含まれている必要があります。

    Returns:
        str:
            <span style='background-color:#FFCCCC; color:red; font-weight:bold;'>…</span>
            でハイライトされた HTML 文字列。
            unsafe_allow_html=True で Streamlit に渡すことを想定しています。

    Examples:
        >>> text = "肌のくすみを改善"
        >>> violations = [{"開始位置": 3, "終了位置": 5}]
        >>> highlight_prohibited_phrases(text, violations)
        '肌の<span style=\'background-color:#FFCCCC; color:red; font-weight:bold;\'>くすみ</span>を改善'
    """
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
    """
    指定された特記成分（ingredient_placeholder）が広告文中に登場するたびに、
    その前後 window 文字以内に効果表現（effect_placeholder）が含まれているかをチェックします。
    除外表現（exclusion_placeholder）が対象成分を完全に覆っている場合は、その箇所をチェック対象外とします。

    Args:
        ad_text (str):
            広告文テキスト。
        ingredient_placeholder (str):
            特定成分のプレースホルダ文字列（例 "{SEIBUN}"）。
        effect_placeholder (str):
            効果表現のプレースホルダ文字列（例 "{MOKUTEKI}"）。
        exclusion_placeholder (Optional[str]):
            除外表現のプレースホルダ文字列（例 "{JYOGAI}"）。  
            None の場合、除外処理は行いません。
        window (int):
            成分出現箇所の前後で検索する文字数（デフォルト 80）。

    Returns:
        List[ViolationItem]:
            以下のキーを持つ辞書のリスト。空の場合はすべての成分に対して
            効果表現が見つかったことを意味します。
            - "ingredient" (str): マッチした元の成分文字列
            - "context" (str): 正規化後テキストから抽出した前後 window 範囲の文脈
            - "開始位置" (int): 元テキストにおける一致開始インデックス
            - "終了位置" (int): 元テキストにおける一致終了インデックス
            - "message" (str): 指摘メッセージ
            - "改善提案" (str)
            - "適正表現例" (List[str])
            - "関連法令等" (List[str])

    Examples:
        >>> # プレースホルダ展開の設定例
        >>> PLACEHOLDER_VALUES = {"SEIBUN": ["ヒアルロン酸"], "MOKUTEKI": ["保湿"]}
        >>> text = "ヒアルロン酸配合で肌にうるおいを与える"
        >>> check_ingredient_context(text, "{SEIBUN}", "{MOKUTEKI}")
        []
        >>> # 効果表現がない場合
        >>> text2 = "ヒアルロン酸配合"
        >>> check_ingredient_context(text2, "{SEIBUN}", "{MOKUTEKI}")
        [{
            "ingredient": "ヒアルロン酸",
            "context": "ひあ…",  # 正規化文脈一部
            "開始位置": 0,
            "終了位置": 6,
            "message": "...",
            "改善提案": "...",
            "適正表現例": [...],
            "関連法令等": [...]
        }]
    """
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

