"""Poe API 客戶端"""

import re
import requests
from config import Config
from utils.logger import logger
from utils.rate_limiter import RateLimiter
from utils.retry import retry_with_backoff

# Poe API 速率限制器
poe_limiter = RateLimiter(calls_per_second=Config.API_RATE_LIMIT)


@retry_with_backoff(max_retries=3, base_delay=2, max_delay=30)
def call_poe(prompt_text: str, model: str = "GPT-4o") -> tuple:
    """
    呼叫 Poe API

    Args:
        prompt_text: 提示文本
        model: 模型名稱（如 GPT-4o, Claude-3.5-Sonnet 等）

    Returns:
        tuple: (內容, 使用的 tokens)
    """
    if not Config.POE_API_KEY:
        logger.error("❌ [Poe] 未載入 POE_API_KEY，請檢查 .env 檔案")
        return "", 0

    prompt_len = len(prompt_text)
    logger.info(f"🔄 [Poe] 開始 API 呼叫：model={model}，prompt 長度={prompt_len} 字元")

    poe_limiter.wait()

    headers = {
        "Authorization": f"Bearer {Config.POE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": Config.DEEPSEEK_TEMPERATURE,
        "max_tokens": Config.DEEPSEEK_MAX_TOKENS
    }

    try:
        response = requests.post(
            Config.POE_API_URL,
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

            # 過濾 thinking 內容
            content = filter_thinking_content(content)

            logger.info(f"✅ [Poe] API 呼叫成功：model={model}")
            logger.info(f"📊 [Poe] 響應統計：輸出={len(content)} 字元，tokens（prompt={prompt_tokens}, completion={completion_tokens}, total={tokens_used}）")
            return content, tokens_used
        else:
            logger.error(f"❌ [Poe] API 錯誤：HTTP {response.status_code} - {response.text[:200]}")
            return "", 0

    except requests.Timeout:
        logger.error(f"⚠️ [Poe] API 呼叫逾時：model={model}，timeout={Config.DEEPSEEK_TIMEOUT}s")
        return "", 0
    except Exception as e:
        logger.error(f"⚠️ [Poe] API 呼叫失敗：model={model}，錯誤={e}")
        return "", 0


def filter_thinking_content(content: str) -> str:
    """
    過濾 thinking/chain-of-thought 內容

    移除常見的 thinking 標記：
    - <thinking>...</thinking>
    - <think>...</think>
    - [Thinking]...[/Thinking]
    """
    if not content:
        return content

    # 移除 <thinking>...</thinking> 標籤
    content = re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL | re.IGNORECASE)

    # 移除 <think>...</think> 標籤
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL | re.IGNORECASE)

    # 移除 [Thinking]...[/Thinking] 標記
    content = re.sub(r'\[thinking\].*?\[/thinking\]', '', content, flags=re.DOTALL | re.IGNORECASE)

    # 清理多餘空行
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip()
