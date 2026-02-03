"""智能深度爬蟲模組

實現智能深度爬取功能：
1. 追蹤 SERP 頁面內的相關內部連結
2. 使用關鍵字相關性評分過濾不相關的連結
3. 控制爬取深度和資源使用
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Any, Callable
from urllib.parse import urlparse, urljoin
from collections import defaultdict

from bs4 import BeautifulSoup

from config import Config
from utils.logger import logger
from services.serp_scraper import scrape_url, should_skip_url, DEFAULT_USER_AGENT

import requests


@dataclass
class DeepCrawlConfig:
    """深度爬取配置"""
    max_depth: int = 2                    # 最大深度（SERP 頁面 + 內部連結）
    max_pages_per_domain: int = 5         # 每個域名最多頁數
    max_total_pages: int = 30             # 總頁面上限
    min_relevance_score: float = 0.3      # 最低相關性分數
    timeout_per_page: int = 10            # 單頁超時（秒）
    total_timeout: int = 300              # 總超時（秒）
    delay_between_requests: float = 0.5   # 請求間延遲（秒）
    max_links_per_page: int = 20          # 每頁最多提取連結數


@dataclass
class CrawledPage:
    """爬取的頁面結果"""
    url: str
    title: str = ""
    meta_description: str = ""
    main_content: str = ""
    word_count: int = 0
    depth: int = 0
    relevance_score: float = 0.0
    quality_score: float = 0.0
    combined_score: float = 0.0
    success: bool = False
    error: Optional[str] = None
    source_url: Optional[str] = None  # 來源頁面 URL
    internal_links: List[Dict] = field(default_factory=list)


# 應跳過的 URL 模式（導航頁、標籤頁等）
SKIP_URL_PATTERNS = [
    r'/tag/',
    r'/tags/',
    r'/category/',
    r'/categories/',
    r'/author/',
    r'/authors/',
    r'/page/\d+',
    r'/login',
    r'/logout',
    r'/cart',
    r'/checkout',
    r'/account',
    r'/register',
    r'/signup',
    r'/search',
    r'\?page=',
    r'\?p=\d+',
    r'/wp-admin',
    r'/admin',
    r'#',  # 錨點連結
]

# 優選的 URL 模式（文章、博客等）
PREFERRED_URL_PATTERNS = [
    r'/article/',
    r'/articles/',
    r'/blog/',
    r'/post/',
    r'/posts/',
    r'/news/',
    r'/guide/',
    r'/guides/',
    r'/tutorial/',
    r'/tutorials/',
    r'/how-to/',
    r'/learn/',
    r'/resources/',
]


def should_skip_link(url: str) -> bool:
    """檢查是否應跳過此連結"""
    url_lower = url.lower()
    for pattern in SKIP_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True
    return False


def is_preferred_url(url: str) -> bool:
    """檢查是否為優選 URL 模式"""
    url_lower = url.lower()
    for pattern in PREFERRED_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True
    return False


def get_url_depth(url: str) -> int:
    """計算 URL 的路徑深度"""
    try:
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if not path:
            return 0
        return len(path.split('/'))
    except Exception:
        return 0


def normalize_url(url: str) -> str:
    """標準化 URL（移除錨點和尾部斜線）"""
    try:
        parsed = urlparse(url)
        # 移除錨點
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        # 移除尾部斜線（但保留根路徑）
        if normalized.endswith('/') and len(parsed.path) > 1:
            normalized = normalized.rstrip('/')
        return normalized
    except Exception:
        return url


class DeepCrawler:
    """智能深度爬蟲"""

    def __init__(self, config: DeepCrawlConfig = None, stop_check: Optional[Callable[[], bool]] = None):
        """
        初始化深度爬蟲

        Args:
            config: 爬取配置，若為 None 則使用預設值
            stop_check: 停止檢查回調，返回 True 時停止爬取
        """
        self.config = config or DeepCrawlConfig()
        self.visited_urls: Set[str] = set()
        self.domain_page_count: Dict[str, int] = defaultdict(int)
        self.total_pages_crawled: int = 0
        self.start_time: float = 0
        self.keywords: List[str] = []
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        self.stop_check: Optional[Callable[[], bool]] = stop_check

    def crawl_with_depth(
        self,
        seed_urls: List[str],
        keywords: List[str],
        max_results: int = 20,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[CrawledPage]:
        """
        從種子 URLs 開始深度爬取

        Args:
            seed_urls: 種子 URL 列表（通常來自 SERP 結果）
            keywords: 關鍵字列表（用於計算相關性）
            max_results: 返回的最大結果數
            progress_callback: 進度回調函數，接收 (pages_crawled, total_pages, current_url)

        Returns:
            按綜合分數排序的爬取頁面列表
        """
        self.start_time = time.time()
        self.visited_urls.clear()
        self.domain_page_count.clear()
        self.total_pages_crawled = 0
        self.keywords = [k.lower() for k in keywords]
        self.progress_callback = progress_callback

        all_results: List[CrawledPage] = []

        # 深度 0：爬取種子頁面
        logger.info(f"Deep crawl starting with {len(seed_urls)} seed URLs, keywords: {keywords}")

        depth_0_results = self._crawl_urls_at_depth(seed_urls, depth=0)
        all_results.extend(depth_0_results)

        # 檢查是否已達限制或超時
        if self._should_stop():
            logger.info("Deep crawl stopped after depth 0")
            return self._finalize_results(all_results, max_results)

        # 深度 1：爬取相關內部連結
        if self.config.max_depth >= 2:
            depth_1_urls = self._collect_relevant_links(depth_0_results)
            if depth_1_urls:
                logger.info(f"Crawling {len(depth_1_urls)} depth-1 URLs")
                depth_1_results = self._crawl_urls_at_depth(depth_1_urls, depth=1)
                all_results.extend(depth_1_results)

        logger.info(f"Deep crawl completed: {len(all_results)} pages crawled")
        return self._finalize_results(all_results, max_results)

    def _crawl_urls_at_depth(
        self,
        urls: List[str],
        depth: int
    ) -> List[CrawledPage]:
        """
        爬取指定深度的 URLs

        Args:
            urls: URL 列表
            depth: 當前深度

        Returns:
            爬取結果列表
        """
        results = []
        urls_to_crawl = []

        # 過濾已訪問和已達限制的 URL
        for url in urls:
            normalized = normalize_url(url)
            if normalized in self.visited_urls:
                continue

            domain = urlparse(url).netloc
            if self.domain_page_count[domain] >= self.config.max_pages_per_domain:
                continue

            if self.total_pages_crawled >= self.config.max_total_pages:
                break

            urls_to_crawl.append(url)
            self.visited_urls.add(normalized)

        if not urls_to_crawl:
            return results

        # 並發爬取
        max_workers = getattr(Config, 'SCRAPE_MAX_CONCURRENT', 3)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {}
            for i, url in enumerate(urls_to_crawl):
                if self._should_stop():
                    break
                if i > 0:
                    time.sleep(self.config.delay_between_requests)
                future = executor.submit(
                    self._crawl_single_page,
                    url,
                    depth
                )
                future_to_url[future] = url

            for future in as_completed(future_to_url):
                try:
                    result = future.result()
                    if result:
                        domain = urlparse(result.url).netloc
                        self.domain_page_count[domain] += 1
                        self.total_pages_crawled += 1
                        results.append(result)

                        # 調用進度回調
                        if self.progress_callback:
                            try:
                                self.progress_callback(
                                    self.total_pages_crawled,
                                    self.config.max_total_pages,
                                    result.url
                                )
                            except Exception as cb_err:
                                logger.warning(f"Progress callback error: {cb_err}")
                except Exception as e:
                    url = future_to_url[future]
                    logger.error(f"Error crawling {url}: {e}")

        return results

    def _crawl_single_page(
        self,
        url: str,
        depth: int,
        source_url: str = None
    ) -> Optional[CrawledPage]:
        """
        爬取單一頁面並提取內部連結

        Args:
            url: 目標 URL
            depth: 當前深度
            source_url: 來源頁面 URL

        Returns:
            CrawledPage 物件或 None
        """
        try:
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }

            response = requests.get(
                url,
                headers=headers,
                timeout=self.config.timeout_per_page,
                allow_redirects=True
            )
            response.raise_for_status()

            # 檢查內容類型
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type.lower():
                return None

            response.encoding = response.apparent_encoding or "utf-8"
            html_content = response.text

            # 解析 HTML
            soup = BeautifulSoup(html_content, "html.parser")

            # 在移除導航元素之前提取內部連結
            internal_links = []
            if depth < self.config.max_depth - 1:
                internal_links = self._extract_internal_links(soup, url)

            # 提取標題
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

            # 提取 meta description
            meta_desc = soup.find("meta", attrs={"name": "description"})
            meta_description = meta_desc.get("content", "") if meta_desc else ""

            # 移除不需要的元素後提取主要內容
            for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
                tag.decompose()

            main_content = self._extract_main_content(soup)

            # 計算字數
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', main_content))
            english_words = len(re.findall(r'\b[a-zA-Z]+\b', main_content))
            word_count = chinese_chars + english_words

            # 計算分數
            content_relevance = self._calculate_content_relevance(title, main_content)
            quality_score = self._calculate_quality_score(
                title, meta_description, main_content, word_count
            )
            combined_score = (content_relevance * 0.6) + (quality_score * 0.4)

            result = CrawledPage(
                url=url,
                title=title,
                meta_description=meta_description,
                main_content=main_content,
                word_count=word_count,
                depth=depth,
                relevance_score=content_relevance,
                quality_score=quality_score,
                combined_score=combined_score,
                success=True,
                source_url=source_url,
                internal_links=internal_links
            )

            logger.info(f"Crawled: {url} (depth={depth}, relevance={content_relevance:.2f}, quality={quality_score:.2f})")
            return result

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout crawling: {url}")
            return CrawledPage(url=url, depth=depth, error="Timeout")

        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error crawling {url}: {e}")
            return CrawledPage(url=url, depth=depth, error=f"HTTP {e.response.status_code}")

        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            return CrawledPage(url=url, depth=depth, error=str(e))

    def _extract_internal_links(
        self,
        soup: BeautifulSoup,
        base_url: str
    ) -> List[Dict]:
        """
        提取頁面內的同域名連結

        Args:
            soup: BeautifulSoup 物件
            base_url: 基礎 URL

        Returns:
            內部連結列表 [{"url": str, "anchor_text": str, "context": str, "relevance": float}]
        """
        links = []
        seen_urls = set()
        base_domain = urlparse(base_url).netloc

        # 找到所有錨點標籤
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '').strip()
            if not href:
                continue

            # 解析並標準化 URL
            try:
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)

                # 只處理同域名的 HTTP(S) 連結
                if parsed.scheme not in ('http', 'https'):
                    continue
                if parsed.netloc != base_domain:
                    continue

                normalized = normalize_url(full_url)
                if normalized in seen_urls:
                    continue
                if should_skip_url(full_url) or should_skip_link(full_url):
                    continue

                seen_urls.add(normalized)

                # 提取錨點文字
                anchor_text = a_tag.get_text(strip=True)

                # 提取周圍上下文（父元素的文字）
                context = ""
                parent = a_tag.parent
                if parent:
                    context = parent.get_text(strip=True)[:200]

                # 計算連結相關性
                relevance = self._calculate_link_relevance(
                    full_url, anchor_text, context, base_url
                )

                links.append({
                    "url": full_url,
                    "anchor_text": anchor_text,
                    "context": context,
                    "relevance": relevance
                })

                if len(links) >= self.config.max_links_per_page:
                    break

            except Exception as e:
                logger.debug(f"Error processing link {href}: {e}")
                continue

        # 按相關性排序
        links.sort(key=lambda x: x["relevance"], reverse=True)
        return links

    def _calculate_link_relevance(
        self,
        url: str,
        anchor_text: str,
        context: str,
        parent_url: str
    ) -> float:
        """
        計算連結相關性分數

        評分標準：
        - 基礎分: 0.0
        - +0.4: 關鍵字出現在 URL 中
        - +0.2: 符合優選 URL 模式
        - +0.1: 連結深度不超過父頁面 +1
        - +0.2: 關鍵字出現在錨點文字中
        - +0.1: 關鍵字出現在上下文中

        Args:
            url: 目標 URL
            anchor_text: 錨點文字
            context: 周圍上下文
            parent_url: 父頁面 URL

        Returns:
            相關性分數 (0.0 - 1.0)
        """
        score = 0.0  # 基礎分改為 0，讓閾值過濾生效

        url_lower = url.lower()
        anchor_lower = anchor_text.lower() if anchor_text else ""
        context_lower = context.lower() if context else ""

        # 關鍵字在 URL 中
        for keyword in self.keywords:
            if keyword in url_lower:
                score += 0.4
                break

        # 優選 URL 模式
        if is_preferred_url(url):
            score += 0.2

        # 連結深度檢查
        url_depth = get_url_depth(url)
        parent_depth = get_url_depth(parent_url)
        if url_depth <= parent_depth + 1:
            score += 0.1

        # 關鍵字在錨點文字中
        for keyword in self.keywords:
            if keyword in anchor_lower:
                score += 0.2
                break

        # 關鍵字在上下文中
        for keyword in self.keywords:
            if keyword in context_lower:
                score += 0.1
                break

        return min(score, 1.0)

    def _calculate_content_relevance(
        self,
        title: str,
        content: str
    ) -> float:
        """
        計算內容相關性分數

        評分標準：
        - +0.3: 標題包含關鍵字
        - +min(出現次數 * 0.1, 0.4): 內容包含關鍵字

        Args:
            title: 頁面標題
            content: 主要內容

        Returns:
            相關性分數 (0.0 - 1.0)
        """
        score = 0.0

        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""

        # 標題包含關鍵字
        for keyword in self.keywords:
            if keyword in title_lower:
                score += 0.3
                break

        # 內容包含關鍵字（計算出現次數）
        keyword_count = 0
        for keyword in self.keywords:
            keyword_count += content_lower.count(keyword)

        score += min(keyword_count * 0.1, 0.4)

        return min(score, 1.0)

    def _calculate_quality_score(
        self,
        title: str,
        meta_description: str,
        content: str,
        word_count: int
    ) -> float:
        """
        計算內容質量分數

        評分標準：
        - +0.3: 字數 >= 100
        - +0.2: 字數 >= 500
        - +0.1: 字數 >= 1000
        - +0.2: 內容長度 >= 200 字元
        - +0.1: 有標題
        - +0.1: 有 meta description

        Args:
            title: 頁面標題
            meta_description: Meta 描述
            content: 主要內容
            word_count: 字數

        Returns:
            質量分數 (0.0 - 1.0)
        """
        score = 0.0

        # 字數評分
        if word_count >= 100:
            score += 0.3
        if word_count >= 500:
            score += 0.2
        if word_count >= 1000:
            score += 0.1

        # 內容長度
        if len(content) >= 200:
            score += 0.2

        # 有標題
        if title and len(title.strip()) > 0:
            score += 0.1

        # 有 meta description
        if meta_description and len(meta_description.strip()) > 0:
            score += 0.1

        return min(score, 1.0)

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """提取主要內容"""
        # 嘗試找到主要內容區域
        main_content = None
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

        if not main_content:
            main_content = soup.find("body")

        if not main_content:
            return ""

        text = main_content.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        lines = [line for line in lines if len(line) > 20 or re.search(r'[\u4e00-\u9fff]', line)]

        return "\n".join(lines)

    def _collect_relevant_links(
        self,
        crawled_pages: List[CrawledPage]
    ) -> List[str]:
        """
        從已爬取頁面收集相關連結

        Args:
            crawled_pages: 已爬取的頁面列表

        Returns:
            需要爬取的 URL 列表
        """
        all_links = []

        for page in crawled_pages:
            if not page.success or not page.internal_links:
                continue

            for link in page.internal_links:
                if link["relevance"] >= self.config.min_relevance_score:
                    normalized = normalize_url(link["url"])
                    if normalized not in self.visited_urls:
                        all_links.append({
                            "url": link["url"],
                            "relevance": link["relevance"],
                            "source": page.url
                        })

        # 去重並按相關性排序
        seen = set()
        unique_links = []
        for link in sorted(all_links, key=lambda x: x["relevance"], reverse=True):
            normalized = normalize_url(link["url"])
            if normalized not in seen:
                seen.add(normalized)
                unique_links.append(link["url"])

        return unique_links

    def _should_stop(self) -> bool:
        """檢查是否應停止爬取"""
        # 檢查外部停止信號
        if self.stop_check and self.stop_check():
            logger.info("Deep crawl stopped by external signal")
            return True

        # 檢查總頁面數限制
        if self.total_pages_crawled >= self.config.max_total_pages:
            return True

        # 檢查超時
        elapsed = time.time() - self.start_time
        if elapsed >= self.config.total_timeout:
            logger.warning(f"Deep crawl timeout after {elapsed:.1f}s")
            return True

        return False

    def _finalize_results(
        self,
        results: List[CrawledPage],
        max_results: int
    ) -> List[CrawledPage]:
        """
        最終處理結果

        Args:
            results: 所有爬取結果
            max_results: 最大返回數量

        Returns:
            過濾、排序後的結果
        """
        # 過濾失敗的結果
        successful = [r for r in results if r.success]

        # 按綜合分數排序
        successful.sort(key=lambda x: x.combined_score, reverse=True)

        # 返回前 N 個結果
        return successful[:max_results]


def create_deep_crawler_from_config(stop_check: Optional[Callable[[], bool]] = None) -> DeepCrawler:
    """從全局配置創建深度爬蟲實例

    Args:
        stop_check: 停止檢查回調，返回 True 時停止爬取
    """
    config = DeepCrawlConfig(
        max_depth=getattr(Config, 'DEEP_CRAWL_MAX_DEPTH', 2),
        max_pages_per_domain=getattr(Config, 'DEEP_CRAWL_MAX_PAGES_PER_DOMAIN', 5),
        max_total_pages=getattr(Config, 'DEEP_CRAWL_MAX_TOTAL_PAGES', 30),
        min_relevance_score=getattr(Config, 'DEEP_CRAWL_MIN_RELEVANCE', 0.3),
        total_timeout=getattr(Config, 'DEEP_CRAWL_TIMEOUT', 300),
        timeout_per_page=getattr(Config, 'SCRAPE_TIMEOUT', 10),
    )
    return DeepCrawler(config, stop_check=stop_check)
