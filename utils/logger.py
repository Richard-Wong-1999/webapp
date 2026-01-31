"""日誌系統配置"""

import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logger(app_name="webapp", log_level=logging.INFO):
    """配置應用日誌系統

    Args:
        app_name: Logger 名稱
        log_level: 日誌級別

    Returns:
        配置好的 logger 實例
    """
    logger = logging.getLogger(app_name)
    logger.setLevel(log_level)

    # 避免重複添加 handler
    if logger.handlers:
        return logger

    # Console handler - 輸出到控制台
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # File handler - 輸出到檔案（10MB，保留5個檔案）
    try:
        file_handler = RotatingFileHandler(
            "app.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
    except Exception as e:
        print(f"⚠️ 無法創建日誌檔案：{e}")
        file_handler = None

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    if file_handler:
        file_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(console_handler)
    if file_handler:
        logger.addHandler(file_handler)

    return logger


# 全域 logger 實例
logger = setup_logger()
