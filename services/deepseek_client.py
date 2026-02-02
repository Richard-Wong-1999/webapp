"""DeepSeek API 客戶端"""

import requests
from config import Config
from utils.logger import logger
from utils.rate_limiter import RateLimiter

# 全域速率限制器（每2秒1次請求）
api_limiter = RateLimiter(calls_per_second=Config.API_RATE_LIMIT)


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
        logger.error("❌ 未載入 DEEPSEEK_API_KEY，請檢查 .env 檔案")
        return ""

    # 速率限制
    api_limiter.wait()

    # 使用指定模型或預設模型
    use_model = model or Config.DEEPSEEK_MODEL

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
            logger.info(f"✅ DeepSeek API ({use_model}) 呼叫成功（{len(content)} 字元）")
            return content
        else:
            logger.error(f"❌ DeepSeek 錯誤：{response.status_code} - {response.text}")
            return ""

    except requests.Timeout:
        logger.error("⚠️ DeepSeek API 呼叫逾時")
        return ""
    except Exception as e:
        logger.error(f"⚠️ 呼叫 DeepSeek 失敗：{e}")
        return ""


def reset_rate_limiter():
    """重置速率限制器（用於測試或重置）"""
    api_limiter.reset()
