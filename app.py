"""
Flask AI 趨勢偵測系統 - 重構版
精簡主程式，模組化架構
"""

import os
import json
import threading
from datetime import datetime, timezone, timedelta
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
    clear_article_cache,
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
from services.article_generator import (
    generate_single_article_with_seo,
    background_generate_articles_by_source
)

# 工具
from utils import logger, cache_manager

# 爬蟲
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


# 香港時區 (UTC+8)
HK_TIMEZONE = timezone(timedelta(hours=8))

@app.template_filter('to_hk_time')
def to_hk_time_filter(value, fmt='%Y-%m-%d %H:%M'):
    """將 UTC 時間轉換為香港時間 (UTC+8)"""
    if not value:
        return '未知時間'
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        hk_time = value.astimezone(HK_TIMEZONE)
        return hk_time.strftime(fmt)
    except (AttributeError, ValueError):
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

        # 列出爬取結果
        import os as _os
        ha_files = [f for f in _os.listdir(Config.HA_DIR) if f.endswith(".json") and f != "press_releases_recent.json"]
        logger.info(f"✅ HA 爬蟲完成，共儲存 {len(ha_files)} 個 JSON 檔案到 {Config.HA_DIR}")

        ha_crawl_progress.update(
            running=False,
            status="completed",
            message=f"✅ HA 爬蟲完成！共 {len(ha_files)} 篇文章。關鍵字將自動更新。"
        )

        # 清除舊的文章快取，確保讀取最新資料
        clear_article_cache("ha")

        # 爬完立刻更新 HA keywords cache（使用與爬蟲相同的天數）
        logger.info(f"🔄 開始更新 HA 關鍵字快取（days={days}）...")
        compute_and_store_keywords("ha", days=days)

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
        result = compute_and_store_keywords(source=source, days=30)

    return render_template("keywords.html", keywords=result, source=source)


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
        # 使用 30 天範圍以匹配爬蟲的範圍
        cached_keywords = compute_and_store_keywords(source=source, days=30)
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
    """生成文章（根據關鍵字來源選擇參考資料）"""
    selected_keywords = request.form.getlist("selected_keywords")
    keyword_source = request.form.get("keyword_source", "swd")

    logger.info(f"📝 收到生成請求: {len(selected_keywords)} 個關鍵字, keyword_source={keyword_source}")

    # 獲取每個關鍵字的來源映射（從隱藏欄位或 data 屬性）
    keyword_sources_map = {}
    for key, value in request.form.items():
        if key.startswith("keyword_source_"):
            kw = key.replace("keyword_source_", "")
            keyword_sources_map[kw] = value

    # 如果沒有映射，嘗試從 JSON 獲取
    if not keyword_sources_map:
        sources_json = request.form.get("keyword_sources_json", "{}")
        logger.info(f"📝 keyword_sources_json: {sources_json}")
        try:
            keyword_sources_map = json.loads(sources_json)
        except Exception as e:
            logger.error(f"❌ 解析 keyword_sources_json 失敗: {e}")

    logger.info(f"📝 keyword_sources_map: {keyword_sources_map}")

    # 標準化 keyword_source
    if keyword_source not in ('swd', 'ha', 'seo', 'trends', 'mixed'):
        keyword_source = 'swd'

    if not selected_keywords or len(selected_keywords) < 1:
        return render_template(
            "error.html",
            title="未選擇關鍵詞",
            message="⚠️ 請至少選擇 1 個關鍵詞才能生成文章。",
            back_url="/keywords",
            back_text="返回關鍵字頁"
        ), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 使用新的根據來源生成函數
    threading.Thread(
        target=background_generate_articles_by_source,
        args=(selected_keywords, timestamp, keyword_source, keyword_sources_map)
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
    """SEO 關鍵字研究（使用 DataForSEO Labs API 一次性獲取所有數據）"""
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

        # 使用 Labs API 一次性獲取所有數據（替代 3 個 API）
        labs_data = dataforseo_client.get_related_keywords_labs_full(keyword, limit=30)

        seed_metrics = labs_data.get("seed_keyword_metrics", {})
        related = labs_data.get("related_keywords", [])

        return jsonify({
            "success": True,
            "keyword": keyword,
            "metrics": {
                "search_volume": seed_metrics.get("search_volume", 0),
                "cpc": seed_metrics.get("cpc", 0),
                "competition": seed_metrics.get("competition", 0),
                "competition_level": seed_metrics.get("competition_level", ""),
                "keyword_difficulty": seed_metrics.get("keyword_difficulty"),
                "search_intent": seed_metrics.get("search_intent"),
                "serp_count": seed_metrics.get("serp_count"),
                "serp_item_types": seed_metrics.get("serp_item_types", []),
                "search_volume_trend": seed_metrics.get("search_volume_trend", {}),
                "avg_backlinks": seed_metrics.get("avg_backlinks")
            },
            "suggestions": related
        })

    except Exception as e:
        logger.error(f"SEO keyword research error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/keyword_suggestions", methods=["GET"])
def seo_keyword_suggestions():
    """取得關鍵字建議（使用 Labs API）"""
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

        # 使用 Labs API 獲取相關關鍵字
        labs_data = dataforseo_client.get_related_keywords_labs(keyword, limit=limit)
        suggestions = labs_data.get("related_keywords", [])

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
