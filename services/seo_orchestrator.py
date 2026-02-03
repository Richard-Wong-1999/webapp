"""SEO 流程協調服務

協調 DataForSEO API 和網站爬蟲，提供完整的 SEO 分析流程
"""

import json
import re
import time
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed


def sanitize_for_postgres(text: str) -> str:
    """清理字串中 PostgreSQL 不支援的字符（如 NUL 字符）

    Args:
        text: 原始字串

    Returns:
        清理後的字串
    """
    if not text:
        return text
    # 移除 NUL 字符 (\x00, \u0000)
    return text.replace('\x00', '').replace('\u0000', '')


def sanitize_dict_for_postgres(data: Any) -> Any:
    """遞迴清理字典/列表中所有字串的 NUL 字符

    Args:
        data: 任意資料結構

    Returns:
        清理後的資料結構
    """
    if isinstance(data, str):
        return sanitize_for_postgres(data)
    elif isinstance(data, dict):
        return {k: sanitize_dict_for_postgres(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_dict_for_postgres(item) for item in data]
    else:
        return data

from config import Config
from utils.logger import logger
from services.dataforseo_client import dataforseo_client
from services.serp_scraper import scrape_serp_urls, summarize_content
from services.deep_crawler import DeepCrawler, DeepCrawlConfig, CrawledPage, create_deep_crawler_from_config
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
        # 清理 NUL 字符以避免 PostgreSQL 錯誤
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
            sanitize_for_postgres(data.get("title", "")),
            sanitize_for_postgres(data.get("meta_description", "")),
            sanitize_for_postgres(data.get("main_content", "")),
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


def analyze_keyword_full_with_deep_crawl(
    keyword: str,
    deep_crawl_enabled: bool = None,
    skip_api_calls: bool = False
) -> Dict[str, Any]:
    """執行帶深度爬取的完整分析

    與 analyze_keyword_full 類似，但使用智能深度爬取來獲取更多相關內容。

    Args:
        keyword: 要分析的關鍵字
        deep_crawl_enabled: 是否啟用深度爬取，None 則使用全局配置
        skip_api_calls: 是否跳過 API 調用（僅做爬取）

    Returns:
        {
            "keyword": str,
            "trends": {...},
            "keyword_data": {...},
            "serp": {...},
            "scraped_content": [...],  # 深度爬取的結果
            "deep_crawl_stats": {...},  # 深度爬取統計
            "error": str (if failed)
        }
    """
    global seo_analysis_progress

    # 確定是否啟用深度爬取
    if deep_crawl_enabled is None:
        deep_crawl_enabled = getattr(Config, 'DEEP_CRAWL_ENABLED', True)

    seo_analysis_progress = {
        "running": True,
        "keyword": keyword,
        "step": "初始化",
        "completed_steps": 0,
        "total_steps": 4 if deep_crawl_enabled else 3,
        "message": "開始分析（深度爬取模式）..." if deep_crawl_enabled else "開始分析...",
        "error": None
    }

    result = {
        "keyword": keyword,
        "trends": None,
        "keyword_data": None,
        "serp": None,
        "scraped_content": [],
        "deep_crawl_stats": None,
        "error": None
    }

    try:
        # Step 1: 取得關鍵字數據（與原始函數相同）
        if not skip_api_calls:
            update_progress("keyword_data", "正在取得關鍵字完整數據...", 0)

            keyword_data = get_cached_keyword_data(keyword)
            trends = get_cached_trends(keyword)

            if not keyword_data or not trends:
                logger.info(f"Fetching complete keyword data for: {keyword}")
                labs_data = dataforseo_client.get_related_keywords_labs(keyword, limit=20)

                seed_metrics = labs_data.get("seed_keyword_metrics", {})
                related = labs_data.get("related_keywords", [])

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

                queries = [
                    {
                        "query": r.get("keyword", ""),
                        "type": "related",
                        "value": r.get("search_volume", 0)
                    }
                    for r in related[:20]
                ]

                trends = {
                    "topics": [],
                    "queries": queries
                }

                store_keyword_cache(keyword, keyword_data)
                store_trends_cache(keyword, trends)

            result["keyword_data"] = keyword_data
            result["trends"] = trends
            update_progress("keyword_data", "關鍵字數據完成", 1)

        # Step 2: SERP Results
        update_progress("serp", "正在取得搜尋結果...", 1)

        serp = get_cached_serp(keyword)
        if not serp and not skip_api_calls:
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

        # Step 3: 深度爬取或普通爬取
        if serp and serp.get("organic_results"):
            seed_urls = [item.get("url", "") for item in serp["organic_results"][:10] if item.get("url")]

            if deep_crawl_enabled and seed_urls:
                update_progress("deep_crawling", "正在執行智能深度爬取...", 2)

                # 構建關鍵字列表（包含主關鍵字和相關關鍵字）
                keywords_for_relevance = [keyword]

                # 添加相關搜尋詞
                if serp.get("related_searches"):
                    keywords_for_relevance.extend(serp["related_searches"][:5])

                # 創建深度爬蟲並執行（傳入停止檢查回調）
                crawler = create_deep_crawler_from_config(stop_check=is_crawl_stopped)
                crawled_pages = crawler.crawl_with_depth(
                    seed_urls=seed_urls,
                    keywords=keywords_for_relevance,
                    max_results=20
                )

                # 轉換結果格式以匹配原有格式（清理 NUL 字符）
                for page in crawled_pages:
                    content_dict = {
                        "url": page.url,
                        "title": sanitize_for_postgres(page.title),
                        "meta_description": sanitize_for_postgres(page.meta_description),
                        "main_content": sanitize_for_postgres(page.main_content),
                        "word_count": page.word_count,
                        "success": page.success,
                        "error": sanitize_for_postgres(page.error) if page.error else None,
                        # 新增深度爬取特有欄位
                        "depth": page.depth,
                        "relevance_score": page.relevance_score,
                        "quality_score": page.quality_score,
                        "combined_score": page.combined_score,
                        "source_url": page.source_url
                    }
                    result["scraped_content"].append(content_dict)

                    # 同時存入快取
                    if page.success:
                        store_scraped_content(content_dict)

                # 統計資訊
                result["deep_crawl_stats"] = {
                    "total_pages_crawled": crawler.total_pages_crawled,
                    "unique_domains": len(crawler.domain_page_count),
                    "domain_breakdown": dict(crawler.domain_page_count),
                    "depth_0_count": sum(1 for p in crawled_pages if p.depth == 0),
                    "depth_1_count": sum(1 for p in crawled_pages if p.depth == 1),
                    "avg_relevance": sum(p.relevance_score for p in crawled_pages) / len(crawled_pages) if crawled_pages else 0,
                    "avg_quality": sum(p.quality_score for p in crawled_pages) / len(crawled_pages) if crawled_pages else 0
                }

                update_progress("deep_crawling", f"深度爬取完成（{len(crawled_pages)} 頁）", 3)
                logger.info(f"Deep crawl completed: {result['deep_crawl_stats']}")

            else:
                # 回退到普通爬取
                update_progress("scraping", "正在爬取競爭對手網站...", 2)

                urls_to_scrape = []
                for item in serp["organic_results"][:10]:
                    url = item.get("url", "")
                    if url:
                        cached = get_cached_scraped_content(url)
                        if cached:
                            result["scraped_content"].append(cached)
                        else:
                            urls_to_scrape.append(url)

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
        logger.error(f"Error in analyze_keyword_full_with_deep_crawl: {e}")
        result["error"] = str(e)
        seo_analysis_progress["running"] = False
        seo_analysis_progress["error"] = str(e)
        seo_analysis_progress["message"] = f"分析失敗: {e}"

    return result


def prepare_deep_crawl_context_for_prompt(
    keyword: str,
    analysis_result: Dict[str, Any],
    max_content_length: int = 1500,
    max_pages: int = 5
) -> str:
    """準備深度爬取結果的 SEO 上下文供 AI 生成使用

    與 prepare_seo_context_for_prompt 類似，但針對深度爬取結果做優化，
    優先展示高相關性和高質量的內容。

    Args:
        keyword: 關鍵字
        analysis_result: analyze_keyword_full_with_deep_crawl 的結果
        max_content_length: 每個競爭對手內容的最大長度
        max_pages: 最多展示的頁面數

    Returns:
        格式化的 SEO 上下文字串
    """
    sections = []

    # 關鍵字指標（與原函數相同）
    keyword_data = analysis_result.get("keyword_data", {})
    if keyword_data:
        search_volume = keyword_data.get("search_volume", 0)
        cpc = keyword_data.get("cpc", 0)
        competition_level = keyword_data.get("competition_level", "N/A")

        sections.append(f"""## SEO 關鍵字指標
- 月搜尋量：{search_volume:,}
- 平均 CPC：${cpc:.2f}
- 競爭程度：{competition_level}""")

    # 相關關鍵字
    related_keywords = keyword_data.get("related_keywords", [])[:10]
    if related_keywords:
        related_list = ", ".join([k.get("keyword", "") for k in related_keywords if k.get("keyword")])
        sections.append(f"""## 相關關鍵字（可作為長尾關鍵字）
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
            sections.append(f"""## 用戶常問問題（建議在文章中回答）
{chr(10).join(questions)}""")

    # 相關搜尋
    related_searches = serp.get("related_searches", [])
    if related_searches:
        searches = ", ".join(related_searches[:8])
        sections.append(f"""## 相關搜尋詞
{searches}""")

    # 深度爬取統計（如果有）
    deep_stats = analysis_result.get("deep_crawl_stats")
    if deep_stats:
        sections.append(f"""## 深度爬取統計
- 總爬取頁面：{deep_stats.get('total_pages_crawled', 0)}
- 涵蓋域名數：{deep_stats.get('unique_domains', 0)}
- SERP 頁面：{deep_stats.get('depth_0_count', 0)}
- 內部連結頁面：{deep_stats.get('depth_1_count', 0)}
- 平均相關性：{deep_stats.get('avg_relevance', 0):.2f}
- 平均質量：{deep_stats.get('avg_quality', 0):.2f}""")

    # 競爭對手內容摘要（按綜合分數排序）
    scraped_content = analysis_result.get("scraped_content", [])
    if scraped_content:
        # 按綜合分數排序（如果有），否則按原順序
        sorted_content = sorted(
            scraped_content,
            key=lambda x: x.get("combined_score", 0),
            reverse=True
        )

        competitor_sections = []
        for i, content in enumerate(sorted_content[:max_pages], 1):
            title = content.get("title", "")
            main_content = content.get("main_content", "")
            url = content.get("url", "")
            relevance = content.get("relevance_score", 0)
            quality = content.get("quality_score", 0)
            depth = content.get("depth", 0)

            if main_content:
                summary = summarize_content(main_content, max_content_length)

                # 添加深度和分數資訊
                depth_info = "（SERP 頁面）" if depth == 0 else "（深度連結）"
                score_info = f"相關性: {relevance:.2f}, 質量: {quality:.2f}" if relevance or quality else ""

                competitor_sections.append(f"""### 參考 {i}: {title} {depth_info}
來源：{url}
{score_info}
內容摘要：
{summary}
""")

        if competitor_sections:
            sections.append(f"""## 競爭對手內容參考（按相關性排序）
{chr(10).join(competitor_sections)}""")

    return "\n\n".join(sections) if sections else ""


# ========== 分層摘要功能 ==========

def group_by_domain(scraped_content: List[Dict]) -> Dict[str, List[Dict]]:
    """將爬取內容按域名分組

    Args:
        scraped_content: 爬取的頁面列表

    Returns:
        按域名分組的字典 {domain: [pages]}
    """
    domain_groups = {}

    for page in scraped_content:
        url = page.get("url", "")
        if not url:
            continue

        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain:
                if domain not in domain_groups:
                    domain_groups[domain] = []
                domain_groups[domain].append(page)
        except Exception as e:
            logger.warning(f"Failed to parse URL {url}: {e}")
            continue

    return domain_groups


def get_cached_domain_summary(keyword: str, domain: str) -> Optional[str]:
    """檢查是否有快取的域名摘要

    Args:
        keyword: 關鍵字
        domain: 域名

    Returns:
        快取的摘要文本，或 None
    """
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        ttl = getattr(Config, 'DOMAIN_SUMMARY_CACHE_TTL', 21600)

        cur.execute("""
            SELECT summary
            FROM seo_domain_summary
            WHERE keyword = %s AND domain = %s
              AND created_at > NOW() - INTERVAL '1 second' * %s
        """, (keyword, domain, ttl))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row:
            logger.info(f"Cache hit for domain summary: {domain} (keyword: {keyword})")
            return row[0]
        return None

    except Exception as e:
        logger.error(f"Error getting cached domain summary: {e}")
        if conn:
            return_db_connection(conn)
        return None


def store_domain_summary(keyword: str, domain: str, summary: str, urls: List[str]):
    """儲存域名摘要到快取

    Args:
        keyword: 關鍵字
        domain: 域名
        summary: 生成的摘要
        urls: 來源 URL 列表
    """
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seo_domain_summary (keyword, domain, summary, page_count, source_urls)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (keyword, domain)
            DO UPDATE SET
                summary = EXCLUDED.summary,
                page_count = EXCLUDED.page_count,
                source_urls = EXCLUDED.source_urls,
                created_at = CURRENT_TIMESTAMP
        """, (
            keyword,
            domain,
            summary,
            len(urls),
            json.dumps(urls, ensure_ascii=False)
        ))
        conn.commit()
        cur.close()
        return_db_connection(conn)
        logger.info(f"Stored domain summary for {domain} (keyword: {keyword})")

    except Exception as e:
        logger.error(f"Error storing domain summary: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def summarize_domain_content(
    domain: str,
    pages: List[Dict],
    keyword: str,
    max_content_per_page: int = 3000
) -> str:
    """為單一域名的所有頁面生成摘要

    Args:
        domain: 域名
        pages: 該域名的頁面列表
        keyword: 關鍵字
        max_content_per_page: 每個頁面內容的最大字數

    Returns:
        生成的摘要文本
    """
    from services.deepseek_client import call_deepseek

    # 檢查快取
    cached = get_cached_domain_summary(keyword, domain)
    if cached:
        return cached

    # 構建頁面內容
    page_contents = []
    urls = []

    for i, page in enumerate(pages[:5], 1):  # 每個域名最多取 5 頁
        title = page.get("title", "無標題")
        content = page.get("main_content", "")
        url = page.get("url", "")

        if content:
            # 截斷內容
            if len(content) > max_content_per_page:
                content = content[:max_content_per_page] + "..."

            page_contents.append(f"[頁面{i}: {title}]\n{content}")
            urls.append(url)

    if not page_contents:
        return ""

    combined_content = "\n\n---\n\n".join(page_contents)

    # 構建摘要 prompt
    prompt = f"""你是一位 SEO 內容分析專家。請分析以下來自同一網站的多個頁面，提取與「{keyword}」相關的重要資訊。

網站來源：{domain}
頁面數量：{len(page_contents)}

---
{combined_content}
---

請提取並輸出以下內容（用繁體中文）：

1. **核心觀點**：該網站對「{keyword}」的主要論述（2-3 句）
2. **關鍵數據**：具體數字、統計、日期等不可遺漏的資訊（列表）
3. **獨特見解**：其他競爭對手可能沒有提到的觀點
4. **實用建議**：對讀者有價值的具體建議

請用 400-600 字輸出結構化摘要，保留重要細節但去除冗餘資訊。"""

    try:
        summary = call_deepseek(prompt)
        if summary:
            # 儲存到快取
            store_domain_summary(keyword, domain, summary, urls)
            logger.info(f"Generated summary for domain {domain} ({len(pages)} pages)")
            return summary
        else:
            logger.warning(f"Empty summary returned for domain {domain}")
            return ""
    except Exception as e:
        logger.error(f"Failed to summarize domain {domain}: {e}")
        return ""


def generate_hierarchical_summary(
    scraped_content: List[Dict],
    keyword: str
) -> str:
    """分層摘要處理所有爬蟲數據

    採用 Map-Reduce 模式：
    1. Map 階段：按域名分組，並行生成每個域名的摘要
    2. Reduce 階段：合併所有摘要

    Args:
        scraped_content: 爬取的頁面列表
        keyword: 關鍵字

    Returns:
        合併後的摘要文本
    """
    # 1. 按域名分組
    domain_groups = group_by_domain(scraped_content)

    if not domain_groups:
        logger.warning("No domain groups found for hierarchical summary")
        return ""

    logger.info(f"Hierarchical summary: {len(domain_groups)} domains, {len(scraped_content)} total pages")

    # 2. 並行生成各域名摘要 (Map 階段)
    summaries = {}
    max_workers = getattr(Config, 'DOMAIN_SUMMARY_MAX_WORKERS', 3)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(summarize_domain_content, domain, pages, keyword): domain
            for domain, pages in domain_groups.items()
        }

        for future in as_completed(futures):
            domain = futures[future]
            try:
                result = future.result()
                if result:
                    summaries[domain] = result
                    logger.info(f"Completed summary for domain: {domain}")
            except Exception as e:
                logger.warning(f"Failed to summarize {domain}: {e}")
                # 跳過失敗的域名，繼續處理其他域名
                continue

    if not summaries:
        logger.warning("No summaries generated in hierarchical summary")
        return ""

    # 3. 合併摘要 (Reduce 階段)
    combined_sections = []
    for i, (domain, summary) in enumerate(summaries.items(), 1):
        page_count = len(domain_groups.get(domain, []))
        combined_sections.append(f"""### 來源 {i}: {domain}（{page_count} 頁）
{summary}
""")

    combined_summary = "\n".join(combined_sections)

    logger.info(f"Hierarchical summary completed: {len(summaries)} domain summaries generated")

    return combined_summary


# ========== SEO 預爬蟲任務管理 ==========

# 用於追蹤正在執行的爬蟲任務（避免重複啟動）
_running_crawl_tasks: Dict[str, bool] = {}
_crawl_tasks_lock = threading.Lock()

# 全域停止旗標
_global_crawl_stop_flag = False


def stop_all_crawls() -> Dict:
    """停止所有正在執行的爬蟲任務

    Returns:
        {
            "success": bool,
            "stopped_count": int,
            "message": str
        }
    """
    global _global_crawl_stop_flag, _running_crawl_tasks

    _global_crawl_stop_flag = True

    # 清除記憶體中的任務追蹤
    with _crawl_tasks_lock:
        stopped_keywords = list(_running_crawl_tasks.keys())
        _running_crawl_tasks.clear()

    # 更新資料庫中所有 running 狀態的任務為 stopped
    conn = get_db_connection()
    stopped_count = 0

    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE seo_crawl_tasks
                SET status = 'stopped',
                    error_message = '手動停止',
                    completed_at = NOW()
                WHERE status = 'running'
            """)
            stopped_count = cur.rowcount
            conn.commit()
            cur.close()
            return_db_connection(conn)
            logger.info(f"Stopped {stopped_count} crawl tasks in database")
        except Exception as e:
            logger.error(f"Error stopping crawl tasks: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            if conn:
                return_db_connection(conn)

    logger.info(f"Global crawl stop: {len(stopped_keywords)} memory tasks, {stopped_count} db tasks")

    # 5 秒後重置停止旗標，允許之後啟動新爬蟲
    def reset_flag():
        global _global_crawl_stop_flag
        time.sleep(5)
        _global_crawl_stop_flag = False
        logger.info("Crawl stop flag reset")

    threading.Thread(target=reset_flag, daemon=True).start()

    return {
        "success": True,
        "stopped_count": stopped_count + len(stopped_keywords),
        "message": f"已停止 {stopped_count} 個爬蟲任務"
    }


def is_crawl_stopped() -> bool:
    """檢查是否全域停止爬蟲"""
    return _global_crawl_stop_flag


def get_crawl_task_status(keyword: str) -> Optional[Dict]:
    """從資料庫取得爬蟲任務狀態

    Args:
        keyword: 關鍵字

    Returns:
        任務狀態字典，或 None（不存在）
    """
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT keyword, status, pages_crawled, total_pages, current_url,
                   error_message, started_at, completed_at, created_at
            FROM seo_crawl_tasks
            WHERE keyword = %s
        """, (keyword,))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row:
            return {
                "keyword": row[0],
                "status": row[1],
                "pages_crawled": row[2] or 0,
                "total_pages": row[3] or 30,
                "current_url": row[4] or "",
                "error_message": row[5] or "",
                "started_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None,
                "created_at": row[8].isoformat() if row[8] else None
            }
        return None

    except Exception as e:
        logger.error(f"Error getting crawl task status: {e}")
        if conn:
            return_db_connection(conn)
        return None


def create_or_reset_crawl_task(keyword: str, total_pages: int = 30) -> bool:
    """創建或重置爬蟲任務

    Args:
        keyword: 關鍵字
        total_pages: 預計爬取的總頁數

    Returns:
        是否成功
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seo_crawl_tasks (keyword, status, pages_crawled, total_pages, started_at)
            VALUES (%s, 'running', 0, %s, NOW())
            ON CONFLICT (keyword)
            DO UPDATE SET
                status = 'running',
                pages_crawled = 0,
                total_pages = EXCLUDED.total_pages,
                current_url = NULL,
                crawl_result = NULL,
                error_message = NULL,
                started_at = NOW(),
                completed_at = NULL
        """, (keyword, total_pages))
        conn.commit()
        cur.close()
        return_db_connection(conn)
        return True

    except Exception as e:
        logger.error(f"Error creating/resetting crawl task: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)
        return False


def update_crawl_task_progress(keyword: str, pages_crawled: int, current_url: str):
    """更新爬蟲任務進度

    Args:
        keyword: 關鍵字
        pages_crawled: 已爬取的頁數
        current_url: 當前正在爬取的 URL
    """
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE seo_crawl_tasks
            SET pages_crawled = %s, current_url = %s
            WHERE keyword = %s
        """, (pages_crawled, current_url, keyword))
        conn.commit()
        cur.close()
        return_db_connection(conn)

    except Exception as e:
        logger.error(f"Error updating crawl task progress: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def complete_crawl_task(keyword: str, crawl_result: Dict, error_message: str = None):
    """完成爬蟲任務（成功或失敗）

    Args:
        keyword: 關鍵字
        crawl_result: 爬取結果（scraped_content 等）
        error_message: 錯誤訊息（如果失敗）
    """
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()

        status = 'failed' if error_message else 'completed'

        # 清理 crawl_result 中的 NUL 字符以避免 PostgreSQL 錯誤
        sanitized_result = sanitize_dict_for_postgres(crawl_result) if crawl_result else None

        cur.execute("""
            UPDATE seo_crawl_tasks
            SET status = %s,
                crawl_result = %s,
                error_message = %s,
                completed_at = NOW()
            WHERE keyword = %s
        """, (
            status,
            json.dumps(sanitized_result, ensure_ascii=False) if sanitized_result else None,
            sanitize_for_postgres(error_message) if error_message else None,
            keyword
        ))
        conn.commit()
        cur.close()
        return_db_connection(conn)

        logger.info(f"Crawl task completed for '{keyword}': status={status}")

    except Exception as e:
        logger.error(f"Error completing crawl task: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)


def get_completed_crawl_result(keyword: str, max_age_seconds: int = 3600) -> Optional[Dict]:
    """取得已完成的爬蟲結果（快取）

    Args:
        keyword: 關鍵字
        max_age_seconds: 最大快取時間（秒），預設 1 小時

    Returns:
        爬取結果字典，或 None（不存在/過期/未完成）
    """
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT crawl_result, completed_at
            FROM seo_crawl_tasks
            WHERE keyword = %s
              AND status = 'completed'
              AND completed_at > NOW() - INTERVAL '1 second' * %s
        """, (keyword, max_age_seconds))

        row = cur.fetchone()
        cur.close()
        return_db_connection(conn)

        if row and row[0]:
            logger.info(f"Using cached crawl result for '{keyword}'")
            return row[0]  # JSONB 會自動轉為 dict
        return None

    except Exception as e:
        logger.error(f"Error getting completed crawl result: {e}")
        if conn:
            return_db_connection(conn)
        return None


def start_keyword_crawl_task(keyword: str) -> Dict:
    """啟動關鍵字爬蟲任務（背景執行）

    Args:
        keyword: 要爬取的關鍵字

    Returns:
        {
            "success": bool,
            "message": str,
            "status": str,  # pending/running/completed/failed
            "already_running": bool
        }
    """
    global _running_crawl_tasks

    # 檢查是否有已完成的快取結果
    cached = get_completed_crawl_result(keyword)
    if cached:
        return {
            "success": True,
            "message": "已有快取結果",
            "status": "completed",
            "already_running": False,
            "cached": True
        }

    # 檢查是否已在執行中（記憶體鎖 + 資料庫狀態）
    with _crawl_tasks_lock:
        if _running_crawl_tasks.get(keyword):
            return {
                "success": True,
                "message": "爬蟲任務正在執行中",
                "status": "running",
                "already_running": True
            }

        # 檢查資料庫中的狀態
        existing = get_crawl_task_status(keyword)
        if existing and existing["status"] == "running":
            # 可能是之前的進程留下的，檢查是否超時（超過 10 分鐘視為卡住）
            if existing["started_at"]:
                started = datetime.fromisoformat(existing["started_at"])
                elapsed = (datetime.now() - started).total_seconds()
                if elapsed < 600:  # 10 分鐘內
                    return {
                        "success": True,
                        "message": "爬蟲任務正在執行中",
                        "status": "running",
                        "already_running": True
                    }

        # 標記為執行中
        _running_crawl_tasks[keyword] = True

    # 創建/重置任務記錄
    if not create_or_reset_crawl_task(keyword):
        with _crawl_tasks_lock:
            _running_crawl_tasks.pop(keyword, None)
        return {
            "success": False,
            "message": "無法創建爬蟲任務",
            "status": "failed",
            "already_running": False
        }

    # 啟動背景執行緒
    def run_crawl():
        try:
            _execute_crawl_task(keyword)
        finally:
            with _crawl_tasks_lock:
                _running_crawl_tasks.pop(keyword, None)

    thread = threading.Thread(target=run_crawl, daemon=True)
    thread.start()

    return {
        "success": True,
        "message": "爬蟲任務已啟動",
        "status": "running",
        "already_running": False
    }


def _execute_crawl_task(keyword: str):
    """實際執行爬蟲任務（內部函數）

    Args:
        keyword: 關鍵字
    """
    logger.info(f"Starting crawl task for keyword: {keyword}")

    try:
        # 檢查全域停止旗標
        if is_crawl_stopped():
            logger.info(f"Crawl task for '{keyword}' stopped by global flag")
            complete_crawl_task(keyword, {"scraped_content": []}, "已被停止")
            return

        # 進度回調函數（同時檢查停止旗標）
        def progress_callback(pages_crawled: int, total_pages: int, current_url: str):
            if is_crawl_stopped():
                raise InterruptedError("Crawl stopped by user")
            update_crawl_task_progress(keyword, pages_crawled, current_url)

        # 執行深度爬取分析
        deep_crawl_enabled = getattr(Config, 'DEEP_CRAWL_ENABLED', True)

        # 先取得 SERP 結果
        serp = get_cached_serp(keyword)
        if not serp:
            logger.info(f"Fetching SERP for crawl task: {keyword}")
            serp_result = dataforseo_client.get_serp_results(keyword, num=10)
            if not serp_result.get("error"):
                serp = {
                    "organic_results": serp_result.get("organic_results", []),
                    "people_also_ask": serp_result.get("people_also_ask", []),
                    "related_searches": serp_result.get("related_searches", [])
                }
                store_serp_cache(keyword, serp)
            else:
                serp = {"organic_results": [], "people_also_ask": [], "related_searches": []}

        # 取得種子 URLs
        seed_urls = [item.get("url", "") for item in serp.get("organic_results", [])[:10] if item.get("url")]

        if not seed_urls:
            complete_crawl_task(keyword, {"scraped_content": []}, "無法取得 SERP 結果")
            return

        # 構建關鍵字列表
        keywords_for_relevance = [keyword]
        if serp.get("related_searches"):
            keywords_for_relevance.extend(serp["related_searches"][:5])

        # 創建爬蟲並執行（帶進度回調和停止檢查）
        crawler = create_deep_crawler_from_config(stop_check=is_crawl_stopped)
        crawled_pages = crawler.crawl_with_depth(
            seed_urls=seed_urls,
            keywords=keywords_for_relevance,
            max_results=20,
            progress_callback=progress_callback
        )

        # 轉換結果格式（清理 NUL 字符以避免 PostgreSQL 錯誤）
        scraped_content = []
        for page in crawled_pages:
            content_dict = {
                "url": page.url,
                "title": sanitize_for_postgres(page.title),
                "meta_description": sanitize_for_postgres(page.meta_description),
                "main_content": sanitize_for_postgres(page.main_content),
                "word_count": page.word_count,
                "success": page.success,
                "error": sanitize_for_postgres(page.error) if page.error else None,
                "depth": page.depth,
                "relevance_score": page.relevance_score,
                "quality_score": page.quality_score,
                "combined_score": page.combined_score,
                "source_url": page.source_url
            }
            scraped_content.append(content_dict)

            # 同時存入快取
            if page.success:
                store_scraped_content(content_dict)

        # 儲存結果
        result = {
            "scraped_content": scraped_content,
            "serp": serp,
            "deep_crawl_stats": {
                "total_pages_crawled": crawler.total_pages_crawled,
                "unique_domains": len(crawler.domain_page_count),
                "domain_breakdown": dict(crawler.domain_page_count),
                "depth_0_count": sum(1 for p in crawled_pages if p.depth == 0),
                "depth_1_count": sum(1 for p in crawled_pages if p.depth == 1),
                "avg_relevance": sum(p.relevance_score for p in crawled_pages) / len(crawled_pages) if crawled_pages else 0,
                "avg_quality": sum(p.quality_score for p in crawled_pages) / len(crawled_pages) if crawled_pages else 0
            }
        }

        complete_crawl_task(keyword, result)
        logger.info(f"Crawl task completed for '{keyword}': {len(scraped_content)} pages")

    except InterruptedError as e:
        logger.info(f"Crawl task for '{keyword}' interrupted: {e}")
        complete_crawl_task(keyword, {"scraped_content": scraped_content if 'scraped_content' in dir() else []}, "已被停止")

    except Exception as e:
        logger.error(f"Crawl task failed for '{keyword}': {e}")
        complete_crawl_task(keyword, None, str(e))


def get_crawl_task_progress(keyword: str) -> Dict:
    """取得爬蟲任務進度（供 API 使用）

    Args:
        keyword: 關鍵字

    Returns:
        進度資訊字典
    """
    status = get_crawl_task_status(keyword)

    if not status:
        return {
            "keyword": keyword,
            "status": "not_found",
            "pages_crawled": 0,
            "total_pages": 30,
            "current_url": "",
            "error_message": ""
        }

    return status
