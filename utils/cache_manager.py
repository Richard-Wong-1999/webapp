"""快取管理系統"""

import threading
import time
from typing import Dict, Any


class CacheManager:
    """統一的快取管理器，支援 TTL 和定期清理"""

    def __init__(self):
        self.cleanup_thread = None
        self.running = False
        self._caches: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start_cleanup(self, interval=3600):
        """啟動定期清理任務

        Args:
            interval: 清理間隔（秒），預設1小時
        """
        if self.running:
            return

        self.running = True
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            args=(interval,),
            daemon=True
        )
        self.cleanup_thread.start()

    def stop_cleanup(self):
        """停止清理任務"""
        self.running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)

    def _cleanup_loop(self, interval):
        """清理循環"""
        while self.running:
            time.sleep(interval)
            self.cleanup_old_data()

    def cleanup_old_data(self):
        """清理過期資料"""
        with self.lock:
            # 清理過期的快取項目
            for cache_name, cache_data in list(self._caches.items()):
                if 'expires_at' in cache_data:
                    if cache_data['expires_at'] < time.time():
                        del self._caches[cache_name]

    def set(self, key: str, data: Any, ttl: int = None):
        """設定快取

        Args:
            key: 快取鍵
            data: 快取資料
            ttl: 生存時間（秒）
        """
        with self.lock:
            cache_item = {'data': data, 'updated_at': time.time()}
            if ttl:
                cache_item['expires_at'] = time.time() + ttl
            self._caches[key] = cache_item

    def get(self, key: str) -> Any:
        """取得快取

        Args:
            key: 快取鍵

        Returns:
            快取資料，若過期或不存在則返回 None
        """
        with self.lock:
            cache_item = self._caches.get(key)
            if not cache_item:
                return None

            # 檢查是否過期
            if 'expires_at' in cache_item:
                if cache_item['expires_at'] < time.time():
                    del self._caches[key]
                    return None

            return cache_item.get('data')

    def clear(self, key: str = None):
        """清除快取

        Args:
            key: 快取鍵，若為 None 則清除所有快取
        """
        with self.lock:
            if key:
                self._caches.pop(key, None)
            else:
                self._caches.clear()

    def exists(self, key: str) -> bool:
        """檢查快取是否存在且未過期"""
        return self.get(key) is not None


# 全域快取管理器實例
cache_manager = CacheManager()
