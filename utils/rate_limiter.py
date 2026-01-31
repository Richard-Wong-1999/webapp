"""API 呼叫速率限制器"""

import threading
import time


class RateLimiter:
    """線程安全的速率限制器"""

    def __init__(self, calls_per_second=0.5):
        """
        初始化速率限制器

        Args:
            calls_per_second: 每秒允許的呼叫次數（0.5 = 每2秒1次）
        """
        self.min_interval = 1.0 / calls_per_second if calls_per_second > 0 else 0
        self.last_call = 0
        self.lock = threading.Lock()

    def wait(self):
        """等待至允許下次呼叫的時間"""
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time.sleep(sleep_time)
            self.last_call = time.time()

    def reset(self):
        """重置計時器"""
        with self.lock:
            self.last_call = 0
