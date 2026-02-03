# Gunicorn 配置文件
# 用於 Render 部署，解決多 worker 進程導致的全局變量不共享問題

# 單 worker 模式 - 確保全局變量在所有請求間共享
workers = 1

# 使用多線程處理並發請求（替代多進程）
threads = 8

# 超時設置（爬蟲任務需要較長時間）
timeout = 300  # 5 分鐘

# 綁定地址（Render 會通過 PORT 環境變量指定端口）
import os
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Worker 類型
worker_class = "sync"

# 日誌設置
accesslog = "-"
errorlog = "-"
loglevel = "info"

# 預載入應用（減少記憶體使用）
preload_app = True

# 優雅關閉超時
graceful_timeout = 30
