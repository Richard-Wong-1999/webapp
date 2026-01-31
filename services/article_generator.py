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
from services.keyword_extractor import (
    get_recent_articles_text,
    get_relevant_reference_blocks
)
from services.database import insert_article
from models import ProgressTracker

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
    for art in all_articles:
        result = insert_article(art)
        if result.get("success"):
            title = art.get("title_zh") or art.get("title") or "未命名"
            article_generation_progress.titles.append(title)

    logger.info(f"✅ 成功儲存 {len(all_articles)} 篇雙語文章到資料庫")

    # 完成
    article_generation_progress.update(running=False)
