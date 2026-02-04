"""DeepSeek API 客戶端"""

import requests
from config import Config
from utils.logger import logger
from utils.rate_limiter import RateLimiter
from utils.retry import retry_with_backoff

# 全域速率限制器（每2秒1次請求）
api_limiter = RateLimiter(calls_per_second=Config.API_RATE_LIMIT)


@retry_with_backoff(max_retries=3, base_delay=2, max_delay=30)
def call_deepseek(prompt_text: str, model: str = None, temperature: float = None, max_tokens: int = None) -> str:
    """呼叫 DeepSeek API

    Args:
        prompt_text: 提示文本
        model: 模型名稱（可選，預設使用 Config.DEEPSEEK_MODEL）
        temperature: 溫度參數（可選）
        max_tokens: 最大 token 數（可選）

    Returns:
        API 回應文本，失敗則返回空字串
    """
    if not Config.DEEPSEEK_API_KEY:
        logger.error("❌ [DeepSeek] 未載入 DEEPSEEK_API_KEY，請檢查 .env 檔案")
        return ""

    # 使用指定模型或預設模型
    use_model = model or Config.DEEPSEEK_MODEL
    prompt_len = len(prompt_text)
    logger.info(f"🔄 [DeepSeek] 開始 API 呼叫：model={use_model}，prompt 長度={prompt_len} 字元")

    # 速率限制
    api_limiter.wait()

    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": use_model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": temperature or Config.DEEPSEEK_TEMPERATURE,
        "max_tokens": max_tokens or Config.DEEPSEEK_MAX_TOKENS
    }

    try:
        response = requests.post(
            Config.DEEPSEEK_API_URL,
            headers=headers,
            json=payload,
            timeout=Config.DEEPSEEK_TIMEOUT
        )

        if response.status_code == 200:
            res = response.json()
            content = res["choices"][0]["message"]["content"].strip()
            tokens_used = res.get("usage", {}).get("total_tokens", 0)
            prompt_tokens = res.get("usage", {}).get("prompt_tokens", 0)
            completion_tokens = res.get("usage", {}).get("completion_tokens", 0)

            logger.info(f"✅ [DeepSeek] API 呼叫成功：model={use_model}")
            logger.info(f"📊 [DeepSeek] 響應統計：輸出={len(content)} 字元，tokens（prompt={prompt_tokens}, completion={completion_tokens}, total={tokens_used}）")
            return content
        else:
            logger.error(f"❌ [DeepSeek] API 錯誤：HTTP {response.status_code} - {response.text[:200]}")
            return ""

    except requests.Timeout:
        logger.error(f"⚠️ [DeepSeek] API 呼叫逾時：model={use_model}，timeout={Config.DEEPSEEK_TIMEOUT}s")
        return ""
    except Exception as e:
        logger.error(f"⚠️ [DeepSeek] API 呼叫失敗：model={use_model}，錯誤={e}")
        return ""


def reset_rate_limiter():
    """重置速率限制器（用於測試或重置）"""
    api_limiter.reset()
