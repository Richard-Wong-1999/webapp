"""
SWD 爬蟲函數（從原 app.py 提取）
之後應該移到 services/crawler_service.py 或 crawler/swd_crawler.py
"""

import os
import json
import re
import threading
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import requests
import trafilatura

from config import Config
from utils.logger import logger
from utils.text_processing import parse_ymd_date, make_safe_filename, derive_date_from_text_zh
from services.keyword_extractor import compute_and_store_keywords

# SWD 爬虫进度资讯
crawl_progress = {
    "total": 0,
    "completed": 0,
    "running": False,
    "status": "idle",
    "message": ""
}

INFOGOV_HOST = Config.INFOGOV_HOST


def strip_query(url: str) -> str:
    """移除 query string"""
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


def fetch_swd_list(list_url: str, days: int = 30):
    html = fetch_html(list_url, timeout=30)
    soup = BeautifulSoup(html, "lxml")
    rows = soup.find_all("tr")
    press_list = []

    today = datetime.now().date()
    cutoff = today - timedelta(days=days)

    for row in rows:
        tds = row.find_all("td")
        if len(tds) >= 2:
            date_text = tds[0].get_text(strip=True)
            d = parse_ymd_date(date_text)
            if not d:
                continue

            if d < cutoff:
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

        days = Config.SWD_CRAWL_DAYS

        os.makedirs(Config.SWD_DIR, exist_ok=True)

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
                "message": f"沒有找到近 {days} 天新聞資料"
            })
            # 即使沒資料，也更新一次 keywords cache
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
                filepath = os.path.join(Config.SWD_DIR, filename)

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
                logger.warning(f"⚠️ 處理 {swd_title} 時出錯：{e}")
                continue

        crawl_progress.update({
            "running": False,
            "status": "completed",
            "message": f"✅ 完成！已輸出 {merged_count} 份中英對照 JSON（近 {days} 天 SWD 列表）。"
        })

        # 爬完立刻更新 SWD keywords cache
        compute_and_store_keywords("swd", days=7)

    except Exception as e:
        crawl_progress.update({
            "running": False,
            "status": "error",
            "message": f"爬蟲執行錯誤：{str(e)}"
        })
        logger.error(f"❌ 爬蟲錯誤：{e}")
