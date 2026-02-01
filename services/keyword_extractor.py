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
            return cached.get("keywords", [])
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
    prompt = (
        "你是一位香港社會政策與福利新聞分析專家，請仔細閱讀以下新聞摘要，"
        "根據內容，挑選出20個最能反映近期香港社會於『長者照顧、安老政策、長者福利、銀髮經濟、醫療支援、長期護理』等領域的具代表性關鍵詞。\n\n"
        "請嚴格遵守以下準則：\n"
        "1️⃣ 關鍵詞須屬於政策概念、方案名稱、制度倡議、計劃措施或公共關注議題。\n"
        "2️⃣ 排除數字、時間、地名與無意義名詞。\n"
        "3️⃣ 每個關鍵詞為1至15個中文字的名詞詞組。\n"
        "4️⃣ 請以1-100個關鍵詞作答（繁體中文），並用逗號分隔。\n\n"
        f"{joined_text}\n\n"
        "請直接輸出關鍵詞列表："
    )

    output = call_deepseek(prompt)
    if not output:
        logger.warning("⚠️ DeepSeek 無回應或 API 失敗，返回空關鍵字列表")
        return []

    keywords = [kw.strip() for kw in output.replace("，", ",").split(",") if kw.strip()]
    return keywords[:20]


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

    recent_blocks = []
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
                recent_blocks.append(block)

        except Exception as e:
            logger.warning(f"⚠️ [{source}] 讀取錯誤: {fn} - {e}")

    logger.info(f"📊 [{source}] 結果: {len(recent_blocks)} 篇符合日期，{skipped_old} 篇因日期過舊被跳過")

    # 若無資料，擴大到60天
    if not recent_blocks:
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
                    recent_blocks.append(block)
            except Exception as e:
                logger.warning(f"⚠️ 讀取錯誤: {fn} - {e}")

    # 儲存到快取
    cache_manager.set(cache_key, recent_blocks, ttl=Config.ARTICLE_CACHE_TTL)
    logger.info(f"✅ 已快取文章資料（{source}, {len(recent_blocks)} 篇）")

    return recent_blocks


def compute_and_store_keywords(source: str, days: int = 30) -> List[str]:
    """重新計算並儲存關鍵字

    Args:
        source: 資料來源
        days: 天數

    Returns:
        關鍵字列表
    """
    source = normalize_source(source)

    try:
        texts = get_recent_articles_text(source=source, days=days)
        result = extract_keywords_from_deepseek(texts)
        store_keywords(source, result)
        return result

    except Exception as e:
        logger.error(f"❌ 關鍵字計算失敗（{source}）：{e}")
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
