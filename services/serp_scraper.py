"""SERP 網站內容爬蟲服務

使用 requests + BeautifulSoup 爬取 SERP 排名網站內容
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import Config
from utils.logger import logger


# 預設 User-Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 需要跳過的域名（可能有反爬蟲機制或內容不適合提取）
SKIP_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "youtube.com",
    "linkedin.com",
    "tiktok.com",
    "reddit.com"
}

# 需要移除的標籤（通常包含非主要內容）
REMOVE_TAGS = [
    "script", "style", "nav", "header", "footer",
    "aside", "noscript", "iframe", "form", "button"
]


def should_skip_url(url: str) -> bool:
    """檢查是否應跳過此 URL"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        for skip_domain in SKIP_DOMAINS:
            if skip_domain in domain:
                return True

        # 跳過非 HTTP(S) 連結
        if parsed.scheme not in ("http", "https"):
            return True

        # 跳過檔案連結
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"]):
            return True

        return False

    except Exception:
        return True


def extract_main_content(soup: BeautifulSoup) -> str:
    """從 BeautifulSoup 物件提取主要內容

    Args:
        soup: BeautifulSoup 物件

    Returns:
        提取的主要內容文字
    """
    # 移除不需要的標籤
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    # 嘗試找到主要內容區域
    main_content = None

    # 常見的主要內容選擇器
    content_selectors = [
        "article",
        "main",
        "[role='main']",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".content-body",
        ".article-body",
        "#content",
        ".content"
    ]

    for selector in content_selectors:
        element = soup.select_one(selector)
        if element:
            main_content = element
            break

    # 如果找不到主要內容區域，使用 body
    if not main_content:
        main_content = soup.find("body")

    if not main_content:
        return ""

    # 提取文字
    text = main_content.get_text(separator="\n", strip=True)

    # 清理文字
    # 移除多餘的空白行
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)

    # 移除過短的行（可能是選單項目等）
    lines = [line for line in text.split("\n") if len(line) > 20 or re.search(r'[\u4e00-\u9fff]', line)]
    text = "\n".join(lines)

    return text


def scrape_url(
    url: str,
    timeout: int = None
) -> Dict[str, Any]:
    """爬取單一 URL 的內容

    Args:
        url: 目標 URL
        timeout: 請求超時秒數

    Returns:
        {
            "url": str,
            "title": str,
            "meta_description": str,
            "main_content": str,
            "word_count": int,
            "success": bool,
            "error": str (if failed)
        }
    """
    if timeout is None:
        timeout = getattr(Config, 'SCRAPE_TIMEOUT', 10)

    result = {
        "url": url,
        "title": "",
        "meta_description": "",
        "main_content": "",
        "word_count": 0,
        "success": False,
        "error": None
    }

    if should_skip_url(url):
        result["error"] = "URL skipped (blocked domain or invalid)"
        return result

    try:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()

        # 檢查內容類型
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            result["error"] = f"Invalid content type: {content_type}"
            return result

        # 嘗試正確解碼
        response.encoding = response.apparent_encoding or "utf-8"
        html_content = response.text

        # 解析 HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # 提取標題
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else ""

        # 提取 meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            result["meta_description"] = meta_desc.get("content", "")

        # 提取主要內容
        main_content = extract_main_content(soup)
        result["main_content"] = main_content

        # 計算字數（中文+英文單詞）
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', main_content))
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', main_content))
        result["word_count"] = chinese_chars + english_words

        result["success"] = True
        logger.info(f"Successfully scraped: {url} ({result['word_count']} words)")

    except requests.exceptions.Timeout:
        result["error"] = "Request timeout"
        logger.warning(f"Scrape timeout: {url}")

    except requests.exceptions.HTTPError as e:
        result["error"] = f"HTTP error: {e.response.status_code}"
        logger.warning(f"Scrape HTTP error: {url} - {e}")

    except requests.exceptions.RequestException as e:
        result["error"] = f"Request error: {str(e)}"
        logger.warning(f"Scrape request error: {url} - {e}")

    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"
        logger.error(f"Scrape unexpected error: {url} - {e}")

    return result


def scrape_serp_urls(
    urls: List[str],
    max_concurrent: int = None,
    delay_between: float = 0.5
) -> List[Dict[str, Any]]:
    """並發爬取多個 URL

    Args:
        urls: URL 列表
        max_concurrent: 最大並發數
        delay_between: 每個請求之間的延遲（秒）

    Returns:
        爬取結果列表
    """
    if max_concurrent is None:
        max_concurrent = getattr(Config, 'SCRAPE_MAX_CONCURRENT', 3)

    if not urls:
        return []

    results = []
    processed_urls = set()

    # 去重
    unique_urls = []
    for url in urls:
        if url not in processed_urls:
            processed_urls.add(url)
            unique_urls.append(url)

    logger.info(f"Starting to scrape {len(unique_urls)} URLs with {max_concurrent} workers")

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        # 提交所有任務
        future_to_url = {}
        for i, url in enumerate(unique_urls):
            # 添加延遲以避免過快請求
            if i > 0:
                time.sleep(delay_between)
            future = executor.submit(scrape_url, url)
            future_to_url[future] = url

        # 收集結果
        for future in as_completed(future_to_url):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                url = future_to_url[future]
                results.append({
                    "url": url,
                    "title": "",
                    "meta_description": "",
                    "main_content": "",
                    "word_count": 0,
                    "success": False,
                    "error": str(e)
                })

    # 按原始順序排序
    url_order = {url: i for i, url in enumerate(unique_urls)}
    results.sort(key=lambda x: url_order.get(x["url"], len(unique_urls)))

    success_count = sum(1 for r in results if r["success"])
    logger.info(f"Scraping completed: {success_count}/{len(results)} successful")

    return results


def summarize_content(content: str, max_length: int = 500) -> str:
    """摘要化內容

    Args:
        content: 原始內容
        max_length: 最大長度

    Returns:
        摘要內容
    """
    if not content:
        return ""

    # 取前 N 個字元
    if len(content) <= max_length:
        return content

    # 在 max_length 附近找到合適的斷點
    truncated = content[:max_length]

    # 嘗試在句號、問號、驚嘆號處截斷
    last_sentence_end = max(
        truncated.rfind("。"),
        truncated.rfind("！"),
        truncated.rfind("？"),
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? ")
    )

    if last_sentence_end > max_length * 0.5:
        return truncated[:last_sentence_end + 1]

    # 在空白處截斷
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.7:
        return truncated[:last_space] + "..."

    return truncated + "..."
