"""快取管理系統"""

import threading
import time
from typing import Dict, Any
from utils.logger import logger


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
        cleaned_count = 0
        with self.lock:
            # 清理過期的快取項目
            for cache_name, cache_data in list(self._caches.items()):
                if 'expires_at' in cache_data:
                    if cache_data['expires_at'] < time.time():
                        del self._caches[cache_name]
                        cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"🧹 [CacheManager] 清理過期快取：已移除 {cleaned_count} 項")

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

            # 檢查快取大小警告
            cache_count = len(self._caches)
            if cache_count > 100:
                logger.warning(f"⚠️ [CacheManager] 快取數量較多：{cache_count} 項，建議檢查清理策略")

        logger.debug(f"✅ [CacheManager] 快取寫入：key={key}，TTL={ttl}s")

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
                logger.debug(f"ℹ️ [CacheManager] 快取未命中：key={key}")
                return None

            # 檢查是否過期
            if 'expires_at' in cache_item:
                if cache_item['expires_at'] < time.time():
                    del self._caches[key]
                    logger.debug(f"⏰ [CacheManager] 快取已過期：key={key}")
                    return None

            logger.debug(f"✅ [CacheManager] 快取命中：key={key}")
            return cache_item.get('data')

    def clear(self, key: str = None):
        """清除快取

        Args:
            key: 快取鍵，若為 None 則清除所有快取
        """
        with self.lock:
            if key:
                removed = self._caches.pop(key, None)
                if removed:
                    logger.debug(f"🗑️ [CacheManager] 清除快取：key={key}")
            else:
                count = len(self._caches)
                self._caches.clear()
                logger.info(f"🗑️ [CacheManager] 清除所有快取：已移除 {count} 項")

    def exists(self, key: str) -> bool:
        """檢查快取是否存在且未過期"""
        return self.get(key) is not None


# 全域快取管理器實例
cache_manager = CacheManager()
