"""文章生成服務"""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict
from config import Config
from utils.logger import logger
from utils.text_processing import build_reference_content_blocks_flexible
from services.deepseek_client import call_deepseek
from services.llm_client import call_llm, get_current_model, accumulate_poe_points
from services.keyword_extractor import (
    get_recent_articles_text,
    get_relevant_reference_blocks,
    get_relevant_reference_blocks_by_mapping
)
from services.database import insert_article
from models import ProgressTracker
from services.seo_orchestrator import (
    analyze_keyword_full,
    analyze_keyword_full_with_deep_crawl,
    prepare_seo_context_for_prompt,
    prepare_deep_crawl_context_for_prompt,
    generate_hierarchical_summary,
    get_completed_crawl_result
)
from services.dataforseo_client import dataforseo_client

# 全域進度追蹤器
article_generation_progress = ProgressTracker("article_generation")

# 全域變數儲存 Prompts（用於除錯）
generated_prompts = {}
generated_prompts_lock = threading.Lock()


def build_article_prompt(
    main_keyword: str,
    reference_content: str,
    reference_section_title: str = "參考新聞資料",
    seo_context: str = "",
    chosen_keywords: list = None
) -> str:
    """構建優化後的 Blog 文章生成 Prompt

    Args:
        main_keyword: 主要關鍵詞
        reference_content: 參考資料內容
        reference_section_title: 參考資料區塊標題
        seo_context: SEO 分析數據（可選）
        chosen_keywords: 關鍵詞列表（可選，預設使用 main_keyword）

    Returns:
        優化後的 Prompt 字串
    """
    chosen_keywords = chosen_keywords or [main_keyword]
    keywords_json = json.dumps(chosen_keywords, ensure_ascii=False)

    seo_section = ""
    if seo_context:
        seo_section = f"\n---\n## SEO 分析數據\n{seo_context}\n---\n"

    prompt = f"""你是一位香港地區的專業 Blog 內容寫作顧問與 SEO 專家，專注於長者服務與安老政策領域。

## 任務目標
根據提供的參考資料，以「{main_keyword}」為主題，撰寫一篇高品質的雙語 **Blog 文章**。

## Blog 文章風格特點
- 資訊性與可讀性並重
- 適合網站發佈和社群分享
- 對讀者有實用價值

## 文章結構要求

### 中文 Blog 文章（繁體中文）
1. **標題**：吸引點擊，包含關鍵詞「{main_keyword}」，15-25字
2. **開頭段**：點出主題重要性，吸引讀者繼續閱讀
3. **主體段**：說明要點、政策內容或服務細節，可用條列式增加可讀性
4. **結尾段**：總結重點或呼籲行動

### 英文 Blog 文章（純英文）
1. **Title**: Engaging blog title, includes keyword, under 70 characters
2. **Opening**: Hook and topic introduction
3. **Body**: Key points and details, can use bullet points
4. **Closing**: Summary or call to action

## 寫作風格
- 語調：專業但親切、客觀、關懷長者
- 適合 Blog 閱讀：段落簡短、重點明確
- 避免：過度推銷、誇張用語、政治敏感內容
- 適用對象：關心長者服務的香港市民、照顧者、專業人士

## SEO 優化要求
1. **標題**：關鍵詞靠前，具吸引力，適合搜尋引擎
2. **正文**：自然融入關鍵詞2-3次，避免堆砌
3. **Meta Title**：60字元內，包含關鍵詞
4. **Meta Description**：150字元內，包含關鍵詞，描述文章價值

## 重要規則
1. 內容必須與「長者」或「老人」相關
2. 基於參考資料撰寫，不可捏造數據或事實
3. 英文文章絕對不能包含任何中文字
4. 如參考資料不足，可基於香港社會福利背景補充（但不編造具體數字）
{seo_section}
---
## {reference_section_title}
{reference_content}

---
## 主題關鍵詞
{main_keyword}

---
## 輸出格式

請嚴格按照以下JSON格式輸出，不要添加任何其他文字：

```json
[
  {{
    "zh": {{
      "title": "【範例】{main_keyword}新政策助長者安享晚年",
      "body": "中文 Blog 正文內容...",
      "meta_title": "{main_keyword} | 香港長者服務資訊",
      "meta_description": "了解{main_keyword}的最新資訊，為長者提供優質服務支援。"
    }},
    "en": {{
      "title": "New Policy on {main_keyword} Benefits Elderly",
      "body": "English blog body content...",
      "meta_title": "{main_keyword} | Hong Kong Elderly Services",
      "meta_description": "Learn about the latest {main_keyword} information."
    }},
    "keywords": {keywords_json}
  }}
]
```

請直接輸出JSON："""

    return prompt


def generate_single_article(
    article_index: int,
    main_keyword: str,
    source: str,
    timestamp: str,
    total_articles: int,
    fallback_content: str
) -> tuple:
    """生成單篇文章

    Args:
        article_index: 文章索引
        main_keyword: 主要關鍵詞
        source: 資料來源
        timestamp: 時間戳記
        total_articles: 總文章數
        fallback_content: 備用參考內容

    Returns:
        (索引, 輸出文本, 關鍵詞列表)
    """
    chosen_keywords = [main_keyword]

    logger.info(
        f"📝 正在生成第 {article_index + 1}/{total_articles} 篇文章（中英雙語），"
        f"主題：{main_keyword}（source={source}）"
    )

    # 取得相關參考資料
    reference_blocks = get_relevant_reference_blocks_by_mapping(
        source=source,
        keywords=[main_keyword],
        days=30,
        limit=10
    )

    if reference_blocks:
        reference_content = build_reference_content_blocks_flexible(
            reference_blocks,
            max_chars_zh=Config.MAX_CHARS_ZH,
            max_chars_en=Config.MAX_CHARS_EN,
            prefer_bilingual=True
        )
        if reference_content:
            logger.info(f"✅ 為關鍵詞「{main_keyword}」找到相關新聞（{source}）")
        else:
            reference_content = fallback_content
            logger.warning(f"⚠️ 「{main_keyword}」相關新聞無法組出可用參考，改用 fallback")
    else:
        reference_content = fallback_content
        logger.warning(f"⚠️ 未找到「{main_keyword}」相關新聞，使用備用內容（{source}）")

    # 生成 prompt（使用統一模板）
    prompt_zh = build_article_prompt(
        main_keyword=main_keyword,
        reference_content=reference_content,
        reference_section_title="參考新聞資料（中英並列）",
        seo_context="",
        chosen_keywords=chosen_keywords
    )

    # 儲存 prompt（用於除錯）
    with generated_prompts_lock:
        if timestamp not in generated_prompts:
            generated_prompts[timestamp] = []
        generated_prompts[timestamp].append({
            "index": article_index + 1,
            "keyword": main_keyword,
            "prompt": {"zh": prompt_zh},
            "source": source
        })

    # 呼叫 API
    output = call_deepseek(prompt_zh)

    # 更新進度
    article_generation_progress.increment()

    return (article_index, output, chosen_keywords)


def build_serp_reference_section(scraped_content: list, max_items: int = 5) -> str:
    """將 SERP 爬蟲內容格式化為參考資料

    Args:
        scraped_content: analyze_keyword_full 返回的 scraped_content 列表
        max_items: 最多使用幾個網站的內容

    Returns:
        格式化的參考資料字串
    """
    if not scraped_content:
        return "（無可用的搜尋結果參考資料）"

    sections = ["以下是與此關鍵字相關的網站內容摘要：\n"]

    for i, item in enumerate(scraped_content[:max_items], 1):
        if item.get("success", True) and item.get("main_content"):
            # 摘要內容（限制長度）
            content = item.get("main_content", "")
            if len(content) > 500:
                content = content[:500] + "..."

            title = item.get("title", "未知")
            url = item.get("url", "")

            sections.append(f"【參考 {i}】{title}")
            sections.append(f"來源: {url}")
            sections.append(f"{content}\n")

    return "\n".join(sections)


def build_seo_prompt_section(seo_context: str) -> str:
    """構建 SEO prompt 區塊

    Args:
        seo_context: prepare_seo_context_for_prompt 返回的內容

    Returns:
        格式化的 prompt 區塊
    """
    if not seo_context:
        return ""

    return f"""
---
## 📊 SEO 分析數據（請參考以下資料優化文章）

{seo_context}

---
"""


def build_hierarchical_reference_section(
    hierarchical_summary: str,
    seo_analysis: dict,
    keyword: str
) -> str:
    """構建基於分層摘要的參考資料區塊

    Args:
        hierarchical_summary: generate_hierarchical_summary 返回的合併摘要
        seo_analysis: analyze_keyword_full_with_deep_crawl 的結果
        keyword: 關鍵字

    Returns:
        格式化的參考資料區塊
    """
    sections = []

    # 添加 SEO 指標
    keyword_data = seo_analysis.get("keyword_data", {})
    if keyword_data:
        search_volume = keyword_data.get("search_volume", 0)
        cpc = keyword_data.get("cpc", 0)
        competition_level = keyword_data.get("competition_level", "N/A")

        sections.append(f"""## SEO 關鍵字指標
- 月搜尋量：{search_volume:,}
- 平均 CPC：${cpc:.2f}
- 競爭程度：{competition_level}""")

    # 添加相關關鍵字
    related_keywords = keyword_data.get("related_keywords", [])[:10]
    if related_keywords:
        related_list = ", ".join([k.get("keyword", "") for k in related_keywords if k.get("keyword")])
        sections.append(f"""## 相關關鍵字（可作為長尾關鍵字）
{related_list}""")

    # 用戶常問問題
    serp = seo_analysis.get("serp", {})
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

    # 分層摘要（核心內容）
    if hierarchical_summary:
        sections.append(f"""## 競爭對手分析摘要（基於 {len(seo_analysis.get('scraped_content', []))} 頁深度爬取）

以下是各競爭網站的關鍵內容摘要：

{hierarchical_summary}""")

    # 深度爬取統計
    deep_stats = seo_analysis.get("deep_crawl_stats")
    if deep_stats:
        sections.append(f"""## 深度爬取統計
- 總爬取頁面：{deep_stats.get('total_pages_crawled', 0)}
- 涵蓋域名數：{deep_stats.get('unique_domains', 0)}
- SERP 頁面：{deep_stats.get('depth_0_count', 0)}
- 內部連結頁面：{deep_stats.get('depth_1_count', 0)}""")

    return "\n\n".join(sections) if sections else ""


def build_serp_reference_with_hierarchical_summary(
    scraped_content: list,
    keyword: str,
    seo_analysis: dict = None
) -> str:
    """智能構建 SERP 參考資料（自動選擇是否使用分層摘要）

    當爬取頁面數量超過閾值時，使用分層摘要；否則使用原始截斷方法。

    Args:
        scraped_content: 爬取的頁面列表
        keyword: 關鍵字
        seo_analysis: 完整的 SEO 分析結果（可選）

    Returns:
        格式化的參考資料字串
    """
    if not scraped_content:
        return "（無可用的搜尋結果參考資料）"

    # 檢查是否啟用分層摘要
    hierarchical_enabled = getattr(Config, 'HIERARCHICAL_SUMMARY_ENABLED', True)
    threshold = getattr(Config, 'HIERARCHICAL_SUMMARY_THRESHOLD', 5)

    if hierarchical_enabled and len(scraped_content) > threshold:
        # 使用分層摘要
        logger.info(f"Using hierarchical summary for {len(scraped_content)} pages (threshold: {threshold})")

        hierarchical_summary = generate_hierarchical_summary(scraped_content, keyword)

        if hierarchical_summary and seo_analysis:
            return build_hierarchical_reference_section(
                hierarchical_summary,
                seo_analysis,
                keyword
            )
        elif hierarchical_summary:
            # 只有摘要，沒有其他 SEO 數據
            return f"""## 競爭對手分析摘要

以下是各競爭網站的關鍵內容摘要：

{hierarchical_summary}"""

    # 回退到原始方法（截斷內容）
    logger.info(f"Using traditional truncation for {len(scraped_content)} pages")
    return build_serp_reference_section(scraped_content, max_items=10)


def generate_single_article_with_seo(
    article_index: int,
    main_keyword: str,
    source: str,
    timestamp: str,
    total_articles: int,
    fallback_content: str
) -> tuple:
    """生成單篇 SEO 增強文章

    Args:
        article_index: 文章索引
        main_keyword: 主要關鍵詞
        source: 資料來源
        timestamp: 時間戳記
        total_articles: 總文章數
        fallback_content: 備用參考內容

    Returns:
        (索引, 輸出文本, 關鍵詞列表)
    """
    chosen_keywords = [main_keyword]

    logger.info(
        f"📝 正在生成第 {article_index + 1}/{total_articles} 篇 SEO 增強文章，"
        f"主題：{main_keyword}（source={source}）"
    )

    # 取得 SEO 數據
    seo_context_str = ""
    if dataforseo_client.is_configured():
        try:
            logger.info(f"正在取得「{main_keyword}」的 SEO 數據...")
            seo_result = analyze_keyword_full(main_keyword, skip_scraping=False)
            seo_context_str = prepare_seo_context_for_prompt(main_keyword, seo_result)
            if seo_context_str:
                logger.info(f"✅ 成功取得「{main_keyword}」的 SEO 數據")
        except Exception as e:
            logger.warning(f"⚠️ 取得 SEO 數據失敗：{e}")

    # 取得相關參考資料
    reference_blocks = get_relevant_reference_blocks_by_mapping(
        source=source,
        keywords=[main_keyword],
        days=30,
        limit=10
    )

    if reference_blocks:
        reference_content = build_reference_content_blocks_flexible(
            reference_blocks,
            max_chars_zh=Config.MAX_CHARS_ZH,
            max_chars_en=Config.MAX_CHARS_EN,
            prefer_bilingual=True
        )
        if reference_content:
            logger.info(f"✅ 為關鍵詞「{main_keyword}」找到相關新聞（{source}）")
        else:
            reference_content = fallback_content
            logger.warning(f"⚠️ 「{main_keyword}」相關新聞無法組出可用參考，改用 fallback")
    else:
        reference_content = fallback_content
        logger.warning(f"⚠️ 未找到「{main_keyword}」相關新聞，使用備用內容（{source}）")

    # 生成 prompt（使用統一模板，含 SEO 數據）
    prompt_zh = build_article_prompt(
        main_keyword=main_keyword,
        reference_content=reference_content,
        reference_section_title="參考新聞資料（中英並列）",
        seo_context=seo_context_str,
        chosen_keywords=chosen_keywords
    )

    # 儲存 prompt（用於除錯）
    with generated_prompts_lock:
        if timestamp not in generated_prompts:
            generated_prompts[timestamp] = []
        generated_prompts[timestamp].append({
            "index": article_index + 1,
            "keyword": main_keyword,
            "prompt": {"zh": prompt_zh},
            "source": source,
            "has_seo_data": bool(seo_context_str)
        })

    # 呼叫 API
    output = call_deepseek(prompt_zh)

    # 更新進度
    article_generation_progress.increment()

    return (article_index, output, chosen_keywords)


def generate_single_article_by_source(
    article_index: int,
    main_keyword: str,
    keyword_source: str,
    timestamp: str,
    total_articles: int,
    fallback_content: str,
    actual_source: str = None,
    llm_provider: str = None,
    llm_model: str = None
) -> tuple:
    """根據關鍵字來源生成文章

    根據 keyword_source 或 actual_source 決定使用哪種參考資料：
    - 'swd', 'ha': 使用新聞稿作為參考
    - 'seo', 'trends': 使用 SERP 爬蟲內容作為參考

    Args:
        article_index: 文章索引
        main_keyword: 主要關鍵詞
        keyword_source: 關鍵字來源類型 ('swd', 'ha', 'seo', 'trends', 'mixed')
        timestamp: 時間戳記
        total_articles: 總文章數
        fallback_content: 備用參考內容
        actual_source: 實際的關鍵字來源（當 keyword_source='mixed' 時使用）

    Returns:
        (索引, 輸出文本, 關鍵詞列表, prompt_zh)
    """
    chosen_keywords = [main_keyword]

    # 決定實際使用的來源
    effective_source = actual_source if actual_source else keyword_source

    logger.info(
        f"📝 正在生成第 {article_index + 1}/{total_articles} 篇文章，"
        f"主題：{main_keyword}（effective_source={effective_source}）"
    )

    # 根據來源類型決定參考資料
    if effective_source in ('swd', 'ha'):
        # 使用新聞稿作為參考（優先使用關鍵字映射）
        reference_blocks = get_relevant_reference_blocks_by_mapping(
            source=effective_source,
            keywords=[main_keyword],
            days=30,
            limit=10
        )

        if reference_blocks:
            reference_content = build_reference_content_blocks_flexible(
                reference_blocks,
                max_chars_zh=Config.MAX_CHARS_ZH,
                max_chars_en=Config.MAX_CHARS_EN,
                prefer_bilingual=True
            )
            if reference_content:
                logger.info(f"✅ 為關鍵詞「{main_keyword}」找到相關新聞（{effective_source}）")
            else:
                reference_content = fallback_content
                logger.warning(f"⚠️ 「{main_keyword}」相關新聞無法組出可用參考，改用 fallback")
        else:
            reference_content = fallback_content
            logger.warning(f"⚠️ 未找到「{main_keyword}」相關新聞，使用備用內容（{effective_source}）")

        reference_section_title = "📰 參考新聞資料（中英並列）"
    else:
        # 使用 SERP 爬蟲內容作為參考（SEO/Trends 關鍵字）
        logger.info(f"🔍 正在取得「{main_keyword}」的 SERP 數據...")

        # 優先檢查是否有預爬蟲結果
        cached_crawl = get_completed_crawl_result(main_keyword, max_age_seconds=3600)

        if cached_crawl:
            # 使用預爬蟲的快取結果（秒級響應）
            logger.info(f"✅ 使用「{main_keyword}」的預爬蟲快取結果")
            scraped_content = cached_crawl.get("scraped_content", [])

            if scraped_content:
                # 使用智能參考資料構建
                reference_content = build_serp_reference_with_hierarchical_summary(
                    scraped_content,
                    main_keyword,
                    seo_analysis=cached_crawl
                )
                logger.info(f"✅ 從快取取得「{main_keyword}」的爬蟲內容（{len(scraped_content)} 個頁面）")
            else:
                reference_content = fallback_content
                logger.warning(f"⚠️ 「{main_keyword}」快取爬蟲結果為空，使用備用內容")

        elif dataforseo_client.is_configured():
            # 回退到即時爬取
            logger.info(f"🔄 無快取結果，執行即時深度爬取：{main_keyword}")
            try:
                # 使用深度爬取獲取更多內容
                deep_crawl_enabled = getattr(Config, 'DEEP_CRAWL_ENABLED', True)
                seo_result = analyze_keyword_full_with_deep_crawl(
                    main_keyword,
                    deep_crawl_enabled=deep_crawl_enabled
                )
                scraped_content = seo_result.get("scraped_content", [])

                if scraped_content:
                    # 使用智能參考資料構建（自動選擇分層摘要或截斷）
                    reference_content = build_serp_reference_with_hierarchical_summary(
                        scraped_content,
                        main_keyword,
                        seo_analysis=seo_result
                    )
                    logger.info(f"✅ 成功取得「{main_keyword}」的深度爬蟲內容（{len(scraped_content)} 個頁面）")
                else:
                    reference_content = fallback_content
                    logger.warning(f"⚠️ 「{main_keyword}」SERP 爬蟲無內容，使用備用內容")
            except Exception as e:
                logger.warning(f"⚠️ 取得 SERP 數據失敗：{e}")
                reference_content = fallback_content
        else:
            logger.warning("⚠️ DataForSEO API 未配置，使用備用內容")
            reference_content = fallback_content

        reference_section_title = "🌐 競爭對手深度分析"

    # 生成 prompt（使用統一模板）
    prompt_zh = build_article_prompt(
        main_keyword=main_keyword,
        reference_content=reference_content,
        reference_section_title=reference_section_title,
        seo_context="",
        chosen_keywords=chosen_keywords
    )

    # 儲存 prompt（用於除錯）
    with generated_prompts_lock:
        if timestamp not in generated_prompts:
            generated_prompts[timestamp] = []
        generated_prompts[timestamp].append({
            "index": article_index + 1,
            "keyword": main_keyword,
            "prompt": {"zh": prompt_zh},
            "keyword_source": keyword_source
        })

    # 呼叫 LLM API（支援多模型切換）
    output, llm_metadata = call_llm(prompt_zh, provider=llm_provider, model=llm_model)

    # 更新進度
    article_generation_progress.increment()

    return (article_index, output, chosen_keywords, prompt_zh, llm_metadata)


def background_generate_articles(
    selected_keywords: List[str],
    timestamp: str,
    source: str = "swd"
):
    """背景生成文章（舊版本，建議使用 background_generate_articles_by_source）

    Args:
        selected_keywords: 選中的關鍵詞列表
        timestamp: 時間戳記
        source: 資料來源
    """
    total_articles = len(selected_keywords)

    # 初始化進度（包含診斷欄位重置）
    article_generation_progress.reset()
    article_generation_progress.update(
        total=total_articles,
        completed=0,
        running=True,
        timestamp=timestamp,
        titles=[]
    )

    with generated_prompts_lock:
        generated_prompts[timestamp] = []

    logger.info(f"🚀 開始生成 {total_articles} 篇文章（source={source}）")

    # 準備備用內容
    recent_blocks = get_recent_articles_text(source=source, days=30)
    if not recent_blocks:
        logger.warning("⚠️ 沒有找到近期新聞，將使用關鍵字生成")
        fallback_content = "（無可用參考資料，請基於關鍵詞生成符合香港社會福利/醫療政策背景的專業內容）"
    else:
        fallback_content = build_reference_content_blocks_flexible(
            recent_blocks,
            max_chars_zh=Config.MAX_CHARS_ZH,
            max_chars_en=Config.MAX_CHARS_EN,
            prefer_bilingual=True
        )

    results = []

    # 使用線程池生成文章（減少到3個 worker）
    with ThreadPoolExecutor(max_workers=Config.ARTICLE_GENERATION_WORKERS) as executor:
        futures = [
            executor.submit(
                generate_single_article,
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
                logger.error(f"❌ 文章生成失敗：{e}")

    # 解析並儲存文章
    all_articles = []
    for idx, output_text, chosen_kws in sorted(results, key=lambda x: x[0]):
        # 診斷：記錄關鍵字
        keyword_str = json.dumps(chosen_kws, ensure_ascii=False) if isinstance(chosen_kws, list) else str(chosen_kws)

        if not output_text:
            logger.error(f"❌ 第 {idx+1} 篇輸出為空！關鍵字: {keyword_str}")
            article_generation_progress.add_failed_keyword(keyword_str, "LLM 輸出為空")
            continue

        try:
            # 清理 markdown 代碼塊標記
            cleaned_output = output_text.strip()
            if '```' in cleaned_output:
                # 方法1: 嘗試提取代碼塊內容
                code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned_output)
                if code_block_match:
                    cleaned_output = code_block_match.group(1).strip()
                    logger.info(f"🧹 第 {idx+1} 篇已提取 markdown 代碼塊內容")
                else:
                    # 方法2: 直接移除 ``` 標記
                    cleaned_output = re.sub(r'```(?:json)?', '', cleaned_output)
                    cleaned_output = re.sub(r'```', '', cleaned_output)
                    cleaned_output = cleaned_output.strip()
                    logger.info(f"🧹 第 {idx+1} 篇已移除 markdown 標記")

            # 修復 JSON 尾隨逗號問題
            cleaned_output = re.sub(r',(\s*[}\]])', r'\1', cleaned_output)

            match = re.search(r'\[.*\]', cleaned_output, re.S)
            parsed = json.loads(match.group(0)) if match else json.loads(cleaned_output)

            if not isinstance(parsed, list):
                parsed = [parsed]

            for item in parsed:
                if item.get("keywords") != chosen_kws:
                    logger.warning(f"⚠️ AI 返回的關鍵詞不符，已強制使用：{chosen_kws}")
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

        except json.JSONDecodeError as e:
            logger.error(f"⚠️ JSON 解析錯誤 (第 {idx+1} 篇): {e}")
            logger.error(f"原始輸出前 500 字: {output_text[:500]}...")
            article_generation_progress.add_failed_keyword(keyword_str, f"JSON 解析失敗: {e}")
            article_generation_progress.add_parse_failure(keyword_str, str(e), output_text)
            continue
        except Exception as e:
            logger.error(f"⚠️ 解析錯誤 (第 {idx+1} 篇): {e}")
            logger.error(f"原始輸出前 500 字: {output_text[:500]}...")
            article_generation_progress.add_failed_keyword(keyword_str, f"解析異常: {e}")
            article_generation_progress.add_parse_failure(keyword_str, str(e), output_text)
            continue

    # 批次插入資料庫
    saved_count = 0
    db_failures = 0
    for art in all_articles:
        try:
            result = insert_article(art)
            if result.get("success"):
                title = art.get("title_zh") or art.get("title") or "未命名"
                article_generation_progress.titles.append(title)
                saved_count += 1
                logger.info(f"✅ 已儲存文章: {title}")
            else:
                db_failures += 1
                logger.error(f"❌ 儲存文章失敗: {result.get('message', '未知錯誤')}")
                article_generation_progress.add_error(f"資料庫儲存失敗: {result.get('message', '未知錯誤')}")
        except Exception as e:
            db_failures += 1
            logger.error(f"❌ 儲存文章時發生異常: {e}")
            article_generation_progress.add_error(f"資料庫異常: {e}")

    # 診斷摘要
    logger.info("=" * 60)
    logger.info("📊 生成任務診斷摘要")
    logger.info(f"   總請求: {total_articles} 篇")
    logger.info(f"   成功解析: {len(all_articles)} 篇")
    logger.info(f"   成功儲存: {saved_count} 篇")
    logger.info(f"   解析失敗: {total_articles - len(all_articles)} 篇")
    logger.info(f"   儲存失敗: {db_failures} 篇")
    if article_generation_progress.failed_keywords:
        logger.warning(f"   失敗關鍵字: {article_generation_progress.failed_keywords}")
    logger.info("=" * 60)

    # 完成
    article_generation_progress.update(running=False)


def background_generate_articles_by_source(
    selected_keywords: List[str],
    timestamp: str,
    keyword_source: str = "swd",
    keyword_sources_map: Dict[str, str] = None,
    llm_provider: str = None,
    llm_model: str = None
):
    """背景生成文章（根據關鍵字來源選擇參考資料）

    Args:
        selected_keywords: 選中的關鍵詞列表
        timestamp: 時間戳記
        keyword_source: 關鍵字來源類型 ('swd', 'ha', 'seo', 'trends', 'mixed')
        keyword_sources_map: 每個關鍵字的實際來源映射（當 keyword_source='mixed' 時使用）
    """
    total_articles = len(selected_keywords)

    # 初始化進度（包含診斷欄位重置）
    article_generation_progress.reset()
    article_generation_progress.update(
        total=total_articles,
        completed=0,
        running=True,
        timestamp=timestamp,
        titles=[]
    )

    with generated_prompts_lock:
        generated_prompts[timestamp] = []

    # 使用預設值（如果未指定）
    if not llm_provider:
        llm_provider = Config.DEFAULT_PROVIDER
    if not llm_model:
        llm_model = Config.DEFAULT_MODEL

    logger.info(f"🚀 開始生成 {total_articles} 篇文章（keyword_source={keyword_source}）")
    logger.info(f"🤖 使用 LLM 模型: {llm_provider}/{llm_model}")
    logger.info(f"📋 關鍵字來源映射: {keyword_sources_map}")

    # 準備備用內容（使用 SWD 新聞稿）
    source_for_fallback = 'swd'
    recent_blocks = get_recent_articles_text(source=source_for_fallback, days=30)
    if not recent_blocks:
        logger.warning("⚠️ 沒有找到近期新聞，將使用關鍵字生成")
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
        futures = []
        for i in range(total_articles):
            kw = selected_keywords[i]
            # 決定實際來源
            if keyword_sources_map and kw in keyword_sources_map:
                actual_source = keyword_sources_map[kw]
                logger.info(f"📌 關鍵字「{kw}」使用映射來源: {actual_source}")
            elif keyword_source == 'mixed':
                # 如果沒有映射且是 mixed，預設使用 swd
                actual_source = 'swd'
                logger.info(f"📌 關鍵字「{kw}」無映射，預設使用: swd")
            else:
                actual_source = keyword_source
                logger.info(f"📌 關鍵字「{kw}」使用全域來源: {actual_source}")

            futures.append(
                executor.submit(
                    generate_single_article_by_source,
                    i,
                    kw,
                    keyword_source,
                    timestamp,
                    total_articles,
                    fallback_content,
                    actual_source,
                    llm_provider,
                    llm_model
                )
            )

        for future in as_completed(futures):
            try:
                result = future.result()
                logger.info(f"✅ 收到生成結果: index={result[0]}, output_len={len(result[1]) if result[1] else 0}")
                results.append(result)
            except Exception as e:
                logger.error(f"❌ 文章生成失敗：{e}", exc_info=True)

    logger.info(f"📋 共收到 {len(results)} 個結果")

    # 解析並儲存文章
    all_articles = []
    total_tokens_used = 0
    for idx, output_text, chosen_kws, prompt_zh, llm_metadata in sorted(results, key=lambda x: x[0]):
        # 累計 tokens 使用量
        total_tokens_used += llm_metadata.get("tokens_used", 0)
        logger.info(f"🔍 解析第 {idx+1} 篇: provider={llm_metadata.get('provider')}, model={llm_metadata.get('model')}, output_len={len(output_text) if output_text else 0}")

        # 診斷：記錄關鍵字（用於追蹤失敗）
        keyword_str = json.dumps(chosen_kws, ensure_ascii=False) if isinstance(chosen_kws, list) else str(chosen_kws)

        if not output_text:
            logger.error(f"❌ 第 {idx+1} 篇輸出為空！關鍵字: {keyword_str}")
            article_generation_progress.add_failed_keyword(keyword_str, "LLM 輸出為空")
            article_generation_progress.add_error(f"第 {idx+1} 篇輸出為空 (關鍵字: {keyword_str})")
            continue

        # 診斷：記錄原始輸出前 200 字（用於追蹤格式問題）
        logger.debug(f"📝 第 {idx+1} 篇原始輸出前 200 字: {output_text[:200]}...")

        try:
            # 清理 markdown 代碼塊標記（```json ... ``` 或 ``` ... ```）
            cleaned_output = output_text.strip()
            if '```' in cleaned_output:
                # 方法1: 嘗試提取代碼塊內容
                code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned_output)
                if code_block_match:
                    cleaned_output = code_block_match.group(1).strip()
                    logger.info(f"🧹 第 {idx+1} 篇已提取 markdown 代碼塊內容")
                else:
                    # 方法2: 直接移除 ``` 標記
                    cleaned_output = re.sub(r'```(?:json)?', '', cleaned_output)
                    cleaned_output = re.sub(r'```', '', cleaned_output)
                    cleaned_output = cleaned_output.strip()
                    logger.info(f"🧹 第 {idx+1} 篇已移除 markdown 標記")

            # 修復 JSON 尾隨逗號問題（LLM 常見錯誤）
            # 移除 }, 或 ], 後面緊跟 } 或 ] 的情況
            cleaned_output = re.sub(r',(\s*[}\]])', r'\1', cleaned_output)

            # 嘗試多種 JSON 匹配模式
            match = re.search(r'\[.*\]', cleaned_output, re.S)

            # 診斷：記錄是否找到 JSON 數組
            if match:
                logger.debug(f"✅ 第 {idx+1} 篇找到 JSON 數組，長度: {len(match.group(0))}")
            else:
                logger.warning(f"⚠️ 第 {idx+1} 篇未找到 JSON 數組格式，嘗試直接解析")

            parsed = json.loads(match.group(0)) if match else json.loads(cleaned_output)

            if not isinstance(parsed, list):
                parsed = [parsed]

            for item in parsed:
                if item.get("keywords") != chosen_kws:
                    logger.warning(f"⚠️ AI 返回的關鍵詞不符，已強制使用：{chosen_kws}")
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
                    "timestamp": timestamp,
                    "prompt_zh": prompt_zh,
                    "prompt_en": "",  # 目前只有中文 prompt
                    "llm_provider": llm_metadata.get("provider", ""),
                    "llm_model": llm_metadata.get("model", "")
                }

                record["title"] = record["title_zh"] or "未命名"
                record["body"] = record["body_zh"] or ""
                record["meta_title"] = record["meta_title_zh"] or ""
                record["meta_description"] = record["meta_description_zh"] or ""

                all_articles.append(record)

        except json.JSONDecodeError as e:
            logger.error(f"⚠️ JSON 解析錯誤 (第 {idx+1} 篇): {e}")
            logger.error(f"原始輸出前 500 字: {output_text[:500]}...")
            article_generation_progress.add_failed_keyword(keyword_str, f"JSON 解析失敗: {e}")
            article_generation_progress.add_parse_failure(keyword_str, str(e), output_text)
            continue
        except Exception as e:
            logger.error(f"⚠️ 解析錯誤 (第 {idx+1} 篇): {e}")
            logger.error(f"原始輸出前 500 字: {output_text[:500]}...")
            article_generation_progress.add_failed_keyword(keyword_str, f"解析異常: {e}")
            article_generation_progress.add_parse_failure(keyword_str, str(e), output_text)
            continue

    logger.info(f"📊 解析完成，準備儲存 {len(all_articles)} 篇文章")

    # 批次插入資料庫
    saved_count = 0
    db_failures = 0
    for art in all_articles:
        try:
            logger.info(f"💾 正在儲存文章: {art.get('title_zh', '未命名')[:30]}...")
            result = insert_article(art)
            if result.get("success"):
                title = art.get("title_zh") or art.get("title") or "未命名"
                article_generation_progress.titles.append(title)
                saved_count += 1
                logger.info(f"✅ 已儲存文章: {title} (ID: {result.get('id', 'unknown')})")
            else:
                db_failures += 1
                error_msg = result.get('message', '未知錯誤')
                logger.error(f"❌ 儲存文章失敗: {error_msg}")
                article_generation_progress.add_error(f"資料庫儲存失敗: {error_msg}")
        except Exception as e:
            db_failures += 1
            logger.error(f"❌ 儲存文章時發生異常: {e}", exc_info=True)
            article_generation_progress.add_error(f"資料庫異常: {e}")

    # 診斷摘要
    logger.info("=" * 60)
    logger.info("📊 生成任務診斷摘要")
    logger.info(f"   總請求: {total_articles} 篇")
    logger.info(f"   成功解析: {len(all_articles)} 篇")
    logger.info(f"   成功儲存: {saved_count} 篇")
    logger.info(f"   解析失敗: {total_articles - len(all_articles)} 篇")
    logger.info(f"   儲存失敗: {db_failures} 篇")
    logger.info(f"   總 tokens: {total_tokens_used}")
    if article_generation_progress.failed_keywords:
        logger.warning(f"   失敗關鍵字: {article_generation_progress.failed_keywords}")
    logger.info("=" * 60)

    # 完成
    article_generation_progress.update(running=False, tokens_used=total_tokens_used)
    logger.info("🏁 background_generate_articles_by_source 任務完成")
