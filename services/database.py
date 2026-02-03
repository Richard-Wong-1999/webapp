"""資料庫服務模組"""

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from functools import wraps
from typing import Optional, Dict, List, Any
from config import Config
from utils.logger import logger

# 全域連接池
db_pool: Optional[pool.SimpleConnectionPool] = None


def init_connection_pool():
    """初始化資料庫連接池"""
    global db_pool

    if db_pool is not None:
        return db_pool

    try:
        db_pool = pool.SimpleConnectionPool(
            minconn=Config.DB_POOL_MIN,
            maxconn=Config.DB_POOL_MAX,
            dsn=Config.DATABASE_URL
        )
        logger.info(f"✅ 資料庫連接池已初始化 (min={Config.DB_POOL_MIN}, max={Config.DB_POOL_MAX})")
        return db_pool
    except Exception as e:
        logger.error(f"❌ 資料庫連接池初始化失敗：{e}")
        return None


def get_db_connection():
    """從連接池取得資料庫連接"""
    global db_pool

    if db_pool is None:
        init_connection_pool()

    if db_pool is None:
        logger.error("❌ 連接池未初始化")
        return None

    try:
        conn = db_pool.getconn()
        return conn
    except Exception as e:
        logger.error(f"❌ 無法從連接池取得連接：{e}")
        return None


def return_db_connection(conn):
    """歸還連接到連接池"""
    global db_pool

    if db_pool and conn:
        try:
            db_pool.putconn(conn)
        except Exception as e:
            logger.error(f"⚠️ 歸還連接失敗：{e}")


def with_db_connection(func):
    """資料庫連接裝飾器（自動處理連接取得與歸還）"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        conn = None
        try:
            conn = get_db_connection()
            if not conn:
                return {"success": False, "message": "無法連接資料庫"}

            result = func(conn, *args, **kwargs)
            return result

        except Exception as e:
            logger.error(f"Database error in {func.__name__}: {e}")
            return {"success": False, "message": str(e)}

        finally:
            if conn:
                return_db_connection(conn)

    return wrapper


def ensure_database_initialized():
    """確保資料庫已初始化（包含所有必要的資料表）"""
    conn = get_db_connection()
    if not conn:
        logger.error("⚠️ 無法連接資料庫進行初始化檢查")
        return False

    try:
        cur = conn.cursor()

        # 檢查所有必要的資料表
        required_tables = [
            'articles',
            'seo_keyword_data',
            'seo_trends_data',
            'seo_serp_cache',
            'seo_scraped_content',
            'seo_domain_summary'
        ]

        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
        """, (required_tables,))

        existing_tables = {row[0] for row in cur.fetchall()}
        missing_tables = set(required_tables) - existing_tables

        cur.close()
        return_db_connection(conn)

        if missing_tables:
            logger.warning(f"⚠️ 缺少資料表：{missing_tables}，正在創建...")
            return init_database()

        return True

    except Exception as e:
        logger.error(f"❌ 檢查資料表失敗：{e}")
        if conn:
            return_db_connection(conn)
        return False


def init_database():
    """初始化資料表（支援雙語文章）"""
    conn = get_db_connection()
    if not conn:
        logger.error("⚠️ 無法初始化資料庫")
        return False

    try:
        cur = conn.cursor()

        # 建立主表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id SERIAL PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                body TEXT NOT NULL,
                meta_title VARCHAR(200),
                meta_description TEXT,
                keywords TEXT,
                timestamp VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 添加雙語欄位
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS title_zh VARCHAR(500)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS title_en VARCHAR(500)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_zh TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_en TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_title_zh VARCHAR(200)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_title_en VARCHAR(200)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_description_zh TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_description_en TEXT")

        # 添加 prompt 欄位（用於記錄生成文章時使用的 prompt）
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS prompt_zh TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS prompt_en TEXT")

        # 添加 LLM 模型欄位（記錄文章使用的 AI 模型）
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(50)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS llm_model VARCHAR(100)")

        # 添加索引以提升查詢效能
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_created_at
            ON articles(created_at DESC)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_keywords
            ON articles USING gin(to_tsvector('english', keywords))
        """)

        # ========== SEO 相關資料表 ==========

        # SEO 關鍵字指標快取
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seo_keyword_data (
                id SERIAL PRIMARY KEY,
                keyword VARCHAR(500) NOT NULL,
                search_volume INTEGER,
                cpc DECIMAL(10, 4),
                competition DECIMAL(5, 4),
                competition_level VARCHAR(20),
                related_keywords JSONB,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(keyword)
            )
        """)

        # Google Trends 快取
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seo_trends_data (
                id SERIAL PRIMARY KEY,
                keyword VARCHAR(500) NOT NULL,
                topics JSONB,
                queries JSONB,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(keyword)
            )
        """)

        # SERP 結果快取
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seo_serp_cache (
                id SERIAL PRIMARY KEY,
                keyword VARCHAR(500) NOT NULL,
                organic_results JSONB,
                people_also_ask JSONB,
                related_searches JSONB,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(keyword)
            )
        """)

        # 爬取的網站內容
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seo_scraped_content (
                id SERIAL PRIMARY KEY,
                url VARCHAR(2000) NOT NULL UNIQUE,
                title VARCHAR(500),
                meta_description TEXT,
                main_content TEXT,
                word_count INTEGER,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # SEO 資料表索引
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_seo_keyword_data_fetched
            ON seo_keyword_data(fetched_at DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_seo_trends_fetched
            ON seo_trends_data(fetched_at DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_seo_serp_fetched
            ON seo_serp_cache(fetched_at DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_seo_scraped_scraped_at
            ON seo_scraped_content(scraped_at DESC)
        """)

        # 域名摘要快取（用於分層摘要）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seo_domain_summary (
                id SERIAL PRIMARY KEY,
                keyword VARCHAR(500) NOT NULL,
                domain VARCHAR(500) NOT NULL,
                summary TEXT NOT NULL,
                page_count INTEGER,
                source_urls JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(keyword, domain)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_seo_domain_summary_keyword
            ON seo_domain_summary(keyword)
        """)

        conn.commit()
        cur.close()
        return_db_connection(conn)
        logger.info("✅ 資料表初始化/升級完成（含索引及 SEO 資料表）")
        return True

    except Exception as e:
        logger.error(f"❌ 資料表初始化失敗：{e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if conn:
            return_db_connection(conn)
        return False


@with_db_connection
def get_all_articles(conn) -> List[Dict]:
    """取得所有文章"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM articles ORDER BY created_at DESC")
    articles = cur.fetchall()
    cur.close()
    return [dict(article) for article in articles]


@with_db_connection
def get_articles_paginated(conn, page: int = 1, per_page: int = 20) -> Dict:
    """分頁獲取文章"""
    offset = (page - 1) * per_page

    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 總數查詢
    cur.execute("SELECT COUNT(*) as total FROM articles")
    total = cur.fetchone()["total"]

    # 分頁查詢
    cur.execute(
        """
        SELECT * FROM articles
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        (per_page, offset)
    )
    articles = cur.fetchall()
    cur.close()

    return {
        "articles": [dict(a) for a in articles],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }


@with_db_connection
def get_article_by_id(conn, article_id: int) -> Optional[Dict]:
    """根據 ID 取得單篇文章"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
    article = cur.fetchone()
    cur.close()
    return dict(article) if article else None


@with_db_connection
def delete_article(conn, article_id: int) -> Dict:
    """刪除單篇文章"""
    cur = conn.cursor()
    cur.execute("DELETE FROM articles WHERE id = %s", (article_id,))
    conn.commit()
    cur.close()
    return {"success": True, "message": "文章已刪除"}


@with_db_connection
def batch_delete_articles(conn, article_ids: List[int]) -> Dict:
    """批量刪除文章"""
    if not article_ids:
        return {"success": False, "message": "未選擇任何文章"}

    cur = conn.cursor()
    placeholders = ','.join(['%s'] * len(article_ids))
    query = f"DELETE FROM articles WHERE id IN ({placeholders})"
    cur.execute(query, article_ids)
    deleted_count = cur.rowcount
    conn.commit()
    cur.close()

    return {
        "success": True,
        "message": f"成功刪除 {deleted_count} 篇文章"
    }


@with_db_connection
def insert_article(conn, article_data: Dict) -> Dict:
    """插入新文章"""
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO articles (
            title, body, meta_title, meta_description, keywords, timestamp,
            title_zh, body_zh, meta_title_zh, meta_description_zh,
            title_en, body_en, meta_title_en, meta_description_en,
            prompt_zh, prompt_en,
            llm_provider, llm_model
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        article_data.get("title", "未命名"),
        article_data.get("body", ""),
        article_data.get("meta_title", ""),
        article_data.get("meta_description", ""),
        article_data.get("keywords", ""),
        article_data.get("timestamp", ""),
        article_data.get("title_zh", ""),
        article_data.get("body_zh", ""),
        article_data.get("meta_title_zh", ""),
        article_data.get("meta_description_zh", ""),
        article_data.get("title_en", ""),
        article_data.get("body_en", ""),
        article_data.get("meta_title_en", ""),
        article_data.get("meta_description_en", ""),
        article_data.get("prompt_zh", ""),
        article_data.get("prompt_en", ""),
        article_data.get("llm_provider", ""),
        article_data.get("llm_model", "")
    ))

    article_id = cur.fetchone()[0]
    conn.commit()
    cur.close()

    return {"success": True, "id": article_id, "message": "文章已創建"}
