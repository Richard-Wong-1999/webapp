"""文章評分服務"""

import json
import re
import time
from utils.logger import logger
from config import Config
from services.llm_client import call_llm
from services.database import get_article_by_id, update_article_score
from prompts.score_prompt import build_score_prompt


def extract_reference_from_prompt(prompt_zh: str) -> str:
    """從儲存的 prompt_zh 中提取參考資料內容"""
    if not prompt_zh:
        return "（參考資料不可用）"

    match = re.search(r'---\n## .+?\n(.*?)---\n## 主題關鍵詞', prompt_zh, re.DOTALL)
    if match:
        content = match.group(1).strip()
        if content:
            return content

    return "（參考資料不可用）"


def build_article_json_for_scoring(article: dict) -> str:
    """從資料庫記錄重建文章 JSON，用於評分"""
    keywords = []
    if article.get("keywords"):
        try:
            kw = article["keywords"]
            if isinstance(kw, str):
                keywords = json.loads(kw)
            elif isinstance(kw, list):
                keywords = kw
        except (json.JSONDecodeError, TypeError):
            keywords = []

    article_data = [{
        "zh": {
            "title": article.get("title_zh") or article.get("title") or "",
            "body": article.get("body_zh") or article.get("body") or "",
            "meta_title": article.get("meta_title_zh") or article.get("meta_title") or "",
            "meta_description": article.get("meta_description_zh") or article.get("meta_description") or ""
        },
        "en": {
            "title": article.get("title_en") or "",
            "body": article.get("body_en") or "",
            "meta_title": article.get("meta_title_en") or "",
            "meta_description": article.get("meta_description_en") or ""
        },
        "keywords": keywords
    }]

    return json.dumps(article_data, ensure_ascii=False, indent=2)


def score_single_article(article_id: int, keywords_str: str, prompt_zh: str,
                          llm_provider: str = None, llm_model: str = None) -> dict:
    """對單篇文章進行評分"""
    llm_provider = llm_provider or Config.DEFAULT_PROVIDER
    llm_model = llm_model or Config.SCORING_MODEL

    logger.info(f"🎯 開始評分文章 ID={article_id}")

    # 1. 取得文章
    article = get_article_by_id(article_id)
    if not article:
        logger.error(f"❌ 評分失敗：找不到文章 ID={article_id}")
        return {"success": False, "error": "文章不存在"}

    # 2. 提取參考資料
    reference_content = extract_reference_from_prompt(prompt_zh)

    # 3. 重建文章 JSON
    article_json = build_article_json_for_scoring(article)

    # 4. 構建評分 prompt
    score_prompt = build_score_prompt(keywords_str, reference_content, article_json)

    # 5. 呼叫 LLM
    try:
        output, metadata = call_llm(score_prompt, provider=llm_provider, model=llm_model)
    except Exception as e:
        logger.error(f"❌ 評分 LLM 呼叫失敗 ID={article_id}: {e}")
        return {"success": False, "error": str(e)}

    if not output:
        logger.error(f"❌ 評分 LLM 回應為空 ID={article_id}")
        return {"success": False, "error": "LLM 回應為空"}

    # 6. 解析 JSON 回應
    try:
        # 清理 markdown 代碼塊
        cleaned = output.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)

        # 嘗試直接解析
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # 使用 regex 提取 JSON object
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                raise ValueError("無法從回應中提取 JSON")

        # 由程式計算總分，不信任 AI 輸出的 final_score
        deductions = result.get("deduction_log", [])
        total_deducted = sum(abs(d.get("deducted_points", 0)) for d in deductions)
        final_score = max(0, 100 - total_deducted)
        status = "APPROVED" if final_score >= 90 else "REJECTED"
        result["final_score"] = final_score
        result["status"] = status
        score_result_json = json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ 評分 JSON 解析失敗 ID={article_id}: {e}")
        logger.debug(f"原始回應: {output[:500]}")
        return {"success": False, "error": f"JSON 解析失敗: {e}"}

    # 7. 儲存評分結果
    try:
        update_article_score(article_id, final_score, score_result_json, score_prompt)
        logger.info(f"✅ 文章 ID={article_id} 評分完成: {final_score} 分 ({result.get('status', '')})")
        return {"success": True, "score": final_score}
    except Exception as e:
        logger.error(f"❌ 評分結果儲存失敗 ID={article_id}: {e}")
        return {"success": False, "error": str(e)}


def background_score_articles(articles_to_score: list, llm_provider: str = None, llm_model: str = None):
    """背景批次評分文章

    Args:
        articles_to_score: [(article_id, keywords_str, prompt_zh), ...]
        llm_provider: LLM 提供者
        llm_model: LLM 模型
    """
    total = len(articles_to_score)
    logger.info(f"🎯 背景評分開始: 共 {total} 篇文章")

    success_count = 0
    for i, (article_id, keywords_str, prompt_zh) in enumerate(articles_to_score, 1):
        logger.info(f"🎯 評分進度: {i}/{total} (ID={article_id})")

        result = score_single_article(article_id, keywords_str, prompt_zh, llm_provider, llm_model)
        if result.get("success"):
            success_count += 1

        # 避免 API 限流
        if i < total:
            time.sleep(2)

    logger.info(f"🎯 背景評分完成: {success_count}/{total} 篇成功")
