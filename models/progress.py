"""進度追蹤資料模型"""

from dataclasses import dataclass, field
from typing import List
import threading
import time


@dataclass
class ProgressTracker:
    """統一的進度追蹤器"""

    name: str
    total: int = 0
    completed: int = 0
    running: bool = False
    timestamp: str = ""
    status: str = "idle"
    message: str = ""
    titles: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    # 診斷追蹤欄位
    failed_keywords: List[str] = field(default_factory=list)  # 失敗的關鍵字
    parse_failures: List[dict] = field(default_factory=list)  # JSON 解析失敗詳情
    tokens_used: int = 0  # Token 使用量
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, **kwargs):
        """線程安全的批次更新"""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key) and not key.startswith('_'):
                    setattr(self, key, value)

    def increment(self, title: str = None):
        """線程安全的完成計數增加"""
        with self._lock:
            self.completed += 1
            if title and self.titles is not None:
                self.titles.append(title)

    def add_error(self, error: str):
        """添加錯誤訊息"""
        with self._lock:
            if self.errors is not None:
                self.errors.append(error)

    def add_failed_keyword(self, keyword: str, reason: str):
        """記錄失敗的關鍵字"""
        with self._lock:
            if self.failed_keywords is not None:
                self.failed_keywords.append(f"{keyword}: {reason}")

    def add_parse_failure(self, keyword: str, error: str, raw_output_snippet: str):
        """記錄 JSON 解析失敗的詳情"""
        with self._lock:
            if self.parse_failures is not None:
                self.parse_failures.append({
                    "keyword": keyword,
                    "error": str(error),
                    "raw_output": raw_output_snippet[:500] if raw_output_snippet else ""
                })

    def to_dict(self):
        """轉換為字典（用於 JSON 序列化）"""
        with self._lock:
            return {
                "total": self.total,
                "completed": self.completed,
                "running": self.running,
                "timestamp": self.timestamp,
                "status": self.status,
                "message": self.message,
                "titles": self.titles[-100:] if self.titles else [],  # 只保留最近100個
                "errors": self.errors[-50:] if self.errors else [],  # 只保留最近50個
                "failed_keywords": self.failed_keywords[-50:] if self.failed_keywords else [],
                "parse_failures": self.parse_failures[-20:] if self.parse_failures else [],
                "tokens_used": self.tokens_used
            }

    def reset(self):
        """重置進度"""
        with self._lock:
            self.total = 0
            self.completed = 0
            self.running = False
            self.timestamp = ""
            self.status = "idle"
            self.message = ""
            self.tokens_used = 0
            if self.titles:
                self.titles.clear()
            if self.errors:
                self.errors.clear()
            if self.failed_keywords:
                self.failed_keywords.clear()
            if self.parse_failures:
                self.parse_failures.clear()
