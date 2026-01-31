"""
Flask AI 趨勢偵測系統 - 重構版
精簡主程式，模組化架構
"""

import os
import json
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_compress import Compress

# 配置與模型
from config import Config
from models import ProgressTracker

# 服務層
from services import (
    init_connection_pool,
    ensure_database_initialized,
    init_database,
    get_all_articles,
    get_article_by_id,
    delete_article,
    batch_delete_articles,
    normalize_source,
    get_cached_keywords,
    compute_and_store_keywords,
    keywords_cache,
    keywords_cache_lock,
    background_generate_articles,
    article_generation_progress,
    generated_prompts
)
from services.seo_orchestrator import (
    analyze_keyword_full,
    prepare_seo_context_for_prompt,
    get_seo_analysis_progress,
    seo_analysis_progress
)
from services.dataforseo_client import dataforseo_client
from services.article_generator import generate_single_article_with_seo

# 工具
from utils import logger, cache_manager

# 爬蟲
from crawler.google_trends import get_google_trends_data
from crawler.ha_press_spider import run_ha_crawl

# 從原 app.py 導入 SWD 爬蟲相關函數（暫時保留，之後可移到 services/crawler_service.py）
from app_crawler_swd import background_crawl_news, crawl_progress

# ==========================================================
# Flask 應用初始化
# ==========================================================
app = Flask(__name__)
app.config.from_object(Config)

# 啟用壓縮
Compress(app)

# ==========================================================
# ✅ 註冊 Jinja2 過濾器
# ==========================================================
@app.template_filter('fromjson')
def fromjson_filter(value):
    """將 JSON 字串轉換為 Python 對象"""
    if not value:
        return []
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError):
        return []


@app.template_filter('tojson_pretty')
def tojson_pretty_filter(value):
    """將 Python 對象轉換為格式化的 JSON 字串"""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


# ==========================================================
# ✅ HA 爬蟲進度追蹤器
# ==========================================================
ha_crawl_progress = ProgressTracker("ha_crawl")


# ==========================================================
# HA 背景爬蟲
# ==========================================================
def background_crawl_ha(days=30):
    """HA 背景爬蟲"""
    ha_crawl_progress.update(
        total=0,
        completed=0,
        running=True,
        status="running",
        message="HA 爬蟲啟動中..."
    )

    def progress_callback(p: dict):
        """進度回調"""
        try:
            if "total" in p and isinstance(p["total"], int):
                ha_crawl_progress.total = p["total"]
            if "completed" in p and isinstance(p["completed"], int):
                ha_crawl_progress.completed = p["completed"]
            if "message" in p:
                ha_crawl_progress.message = str(p["message"])
            if "status" in p:
                ha_crawl_progress.status = str(p["status"])
        except Exception:
            pass

    try:
        os.makedirs(Config.HA_DIR, exist_ok=True)

        run_ha_crawl(
            out_dir=Config.HA_DIR,
            days=days,
            max_pages=Config.HA_MAX_PAGES,
            max_items=Config.HA_MAX_ITEMS,
            sleep=Config.HA_SLEEP,
            overwrite=True,
            progress_cb=progress_callback,
            enable_debug_html=True,
        )

        ha_crawl_progress.update(
            running=False,
            status="completed",
            message="✅ HA 爬蟲完成！關鍵字將自動更新。"
        )

        # 爬完立刻更新 HA keywords cache
        compute_and_store_keywords("ha", days=7)

    except Exception as e:
        ha_crawl_progress.update(
            running=False,
            status="error",
            message=f"❌ HA 爬蟲執行錯誤：{str(e)}"
        )
        logger.error(f"❌ HA 爬蟲錯誤：{e}")


# ==========================================================
# 路由：首頁
# ==========================================================
@app.route("/")
def index():
    return render_template("index.html")


# ==========================================================
# 路由：關鍵字頁面
# ==========================================================
@app.route("/keywords", methods=["GET", "POST"])
def keywords():
    source = normalize_source(request.args.get("source", "swd"))

    with keywords_cache_lock:
        cached = keywords_cache.get(source, {}) or {}
        result = cached.get("keywords") or []

    if not result:
        result = compute_and_store_keywords(source=source, days=7)

    trend_topic = ""
    trends = None
    if request.method == "POST":
        trend_topic = request.form.get("trend_topic", "").strip()
        if trend_topic:
            trends = get_google_trends_data(keyword=trend_topic, geo="HK")

    return render_template("keywords.html", keywords=result, trends=trends, trend_topic=trend_topic, source=source)


@app.route("/keywords_json", methods=["GET"])
def keywords_json():
    """API：取得關鍵字（JSON）"""
    source = normalize_source(request.args.get("source", "swd"))
    force = (request.args.get("force", "0") == "1")

    with keywords_cache_lock:
        cached = keywords_cache.get(source, {}) or {}
        cached_keywords = cached.get("keywords") or []
        updated_at = cached.get("updated_at") or 0
        error = cached.get("error") or ""

    if force or not cached_keywords:
        cached_keywords = compute_and_store_keywords(source=source, days=7)
        with keywords_cache_lock:
            updated_at = keywords_cache[source].get("updated_at") or 0
            error = keywords_cache[source].get("error") or ""

    # 轉換時間戳為可讀格式
    if updated_at:
        updated_at_str = datetime.fromtimestamp(updated_at).isoformat(timespec="seconds")
    else:
        updated_at_str = ""

    return jsonify({
        "source": source,
        "keywords": cached_keywords,
        "updated_at": updated_at_str,
        "error": error
    })


# ==========================================================
# 路由：SWD 爬蟲控制
# ==========================================================
@app.route("/start_crawl", methods=["POST"])
def start_crawl():
    """啟動 SWD 背景爬蟲"""
    if crawl_progress["running"]:
        return jsonify({"success": False, "message": "爬蟲正在執行中，請稍候..."})

    crawl_progress.update({
        "total": 0,
        "completed": 0,
        "running": True,
        "status": "running",
        "message": "爬蟲啟動中..."
    })

    threading.Thread(target=background_crawl_news, daemon=True).start()
    return jsonify({"success": True, "message": "爬蟲已啟動"})


@app.route("/crawl_progress")
def get_crawl_progress():
    """查詢 SWD 爬蟲進度"""
    return jsonify(crawl_progress)


# ==========================================================
# 路由：HA 爬蟲控制
# ==========================================================
@app.route("/start_crawl_ha", methods=["POST"])
def start_crawl_ha():
    """啟動 HA 背景爬蟲"""
    if ha_crawl_progress.running:
        return jsonify({"success": False, "message": "HA 爬蟲正在執行中，請稍候..."})

    ha_crawl_progress.reset()
    ha_crawl_progress.update(
        running=True,
        status="running",
        message="HA 爬蟲啟動中..."
    )

    threading.Thread(target=background_crawl_ha, kwargs={"days": 30}, daemon=True).start()
    return jsonify({"success": True, "message": "HA 爬蟲已啟動"})


@app.route("/crawl_progress_ha")
def get_crawl_progress_ha():
    """查詢 HA 爬蟲進度"""
    return jsonify(ha_crawl_progress.to_dict())


# ==========================================================
# 路由：文章生成
# ==========================================================
@app.route("/generate_articles", methods=["POST"])
def generate_articles():
    """生成文章"""
    selected_keywords = request.form.getlist("selected_keywords")
    source = normalize_source(request.form.get("source", "swd"))

    if not selected_keywords or len(selected_keywords) < 1:
        return render_template(
            "error.html",
            title="未選擇關鍵詞",
            message="⚠️ 請至少選擇 1 個關鍵詞才能生成文章。",
            back_url="/keywords",
            back_text="返回關鍵字頁"
        ), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    threading.Thread(
        target=background_generate_articles,
        args=(selected_keywords, timestamp, source)
    ).start()

    return render_template("generate.html")


@app.route("/progress")
def progress():
    """查詢文章生成進度"""
    return jsonify(article_generation_progress.to_dict())


@app.route("/get_prompts")
def get_prompts():
    """返回當前批次的 Prompts"""
    timestamp = article_generation_progress.timestamp
    prompts = generated_prompts.get(timestamp, [])
    prompts.sort(key=lambda x: x.get("index", 0))

    return jsonify({
        "timestamp": timestamp,
        "prompts": prompts
    })


# ==========================================================
# 路由：文章管理
# ==========================================================
@app.route("/manage_articles")
def manage_articles():
    """管理資料庫中的文章"""
    ensure_database_initialized()
    articles = get_all_articles()

    if isinstance(articles, dict) and not articles.get("success", True):
        return f"❌ 查詢失敗：{articles.get('message')}", 500

    return render_template("manage_articles.html", articles=articles)


@app.route("/delete_article/<int:article_id>", methods=["POST"])
def delete_article_route(article_id):
    """刪除單篇文章"""
    result = delete_article(article_id)
    return jsonify(result)


@app.route("/batch_delete_articles", methods=["POST"])
def batch_delete_articles_route():
    """批量刪除文章"""
    try:
        data = request.get_json()
        article_ids = data.get("article_ids", [])

        if not article_ids:
            return jsonify({"success": False, "message": "未選擇任何文章"})

        result = batch_delete_articles(article_ids)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "message": f"批量刪除失敗：{str(e)}"})


@app.route("/view_article/<int:article_id>")
def view_article(article_id):
    """查看單篇文章詳情"""
    ensure_database_initialized()

    article = get_article_by_id(article_id)

    if isinstance(article, dict) and not article.get("success", True):
        return f"❌ 查詢失敗：{article.get('message')}", 500

    if not article:
        return "❌ 文章不存在", 404

    # 處理 keywords 欄位
    if article.get('keywords'):
        try:
            if isinstance(article['keywords'], str):
                article['keywords'] = json.loads(article['keywords'])
        except (json.JSONDecodeError, TypeError):
            article['keywords'] = []
    else:
        article['keywords'] = []

    return render_template("view_article.html", article=article)


# ==========================================================
# 路由：資料庫管理
# ==========================================================
@app.route("/init_db")
def manual_init_db():
    """手動初始化資料庫"""
    try:
        success = init_database()
        if success:
            return """
            <h2>✅ 資料庫初始化完成</h2>
            <p>資料表 'articles' 已創建或確認存在（已支援雙語欄位及索引）。</p>
            <a href="/manage_articles">前往管理頁面</a>
            """
        else:
            return "❌ 初始化失敗", 500
    except Exception as e:
        return f"❌ 初始化失敗：{e}", 500


@app.route("/test_db")
def test_db():
    """測試資料庫連接"""
    from services.database import get_db_connection, return_db_connection

    conn = get_db_connection()
    if not conn:
        return "❌ 無法連接資料庫<br>請檢查 DATABASE_URL 環境變數", 500

    try:
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]

        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = cur.fetchall()

        cur.close()
        return_db_connection(conn)

        return f"""
        <h2>✅ 資料庫連接成功</h2>
        <p><strong>PostgreSQL 版本：</strong>{version}</p>
        <p><strong>現有資料表：</strong>{', '.join([t[0] for t in tables]) if tables else '無'}</p>
        <br>
        <a href="/init_db">初始化資料表</a> |
        <a href="/manage_articles">管理文章</a>
        """
    except Exception as e:
        if conn:
            return_db_connection(conn)
        return f"❌ 測試失敗：{e}", 500


# ==========================================================
# 路由：SEO 關鍵字研究
# ==========================================================
@app.route("/api/seo/keyword_research", methods=["POST"])
def seo_keyword_research():
    """SEO 關鍵字研究（Trends + Ads 數據）"""
    try:
        data = request.get_json()
        keyword = data.get("keyword", "").strip()

        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        if not dataforseo_client.is_configured():
            return jsonify({
                "success": False,
                "message": "DataForSEO API 未配置，請設定環境變數"
            }), 500

        # 取得 Trends 數據
        trends = dataforseo_client.get_google_trends(keyword)

        # 取得關鍵字指標
        metrics = dataforseo_client.get_keyword_metrics([keyword])
        keyword_metrics = metrics[0] if metrics else {}

        # 取得相關關鍵字建議
        suggestions = dataforseo_client.get_keyword_suggestions(keyword, limit=30)

        return jsonify({
            "success": True,
            "keyword": keyword,
            "trends": {
                "topics": trends.get("topics", []),
                "queries": trends.get("queries", [])
            },
            "metrics": {
                "search_volume": keyword_metrics.get("search_volume", 0),
                "cpc": keyword_metrics.get("cpc", 0),
                "competition": keyword_metrics.get("competition", 0),
                "competition_level": keyword_metrics.get("competition_level", "")
            },
            "suggestions": suggestions
        })

    except Exception as e:
        logger.error(f"SEO keyword research error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/keyword_suggestions", methods=["GET"])
def seo_keyword_suggestions():
    """取得關鍵字建議"""
    try:
        keyword = request.args.get("keyword", "").strip()
        limit = int(request.args.get("limit", "30"))

        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        if not dataforseo_client.is_configured():
            return jsonify({
                "success": False,
                "message": "DataForSEO API 未配置"
            }), 500

        suggestions = dataforseo_client.get_keyword_suggestions(keyword, limit=limit)

        return jsonify({
            "success": True,
            "keyword": keyword,
            "suggestions": suggestions
        })

    except Exception as e:
        logger.error(f"SEO keyword suggestions error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/analyze_serp", methods=["POST"])
def seo_analyze_serp():
    """分析 SERP 並爬取競爭對手網站"""
    try:
        data = request.get_json()
        keyword = data.get("keyword", "").strip()
        skip_scraping = data.get("skip_scraping", False)

        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        if seo_analysis_progress.get("running"):
            return jsonify({
                "success": False,
                "message": "另一個分析正在進行中"
            }), 400

        # 啟動背景分析
        def run_analysis():
            analyze_keyword_full(keyword, skip_scraping=skip_scraping)

        threading.Thread(target=run_analysis, daemon=True).start()

        return jsonify({
            "success": True,
            "message": "分析已啟動",
            "keyword": keyword
        })

    except Exception as e:
        logger.error(f"SEO analyze SERP error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/analysis_progress", methods=["GET"])
def seo_analysis_progress_route():
    """取得 SEO 分析進度"""
    return jsonify(get_seo_analysis_progress())


@app.route("/api/seo/analysis_result", methods=["GET"])
def seo_analysis_result():
    """取得 SEO 分析結果"""
    try:
        keyword = request.args.get("keyword", "").strip()

        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        # 直接執行完整分析（同步）
        result = analyze_keyword_full(keyword, skip_scraping=False)

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        logger.error(f"SEO analysis result error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ==========================================================
# 路由：SEO 增強文章生成
# ==========================================================
@app.route("/generate_articles_seo", methods=["POST"])
def generate_articles_seo():
    """使用 SEO 數據增強的文章生成"""
    selected_keywords = request.form.getlist("selected_keywords")
    source = normalize_source(request.form.get("source", "swd"))
    use_seo = request.form.get("use_seo", "0") == "1"

    if not selected_keywords or len(selected_keywords) < 1:
        return render_template(
            "error.html",
            title="未選擇關鍵詞",
            message="請至少選擇 1 個關鍵詞才能生成文章。",
            back_url="/keywords",
            back_text="返回關鍵字頁"
        ), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if use_seo and dataforseo_client.is_configured():
        # 使用 SEO 增強生成
        threading.Thread(
            target=background_generate_articles_seo,
            args=(selected_keywords, timestamp, source)
        ).start()
    else:
        # 使用原本的生成方式
        threading.Thread(
            target=background_generate_articles,
            args=(selected_keywords, timestamp, source)
        ).start()

    return render_template("generate.html")


def background_generate_articles_seo(
    selected_keywords: list,
    timestamp: str,
    source: str = "swd"
):
    """背景生成 SEO 增強文章"""
    from services.article_generator import (
        article_generation_progress,
        generated_prompts,
        generated_prompts_lock
    )
    from services.keyword_extractor import get_recent_articles_text, get_relevant_reference_blocks
    from utils.text_processing import build_reference_content_blocks_flexible
    from services.database import insert_article
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import re

    total_articles = len(selected_keywords)

    # 初始化進度
    article_generation_progress.update(
        total=total_articles,
        completed=0,
        running=True,
        timestamp=timestamp,
        titles=[]
    )

    with generated_prompts_lock:
        generated_prompts[timestamp] = []

    logger.info(f"開始生成 {total_articles} 篇 SEO 增強文章（source={source}）")

    # 準備備用內容
    recent_blocks = get_recent_articles_text(source=source, days=30)
    if not recent_blocks:
        fallback_content = "（無可用參考資料，請基於關鍵詞生成符合香港社會福利/醫療政策背景的專業內容）"
    else:
        fallback_content = build_reference_content_blocks_flexible(
            recent_blocks,
            max_chars_zh=Config.MAX_CHARS_ZH,
            max_chars_en=Config.MAX_CHARS_EN,
            prefer_bilingual=True
        )

    results = []

    # 使用線程池生成文章
    with ThreadPoolExecutor(max_workers=Config.ARTICLE_GENERATION_WORKERS) as executor:
        futures = [
            executor.submit(
                generate_single_article_with_seo,
                i,
                selected_keywords[i],
                source,
                timestamp,
                total_articles,
                fallback_content
            )
            for i in range(total_articles)
        ]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logger.error(f"文章生成失敗：{e}")

    # 解析並儲存文章
    all_articles = []
    for idx, output_text, chosen_kws in sorted(results, key=lambda x: x[0]):
        try:
            match = re.search(r'\[.*\]', output_text, re.S)
            parsed = json.loads(match.group(0)) if match else json.loads(output_text)

            if not isinstance(parsed, list):
                parsed = [parsed]

            for item in parsed:
                if item.get("keywords") != chosen_kws:
                    item["keywords"] = chosen_kws

                zh = item.get("zh") or {}
                en = item.get("en") or {}

                record = {
                    "title_zh": (zh.get("title") or "").strip(),
                    "body_zh": (zh.get("body") or "").strip(),
                    "meta_title_zh": (zh.get("meta_title") or "").strip(),
                    "meta_description_zh": (zh.get("meta_description") or "").strip(),
                    "title_en": (en.get("title") or "").strip(),
                    "body_en": (en.get("body") or "").strip(),
                    "meta_title_en": (en.get("meta_title") or "").strip(),
                    "meta_description_en": (en.get("meta_description") or "").strip(),
                    "keywords": json.dumps(item.get("keywords", chosen_kws), ensure_ascii=False),
                    "timestamp": timestamp
                }

                record["title"] = record["title_zh"] or "未命名"
                record["body"] = record["body_zh"] or ""
                record["meta_title"] = record["meta_title_zh"] or ""
                record["meta_description"] = record["meta_description_zh"] or ""

                all_articles.append(record)

        except Exception as e:
            logger.error(f"解析錯誤：{e}")
            continue

    # 批次插入資料庫
    for art in all_articles:
        result = insert_article(art)
        if result.get("success"):
            title = art.get("title_zh") or art.get("title") or "未命名"
            article_generation_progress.titles.append(title)

    logger.info(f"成功儲存 {len(all_articles)} 篇 SEO 增強文章到資料庫")

    # 完成
    article_generation_progress.update(running=False)


@app.route("/api/seo/status", methods=["GET"])
def seo_api_status():
    """檢查 SEO API 配置狀態"""
    return jsonify({
        "configured": dataforseo_client.is_configured(),
        "message": "DataForSEO API 已配置" if dataforseo_client.is_configured() else "DataForSEO API 未配置"
    })


# ==========================================================
# 應用啟動
# ==========================================================
if __name__ == "__main__":
    # 驗證配置
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"❌ 配置錯誤：{e}")
        exit(1)

    # 初始化資料庫連接池
    logger.info("🔧 初始化資料庫連接池...")
    init_connection_pool()

    # 初始化資料庫
    logger.info("🗄️ 初始化資料庫...")
    ensure_database_initialized()

    # 啟動快取管理器清理任務
    logger.info("🧹 啟動快取管理器...")
    cache_manager.start_cleanup(interval=3600)

    # 顯示資訊
    logger.info(f"📂 SWD 爬蟲資料夾: {Config.SWD_DIR}")
    logger.info(f"📂 HA 爬蟲資料夾: {Config.HA_DIR}")
    logger.info("🚀 Flask 應用啟動中...")

    # 啟動 Flask
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=5000)
