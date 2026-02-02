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
    get_relevant_reference_blocks
)
from services.database import insert_article
from models import ProgressTracker
from services.seo_orchestrator import analyze_keyword_full, prepare_seo_context_for_prompt
from services.dataforseo_client import dataforseo_client

# 全域進度追蹤器
article_generation_progress = ProgressTracker("article_generation")

# 全域變數儲存 Prompts（用於除錯）
generated_prompts = {}
generated_prompts_lock = threading.Lock()


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
    reference_blocks = get_relevant_reference_blocks(
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

    # 生成 prompt
    prompt_zh = (
        "你是一位香港地區的專業內容寫作顧問與 SEO 專家。\n\n"
        "## 📋 任務說明\n"
        f"請根據以下**真實新聞參考資料**，以「{main_keyword}」為**唯一主題**，一次輸出：\n"
        "1) 一篇繁體中文 blog 文章（300-400字）\n"
        "2) 一篇英文文章（約 180-250 words）\n\n"
        "⚠️ 重要準則（必須遵守）：\n"
        "1. 文章必須和「老人」或「長者」有關\n"
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
    reference_blocks = get_relevant_reference_blocks(
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

    # 構建 SEO prompt 區塊
    seo_prompt_section = build_seo_prompt_section(seo_context_str)

    # 生成 prompt（含 SEO 數據）
    prompt_zh = (
        "你是一位香港地區的專業內容寫作顧問與 SEO 專家。\n\n"
        "## 📋 任務說明\n"
        f"請根據以下**真實新聞參考資料**和 **SEO 分析數據**，以「{main_keyword}」為**唯一主題**，一次輸出：\n"
        "1) 一篇繁體中文 blog 文章（300-400字）\n"
        "2) 一篇英文文章（約 180-250 words）\n\n"
        "⚠️ 重要準則（必須遵守）：\n"
        "1. 文章必須和「老人」或「長者」有關\n"
        "2. 必須基於下方提供的參考資料內容，不可憑空捏造事實\n"
        "3. 可以重組、摘要、改寫，但核心事實必須來自參考資料\n"
        f"4. 文章標題和內容必須圍繞「{main_keyword}」展開\n"
        "5. 保持客觀、專業的新聞報導風格\n"
        "6. 如果參考資料不足，請基於關鍵詞生成符合香港社會福利/醫療政策背景的專業內容（但仍不要編造具體數據與細節）\n"
    )

    # 加入 SEO 區塊
    if seo_prompt_section:
        prompt_zh += (
            "7. 請參考 SEO 分析數據優化文章：\n"
            "   - 適當融入相關關鍵字和長尾詞\n"
            "   - 回答「用戶常問問題」中的問題\n"
            "   - 參考競爭對手內容的結構和深度\n\n"
        )
        prompt_zh += seo_prompt_section

    prompt_zh += (
        "\n---\n"
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
        # 使用新聞稿作為參考
        reference_blocks = get_relevant_reference_blocks(
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

        if dataforseo_client.is_configured():
            try:
                seo_result = analyze_keyword_full(main_keyword, skip_scraping=False)
                scraped_content = seo_result.get("scraped_content", [])

                if scraped_content:
                    # 改為 10 篇參考資料
                    reference_content = build_serp_reference_section(scraped_content, max_items=10)
                    logger.info(f"✅ 成功取得「{main_keyword}」的 SERP 爬蟲內容（{len(scraped_content)} 個網站）")
                else:
                    reference_content = fallback_content
                    logger.warning(f"⚠️ 「{main_keyword}」SERP 爬蟲無內容，使用備用內容")
            except Exception as e:
                logger.warning(f"⚠️ 取得 SERP 數據失敗：{e}")
                reference_content = fallback_content
        else:
            logger.warning("⚠️ DataForSEO API 未配置，使用備用內容")
            reference_content = fallback_content

        reference_section_title = "🌐 網路搜尋結果參考"

    # 生成 prompt
    prompt_zh = (
        "你是一位香港地區的專業內容寫作顧問與 SEO 專家。\n\n"
        "## 📋 任務說明\n"
        f"請根據以下**參考資料**，以「{main_keyword}」為**唯一主題**，一次輸出：\n"
        "1) 一篇繁體中文 blog 文章（300-400字）\n"
        "2) 一篇英文文章（約 180-250 words）\n\n"
        "⚠️ 重要準則（必須遵守）：\n"
        "1. 文章必須和「老人」或「長者」有關\n"
        "2. 必須基於下方提供的參考資料內容，不可憑空捏造事實\n"
        "3. 可以重組、摘要、改寫，但核心事實必須來自參考資料\n"
        f"4. 文章標題和內容必須圍繞「{main_keyword}」展開\n"
        "5. 保持客觀、專業的新聞報導風格\n"
        "6. 如果參考資料不足，請基於關鍵詞生成符合香港社會福利/醫療政策背景的專業內容（但仍不要編造具體數據與細節）\n\n"
        "---\n"
        f"## {reference_section_title}\n"
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
    """背景生成文章

    Args:
        selected_keywords: 選中的關鍵詞列表
        timestamp: 時間戳記
        source: 資料來源
    """
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
        try:
            match = re.search(r'\[.*\]', output_text, re.S)
            parsed = json.loads(match.group(0)) if match else json.loads(output_text)

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

        except Exception as e:
            logger.error(f"⚠️ 解析錯誤：{e}")
            logger.error(f"原始輸出：{output_text[:400]}...")
            continue

    # 批次插入資料庫
    saved_count = 0
    for art in all_articles:
        try:
            result = insert_article(art)
            if result.get("success"):
                title = art.get("title_zh") or art.get("title") or "未命名"
                article_generation_progress.titles.append(title)
                saved_count += 1
                logger.info(f"✅ 已儲存文章: {title}")
            else:
                logger.error(f"❌ 儲存文章失敗: {result.get('message', '未知錯誤')}")
        except Exception as e:
            logger.error(f"❌ 儲存文章時發生異常: {e}")

    logger.info(f"✅ 成功儲存 {saved_count}/{len(all_articles)} 篇雙語文章到資料庫")

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
                results.append(future.result())
            except Exception as e:
                logger.error(f"❌ 文章生成失敗：{e}")

    # 解析並儲存文章
    all_articles = []
    total_tokens_used = 0
    for idx, output_text, chosen_kws, prompt_zh, llm_metadata in sorted(results, key=lambda x: x[0]):
        # 累計 tokens 使用量
        total_tokens_used += llm_metadata.get("tokens_used", 0)
        try:
            match = re.search(r'\[.*\]', output_text, re.S)
            parsed = json.loads(match.group(0)) if match else json.loads(output_text)

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

        except Exception as e:
            logger.error(f"⚠️ 解析錯誤：{e}")
            logger.error(f"原始輸出：{output_text[:400]}...")
            continue

    logger.info(f"📊 解析完成，準備儲存 {len(all_articles)} 篇文章")

    # 批次插入資料庫
    saved_count = 0
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
                logger.error(f"❌ 儲存文章失敗: {result.get('message', '未知錯誤')}")
        except Exception as e:
            logger.error(f"❌ 儲存文章時發生異常: {e}", exc_info=True)

    logger.info(f"✅ 成功儲存 {saved_count}/{len(all_articles)} 篇雙語文章到資料庫")
    logger.info(f"📊 總 tokens 使用量: {total_tokens_used}")

    # 完成
    article_generation_progress.update(running=False, tokens_used=total_tokens_used)
    logger.info("🏁 background_generate_articles_by_source 任務完成")
