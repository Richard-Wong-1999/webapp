"""SEO 流程協調服務

協調 DataForSEO API 和網站爬蟲，提供完整的 SEO 分析流程
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from config import Config
from utils.logger import logger
from services.dataforseo_client import dataforseo_client
from services.serp_scraper import scrape_serp_urls, summarize_content
from services.database import (
    get_db_connection,
    return_db_connection
)


# 分析進度追蹤
seo_analysis_progress = {
    "running": False,
    "keyword": "",
    "step": "",
    "completed_steps": 0,
    "total_steps": 4,
    "message": "",
    "error": None
}


def update_progress(step: str, message: str, completed: int = None):
    """更新分析進度"""
    seo_analysis_progress["step"] = step
    seo_analysis_progress["message"] = message
    if completed is not None:
        seo_analysis_progress["completed_steps"] = completed


def get_cached_trends(keyword: str) -> Optional[Dict]:
    """從資料庫取得快取的 Trends 數據"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        ttl = getattr(Config, 'SEO_TRENDS_CACHE_TTL', 3600)

        cur.execute("""
            SELECT topics, queries, fetched_at
            FROM seo_trends_data
            WHERE keyword = %s
              AND fetched_at > NOW() - INTERVAL '1 second' * %s
        """, (keyword, ttl))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row:
            return {
                "topics": row[0] if row[0] else [],
                "queries": row[1] if row[1] else [],
                "fetched_at": row[2].isoformat() if row[2] else None
            }
        return None

    except Exception as e:
        logger.error(f"Error getting cached trends: {e}")
        if conn:
            return_db_connection(conn)
        return None


def store_trends_cache(keyword: str, data: Dict):
    """儲存 Trends 數據到快取"""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seo_trends_data (keyword, topics, queries)
            VALUES (%s, %s, %s)
            ON CONFLICT (keyword)
            DO UPDATE SET
                topics = EXCLUDED.topics,
                queries = EXCLUDED.queries,
                fetched_at = CURRENT_TIMESTAMP
        """, (
            keyword,
            json.dumps(data.get("topics", []), ensure_ascii=False),
            json.dumps(data.get("queries", []), ensure_ascii=False)
        ))
        conn.commit()
        cur.close()
        return_db_connection(conn)

    except Exception as e:
        logger.error(f"Error storing trends cache: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def get_cached_keyword_data(keyword: str) -> Optional[Dict]:
    """從資料庫取得快取的關鍵字數據"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        ttl = getattr(Config, 'SEO_KEYWORD_CACHE_TTL', 86400)

        cur.execute("""
            SELECT search_volume, cpc, competition, competition_level,
                   related_keywords, fetched_at
            FROM seo_keyword_data
            WHERE keyword = %s
              AND fetched_at > NOW() - INTERVAL '1 second' * %s
        """, (keyword, ttl))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row:
            return {
                "search_volume": row[0],
                "cpc": float(row[1]) if row[1] else 0,
                "competition": float(row[2]) if row[2] else 0,
                "competition_level": row[3] or "",
                "related_keywords": row[4] if row[4] else [],
                "fetched_at": row[5].isoformat() if row[5] else None
            }
        return None

    except Exception as e:
        logger.error(f"Error getting cached keyword data: {e}")
        if conn:
            return_db_connection(conn)
        return None


def store_keyword_cache(keyword: str, data: Dict):
    """儲存關鍵字數據到快取"""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seo_keyword_data (
                keyword, search_volume, cpc, competition,
                competition_level, related_keywords
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (keyword)
            DO UPDATE SET
                search_volume = EXCLUDED.search_volume,
                cpc = EXCLUDED.cpc,
                competition = EXCLUDED.competition,
                competition_level = EXCLUDED.competition_level,
                related_keywords = EXCLUDED.related_keywords,
                fetched_at = CURRENT_TIMESTAMP
        """, (
            keyword,
            data.get("search_volume", 0),
            data.get("cpc", 0),
            data.get("competition", 0),
            data.get("competition_level", ""),
            json.dumps(data.get("related_keywords", []), ensure_ascii=False)
        ))
        conn.commit()
        cur.close()
        return_db_connection(conn)

    except Exception as e:
        logger.error(f"Error storing keyword cache: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def get_cached_serp(keyword: str) -> Optional[Dict]:
    """從資料庫取得快取的 SERP 數據"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        ttl = getattr(Config, 'SEO_SERP_CACHE_TTL', 21600)

        cur.execute("""
            SELECT organic_results, people_also_ask, related_searches, fetched_at
            FROM seo_serp_cache
            WHERE keyword = %s
              AND fetched_at > NOW() - INTERVAL '1 second' * %s
        """, (keyword, ttl))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row:
            return {
                "organic_results": row[0] if row[0] else [],
                "people_also_ask": row[1] if row[1] else [],
                "related_searches": row[2] if row[2] else [],
                "fetched_at": row[3].isoformat() if row[3] else None
            }
        return None

    except Exception as e:
        logger.error(f"Error getting cached SERP: {e}")
        if conn:
            return_db_connection(conn)
        return None


def store_serp_cache(keyword: str, data: Dict):
    """儲存 SERP 數據到快取"""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seo_serp_cache (
                keyword, organic_results, people_also_ask, related_searches
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (keyword)
            DO UPDATE SET
                organic_results = EXCLUDED.organic_results,
                people_also_ask = EXCLUDED.people_also_ask,
                related_searches = EXCLUDED.related_searches,
                fetched_at = CURRENT_TIMESTAMP
        """, (
            keyword,
            json.dumps(data.get("organic_results", []), ensure_ascii=False),
            json.dumps(data.get("people_also_ask", []), ensure_ascii=False),
            json.dumps(data.get("related_searches", []), ensure_ascii=False)
        ))
        conn.commit()
        cur.close()
        return_db_connection(conn)

    except Exception as e:
        logger.error(f"Error storing SERP cache: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def get_cached_scraped_content(url: str) -> Optional[Dict]:
    """從資料庫取得快取的爬取內容"""
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT title, meta_description, main_content, word_count, scraped_at
            FROM seo_scraped_content
            WHERE url = %s
        """, (url,))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row:
            return {
                "url": url,
                "title": row[0] or "",
                "meta_description": row[1] or "",
                "main_content": row[2] or "",
                "word_count": row[3] or 0,
                "scraped_at": row[4].isoformat() if row[4] else None
            }
        return None

    except Exception as e:
        logger.error(f"Error getting cached scraped content: {e}")
        if conn:
            return_db_connection(conn)
        return None


def store_scraped_content(data: Dict):
    """儲存爬取內容到快取"""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seo_scraped_content (
                url, title, meta_description, main_content, word_count
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url)
            DO UPDATE SET
                title = EXCLUDED.title,
                meta_description = EXCLUDED.meta_description,
                main_content = EXCLUDED.main_content,
                word_count = EXCLUDED.word_count,
                scraped_at = CURRENT_TIMESTAMP
        """, (
            data.get("url", ""),
            data.get("title", ""),
            data.get("meta_description", ""),
            data.get("main_content", ""),
            data.get("word_count", 0)
        ))
        conn.commit()
        cur.close()
        return_db_connection(conn)

    except Exception as e:
        logger.error(f"Error storing scraped content: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def analyze_keyword_full(keyword: str, skip_scraping: bool = False) -> Dict[str, Any]:
    """完整分析關鍵字（Trends + Ads + SERP + 爬蟲）

    Args:
        keyword: 要分析的關鍵字
        skip_scraping: 是否跳過網站爬取（只做 API 查詢）

    Returns:
        {
            "keyword": str,
            "trends": {...},
            "keyword_data": {...},
            "serp": {...},
            "scraped_content": [...],
            "error": str (if failed)
        }
    """
    global seo_analysis_progress

    seo_analysis_progress = {
        "running": True,
        "keyword": keyword,
        "step": "初始化",
        "completed_steps": 0,
        "total_steps": 3 if not skip_scraping else 2,
        "message": "開始分析...",
        "error": None
    }

    result = {
        "keyword": keyword,
        "trends": None,
        "keyword_data": None,
        "serp": None,
        "scraped_content": [],
        "error": None
    }

    try:
        # Step 1 & 2: 使用 DataForSEO Labs API 一次性獲取所有關鍵字數據
        # 這個 API 完全替代了：
        # - Google Trends 相關查詢
        # - Google Ads Search Volume API
        # - Google Ads Keywords For Keywords API
        update_progress("keyword_data", "正在取得關鍵字完整數據...", 0)

        # 檢查快取（優先檢查 keyword_data，因為它包含最完整的數據）
        keyword_data = get_cached_keyword_data(keyword)
        trends = get_cached_trends(keyword)

        if not keyword_data or not trends:
            logger.info(f"Fetching complete keyword data for: {keyword}")

            # 調用 Labs API 一次，獲取所有數據
            labs_data = dataforseo_client.get_related_keywords_labs(keyword, limit=20)

            seed_metrics = labs_data.get("seed_keyword_metrics", {})
            related = labs_data.get("related_keywords", [])

            # 構建 keyword_data（用於關鍵字指標面板）
            keyword_data = {
                "search_volume": seed_metrics.get("search_volume", 0),
                "cpc": seed_metrics.get("cpc", 0),
                "competition": seed_metrics.get("competition", 0),
                "competition_level": seed_metrics.get("competition_level", ""),
                "related_keywords": [
                    {
                        "keyword": r.get("keyword", ""),
                        "search_volume": r.get("search_volume", 0),
                        "cpc": r.get("cpc", 0),
                        "competition": r.get("competition", 0)
                    }
                    for r in related[:20]
                ]
            }

            # 構建 trends（用於相關查詢面板）
            # 將 Labs 相關關鍵字格式化為 queries 格式
            queries = [
                {
                    "query": r.get("keyword", ""),
                    "type": "related",
                    "value": r.get("search_volume", 0)
                }
                for r in related[:20]
            ]

            trends = {
                "topics": [],  # Labs API 不提供 topics
                "queries": queries
            }

            # 存入快取
            store_keyword_cache(keyword, keyword_data)
            store_trends_cache(keyword, trends)

        result["keyword_data"] = keyword_data
        result["trends"] = trends
        update_progress("keyword_data", "關鍵字數據完成", 1)

        # Step 2: SERP Results
        update_progress("serp", "正在取得搜尋結果...", 1)

        serp = get_cached_serp(keyword)
        if not serp:
            logger.info(f"Fetching SERP for: {keyword}")
            serp_result = dataforseo_client.get_serp_results(keyword, num=10)
            if not serp_result.get("error"):
                serp = {
                    "organic_results": serp_result.get("organic_results", []),
                    "people_also_ask": serp_result.get("people_also_ask", []),
                    "related_searches": serp_result.get("related_searches", [])
                }
                store_serp_cache(keyword, serp)
            else:
                serp = {
                    "organic_results": [],
                    "people_also_ask": [],
                    "related_searches": [],
                    "error": serp_result.get("error")
                }

        result["serp"] = serp
        update_progress("serp", "搜尋結果完成", 2)

        # Step 3: Scrape SERP URLs
        if not skip_scraping and serp.get("organic_results"):
            update_progress("scraping", "正在爬取競爭對手網站...", 2)

            urls_to_scrape = []
            for item in serp["organic_results"][:10]:  # 爬前 10 個作為參考
                url = item.get("url", "")
                if url:
                    # 先檢查快取
                    cached = get_cached_scraped_content(url)
                    if cached:
                        result["scraped_content"].append(cached)
                    else:
                        urls_to_scrape.append(url)

            # 爬取未快取的 URL
            if urls_to_scrape:
                scraped = scrape_serp_urls(urls_to_scrape)
                for item in scraped:
                    if item.get("success"):
                        store_scraped_content(item)
                        result["scraped_content"].append(item)

            update_progress("scraping", "網站爬取完成", 3)

        seo_analysis_progress["running"] = False
        seo_analysis_progress["message"] = "分析完成"

    except Exception as e:
        logger.error(f"Error in analyze_keyword_full: {e}")
        result["error"] = str(e)
        seo_analysis_progress["running"] = False
        seo_analysis_progress["error"] = str(e)
        seo_analysis_progress["message"] = f"分析失敗: {e}"

    return result


def prepare_seo_context_for_prompt(
    keyword: str,
    analysis_result: Dict[str, Any],
    max_content_length: int = 1500
) -> str:
    """準備 SEO 上下文供 AI 生成使用

    Args:
        keyword: 關鍵字
        analysis_result: analyze_keyword_full 的結果
        max_content_length: 每個競爭對手內容的最大長度

    Returns:
        格式化的 SEO 上下文字串
    """
    sections = []

    # 關鍵字指標
    keyword_data = analysis_result.get("keyword_data", {})
    if keyword_data:
        search_volume = keyword_data.get("search_volume", 0)
        cpc = keyword_data.get("cpc", 0)
        competition_level = keyword_data.get("competition_level", "N/A")

        sections.append(f"""## 📊 SEO 關鍵字指標
- 月搜尋量：{search_volume:,}
- 平均 CPC：${cpc:.2f}
- 競爭程度：{competition_level}""")

    # 相關關鍵字
    related_keywords = keyword_data.get("related_keywords", [])[:10]
    if related_keywords:
        related_list = ", ".join([k.get("keyword", "") for k in related_keywords if k.get("keyword")])
        sections.append(f"""## 🔗 相關關鍵字（可作為長尾關鍵字）
{related_list}""")

    # 用戶常問問題
    serp = analysis_result.get("serp", {})
    people_also_ask = serp.get("people_also_ask", [])
    if people_also_ask:
        questions = []
        for paa in people_also_ask[:5]:
            q = paa.get("question", "")
            if q:
                questions.append(f"- {q}")
        if questions:
            sections.append(f"""## ❓ 用戶常問問題（建議在文章中回答）
{chr(10).join(questions)}""")

    # 相關搜尋
    related_searches = serp.get("related_searches", [])
    if related_searches:
        searches = ", ".join(related_searches[:8])
        sections.append(f"""## 🔍 相關搜尋詞
{searches}""")

    # 競爭對手內容摘要
    scraped_content = analysis_result.get("scraped_content", [])
    if scraped_content:
        competitor_sections = []
        for i, content in enumerate(scraped_content[:3], 1):
            title = content.get("title", "")
            main_content = content.get("main_content", "")
            url = content.get("url", "")

            if main_content:
                summary = summarize_content(main_content, max_content_length)
                competitor_sections.append(f"""### 競爭對手 {i}: {title}
來源：{url}
內容摘要：
{summary}
""")

        if competitor_sections:
            sections.append(f"""## 📝 競爭對手內容參考
{chr(10).join(competitor_sections)}""")

    return "\n\n".join(sections) if sections else ""


def get_seo_analysis_progress() -> Dict[str, Any]:
    """取得當前 SEO 分析進度"""
    return dict(seo_analysis_progress)
