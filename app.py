import os
import json
import datetime
from datetime import timedelta
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
from crawler.google_trends import get_google_trends_data
import requests
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import psycopg2
from psycopg2.extras import RealDictCursor

# ========== 爬虫相关导入 ==========
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import trafilatura

# ✅ HA 爬蟲
from crawler.ha_press_spider import run_ha_crawl

# ==========================================================
# 初始化設定
# ==========================================================
app = Flask(__name__)
load_dotenv()

# ==========================================================
# ✅ 註冊自定義 Jinja2 過濾器（解決 fromjson 錯誤）
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
# API 與資料庫設定
# ==========================================================
API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEESEEK_API_URL = "https://api.deepseek.com/chat/completions"
MODEL_NAME = "deepseek-chat"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ✅ SWD 資料夾
CRAWLER_DIR = os.path.join(BASE_DIR, "crawler", "swd_press")
# ✅ HA 資料夾
HA_CRAWLER_DIR = os.path.join(BASE_DIR, "crawler", "ha_press")

# ✅ PostgreSQL 連接設定
DATABASE_URL = os.getenv("DATABASE_URL")

# ✅ 全域進度資訊（文章生成）
progress_data = {
    "total": 0,
    "completed": 0,
    "running": False,
    "timestamp": "",
    "titles": []
}

# ✅ SWD 爬虫进度资讯
crawl_progress = {
    "total": 0,
    "completed": 0,
    "running": False,
    "status": "idle",
    "message": ""
}

# ✅ HA 爬虫进度资讯
ha_crawl_progress = {
    "total": 0,
    "completed": 0,
    "running": False,
    "status": "idle",
    "message": ""
}

# ✅ 全域變數儲存 Prompts
generated_prompts = {}

# ==========================================================
# ✅ Keywords cache（新增）
# ==========================================================
keywords_cache = {
    "swd": {"keywords": [], "updated_at": "", "error": ""},
    "ha": {"keywords": [], "updated_at": "", "error": ""},
}
keywords_cache_lock = threading.Lock()


# ==========================================================
# 資料庫連接與初始化
# ==========================================================
def get_db_connection():
    """建立資料庫連接"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"❌ 資料庫連接失敗：{e}")
        return None


def init_database():
    """
    初始化資料表（支援雙語文章，向後相容舊欄位）
    - 保留舊欄位 title/body/meta_title/meta_description
    - 新增 *_zh / *_en 欄位
    """
    conn = get_db_connection()
    if not conn:
        print("⚠️ 無法初始化資料庫")
        return

    try:
        cur = conn.cursor()

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

        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS title_zh VARCHAR(500)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS title_en VARCHAR(500)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_zh TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_en TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_title_zh VARCHAR(200)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_title_en VARCHAR(200)")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_description_zh TEXT")
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS meta_description_en TEXT")

        conn.commit()
        cur.close()
        conn.close()
        print("✅ 資料表初始化/升級完成")
    except Exception as e:
        print(f"❌ 資料表初始化失敗：{e}")
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def ensure_database_initialized():
    """確保資料庫已初始化（安全檢查）"""
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'articles'
            )
        """)
        exists = cur.fetchone()[0]
        cur.close()
        conn.close()

        if not exists:
            print("⚠️ 資料表不存在，正在創建...")
            init_database()
            return True

        init_database()
        return True

    except Exception as e:
        print(f"❌ 檢查資料表失敗：{e}")
        try:
            conn.close()
        except Exception:
            pass
        return False


# ✅ 應用啟動時立即執行初始化
try:
    print("🔧 檢查資料庫狀態...")
    ensure_database_initialized()
except Exception as e:
    print(f"⚠️ 資料庫初始化警告：{e}")


# ==========================================================
# DeepSeek API 呼叫
# ==========================================================
def call_deepseek(prompt_text: str):
    """呼叫 DeepSeek API"""
    if not API_KEY:
        print("❌ 未載入 DEEPSEEK_API_KEY，請檢查 .env 檔案")
        return ""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0.7,
        "max_tokens": 3500
    }
    try:
        response = requests.post(DEESEEK_API_URL, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            res = response.json()
            return res["choices"][0]["message"]["content"].strip()
        else:
            print("❌ DeepSeek 錯誤：", response.status_code, response.text)
            return ""
    except Exception as e:
        print("⚠️ 呼叫 DeepSeek 失敗：", e)
        return ""


# ==========================================================
# ✅ Source helpers
# ==========================================================
def normalize_source(source: str) -> str:
    s = (source or "swd").strip().lower()
    return "ha" if s == "ha" else "swd"


def get_source_dir(source: str) -> str:
    s = normalize_source(source)
    return HA_CRAWLER_DIR if s == "ha" else CRAWLER_DIR


# ==========================================================
# ✅ Helper：解析 YYYY-MM-DD（新增）
# ==========================================================
def parse_ymd_date(s: str):
    try:
        return datetime.datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None


# ==========================================================
# ✅ Helper：從 SWD JSON 取出 title/text 的中英版本
# ==========================================================
def pick_bilingual_fields(data: dict):
    """
    從 crawler/swd_press/*.json 取出 title/text 的中英版本
    回傳：title_zh, title_en, text_zh, text_en
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
    """將 SWD 或 HA 的 JSON 轉成「中英並列 block」字串，供 DeepSeek prompt 使用。"""
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


def parse_date_from_item(source: str, data: dict) -> datetime.date:
    source = normalize_source(source)
    if source == "ha":
        return datetime.datetime.strptime(data["published"], "%Y-%m-%d").date()
    return datetime.datetime.strptime(data["date"], "%Y-%m-%d").date()


# ==========================================================
# 讀取最近新聞文本（回傳「中英並列 block」list）
# ==========================================================
def get_recent_articles_text(source="swd", days=30):
    folder = get_source_dir(source)
    if not os.path.exists(folder):
        return []

    recent_blocks = []
    today = datetime.date.today()
    cutoff = today - timedelta(days=days)

    for fn in os.listdir(folder):
        if not fn.endswith(".json"):
            continue
        if fn == "press_releases_recent.json":
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
            print("⚠️ 讀取錯誤:", fn, e)

    if not recent_blocks:
        cutoff = today - timedelta(days=60)
        for fn in os.listdir(folder):
            if not fn.endswith(".json"):
                continue
            if fn == "press_releases_recent.json":
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
                print("⚠️ 讀取錯誤:", fn, e)

    return recent_blocks


def get_relevant_reference_blocks(source: str, keywords: list[str], days=30, limit=5) -> list[str]:
    """依關鍵詞找相關新聞，回傳最多 limit 個「中英並列 block」。"""
    folder = get_source_dir(source)
    if not os.path.exists(folder):
        return []

    source = normalize_source(source)
    keywords = [k for k in (keywords or []) if k and isinstance(k, str)]
    if not keywords:
        return []

    today = datetime.date.today()
    cutoff = today - timedelta(days=days)

    matched: list[tuple[str, str]] = []

    for fn in os.listdir(folder):
        if not fn.endswith(".json"):
            continue
        if fn == "press_releases_recent.json":
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


# ==========================================================
# DeepSeek 關鍵詞提取
# ==========================================================
def extract_keywords_from_deepseek(summaries):
    if not summaries:
        return ["（沒有近30天新聞稿資料）"]

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
        return ["（DeepSeek 無回應或 API 失敗）"]

    keywords = [kw.strip() for kw in output.replace("，", ",").split(",") if kw.strip()]
    return keywords[:20]


# ==========================================================
# ✅ Keywords cache helpers（新增）
# ==========================================================
def compute_and_store_keywords(source: str, days: int = 7) -> list[str]:
    """重新計算某來源 keywords，並寫入 cache。"""
    source = normalize_source(source)
    try:
        texts = get_recent_articles_text(source=source, days=days)
        result = extract_keywords_from_deepseek(texts)
        with keywords_cache_lock:
            keywords_cache[source] = {
                "keywords": result,
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "error": ""
            }
        return result
    except Exception as e:
        with keywords_cache_lock:
            keywords_cache[source]["error"] = str(e)
            keywords_cache[source]["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        return ["（關鍵字更新失敗）"]


# ==========================================================
# ✅ SWD 爬蟲：InfoGov 配對 + 中英合併輸出
# ==========================================================
INFOGOV_HOST = "www.info.gov.hk"

def strip_query(url: str) -> str:
    """移除 query string（例如 ?fontSize=1）避免重複"""
    try:
        u = urlparse(url)
        return urlunparse((u.scheme, u.netloc, u.path, "", "", ""))
    except Exception:
        return url


def is_infogov_url(url: str) -> bool:
    try:
        u = urlparse(url)
        return u.netloc.lower().endswith(INFOGOV_HOST)
    except Exception:
        return False


def extract_infogov_id(url: str) -> str:
    u = strip_query(url)
    m = re.search(r"/(P\d+)\.htm$", u)
    return m.group(1) if m else ""


def fetch_html(url: str, timeout=30) -> str:
    r = requests.get(url, timeout=timeout)
    r.encoding = "utf-8"
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    return r.text


def trafi_extract(url: str):
    downloaded = trafilatura.fetch_url(url)
    text = ""
    meta = {}
    if downloaded:
        data = trafilatura.extract(downloaded, with_metadata=True, output_format='json')
        if data:
            meta = json.loads(data)
            text = meta.get("text", "") or ""
        else:
            text = trafilatura.extract(downloaded) or ""
    return text.strip(), meta


def find_infogov_link_in_swd_page(swd_url: str):
    try:
        html = fetch_html(swd_url, timeout=30)
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full = urljoin(swd_url, href)
            if is_infogov_url(full) and "/gia/general/" in full:
                return strip_query(full)
    except Exception:
        return ""
    return ""


def find_other_language_infogov_url(infogov_url: str):
    try:
        html = fetch_html(infogov_url, timeout=30)
        soup = BeautifulSoup(html, "lxml")

        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full = urljoin(infogov_url, href)
            full = strip_query(full)
            if is_infogov_url(full) and "/gia/general/" in full and re.search(r"/P\d+\.htm$", full):
                if strip_query(full) != strip_query(infogov_url):
                    candidates.append(full)

        seen = set()
        uniq = []
        for c in candidates:
            if c not in seen:
                uniq.append(c)
                seen.add(c)

        return uniq[0] if uniq else ""
    except Exception:
        return ""


def detect_lang_from_url(url: str) -> str:
    u = (url or "").lower()
    if "/tc/" in u or "chi" in u:
        return "zh"
    if "/en/" in u or "eng" in u:
        return "en"
    return "unknown"


# ✅ 改成只取近 N 天（不再用 target_years）
def fetch_swd_list(list_url: str, days: int = 30):
    html = fetch_html(list_url, timeout=30)
    soup = BeautifulSoup(html, "lxml")
    rows = soup.find_all("tr")
    press_list = []

    today = datetime.date.today()
    cutoff = today - timedelta(days=days)

    for row in rows:
        tds = row.find_all("td")
        if len(tds) >= 2:
            date_text = tds[0].get_text(strip=True)
            d = parse_ymd_date(date_text)
            if not d:
                continue

            # ✅ 只取近 N 天
            if d < cutoff:
                # 如果你確定列表永遠由新到舊，可改用 break 省時間
                # break
                continue

            a_tag = tds[1].find("a")
            if a_tag and a_tag.get("href"):
                title = a_tag.get_text(strip=True)
                href = a_tag["href"]
                full_url = urljoin(list_url, href)
                press_list.append({
                    "date": date_text,
                    "title": title,
                    "url": full_url
                })

    return press_list


def make_safe_filename(s: str, max_len=180) -> str:
    s = s or ""
    s = re.sub(r'[\\/*?:"<>|]', '', s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] if len(s) > max_len else s


def derive_date_from_text_zh(text: str) -> str:
    if not text:
        return ""
    m = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日', text)
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def background_crawl_news():
    global crawl_progress

    crawl_progress.update({
        "total": 0,
        "completed": 0,
        "running": True,
        "status": "running",
        "message": "正在連接社會福利署網站(中/英)..."
    })

    try:
        base_url_zh = "https://www.swd.gov.hk/tc/whatsnew/press/"
        base_url_en = "https://www.swd.gov.hk/en/whatsnew/press/"

        # ✅ 只爬近 30 天（你可以改成參數）
        days = 30

        os.makedirs(CRAWLER_DIR, exist_ok=True)

        crawl_progress["message"] = f"正在抓取 SWD 中英文新聞列表（近 {days} 天）..."
        zh_list = fetch_swd_list(base_url_zh, days=days)
        en_list = fetch_swd_list(base_url_en, days=days)

        all_items = zh_list + en_list
        total = len(all_items)

        crawl_progress["total"] = total
        crawl_progress["message"] = f"發現 {total} 筆 SWD 列表項目（近 {days} 天），開始解析 InfoGov..."

        if total == 0:
            crawl_progress.update({
                "running": False,
                "status": "completed",
                "message": "沒有找到近 30 天新聞資料"
            })
            # ✅ 即使沒資料，也更新一次 keywords cache（會回傳「沒有近30天新聞稿資料」）
            compute_and_store_keywords("swd", days=7)
            return

        visited_infogov = set()
        merged_count = 0

        for i, item in enumerate(all_items, start=1):
            swd_date = item["date"]
            swd_title = item["title"]
            swd_url = item["url"]

            crawl_progress["completed"] = i
            crawl_progress["message"] = f"正在處理第 {i}/{total} 筆：{swd_title[:30]}..."

            try:
                infogov_url = find_infogov_link_in_swd_page(swd_url)
                if not infogov_url:
                    continue

                infogov_url = strip_query(infogov_url)
                if infogov_url in visited_infogov:
                    continue
                visited_infogov.add(infogov_url)

                other_url = find_other_language_infogov_url(infogov_url)
                other_url = strip_query(other_url) if other_url else ""

                text_a, meta_a = trafi_extract(infogov_url)
                title_a = meta_a.get("title", "") if meta_a else ""

                text_b, meta_b = ("", {})
                title_b = ""
                if other_url:
                    text_b, meta_b = trafi_extract(other_url)
                    title_b = meta_b.get("title", "") if meta_b else ""

                lang_a = (meta_a.get("language") if meta_a else "") or detect_lang_from_url(infogov_url)
                lang_b = (meta_b.get("language") if meta_b else "") or detect_lang_from_url(other_url)

                zh_url = ""
                en_url = ""
                zh_title = ""
                en_title = ""
                zh_text = ""
                en_text = ""
                zh_meta = {}
                en_meta = {}

                def assign(lang, url, title, text, meta):
                    nonlocal zh_url, en_url, zh_title, en_title, zh_text, en_text, zh_meta, en_meta
                    if lang and str(lang).lower().startswith("zh"):
                        zh_url, zh_title, zh_text, zh_meta = url, title, text, meta
                        return True
                    if lang and str(lang).lower().startswith("en"):
                        en_url, en_title, en_text, en_meta = url, title, text, meta
                        return True
                    return False

                ok_a = assign(lang_a, infogov_url, title_a, text_a, meta_a)
                ok_b = assign(lang_b, other_url, title_b, text_b, meta_b)

                if not ok_a:
                    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text_a))
                    if zh_chars > 30:
                        zh_url, zh_title, zh_text, zh_meta = infogov_url, title_a, text_a, meta_a
                    else:
                        en_url, en_title, en_text, en_meta = infogov_url, title_a, text_a, meta_a

                if other_url and not ok_b:
                    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text_b))
                    if zh_chars > 30:
                        zh_url, zh_title, zh_text, zh_meta = other_url, title_b, text_b, meta_b
                    else:
                        en_url, en_title, en_text, en_meta = other_url, title_b, text_b, meta_b

                derived_date = derive_date_from_text_zh(zh_text) or swd_date
                pid_a = extract_infogov_id(infogov_url)
                pid_b = extract_infogov_id(other_url) if other_url else ""
                pairing_key = pid_a or pid_b or f"{swd_date}|{urlparse(infogov_url).path}"

                safe_key = make_safe_filename(pairing_key.replace("/", "_"))
                filename = f"{derived_date}_{safe_key}.json"
                filepath = os.path.join(CRAWLER_DIR, filename)

                article_data = {
                    "date": derived_date,
                    "pairing_key": pairing_key,
                    "source": "swd_press + infogov",
                    "url": {"zh": zh_url, "en": en_url},
                    "title": {
                        "zh": zh_title or (swd_title if zh_url else ""),
                        "en": en_title or (swd_title if en_url else "")
                    },
                    "text": {"zh": (zh_text or "").strip(), "en": (en_text or "").strip()},
                    "metadata": {"zh": zh_meta or {}, "en": en_meta or {}},
                    "swd": {
                        "list_date": swd_date,
                        "list_title": swd_title,
                        "list_url": swd_url
                    }
                }

                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(article_data, f, ensure_ascii=False, indent=2)

                merged_count += 1

            except Exception as e:
                print(f"⚠️ 處理 {swd_title} 時出錯：", e)
                continue

        crawl_progress.update({
            "running": False,
            "status": "completed",
            "message": f"✅ 完成！已輸出 {merged_count} 份中英對照 JSON（近 {days} 天 SWD 列表）。"
        })

        # ✅ 爬完立刻更新 SWD keywords cache（供前端快速切換/自動刷新）
        compute_and_store_keywords("swd", days=7)

    except Exception as e:
        crawl_progress.update({
            "running": False,
            "status": "error",
            "message": f"爬蟲執行錯誤：{str(e)}"
        })
        print("❌ 爬蟲錯誤：", e)


# ==========================================================
# ✅ HA 背景爬蟲
# ==========================================================
def background_crawl_ha(days=30):
    global ha_crawl_progress

    ha_crawl_progress.update({
        "total": 0,
        "completed": 0,
        "running": True,
        "status": "running",
        "message": "HA 爬蟲啟動中..."
    })

    def cb(p: dict):
        try:
            if "total" in p and isinstance(p["total"], int):
                ha_crawl_progress["total"] = p["total"]
            if "completed" in p and isinstance(p["completed"], int):
                ha_crawl_progress["completed"] = p["completed"]
            if "message" in p:
                ha_crawl_progress["message"] = str(p["message"])
            if "status" in p:
                ha_crawl_progress["status"] = str(p["status"])
        except Exception:
            pass

    try:
        os.makedirs(HA_CRAWLER_DIR, exist_ok=True)

        run_ha_crawl(
            out_dir=HA_CRAWLER_DIR,
            days=days,
            max_pages=200,
            max_items=500,
            sleep=0.8,
            overwrite=True,
            progress_cb=cb,
            enable_debug_html=True,
        )

        ha_crawl_progress.update({
            "running": False,
            "status": "completed",
            "message": "✅ HA 爬蟲完成！關鍵字將自動更新。"
        })

        # ✅ 爬完立刻更新 HA keywords cache
        compute_and_store_keywords("ha", days=7)

    except Exception as e:
        ha_crawl_progress.update({
            "running": False,
            "status": "error",
            "message": f"❌ HA 爬蟲執行錯誤：{str(e)}"
        })
        print("❌ HA 爬蟲錯誤：", e)


# ==========================================================
# ✅ 背景生成文章（支援 source：swd/ha）
# ==========================================================
def background_generate_articles(selected_keywords, timestamp, source="swd"):
    global generated_prompts

    source = normalize_source(source)

    total_articles = len(selected_keywords)
    progress_data.update({
        "total": total_articles,
        "completed": 0,
        "running": True,
        "timestamp": timestamp,
        "titles": []
    })

    generated_prompts[timestamp] = []

    recent_blocks = get_recent_articles_text(source=source, days=30)
    if not recent_blocks:
        print("⚠️ 沒有找到近期新聞，將使用關鍵字生成")
        fallback_content = "（無可用參考資料，請基於關鍵詞生成符合香港社會福利/醫療政策背景的專業內容）"
    else:
        fallback_content = "\n\n---\n\n".join(recent_blocks[:3])[:2500]

    lock = threading.Lock()
    results = []

    def generate_single_article(article_index):
        main_keyword = selected_keywords[article_index]
        chosen_keywords = [main_keyword]

        print(f"📝 正在生成第 {article_index + 1}/{total_articles} 篇文章（中英雙語），主題：{main_keyword}（source={source}）")

        reference_blocks = get_relevant_reference_blocks(source=source, keywords=[main_keyword], days=30, limit=5)

        if reference_blocks:
            reference_content = "\n\n---\n\n".join(reference_blocks)[:4200]
            print(f"✅ 為關鍵詞「{main_keyword}」找到 {len(reference_blocks)} 篇相關新聞（{source}，含中英對照）")
        else:
            reference_content = fallback_content
            print(f"⚠️ 未找到「{main_keyword}」相關新聞，使用備用內容（{source}，含中英）")

        prompt_zh = (
            "你是一位香港地區的專業內容寫作顧問與 SEO 專家。\n\n"
            "## 📋 任務說明\n"
            f"請根據以下**真實新聞參考資料**，以「{main_keyword}」為**唯一主題**，一次輸出：\n"
            "1) 一篇繁體中文 blog 文章（300-400字）\n"
            "2) 一篇英文文章（約 180-250 words）\n\n"
            "⚠️ 重要準則（必須遵守）：\n"
            "1. 文章必須專注於單一主題，不要加入其他無關議題\n"
            "2. 必須基於下方提供的參考資料內容，不可憑空捏造事實\n"
            "3. 可以重組、摘要、改寫，但核心事實必須來自參考資料\n"
            f"4. 文章標題和內容必須圍繞「{main_keyword}」展開\n"
            "5. 保持客觀、專業的新聞報導風格\n"
            "6. 如果參考資料不足，請基於關鍵詞生成符合香港社會福利/醫療政策背景的專業內容（但仍不要編造具體數據與細節）\n\n"
            "---\n"
            "## 📰 參考新聞資料（中英並列）\n"
            f"{reference_content}\n\n"
            "---\n\n"
            "## 🎯 文章主題（唯一關鍵詞）\n"
            f"**{main_keyword}**\n\n"
            "---\n"
            "## 📤 輸出格式（只輸出 JSON，不要任何說明文字）\n"
            "請輸出 JSON 陣列，陣列只包含 1 個物件，格式如下：\n\n"
            "```json\n"
            "[\n"
            "  {\n"
            '    "zh": {\n'
            f'      "title": "中文標題（必須包含「{main_keyword}」）",\n'
            '      "body": "中文正文（繁體中文 300-400 字）",\n'
            f'      "meta_title": "中文SEO標題（60字內，必須包含「{main_keyword}」）",\n'
            '      "meta_description": "中文SEO摘要（150字內）"\n'
            "    },\n"
            '    "en": {\n'
            f'      "title": "English title (must include \\"{main_keyword}\\")",\n'
            '      "body": "English body (about 180-250 words)",\n'
            f'      "meta_title": "English SEO title (<=60 chars, must include \\"{main_keyword}\\")",\n'
            '      "meta_description": "English SEO description (<=150 chars)"\n'
            "    },\n"
            f'    "keywords": {json.dumps(chosen_keywords, ensure_ascii=False)}\n'
            "  }\n"
            "]\n"
            "```\n\n"
            "🔴 **重要提醒：**\n"
            f"- `keywords` 欄位必須完全使用：{json.dumps(chosen_keywords, ensure_ascii=False)}\n"
            "- 不可添加、修改或替換關鍵詞\n"
            "- 請確保 JSON 格式正確，可直接解析\n"
            "- 直接輸出 JSON 陣列，不要包含其他說明文字\n"
        )

        with lock:
            generated_prompts[timestamp].append({
                "index": article_index + 1,
                "keyword": main_keyword,
                "prompt": {"zh": prompt_zh},
                "source": source
            })

        output = call_deepseek(prompt_zh)

        with lock:
            progress_data["completed"] += 1

        return (article_index, output, chosen_keywords)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(generate_single_article, i) for i in range(total_articles)]
        for future in as_completed(futures):
            results.append(future.result())

    conn = get_db_connection()
    if not conn:
        print("❌ 無法連接資料庫，文章生成失敗")
        progress_data["running"] = False
        return

    try:
        cur = conn.cursor()
        all_articles = []

        for idx, output_text, chosen_kws in sorted(results, key=lambda x: x[0]):
            try:
                match = re.search(r'\[.*\]', output_text, re.S)
                parsed = json.loads(match.group(0)) if match else json.loads(output_text)

                if not isinstance(parsed, list):
                    parsed = [parsed]

                for item in parsed:
                    if item.get("keywords") != chosen_kws:
                        print(f"⚠️ AI 返回的關鍵詞不符，已強制使用：{chosen_kws}")
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
                        "keywords": item.get("keywords", chosen_kws)
                    }

                    record["title"] = record["title_zh"] or "未命名"
                    record["body"] = record["body_zh"] or ""
                    record["meta_title"] = record["meta_title_zh"] or ""
                    record["meta_description"] = record["meta_description_zh"] or ""

                    all_articles.append(record)

            except Exception as e:
                print(f"⚠️ 解析錯誤：{e}")
                print(f"原始輸出：{output_text[:400]}...")
                continue

        for art in all_articles:
            keywords_json = json.dumps(art.get("keywords", []), ensure_ascii=False)

            cur.execute("""
                INSERT INTO articles (
                    title, body, meta_title, meta_description, keywords, timestamp,
                    title_zh, body_zh, meta_title_zh, meta_description_zh,
                    title_en, body_en, meta_title_en, meta_description_en
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                art.get("title", "未命名"),
                art.get("body", ""),
                art.get("meta_title", ""),
                art.get("meta_description", ""),
                keywords_json,
                timestamp,
                art.get("title_zh", ""),
                art.get("body_zh", ""),
                art.get("meta_title_zh", ""),
                art.get("meta_description_zh", ""),
                art.get("title_en", ""),
                art.get("body_en", ""),
                art.get("meta_title_en", ""),
                art.get("meta_description_en", "")
            ))

            progress_data["titles"].append(art.get("title_zh") or art.get("title") or "未命名")

        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ 成功儲存 {len(all_articles)} 篇雙語文章到資料庫")

    except Exception as e:
        print(f"❌ 儲存文章失敗：{e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        progress_data["running"] = False


# ==========================================================
# Flask 路由
# ==========================================================
@app.route("/")
def index():
    return render_template("index.html")


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
    source = normalize_source(request.args.get("source", "swd"))
    force = (request.args.get("force", "0") == "1")

    with keywords_cache_lock:
        cached = keywords_cache.get(source, {}) or {}
        cached_keywords = cached.get("keywords") or []
        updated_at = cached.get("updated_at") or ""
        error = cached.get("error") or ""

    if force or not cached_keywords:
        cached_keywords = compute_and_store_keywords(source=source, days=7)
        with keywords_cache_lock:
            updated_at = keywords_cache[source].get("updated_at") or ""
            error = keywords_cache[source].get("error") or ""

    return jsonify({
        "source": source,
        "keywords": cached_keywords,
        "updated_at": updated_at,
        "error": error
    })


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


@app.route("/start_crawl_ha", methods=["POST"])
def start_crawl_ha():
    """啟動 HA 背景爬蟲"""
    if ha_crawl_progress["running"]:
        return jsonify({"success": False, "message": "HA 爬蟲正在執行中，請稍候..."})

    ha_crawl_progress.update({
        "total": 0,
        "completed": 0,
        "running": True,
        "status": "running",
        "message": "HA 爬蟲啟動中..."
    })

    threading.Thread(target=background_crawl_ha, kwargs={"days": 30}, daemon=True).start()
    return jsonify({"success": True, "message": "HA 爬蟲已啟動"})


@app.route("/crawl_progress_ha")
def get_crawl_progress_ha():
    """查詢 HA 爬蟲進度"""
    return jsonify(ha_crawl_progress)


@app.route("/generate_articles", methods=["POST"])
def generate_articles():
    selected_keywords = request.form.getlist("selected_keywords")
    source = normalize_source(request.form.get("source", "swd"))

    if not selected_keywords or len(selected_keywords) < 1:
        return "<h3>⚠️ 請至少選擇 1 個關鍵詞才能生成文章。</h3><a href='/keywords'>返回</a>"

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    threading.Thread(target=background_generate_articles, args=(selected_keywords, timestamp, source)).start()

    return render_template("generate.html")


@app.route("/progress")
def progress():
    return jsonify(progress_data)


@app.route("/get_prompts")
def get_prompts():
    """返回當前批次的 Prompts"""
    timestamp = progress_data.get("timestamp", "")
    prompts = generated_prompts.get(timestamp, [])
    prompts.sort(key=lambda x: x.get("index", 0))

    return jsonify({
        "timestamp": timestamp,
        "prompts": prompts
    })


# ==========================================================
# ✅ 文章管理路由
# ==========================================================
@app.route("/manage_articles")
def manage_articles():
    """管理資料庫中的文章"""
    ensure_database_initialized()

    conn = get_db_connection()
    if not conn:
        return "❌ 無法連接資料庫", 500

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM articles ORDER BY created_at DESC")
        articles = cur.fetchall()
        cur.close()
        conn.close()

        return render_template("manage_articles.html", articles=articles)
    except Exception as e:
        print(f"⚠️ 第一次查詢失敗，嘗試初始化：{e}")
        init_database()

        conn = get_db_connection()
        if not conn:
            return "❌ 無法連接資料庫", 500

        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM articles ORDER BY created_at DESC")
            articles = cur.fetchall()
            cur.close()
            conn.close()
            return render_template("manage_articles.html", articles=articles)
        except Exception as e2:
            return f"❌ 查詢失敗：{e2}<br><br>請檢查 DATABASE_URL 環境變數是否正確設定。", 500


@app.route("/delete_article/<int:article_id>", methods=["POST"])
def delete_article(article_id):
    """刪除單篇文章"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "無法連接資料庫"})

    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM articles WHERE id = %s", (article_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": "文章已刪除"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/batch_delete_articles", methods=["POST"])
def batch_delete_articles():
    """批量刪除文章"""
    try:
        data = request.get_json()
        article_ids = data.get("article_ids", [])

        if not article_ids:
            return jsonify({"success": False, "message": "未選擇任何文章"})

        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "message": "無法連接資料庫"})

        cur = conn.cursor()
        placeholders = ','.join(['%s'] * len(article_ids))
        query = f"DELETE FROM articles WHERE id IN ({placeholders})"
        cur.execute(query, article_ids)
        deleted_count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"成功刪除 {deleted_count} 篇文章"
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"批量刪除失敗：{str(e)}"})


@app.route("/view_article/<int:article_id>")
def view_article(article_id):
    """查看單篇文章詳情"""
    ensure_database_initialized()

    conn = get_db_connection()
    if not conn:
        return "❌ 無法連接資料庫", 500

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
        article = cur.fetchone()
        cur.close()
        conn.close()

        if not article:
            return "❌ 文章不存在", 404

        article_dict = dict(article)

        if article_dict.get('keywords'):
            try:
                if isinstance(article_dict['keywords'], str):
                    article_dict['keywords'] = json.loads(article_dict['keywords'])
            except (json.JSONDecodeError, TypeError):
                article_dict['keywords'] = []
        else:
            article_dict['keywords'] = []

        return render_template("view_article.html", article=article_dict)
    except Exception as e:
        return f"❌ 查詢失敗：{e}", 500


# ==========================================================
# ✅ 資料庫管理路由
# ==========================================================
@app.route("/init_db")
def manual_init_db():
    """手動初始化資料庫（管理用）"""
    try:
        init_database()
        return """
        <h2>✅ 資料庫初始化完成</h2>
        <p>資料表 'articles' 已創建或確認存在（已支援雙語欄位）。</p>
        <a href="/manage_articles">前往管理頁面</a>
        """
    except Exception as e:
        return f"❌ 初始化失敗：{e}", 500


@app.route("/test_db")
def test_db():
    """測試資料庫連接"""
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
        conn.close()

        return f"""
        <h2>✅ 資料庫連接成功</h2>
        <p><strong>PostgreSQL 版本：</strong>{version}</p>
        <p><strong>現有資料表：</strong>{', '.join([t[0] for t in tables]) if tables else '無'}</p>
        <br>
        <a href="/init_db">初始化資料表</a> | 
        <a href="/manage_articles">管理文章</a>
        """
    except Exception as e:
        return f"❌ 測試失敗：{e}", 500


# ==========================================================
# 啟動伺服器
# ==========================================================
if __name__ == "__main__":
    print("📂 SWD 爬蟲資料夾:", CRAWLER_DIR)
    print("📂 HA 爬蟲資料夾:", HA_CRAWLER_DIR)
    print("🗄️ 初始化資料庫...")
    init_database()
    print("🚀 Flask 啟動中...")
    app.run(debug=True)
