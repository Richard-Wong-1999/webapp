"""關鍵字提取服務"""

import os
import json
import threading
from datetime import datetime, timedelta
from typing import List, Dict
from config import Config
from utils.logger import logger
from utils.cache_manager import cache_manager
from services.deepseek_client import call_deepseek
from services.llm_client import call_llm
from prompts.keyword_prompt import build_keyword_prompt


def clear_article_cache(source: str = None):
    """清除文章快取

    Args:
        source: 資料來源，若為 None 則清除所有來源的快取
    """
    if source:
        source = normalize_source(source)
        # 清除該來源的所有天數快取
        for days in [7, 30, 60]:
            cache_key = f"articles_{source}_{days}"
            cache_manager.clear(cache_key)
        logger.info(f"🗑️ 已清除 {source} 的文章快取")
    else:
        # 清除所有來源的快取
        for src in ["swd", "ha"]:
            for days in [7, 30, 60]:
                cache_key = f"articles_{src}_{days}"
                cache_manager.clear(cache_key)
        logger.info("🗑️ 已清除所有文章快取")


# 關鍵字快取結構（帶 TTL）
keywords_cache = {
    "swd": {"keywords": [], "updated_at": 0, "expires_at": 0, "error": ""},
    "ha": {"keywords": [], "updated_at": 0, "expires_at": 0, "error": ""},
}
keywords_cache_lock = threading.Lock()

# 關鍵字-來源映射（記錄每個關鍵字來自哪些文章）
keyword_source_mapping = {
    "swd": {"mapping": {}, "updated_at": 0, "expires_at": 0},
    "ha": {"mapping": {}, "updated_at": 0, "expires_at": 0},
}
keyword_source_mapping_lock = threading.Lock()


def normalize_source(source: str) -> str:
    """標準化資料來源名稱"""
    s = (source or "swd").strip().lower()
    return "ha" if s == "ha" else "swd"


def get_source_dir(source: str) -> str:
    """取得資料來源目錄"""
    s = normalize_source(source)
    return Config.HA_DIR if s == "ha" else Config.SWD_DIR


def get_cached_keywords(source: str) -> List[str]:
    """取得快取的關鍵字（檢查 TTL）

    Args:
        source: 資料來源

    Returns:
        關鍵字列表，若過期或不存在則返回 None
    """
    source = normalize_source(source)
    with keywords_cache_lock:
        cached = keywords_cache.get(source, {})
        if cached.get("expires_at", 0) > datetime.now().timestamp():
            keywords = cached.get("keywords", [])
            logger.info(f"✅ [KeywordExtractor] 快取命中：{source}（{len(keywords)} 個關鍵字）")
            return keywords
        logger.info(f"ℹ️ [KeywordExtractor] 快取未命中或已過期：{source}")
        return None


def store_keywords(source: str, keywords: List[str], error: str = ""):
    """儲存關鍵字到快取（帶 TTL）

    Args:
        source: 資料來源
        keywords: 關鍵字列表
        error: 錯誤訊息（可選）
    """
    source = normalize_source(source)
    now = datetime.now()

    with keywords_cache_lock:
        keywords_cache[source] = {
            "keywords": keywords,
            "updated_at": now.timestamp(),
            "expires_at": now.timestamp() + Config.KEYWORD_CACHE_TTL,
            "error": error
        }

    logger.info(f"✅ 已儲存 {source} 關鍵字快取（{len(keywords)} 個，TTL={Config.KEYWORD_CACHE_TTL}秒）")


def extract_keywords_from_deepseek(summaries: List[str]) -> List[str]:
    """使用 DeepSeek 提取關鍵字

    Args:
        summaries: 文章摘要列表

    Returns:
        關鍵字列表
    """
    if not summaries:
        logger.info("⚠️ 沒有文章摘要，返回空關鍵字列表")
        return []

    joined_text = "\n\n".join(summaries[:10])
    prompt = build_keyword_prompt(joined_text)

    # 使用 DeepSeek 進行關鍵字提取
    output, metadata = call_llm(prompt, provider="deepseek", model="deepseek-chat")
    logger.info(f"🤖 關鍵字提取使用模型: {metadata.get('provider')}/{metadata.get('model')}")

    if not output:
        logger.warning("⚠️ DeepSeek 無回應或 API 失敗，返回空關鍵字列表")
        return []

    keywords = [kw.strip() for kw in output.replace("，", ",").split(",") if kw.strip()]
    return keywords[:20]


def get_recent_articles_with_filenames(source: str = "swd", days: int = 30) -> List[tuple]:
    """取得最近文章（回傳 (檔案名, block) 列表，用於關鍵字映射）

    Args:
        source: 資料來源
        days: 天數

    Returns:
        [(filename, block), ...] 列表，按日期降序排序
    """
    folder = get_source_dir(source)
    logger.info(f"📂 [KeywordExtractor] 開始讀取文章：{source}，目錄：{folder}，天數：{days}")

    if not os.path.exists(folder):
        logger.warning(f"⚠️ [KeywordExtractor] 資料夾不存在：{folder}")
        return []

    all_files = os.listdir(folder)
    json_files = [f for f in all_files if f.endswith(".json") and f != "press_releases_recent.json"]
    logger.info(f"📂 [KeywordExtractor] 找到 {len(json_files)} 個 JSON 檔案")

    articles_with_date = []
    today = datetime.now().date()
    cutoff = today - timedelta(days=days)
    skipped_old = 0
    skipped_error = 0
    skipped_empty = 0

    for fn in json_files:
        try:
            with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                data = json.load(f)

            d = parse_date_from_item(source, data)
            if d < cutoff:
                skipped_old += 1
                continue

            block = make_reference_block_from_json(source, data)
            if block:
                articles_with_date.append((d, fn, block))
            else:
                skipped_empty += 1

        except Exception as e:
            skipped_error += 1
            logger.warning(f"⚠️ [KeywordExtractor] 讀取錯誤: {fn} - {e}")

    # 按日期降序排序
    articles_with_date.sort(key=lambda x: x[0], reverse=True)

    logger.info(f"✅ [KeywordExtractor] 文章讀取完成：{len(articles_with_date)} 篇符合條件")
    if skipped_old > 0 or skipped_error > 0 or skipped_empty > 0:
        logger.info(f"📊 [KeywordExtractor] 跳過統計：日期過舊={skipped_old}，讀取錯誤={skipped_error}，內容為空={skipped_empty}")

    return [(fn, block) for _, fn, block in articles_with_date]


def extract_keywords_with_sources(source: str, days: int = 30) -> tuple:
    """提取關鍵字並建立來源映射

    調用 GPT 提取關鍵字，驗證每個關鍵字確實存在於來源文章中，
    建立 {關鍵字: [來源檔案名列表]} 映射，過濾掉 GPT 創造的無效關鍵字。

    Args:
        source: 資料來源 ('swd' 或 'ha')
        days: 天數

    Returns:
        (valid_keywords, keyword_mapping) 元組
        - valid_keywords: 驗證通過的關鍵字列表
        - keyword_mapping: {關鍵字: [來源檔案名列表]} 映射
    """
    source = normalize_source(source)

    # 取得文章（包含檔案名）
    articles = get_recent_articles_with_filenames(source=source, days=days)
    if not articles:
        logger.warning(f"⚠️ [{source}] 沒有找到文章")
        return [], {}

    # 只取前10篇用於關鍵字提取
    top_articles = articles[:10]
    blocks = [block for _, block in top_articles]

    # 調用 GPT 提取關鍵字
    raw_keywords = extract_keywords_from_deepseek(blocks)
    if not raw_keywords:
        logger.warning(f"⚠️ [{source}] GPT 未返回關鍵字")
        return [], {}

    logger.info(f"🔍 [{source}] GPT 返回 {len(raw_keywords)} 個關鍵字，開始驗證...")

    # 驗證關鍵字並建立映射
    valid_keywords = []
    keyword_mapping = {}
    invalid_keywords = []

    for kw in raw_keywords:
        if not kw or len(kw) < 2:
            continue

        # 檢查關鍵字在哪些文章中出現
        source_files = []
        for fn, block in articles:  # 在所有文章中搜索，不只是前10篇
            if kw in block:
                source_files.append(fn)

        if source_files:
            valid_keywords.append(kw)
            keyword_mapping[kw] = source_files
            logger.debug(f"✅ 關鍵字「{kw}」在 {len(source_files)} 篇文章中找到")
        else:
            invalid_keywords.append(kw)
            logger.warning(f"⚠️ 過濾無效關鍵字「{kw}」（在原文中找不到）")

    logger.info(f"📊 [{source}] 關鍵字驗證結果: {len(valid_keywords)} 個有效，{len(invalid_keywords)} 個被過濾")
    if invalid_keywords:
        logger.info(f"🚫 被過濾的關鍵字: {invalid_keywords}")

    return valid_keywords, keyword_mapping


def store_keyword_source_mapping(source: str, mapping: Dict[str, List[str]]):
    """儲存關鍵字-來源映射到快取

    Args:
        source: 資料來源
        mapping: {關鍵字: [來源檔案名列表]} 映射
    """
    source = normalize_source(source)
    now = datetime.now()

    with keyword_source_mapping_lock:
        keyword_source_mapping[source] = {
            "mapping": mapping,
            "updated_at": now.timestamp(),
            "expires_at": now.timestamp() + Config.KEYWORD_CACHE_TTL,
        }

    logger.info(f"✅ 已儲存 {source} 關鍵字映射（{len(mapping)} 個關鍵字）")


def get_keyword_source_mapping(source: str) -> Dict[str, List[str]]:
    """取得關鍵字-來源映射（檢查 TTL）

    Args:
        source: 資料來源

    Returns:
        {關鍵字: [來源檔案名列表]} 映射，若過期或不存在則返回空字典
    """
    source = normalize_source(source)
    with keyword_source_mapping_lock:
        cached = keyword_source_mapping.get(source, {})
        if cached.get("expires_at", 0) > datetime.now().timestamp():
            mapping = cached.get("mapping", {})
            logger.debug(f"✅ [KeywordExtractor] 映射快取命中：{source}（{len(mapping)} 個關鍵字）")
            return mapping
        logger.debug(f"ℹ️ [KeywordExtractor] 映射快取未命中或已過期：{source}")
        return {}


def pick_bilingual_fields(data: dict) -> tuple:
    """從 JSON 取出 title/text 的中英版本

    Args:
        data: JSON 資料

    Returns:
        (title_zh, title_en, text_zh, text_en)
    """
    title = data.get("title", "")
    text = data.get("text", "")

    if isinstance(title, dict):
        title_zh = (title.get("zh") or "").strip()
        title_en = (title.get("en") or "").strip()
    else:
        title_zh = (title or "").strip()
        title_en = ""

    if isinstance(text, dict):
        text_zh = (text.get("zh") or "").strip()
        text_en = (text.get("en") or "").strip()
    else:
        text_zh = (text or "").strip()
        text_en = ""

    return title_zh, title_en, text_zh, text_en


def make_reference_block_from_json(source: str, data: dict) -> str:
    """將 JSON 轉成「中英並列 block」字串

    Args:
        source: 資料來源
        data: JSON 資料

    Returns:
        中英並列的文本塊
    """
    source = normalize_source(source)

    if source == "ha":
        title = (data.get("title") or "").strip()
        published = (data.get("published") or "").strip()

        paras = data.get("paragraphs") or []
        zh_lines = []
        en_lines = []
        for p in paras:
            if not isinstance(p, dict):
                continue
            z = (p.get("zh") or "").strip()
            e = (p.get("en") or "").strip()
            if z:
                zh_lines.append(z)
            if e:
                en_lines.append(e)

        zh_text = "\n".join(zh_lines).strip()
        en_text = "\n".join(en_lines).strip()

        parts = []
        if title or zh_text:
            parts.append(f"【ZH｜{title or '（無中文標題）'}｜{published}】\n{zh_text or '（無中文內文）'}")
        if title or en_text:
            parts.append(f"【EN｜{title or '(No English title)'}｜{published}】\n{en_text or '(No English content)'}")
        return "\n\n".join(parts).strip()

    title_zh, title_en, text_zh, text_en = pick_bilingual_fields(data)
    date_str = (data.get("date") or "").strip()
    parts = []
    if title_zh or text_zh:
        parts.append(f"【ZH｜{title_zh or '（無中文標題）'}｜{date_str}】\n{text_zh or '（無中文內文）'}")
    if title_en or text_en:
        parts.append(f"【EN｜{title_en or '(No English title)'}｜{date_str}】\n{text_en or '(No English content)'}")
    return "\n\n".join(parts).strip()


def parse_date_from_item(source: str, data: dict) -> datetime:
    """從 JSON 解析日期

    Args:
        source: 資料來源
        data: JSON 資料

    Returns:
        日期物件
    """
    source = normalize_source(source)
    date_str = data.get("published" if source == "ha" else "date", "")
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def get_recent_articles_text(source: str = "swd", days: int = 30) -> List[str]:
    """取得最近文章（回傳 block 列表，用於快取）

    Args:
        source: 資料來源
        days: 天數

    Returns:
        文章塊列表
    """
    # 檢查快取
    cache_key = f"articles_{source}_{days}"
    cached = cache_manager.get(cache_key)
    if cached is not None:
        logger.info(f"✅ 使用快取的文章資料（{source}, {days}天）")
        return cached

    # 讀取檔案
    folder = get_source_dir(source)
    logger.info(f"📂 [{source}] 正在讀取資料夾: {folder}")

    if not os.path.exists(folder):
        logger.warning(f"⚠️ [{source}] 資料夾不存在：{folder}")
        return []

    # 列出資料夾中的所有檔案
    all_files = os.listdir(folder)
    json_files = [f for f in all_files if f.endswith(".json") and f != "press_releases_recent.json"]
    logger.info(f"📂 [{source}] 找到 {len(json_files)} 個 JSON 檔案")

    # 收集 (日期, 檔案名, block) 三元組
    articles_with_date = []
    today = datetime.now().date()
    cutoff = today - timedelta(days=days)
    logger.info(f"📅 [{source}] 日期範圍: {cutoff} 至 {today}")

    skipped_old = 0
    for fn in json_files:
        try:
            with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                data = json.load(f)

            d = parse_date_from_item(source, data)
            if d < cutoff:
                skipped_old += 1
                continue

            block = make_reference_block_from_json(source, data)
            if block:
                articles_with_date.append((d, fn, block))

        except Exception as e:
            logger.warning(f"⚠️ [{source}] 讀取錯誤: {fn} - {e}")

    logger.info(f"📊 [{source}] 結果: {len(articles_with_date)} 篇符合日期，{skipped_old} 篇因日期過舊被跳過")

    # 若無資料，擴大到60天
    if not articles_with_date:
        cutoff = today - timedelta(days=60)
        for fn in os.listdir(folder):
            if not fn.endswith(".json") or fn == "press_releases_recent.json":
                continue
            try:
                with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                    data = json.load(f)
                d = parse_date_from_item(source, data)
                if d < cutoff:
                    continue
                block = make_reference_block_from_json(source, data)
                if block:
                    articles_with_date.append((d, fn, block))
            except Exception as e:
                logger.warning(f"⚠️ 讀取錯誤: {fn} - {e}")

    # 按日期降序排序，確保最新文章優先
    articles_with_date.sort(key=lambda x: x[0], reverse=True)
    recent_blocks = [block for _, _, block in articles_with_date]

    # 儲存到快取
    cache_manager.set(cache_key, recent_blocks, ttl=Config.ARTICLE_CACHE_TTL)
    logger.info(f"✅ 已快取文章資料（{source}, {len(recent_blocks)} 篇，已按日期排序）")

    return recent_blocks


def compute_and_store_keywords(source: str, days: int = 30) -> List[str]:
    """重新計算並儲存關鍵字（使用新的驗證流程）

    使用 extract_keywords_with_sources() 提取關鍵字並驗證，
    只保留在原文中確實存在的關鍵字，過濾掉 GPT 創造的無效關鍵字。

    Args:
        source: 資料來源
        days: 天數

    Returns:
        關鍵字列表（已驗證）
    """
    source = normalize_source(source)
    logger.info(f"🔄 [KeywordExtractor] 開始計算關鍵字：{source}，天數：{days}")
    start_time = datetime.now()

    try:
        # 使用新的驗證流程提取關鍵字
        valid_keywords, keyword_mapping = extract_keywords_with_sources(source=source, days=days)

        # 儲存關鍵字到快取
        store_keywords(source, valid_keywords)

        # 儲存關鍵字-來源映射
        if keyword_mapping:
            store_keyword_source_mapping(source, keyword_mapping)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"✅ [KeywordExtractor] 關鍵字計算完成：{source}")
        logger.info(f"📊 [KeywordExtractor] 計算統計：{len(valid_keywords)} 個有效關鍵字，{len(keyword_mapping)} 個映射，耗時 {elapsed:.2f} 秒")
        return valid_keywords

    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ [KeywordExtractor] 關鍵字計算失敗（{source}）：{e}，耗時 {elapsed:.2f} 秒")
        store_keywords(source, [], error=str(e))
        return []


def get_relevant_reference_blocks(
    source: str,
    keywords: List[str],
    days: int = 30,
    limit: int = 5
) -> List[str]:
    """根據關鍵詞找相關新聞

    Args:
        source: 資料來源
        keywords: 關鍵字列表
        days: 天數
        limit: 最多返回數量

    Returns:
        相關文章塊列表
    """
    folder = get_source_dir(source)
    if not os.path.exists(folder):
        return []

    source = normalize_source(source)
    keywords = [k for k in (keywords or []) if k and isinstance(k, str)]
    if not keywords:
        return []

    today = datetime.now().date()
    cutoff = today - timedelta(days=days)

    matched: List[tuple] = []

    for fn in os.listdir(folder):
        if not fn.endswith(".json") or fn == "press_releases_recent.json":
            continue

        try:
            with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                data = json.load(f)

            d = parse_date_from_item(source, data)
            if d < cutoff:
                continue

            block = make_reference_block_from_json(source, data)
            if not block:
                continue

            if any(kw in block for kw in keywords):
                matched.append((d.isoformat(), block))

        except Exception:
            continue

    matched.sort(key=lambda x: x[0], reverse=True)
    return [b for _, b in matched[:limit]]


def get_relevant_reference_blocks_by_mapping(
    source: str,
    keywords: List[str],
    days: int = 30,
    limit: int = 5
) -> List[str]:
    """根據關鍵字映射找相關新聞（優先使用映射）

    優先從關鍵字-來源映射中獲取來源文章，
    若映射中無資料則 fallback 到現有的搜索邏輯。

    Args:
        source: 資料來源
        keywords: 關鍵字列表
        days: 天數
        limit: 最多返回數量

    Returns:
        相關文章塊列表
    """
    source = normalize_source(source)
    keywords = [k for k in (keywords or []) if k and isinstance(k, str)]
    if not keywords:
        return []

    # 嘗試從映射中獲取來源文章
    mapping = get_keyword_source_mapping(source)
    if mapping:
        # 收集所有關鍵字對應的來源檔案
        source_files = set()
        for kw in keywords:
            if kw in mapping:
                source_files.update(mapping[kw])
                logger.info(f"✅ 關鍵字「{kw}」從映射中找到 {len(mapping[kw])} 個來源文章")

        if source_files:
            folder = get_source_dir(source)
            if not os.path.exists(folder):
                logger.warning(f"⚠️ [{source}] 資料夾不存在：{folder}")
                return get_relevant_reference_blocks(source, keywords, days, limit)

            # 讀取映射中的來源文章
            matched: List[tuple] = []
            today = datetime.now().date()
            cutoff = today - timedelta(days=days)

            for fn in source_files:
                try:
                    filepath = os.path.join(folder, fn)
                    if not os.path.exists(filepath):
                        logger.warning(f"⚠️ 映射中的檔案不存在: {fn}")
                        continue

                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    d = parse_date_from_item(source, data)
                    if d < cutoff:
                        continue

                    block = make_reference_block_from_json(source, data)
                    if block:
                        matched.append((d.isoformat(), block))

                except Exception as e:
                    logger.warning(f"⚠️ 讀取映射文章錯誤: {fn} - {e}")
                    continue

            if matched:
                matched.sort(key=lambda x: x[0], reverse=True)
                logger.info(f"✅ 從映射中找到 {len(matched)} 篇相關文章（限制 {limit} 篇）")
                return [b for _, b in matched[:limit]]

            logger.warning(f"⚠️ 映射中的文章都不符合日期範圍，fallback 到搜索邏輯")
        else:
            logger.warning(f"⚠️ 關鍵字「{keywords}」在映射中找不到，fallback 到搜索邏輯")
    else:
        logger.info(f"ℹ️ 無關鍵字映射快取，使用搜索邏輯")

    # Fallback 到現有的搜索邏輯
    return get_relevant_reference_blocks(source, keywords, days, limit)
