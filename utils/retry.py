"""重試機制工具

提供指數退避重試裝飾器，用於處理網絡請求的臨時失敗
"""

import time
from functools import wraps
import requests
from utils.logger import logger


def retry_with_backoff(max_retries=3, base_delay=2, max_delay=30):
    """指數退避重試裝飾器

    當函數因網絡錯誤（Timeout, ConnectionError）失敗時，
    自動重試並使用指數退避策略等待。

    Args:
        max_retries: 最大重試次數（預設 3）
        base_delay: 基礎延遲秒數（預設 2）
        max_delay: 最大延遲秒數（預設 30）

    Returns:
        裝飾器函數

    使用範例:
        @retry_with_backoff(max_retries=3, base_delay=2)
        def call_api():
            return requests.get(url)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.Timeout, requests.ConnectionError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(f"嘗試 {attempt + 1} 失敗，{delay} 秒後重試: {e}")
                        time.sleep(delay)
            logger.error(f"重試 {max_retries} 次後仍然失敗")
            raise last_exception
        return wrapper
    return decorator
