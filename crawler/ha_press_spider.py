from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

import fitz  # PyMuPDF
from zoneinfo import ZoneInfo


BASE_URL = "https://www.ha.org.hk/"

DEFAULT_DAYS = 30
DEFAULT_MAX_PAGES = 200
DEFAULT_MAX_ITEMS = 500
DEFAULT_SLEEP = 0.3

# 中文列表/內頁用 CHIB5（繁體 Big5）；英文用 ENG
LANG_ZH = "CHIB5"
LANG_EN = "ENG"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 "
    "HA-PressRelease-Scraper/2.8",
    "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.6",
}

ProgressCb = Optional[Callable[[dict], None]]


@dataclass(frozen=True)
class ListItem:
    title: str
    published: date
    link_url: str
    content_id: Optional[str] = None


@dataclass
class Result:
    title: str
    published: str
    list_link_url: str

    pdf_url_zh: Optional[str] = None
    pdf_url_en: Optional[str] = None

    pdf_path_zh: Optional[str] = None
    pdf_path_en: Optional[str] = None

    json_path_bilingual: Optional[str] = None


# -----------------------------
# URL / HTTP helpers
# -----------------------------


def ensure_lang(url: str, lang: str) -> str:
    """確保 URL query 有 Lang=...（如原本有就覆蓋）。"""
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q["Lang"] = lang
    new_query = urlencode(q, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))


def decode_maybe_big5(resp: requests.Response) -> str:
    raw = resp.content
    if resp.encoding:
        try:
            return raw.decode(resp.encoding, errors="strict")
        except Exception:
            pass
    for enc in ("big5hkscs", "cp950", "big5", "utf-8"):
        try:
            return raw.decode(enc, errors="strict")
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def http_get_html(session: requests.Session, url: str) -> str:
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return decode_maybe_big5(r)


def http_post_html(session: requests.Session, url: str, data: dict) -> str:
    r = session.post(url, headers=HEADERS, data=data, timeout=30)
    r.raise_for_status()
    return decode_maybe_big5(r)


# -----------------------------
# Parsing / extraction
# -----------------------------


def extract_pdf_url_from_text(s: str) -> Optional[str]:
    if not s:
        return None
    m = re.search(r"(https?://[^\s\"']+?\.pdf|/[^\s\"']+?\.pdf)", s, flags=re.IGNORECASE)
    return m.group(1) if m else None


def parse_dd_mm_yyyy(s: str) -> Optional[date]:
    s = s.strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if not m:
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


def extract_content_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"[?&]Content_ID=(\d+)", url)
    return m.group(1) if m else None


def safe_filename(name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("_")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def classify_pdf_lang(url: str) -> Optional[str]:
    """用 URL 字眼粗略判斷 PDF 屬中文定英文。"""
    u = url.lower()
    # 常見：..._c.pdf / ..._e.pdf、chi/eng、chib5/eng
    if re.search(r"(^|[_-])c\.pdf$", u) or "chib5" in u or "chi" in u or "tc" in u:
        return "zh"
    if re.search(r"(^|[_-])e\.pdf$", u) or "eng" in u:
        return "en"
    return None


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    parts = [page.get_text("text") for page in doc]
    doc.close()
    lines = []
    for ln in "\n".join(parts).splitlines():
        t = ln.strip()
        if t:
            lines.append(t)
    return "\n".join(lines)


def split_paragraphs(text: str) -> list[str]:
    """
    以空行分段（同時兼容 PDF 抽出嚟好多單行的情況）：
    - 先按空行切段
    - 段內再合併多行成一段（用空格連）
    """
    if not text:
        return []
    raw_paras = re.split(r"\n\s*\n+", text.strip())
    paras: list[str] = []
    for p in raw_paras:
        lines = [ln.strip() for ln in p.splitlines() if ln.strip()]
        if not lines:
            continue
        paras.append(" ".join(lines))
    return paras


def make_bilingual_pairs(zh_text: str, en_text: str) -> list[dict]:
    """
    回傳：
    [
      {"index": 1, "zh": "...", "en": "..."},
      ...
    ]
    """
    zh_paras = split_paragraphs(zh_text)
    en_paras = split_paragraphs(en_text)
    n = max(len(zh_paras), len(en_paras))

    pairs: list[dict] = []
    for i in range(n):
        pairs.append(
            {
                "index": i + 1,
                "zh": zh_paras[i] if i < len(zh_paras) else "",
                "en": en_paras[i] if i < len(en_paras) else "",
            }
        )
    return pairs


def make_bilingual_json_obj(
    *,
    title: str,
    published: str,
    content_id: Optional[str],
    list_link_url: str,
    pdf_url_zh: Optional[str],
    pdf_url_en: Optional[str],
    pairs: list[dict],
) -> dict:
    return {
        "schema": "ha_press_release_bilingual_v1",
        "title": title,
        "published": published,  # ISO date string
        "content_id": content_id,
        "list_link_url": list_link_url,
        "pdf_url_zh": pdf_url_zh,
        "pdf_url_en": pdf_url_en,
        "paragraph_count": len(pairs),
        "paragraphs": pairs,
    }


def download_single_pdf(session: requests.Session, url: str, path: Path, sleep_time: float) -> bool:
    """下載單個 PDF（用於並行下載）

    Args:
        session: requests Session
        url: PDF URL
        path: 儲存路徑
        sleep_time: 下載後的等待時間

    Returns:
        是否成功
    """
    if not url or not path:
        return False
    try:
        r = session.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
        time.sleep(sleep_time)
        return True
    except Exception:
        return False


# -----------------------------
# List page scraping
# -----------------------------


def parse_list_page(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []

    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if not text or "Title" in text or "Release Date" in text or "主題" in text or "日期" in text:
            continue

        dt = None
        for cell in tr.find_all(["td", "th"]):
            maybe = parse_dd_mm_yyyy(cell.get_text(strip=True))
            if maybe:
                dt = maybe
                break
        if not dt:
            continue

        a = tr.find("a")
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        href = a.get("href", "") or ""
        onclick = a.get("onclick", "") or ""

        link = href or extract_pdf_url_from_text(onclick) or ""
        if not link:
            continue

        link_url = urljoin(BASE_URL, link)
        content_id = extract_content_id_from_url(link_url)

        items.append(ListItem(title=title, published=dt, link_url=link_url, content_id=content_id))

    return items


def scrape_recent_list_items(
    session: requests.Session,
    days: int,
    max_pages: int = DEFAULT_MAX_PAGES,
    sleep: float = 0.2,
    debug_dir: Optional[Path] = None,
) -> list[ListItem]:
    tz = ZoneInfo("Asia/Hong_Kong")
    today = datetime.now(tz).date()
    cutoff = today - timedelta(days=days)

    all_items: list[ListItem] = []
    seen_keys: set[str] = set()

    post_url = urljoin(BASE_URL, "/visitor/template114.asp")

    base_form = {
        "RadioCategory": "simple",
        "is_using_filter": "0",
        "is_a_new_submit_search": "0",
        "content_ID": "643",
        "strOldStartDate": "",
        "strOldEndDate": "",
        "hidden_s_dd": "",
        "hidden_s_mm": "",
        "hidden_s_yyyy": "",
        "hidden_e_dd": "",
        "hidden_e_mm": "",
        "hidden_e_yyyy": "",
        "page_size": "10",
        "Lang": LANG_ZH,  # 用中文列表較穩定
    }

    for page in range(1, max_pages + 1):
        form = dict(base_form)
        form["page_number"] = str(page)

        html = http_post_html(session, post_url, data=form)

        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"list_page_{page:02d}.html").write_text(html, encoding="utf-8")

        items = parse_list_page(html)
        if not items:
            break

        page_dates = [it.published for it in items]
        min_dt = min(page_dates)
        max_dt = max(page_dates)

        new_count = 0
        for it in items:
            key = it.content_id or f"{it.published.isoformat()}|{it.title}|{it.link_url}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_items.append(it)
            new_count += 1

        if max_dt < cutoff:
            break

        time.sleep(sleep)

    recent = [x for x in all_items if x.published >= cutoff]
    recent.sort(key=lambda x: x.published, reverse=True)
    return recent


# -----------------------------
# PDF URL resolving (bilingual)
# -----------------------------


def resolve_pdf_urls_bilingual(session: requests.Session, link_url: str) -> tuple[Optional[str], Optional[str]]:
    """
    回傳 (pdf_zh, pdf_en)。
    1) 如果 link 本身係 pdf：只會當作未知語言，會試圖用規則判斷 zh/en
    2) 如果係內頁：搜集所有 pdf link，分類後揀 zh/en 各一
    3) 分類失敗：用 Lang=CHIB5/ENG 再入一次內頁嘗試（某些頁語言會影響連結）
    """

    def parse_pdf_links_from_html(html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        pdfs: list[str] = []
        for a in soup.find_all("a"):
            href = a.get("href", "") or ""
            onclick = a.get("onclick", "") or ""
            pdf = extract_pdf_url_from_text(href) or extract_pdf_url_from_text(onclick)
            if pdf:
                pdfs.append(urljoin(BASE_URL, pdf))
        if not pdfs:
            pdf = extract_pdf_url_from_text(html)
            if pdf:
                pdfs.append(urljoin(BASE_URL, pdf))
        out: list[str] = []
        seen = set()
        for u in pdfs:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def classify(pdfs: list[str]) -> tuple[Optional[str], Optional[str]]:
        zh = en = None
        for u in pdfs:
            lang = classify_pdf_lang(u)
            if lang == "zh" and zh is None:
                zh = u
            elif lang == "en" and en is None:
                en = u
        if zh is None or en is None:
            for u in pdfs:
                if u == zh or u == en:
                    continue
                if zh is None and (classify_pdf_lang(u) != "en"):
                    zh = zh or u
                elif en is None and (classify_pdf_lang(u) != "zh"):
                    en = en or u
        return zh, en

    if link_url.lower().endswith(".pdf"):
        u = link_url
        lang = classify_pdf_lang(u)
        if lang == "zh":
            return u, None
        if lang == "en":
            return None, u
        return u, None

    html0 = http_get_html(session, link_url)
    pdfs0 = parse_pdf_links_from_html(html0)
    zh0, en0 = classify(pdfs0)

    if zh0 and en0:
        return zh0, en0

    link_zh = ensure_lang(link_url, LANG_ZH)
    link_en = ensure_lang(link_url, LANG_EN)

    html_zh = http_get_html(session, link_zh) if link_zh != link_url else html0
    html_en = http_get_html(session, link_en) if link_en != link_url else html0

    pdfs = []
    pdfs.extend(parse_pdf_links_from_html(html_zh))
    pdfs.extend(parse_pdf_links_from_html(html_en))

    uniq = []
    seen = set()
    for u in pdfs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)

    zh, en = classify(uniq)
    zh = zh or zh0
    en = en or en0
    return zh, en


# -----------------------------
# Public entry for Flask
# -----------------------------


def run_ha_crawl(
    *,
    out_dir: str | Path,
    days: int = DEFAULT_DAYS,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    sleep: float = DEFAULT_SLEEP,
    overwrite: bool = True,
    progress_cb: ProgressCb = None,
    enable_debug_html: bool = True,
    stop_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """
    供 Flask 呼叫的 HA 爬蟲。
    會輸出：
      - {out_dir}/pdfs/*.pdf
      - {out_dir}/*.json  （每篇 bilingual JSON，檔名：{prefix}_bilingual.json）
      - {out_dir}/press_releases_recent.json（摘要清單）
      - (可選) {out_dir}/debug/list_page_XX.html
    """
    out_dir = Path(out_dir)
    pdf_dir = out_dir / "pdfs"
    debug_dir = out_dir / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    if enable_debug_html:
        debug_dir.mkdir(parents=True, exist_ok=True)

    def report(payload: dict):
        if progress_cb:
            progress_cb(payload)

    session = requests.Session()

    report({"status": "running", "phase": "list", "message": "正在抓取 HA 新聞稿列表..."})
    items = scrape_recent_list_items(
        session=session,
        days=days,
        max_pages=max_pages,
        sleep=0.2,
        debug_dir=(debug_dir if enable_debug_html else None),
    )
    items = items[:max_items]

    report(
        {
            "status": "running",
            "phase": "download",
            "total": len(items),
            "completed": 0,
            "message": f"列表共 {len(items)} 筆（最近 {days} 天），開始解析 PDF（中英）並輸出 JSON...",
        }
    )

    results: list[Result] = []

    for i, it in enumerate(items, start=1):
        # 檢查是否被停止
        if stop_check and stop_check():
            report({
                "status": "stopped",
                "phase": "download",
                "total": len(items),
                "completed": i - 1,
                "message": f"已停止。已處理 {i-1}/{len(items)} 筆。",
            })
            return {"count": i - 1, "out_dir": str(out_dir), "stopped": True}

        report(
            {
                "status": "running",
                "phase": "download",
                "total": len(items),
                "completed": i,
                "message": f"[{i}/{len(items)}] {it.published.isoformat()} | {it.title}",
            }
        )

        pdf_zh_url, pdf_en_url = resolve_pdf_urls_bilingual(session, it.link_url)

        prefix = it.content_id or it.published.isoformat()
        pdf_path_zh: Optional[Path] = None
        pdf_path_en: Optional[Path] = None

        if pdf_zh_url:
            base = safe_filename(pdf_zh_url.split("/")[-1] or f"{prefix}_zh.pdf")
            name = f"{prefix}_ZH_{base}"
            pdf_path_zh = pdf_dir / name

        if pdf_en_url:
            base = safe_filename(pdf_en_url.split("/")[-1] or f"{prefix}_en.pdf")
            name = f"{prefix}_EN_{base}"
            pdf_path_en = pdf_dir / name

        # ✅ 每篇 bilingual JSON 直接放在 out_dir（符合你想要：webapp/crawler/ha_press/*.json）
        json_path = out_dir / f"{prefix}_bilingual.json"

        # 下載 PDFs（並行下載中英文版本）
        with ThreadPoolExecutor(max_workers=2) as pdf_executor:
            futures = []
            if pdf_zh_url and pdf_path_zh and (overwrite or not pdf_path_zh.exists()):
                futures.append(pdf_executor.submit(
                    download_single_pdf, session, pdf_zh_url, pdf_path_zh, sleep / 2
                ))
            if pdf_en_url and pdf_path_en and (overwrite or not pdf_path_en.exists()):
                futures.append(pdf_executor.submit(
                    download_single_pdf, session, pdf_en_url, pdf_path_en, sleep / 2
                ))
            # 等待所有下載完成
            for f in futures:
                f.result()

        # 抽字 + 產生 bilingual JSON
        if overwrite or (not json_path.exists()):
            zh_text = extract_pdf_text(pdf_path_zh) if (pdf_path_zh and pdf_path_zh.exists()) else ""
            en_text = extract_pdf_text(pdf_path_en) if (pdf_path_en and pdf_path_en.exists()) else ""

            pairs = make_bilingual_pairs(zh_text, en_text)
            obj = make_bilingual_json_obj(
                title=it.title,
                published=it.published.isoformat(),
                content_id=it.content_id,
                list_link_url=it.link_url,
                pdf_url_zh=pdf_zh_url,
                pdf_url_en=pdf_en_url,
                pairs=pairs,
            )
            json_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

        results.append(
            Result(
                title=it.title,
                published=it.published.isoformat(),
                list_link_url=it.link_url,
                pdf_url_zh=pdf_zh_url,
                pdf_url_en=pdf_en_url,
                pdf_path_zh=str(pdf_path_zh) if pdf_path_zh else None,
                pdf_path_en=str(pdf_path_en) if pdf_path_en else None,
                json_path_bilingual=str(json_path),
            )
        )

    out_json = out_dir / "press_releases_recent.json"
    out_json.write_text(
        json.dumps([asdict(x) for x in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report({"status": "completed", "phase": "done", "message": f"✅ HA 爬蟲完成：輸出 {len(results)} 篇 JSON"})
    return {"count": len(results), "out_dir": str(out_dir)}
