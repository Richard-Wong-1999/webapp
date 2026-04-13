"""
Flask AI 趨勢偵測系統 - 重構版
精簡主程式，模組化架構
"""

import os
import json
import re
import time
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request, session
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
    insert_article,
    update_article_score,
    update_article_content,
    get_article_scores_by_ids,
    normalize_source,
    get_cached_keywords,
    compute_and_store_keywords,
    clear_article_cache,
    keywords_cache,
    keywords_cache_lock,
    article_generation_progress,
    generated_prompts
)
from services.seo_orchestrator import (
    analyze_keyword_full,
    prepare_seo_context_for_prompt,
    get_seo_analysis_progress,
    seo_analysis_progress,
    start_keyword_crawl_task,
    get_crawl_task_progress,
    get_completed_crawl_result,
    stop_all_crawls
)
from services.dataforseo_client import dataforseo_client
from services.article_generator import background_generate_articles_by_source
from services.llm_client import (
    get_available_models,
    get_poe_points,
    call_llm
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

# 初始化資料庫（在 module load 時執行，支援 gunicorn）
init_connection_pool()
ensure_database_initialized()

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

        # 停止檢查回調
        def stop_check():
            return not ha_crawl_progress.running

        run_ha_crawl(
            out_dir=Config.HA_DIR,
            days=days,
            max_pages=Config.HA_MAX_PAGES,
            max_items=Config.HA_MAX_ITEMS,
            sleep=Config.HA_SLEEP,
            overwrite=True,
            progress_cb=progress_callback,
            enable_debug_html=True,
            stop_check=stop_check,
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

    llm_provider = Config.DEFAULT_PROVIDER
    llm_model = Config.DEFAULT_MODEL

    logger.info(f"🤖 使用 LLM 模型: {llm_provider}/{llm_model}")

    # 使用新的根據來源生成函數
    threading.Thread(
        target=background_generate_articles_by_source,
        args=(selected_keywords, timestamp, keyword_source, keyword_sources_map, llm_provider, llm_model)
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


@app.route("/diagnostics")
def diagnostics():
    """查詢文章生成診斷信息（用於排查問題）"""
    progress_data = article_generation_progress.to_dict()

    return jsonify({
        "timestamp": progress_data.get("timestamp", ""),
        "total_requested": progress_data.get("total", 0),
        "successfully_saved": len(progress_data.get("titles", [])),
        "failed_keywords": progress_data.get("failed_keywords", []),
        "parse_failures": progress_data.get("parse_failures", []),
        "errors": progress_data.get("errors", []),
        "tokens_used": progress_data.get("tokens_used", 0),
        "is_running": progress_data.get("running", False),
        "summary": {
            "parse_failure_count": len(progress_data.get("parse_failures", [])),
            "error_count": len(progress_data.get("errors", [])),
            "success_rate": f"{len(progress_data.get('titles', [])) / max(progress_data.get('total', 1), 1) * 100:.1f}%"
        }
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


@app.route("/api/article_scores", methods=["GET"])
def api_article_scores():
    """查詢文章評分狀態（輪詢用）"""
    ids_param = request.args.get("ids", "")
    if not ids_param:
        return jsonify({"success": False, "message": "未提供文章 ID"}), 400

    try:
        article_ids = [int(x) for x in ids_param.split(",") if x.strip()]
    except ValueError:
        return jsonify({"success": False, "message": "無效的文章 ID"}), 400

    results = get_article_scores_by_ids(article_ids)
    if isinstance(results, dict) and not results.get("success", True):
        return jsonify(results), 500

    scores = {}
    for row in results:
        aid = str(row["id"])
        if row["score"] is not None:
            score_result = {}
            if row.get("score_result"):
                try:
                    score_result = json.loads(row["score_result"])
                except (json.JSONDecodeError, TypeError):
                    pass
            scores[aid] = {
                "score": row["score"],
                "status": score_result.get("status", ""),
                "deductions": score_result.get("deduction_log", []),
                "title": row.get("title", ""),
                "keywords": row.get("keywords", "")
            }
        else:
            scores[aid] = {
                "score": None,
                "title": row.get("title", ""),
                "keywords": row.get("keywords", "")
            }

    return jsonify({"success": True, "scores": scores})


def _regenerate_single_article(article_id, prompt_zh, llm_provider, llm_model):
    """背景執行單篇文章重新生成（內部函式）"""
    from services.article_scorer import score_single_article
    from utils.logger import logger

    try:
        output, llm_metadata = call_llm(prompt_zh, provider=llm_provider, model=llm_model)
        if not output:
            logger.error(f"❌ 重新生成失敗 ID={article_id}: LLM 輸出為空")
            return

        # 解析 LLM 輸出
        cleaned = output.strip()
        if '```' in cleaned:
            code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned)
            if code_block_match:
                cleaned = code_block_match.group(1).strip()
            else:
                cleaned = re.sub(r'```(?:json)?', '', cleaned)
                cleaned = re.sub(r'```', '', cleaned)
                cleaned = cleaned.strip()

        cleaned = re.sub(r',(\s*[}\]])', r'\1', cleaned)
        match = re.search(r'\[.*\]', cleaned, re.S)
        parsed = json.loads(match.group(0)) if match else json.loads(cleaned)
        if not isinstance(parsed, list):
            parsed = [parsed]

        item = parsed[0]
        zh = item.get("zh") or {}
        en = item.get("en") or {}

        new_data = {
            "title": (zh.get("title") or "").strip() or "未命名",
            "body": (zh.get("body") or "").strip(),
            "meta_title": (zh.get("meta_title") or "").strip(),
            "meta_description": (zh.get("meta_description") or "").strip(),
            "title_zh": (zh.get("title") or "").strip(),
            "body_zh": (zh.get("body") or "").strip(),
            "meta_title_zh": (zh.get("meta_title") or "").strip(),
            "meta_description_zh": (zh.get("meta_description") or "").strip(),
            "title_en": (en.get("title") or "").strip(),
            "body_en": (en.get("body") or "").strip(),
            "meta_title_en": (en.get("meta_title") or "").strip(),
            "meta_description_en": (en.get("meta_description") or "").strip(),
            "keywords": json.dumps(item.get("keywords", []), ensure_ascii=False),
            "prompt_zh": prompt_zh,
        }

        update_article_content(article_id, new_data)
        logger.info(f"✅ 文章 ID={article_id} 重新生成完成，開始重新評分")

        # 重新評分
        score_single_article(article_id, new_data["keywords"], prompt_zh, llm_provider, llm_model)

    except Exception as e:
        logger.error(f"❌ 重新生成錯誤 ID={article_id}: {e}", exc_info=True)


@app.route("/api/regenerate_article/<int:article_id>", methods=["POST"])
def regenerate_article_route(article_id):
    """重新生成單篇文章"""
    article = get_article_by_id(article_id)
    if not article:
        return jsonify({"success": False, "message": "找不到文章"}), 404

    prompt_zh = article.get("prompt_zh")
    if not prompt_zh:
        return jsonify({"success": False, "message": "此文章沒有儲存生成 prompt，無法重新生成"}), 400

    # 立即清除分數
    update_article_score(article_id, None, None, None)

    llm_provider = article.get("llm_provider") or Config.DEFAULT_PROVIDER
    llm_model = article.get("llm_model") or Config.DEFAULT_MODEL

    threading.Thread(
        target=_regenerate_single_article,
        args=(article_id, prompt_zh, llm_provider, llm_model),
        daemon=True
    ).start()

    return jsonify({"success": True, "message": "重新生成已啟動"})


@app.route("/api/batch_regenerate_articles", methods=["POST"])
def batch_regenerate_articles_route():
    """批量重新生成文章"""
    data = request.get_json()
    article_ids = data.get("article_ids", [])
    if not article_ids:
        return jsonify({"success": False, "message": "未選擇任何文章"}), 400

    # 立即清除所有選中文章的分數
    for aid in article_ids:
        update_article_score(aid, None, None, None)

    def background_batch_regenerate(aids):
        from utils.logger import logger
        logger.info(f"🔄 批量重新生成開始: 共 {len(aids)} 篇")
        success_count = 0
        for i, aid in enumerate(aids, 1):
            article = get_article_by_id(aid)
            if not article or not article.get("prompt_zh"):
                logger.warning(f"⚠️ 跳過文章 ID={aid}: 無 prompt_zh")
                continue
            llm_provider = article.get("llm_provider") or Config.DEFAULT_PROVIDER
            llm_model = article.get("llm_model") or Config.DEFAULT_MODEL
            _regenerate_single_article(aid, article["prompt_zh"], llm_provider, llm_model)
            success_count += 1
            if i < len(aids):
                time.sleep(2)
        logger.info(f"🔄 批量重新生成完成: {success_count}/{len(aids)} 篇成功")

    threading.Thread(
        target=background_batch_regenerate,
        args=(article_ids,),
        daemon=True
    ).start()

    return jsonify({"success": True, "message": f"已啟動 {len(article_ids)} 篇文章的重新生成"})


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
# 路由：SEO 預爬蟲功能
# ==========================================================
@app.route("/api/seo/start_crawl", methods=["POST"])
def start_seo_crawl():
    """啟動 SEO 關鍵字爬蟲任務

    在用戶選擇 SEO 關鍵字時立即啟動背景爬蟲，
    爬取結果會快取到資料庫供文章生成時使用。
    """
    try:
        data = request.get_json()
        keyword = data.get("keyword", "").strip()

        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        if not dataforseo_client.is_configured():
            return jsonify({
                "success": False,
                "message": "DataForSEO API 未配置"
            }), 500

        # 啟動爬蟲任務
        result = start_keyword_crawl_task(keyword)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Start SEO crawl error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/crawl_progress/<path:keyword>", methods=["GET"])
def get_seo_crawl_progress(keyword):
    """取得 SEO 爬蟲任務進度

    前端輪詢此端點以獲取爬蟲進度，用於更新進度條 UI。
    """
    try:
        keyword = keyword.strip()
        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        progress = get_crawl_task_progress(keyword)

        return jsonify({
            "success": True,
            **progress
        })

    except Exception as e:
        logger.error(f"Get SEO crawl progress error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/crawl_result/<path:keyword>", methods=["GET"])
def get_seo_crawl_result(keyword):
    """取得 SEO 爬蟲結果（從快取）

    用於文章生成時直接取得預爬蟲的結果。
    """
    try:
        keyword = keyword.strip()
        if not keyword:
            return jsonify({"success": False, "message": "請提供關鍵字"}), 400

        # 取得快取的爬蟲結果（預設 1 小時內有效）
        max_age = request.args.get("max_age", 3600, type=int)
        result = get_completed_crawl_result(keyword, max_age_seconds=max_age)

        if result:
            return jsonify({
                "success": True,
                "cached": True,
                "data": result
            })
        else:
            return jsonify({
                "success": False,
                "cached": False,
                "message": "無快取結果或結果已過期"
            })

    except Exception as e:
        logger.error(f"Get SEO crawl result error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/seo/stop_all_crawls", methods=["POST"])
def api_stop_all_crawls():
    """停止所有正在執行的爬蟲任務（SEO、SWD、HA）

    用於緊急停止所有爬蟲，例如重啟前或資源不足時。
    """
    try:
        stopped_count = 0
        messages = []

        # 1. 停止 SEO 爬蟲
        seo_result = stop_all_crawls()
        stopped_count += seo_result.get("stopped_count", 0)
        if seo_result.get("stopped_count", 0) > 0:
            messages.append(f"SEO: {seo_result.get('stopped_count', 0)}")

        # 2. 停止 SWD 爬蟲
        if crawl_progress.get("running"):
            crawl_progress["running"] = False
            crawl_progress["status"] = "stopped"
            crawl_progress["message"] = "手動停止"
            stopped_count += 1
            messages.append("SWD: 1")
            logger.info("SWD crawl stopped by user")

        # 3. 停止 HA 爬蟲
        if ha_crawl_progress.running:
            ha_crawl_progress.running = False
            ha_crawl_progress.status = "stopped"
            ha_crawl_progress.message = "手動停止"
            stopped_count += 1
            messages.append("HA: 1")
            logger.info("HA crawl stopped by user")

        result = {
            "success": True,
            "stopped_count": stopped_count,
            "message": f"已停止 {stopped_count} 個爬蟲任務" + (f" ({', '.join(messages)})" if messages else "")
        }
        logger.info(f"Stop all crawls: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Stop all crawls error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/available_models", methods=["GET"])
def api_available_models():
    """獲取所有可用的模型清單"""
    return jsonify(get_available_models())


@app.route("/api/poe_usage", methods=["GET"])
def api_poe_usage():
    """獲取 Poe API 使用量"""
    points_used = get_poe_points(session)
    return jsonify({
        "points_used": points_used,
        "points_remaining": None  # Poe API 目前不支援查詢餘額
    })


@app.route("/api/debug/test_poe", methods=["GET"])
def api_debug_test_poe():
    """測試 Poe API 連接（除錯用）"""
    from services.poe_client import call_poe
    from config import Config

    # 從 query string 取得要測試的模型，預設 o4-mini
    test_model = request.args.get("model", "o4-mini")

    result = {
        "poe_api_key_set": bool(Config.POE_API_KEY),
        "poe_api_url": Config.POE_API_URL,
        "test_model": test_model,
        "success": False,
        "response": None,
        "error": None
    }

    if not Config.POE_API_KEY:
        result["error"] = "POE_API_KEY 未設定"
        return jsonify(result)

    try:
        content, tokens = call_poe("Say 'Hello' in one word.", model=test_model)
        if content:
            result["success"] = True
            result["response"] = content[:100]
            result["tokens_used"] = tokens
        else:
            result["error"] = "API 返回空內容"
    except Exception as e:
        result["error"] = str(e)

    return jsonify(result)


@app.route("/api/debug/test_generate", methods=["GET"])
def api_debug_test_generate():
    """測試文章生成流程（除錯用）"""
    from services.llm_client import call_llm
    import json
    import re

    test_model = request.args.get("model", "o4-mini")
    provider = "poe" if test_model != "deepseek-chat" else "deepseek"

    result = {
        "provider": provider,
        "model": test_model,
        "success": False,
        "raw_response": None,
        "parsed_json": None,
        "error": None
    }

    # 簡化的測試 prompt
    test_prompt = '''請輸出以下 JSON 格式（只輸出 JSON，不要其他文字）：
```json
[
  {
    "zh": {"title": "測試標題", "body": "測試內容"},
    "en": {"title": "Test Title", "body": "Test content"},
    "keywords": ["測試"]
  }
]
```'''

    try:
        content, metadata = call_llm(test_prompt, provider=provider, model=test_model)
        result["raw_response"] = content[:500] if content else None
        result["tokens_used"] = metadata.get("tokens_used", 0)

        if not content:
            result["error"] = "LLM 返回空內容"
            return jsonify(result)

        # 嘗試解析 JSON
        match = re.search(r'\[.*\]', content, re.S)
        if match:
            parsed = json.loads(match.group(0))
            result["parsed_json"] = parsed
            result["success"] = True
        else:
            result["error"] = "無法找到 JSON 陣列"

    except json.JSONDecodeError as e:
        result["error"] = f"JSON 解析錯誤: {str(e)}"
    except Exception as e:
        result["error"] = f"錯誤: {str(e)}"

    return jsonify(result)


@app.route("/api/debug/db_status", methods=["GET"])
def api_debug_db_status():
    """檢查資料庫狀態（除錯用）"""
    from services.database import get_db_connection, return_db_connection

    result = {
        "connection": False,
        "articles_table_exists": False,
        "article_count": 0,
        "columns": [],
        "error": None
    }

    conn = get_db_connection()
    if not conn:
        result["error"] = "無法連接資料庫"
        return jsonify(result)

    result["connection"] = True

    try:
        cur = conn.cursor()

        # 檢查 articles 表是否存在
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'articles'
            )
        """)
        result["articles_table_exists"] = cur.fetchone()[0]

        if result["articles_table_exists"]:
            # 取得欄位列表
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'articles'
                ORDER BY ordinal_position
            """)
            result["columns"] = [row[0] for row in cur.fetchall()]

            # 取得文章數量
            cur.execute("SELECT COUNT(*) FROM articles")
            result["article_count"] = cur.fetchone()[0]

        cur.close()
        return_db_connection(conn)

    except Exception as e:
        result["error"] = str(e)
        if conn:
            return_db_connection(conn)

    return jsonify(result)


# ==========================================================
# 路由：Wix Blog 整合
# ==========================================================
from services.wix_client import wix_client
logger.info("[WIX] wix_client 模組已載入")

@app.route("/api/wix/status", methods=["GET"])
def wix_api_status():
    """檢查 Wix API 配置狀態"""
    configured = wix_client.is_configured()
    return jsonify({
        "configured": configured,
        "message": "Wix API 已配置" if configured else "Wix API 未配置，請設定環境變數"
    })


@app.route("/send_to_wix/<int:article_id>", methods=["POST"])
def send_to_wix(article_id):
    """將單篇文章發送到 Wix Blog（草稿）

    只發送中文版本的文章
    """
    logger.info(f"[WIX] 收到發送請求：article_id={article_id}")

    # 檢查 Wix API 配置
    if not wix_client.is_configured():
        return jsonify({
            "success": False,
            "message": "Wix API 未配置，請先設定環境變數"
        }), 400

    # 獲取文章
    article = get_article_by_id(article_id)
    if not article:
        return jsonify({
            "success": False,
            "message": "文章不存在"
        }), 404

    # 檢查中文內容
    title_zh = article.get("title_zh") or article.get("title") or ""
    body_zh = article.get("body_zh") or article.get("body") or ""

    if not title_zh or not body_zh:
        return jsonify({
            "success": False,
            "message": "文章缺少中文標題或內容"
        }), 400

    # 準備摘要（使用 meta_description 或截取 body）
    excerpt = article.get("meta_description_zh") or article.get("meta_description") or ""
    if not excerpt and body_zh:
        # 截取前 150 個字元作為摘要
        import re
        clean_text = re.sub(r'<[^>]+>', '', body_zh)  # 移除 HTML 標籤
        excerpt = clean_text[:150] + "..." if len(clean_text) > 150 else clean_text

    try:
        result = wix_client.create_draft_post(
            title=title_zh,
            content_html=body_zh,
            excerpt=excerpt
        )

        draft_id = result.get("draftPost", {}).get("id", "unknown")

        return jsonify({
            "success": True,
            "message": f"文章已發送到 Wix Blog（草稿）",
            "draft_id": draft_id,
            "title": title_zh
        })

    except Exception as e:
        logger.error(f"發送到 Wix 失敗: {e}")
        return jsonify({
            "success": False,
            "message": f"發送失敗：{str(e)}"
        }), 500


@app.route("/api/wix/test", methods=["POST"])
def wix_api_test():
    """測試 Wix API 連接（使用簡單內容）"""
    if not wix_client.is_configured():
        return jsonify({"success": False, "message": "Wix API 未配置"}), 400

    try:
        # 使用最簡單的內容測試
        result = wix_client.create_draft_post(
            title="[API Test] 測試文章 - 可刪除",
            content_html="<p>這是一個測試。</p>",
            excerpt="API 測試"
        )
        draft_id = result.get("draftPost", {}).get("id", "unknown")
        return jsonify({
            "success": True,
            "message": "測試成功！",
            "draft_id": draft_id
        })
    except Exception as e:
        logger.error(f"Wix 測試失敗: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/batch_send_to_wix", methods=["POST"])
def batch_send_to_wix():
    """批量發送文章到 Wix Blog（草稿）

    只發送中文版本的文章
    """
    # 檢查 Wix API 配置
    if not wix_client.is_configured():
        return jsonify({
            "success": False,
            "message": "Wix API 未配置，請先設定環境變數"
        }), 400

    try:
        data = request.get_json()
        article_ids = data.get("article_ids", [])

        if not article_ids:
            return jsonify({
                "success": False,
                "message": "未選擇任何文章"
            }), 400

        results = {
            "total": len(article_ids),
            "success_count": 0,
            "failed_count": 0,
            "details": []
        }

        for article_id in article_ids:
            article = get_article_by_id(article_id)
            if not article:
                results["failed_count"] += 1
                results["details"].append({
                    "id": article_id,
                    "success": False,
                    "message": "文章不存在"
                })
                continue

            title_zh = article.get("title_zh") or article.get("title") or ""
            body_zh = article.get("body_zh") or article.get("body") or ""

            if not title_zh or not body_zh:
                results["failed_count"] += 1
                results["details"].append({
                    "id": article_id,
                    "success": False,
                    "message": "缺少中文內容"
                })
                continue

            # 準備摘要
            excerpt = article.get("meta_description_zh") or article.get("meta_description") or ""
            if not excerpt and body_zh:
                import re
                clean_text = re.sub(r'<[^>]+>', '', body_zh)
                excerpt = clean_text[:150] + "..." if len(clean_text) > 150 else clean_text

            try:
                result = wix_client.create_draft_post(
                    title=title_zh,
                    content_html=body_zh,
                    excerpt=excerpt
                )

                draft_id = result.get("draftPost", {}).get("id", "unknown")
                results["success_count"] += 1
                results["details"].append({
                    "id": article_id,
                    "success": True,
                    "draft_id": draft_id,
                    "title": title_zh
                })

            except Exception as e:
                results["failed_count"] += 1
                results["details"].append({
                    "id": article_id,
                    "success": False,
                    "message": str(e)
                })

            # 避免 API 限流，每篇文章間隔 0.5 秒
            time.sleep(0.5)

        return jsonify({
            "success": True,
            "message": f"批量發送完成：成功 {results['success_count']} 篇，失敗 {results['failed_count']} 篇",
            "results": results
        })

    except Exception as e:
        logger.error(f"批量發送到 Wix 失敗: {e}")
        return jsonify({
            "success": False,
            "message": f"批量發送失敗：{str(e)}"
        }), 500


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

    # 啟動 Flask（啟用多線程以支援背景爬蟲任務）
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=5000, threaded=True)
