# 🚀 部署與驗證清單

## ✅ 部署前檢查

### 1. 環境準備
- [ ] Python 3.8+ 已安裝
- [ ] PostgreSQL 資料庫可訪問
- [ ] DeepSeek API 金鑰已取得
- [ ] Git 已安裝（可選）

### 2. 檔案完整性
- [ ] 所有新檔案已就位
  - [ ] `config.py`
  - [ ] `models/` 目錄及檔案
  - [ ] `services/` 目錄及檔案
  - [ ] `utils/` 目錄及檔案
  - [ ] 新的 `app.py`（460 行）
  - [ ] `app_old.py` 備份存在
  - [ ] `requirements.txt` 已更新（包含 flask-compress）

### 3. 配置設定
- [ ] 複製 `.env.example` 為 `.env`
- [ ] 填入 `DATABASE_URL`
- [ ] 填入 `DEEPSEEK_API_KEY`
- [ ] 檢查其他可選配置（如需要）

---

## 📦 安裝步驟

### 1. 安裝依賴
```bash
pip install -r requirements.txt
```

**檢查點：**
- [ ] 沒有安裝錯誤
- [ ] `flask-compress` 已安裝
- [ ] `psycopg2-binary` 已安裝

### 2. 資料庫初始化
```bash
# 方法 1: 訪問網頁
# http://localhost:5000/init_db

# 方法 2: Python 腳本
python -c "from services.database import init_database; init_database()"
```

**檢查點：**
- [ ] 資料表 `articles` 已建立
- [ ] 索引已建立（`idx_articles_created_at`, `idx_articles_keywords`）
- [ ] 雙語欄位存在（`title_zh`, `title_en` 等）

---

## 🧪 功能驗證

### 1. 啟動應用
```bash
python app.py
```

**預期輸出：**
```
🔧 初始化資料庫連接池...
✅ 資料庫連接池已初始化 (min=2, max=10)
🗄️ 初始化資料庫...
✅ 資料表初始化/升級完成（含索引）
🧹 啟動快取管理器...
📂 SWD 爬蟲資料夾: C:\...\crawler\swd_press
📂 HA 爬蟲資料夾: C:\...\crawler\ha_press
🚀 Flask 應用啟動中...
 * Running on http://0.0.0.0:5000
```

**檢查點：**
- [ ] 沒有錯誤訊息
- [ ] 連接池初始化成功
- [ ] 資料庫初始化成功
- [ ] 伺服器啟動成功

### 2. 測試首頁
訪問：http://localhost:5000

**檢查點：**
- [ ] 頁面正常載入
- [ ] 沒有 500 錯誤
- [ ] 連結可點擊

### 3. 測試資料庫連接
訪問：http://localhost:5000/test_db

**檢查點：**
- [ ] 顯示 PostgreSQL 版本
- [ ] 顯示資料表列表
- [ ] `articles` 表存在

### 4. 測試關鍵字頁面
訪問：http://localhost:5000/keywords

**檢查點：**
- [ ] 頁面正常載入
- [ ] 關鍵字列表顯示（或顯示載入中）
- [ ] 切換 SWD/HA 按鈕可用
- [ ] 爬蟲按鈕可用

### 5. 測試 SWD 爬蟲
點擊「📥 爬取 SWD 最新新聞稿」

**檢查點：**
- [ ] 進度條出現
- [ ] 進度訊息更新
- [ ] 完成後顯示成功訊息
- [ ] 關鍵字自動更新

### 6. 測試 HA 爬蟲
點擊「📥 爬取 HA 新聞稿」

**檢查點：**
- [ ] 進度條出現
- [ ] 進度訊息更新
- [ ] 完成後顯示成功訊息
- [ ] 關鍵字自動更新

### 7. 測試文章生成
1. 選擇 3-5 個關鍵字
2. 點擊「生成文章」

**檢查點：**
- [ ] 跳轉到生成頁面
- [ ] 進度顯示正確
- [ ] 文章標題逐一出現
- [ ] 完成後可查看 Prompts
- [ ] 資料庫中有新文章

### 8. 測試文章管理
訪問：http://localhost:5000/manage_articles

**檢查點：**
- [ ] 文章列表顯示
- [ ] 可查看單篇文章
- [ ] 可刪除文章
- [ ] 批次刪除功能正常

---

## 🔍 性能驗證

### 1. 資料庫連接池
```python
# Python console 測試
from services.database import get_db_connection, return_db_connection

# 取得多個連接
conns = [get_db_connection() for _ in range(5)]
print(f"取得 {len(conns)} 個連接")

# 歸還連接
for conn in conns:
    return_db_connection(conn)
print("已歸還所有連接")
```

**檢查點：**
- [ ] 可同時取得多個連接
- [ ] 連接數不超過最大值（10）
- [ ] 歸還後可重新取得

### 2. API 速率限制
觀察文章生成時的 API 呼叫間隔

**檢查點：**
- [ ] 每次呼叫間隔約 2 秒
- [ ] 沒有快速連續呼叫
- [ ] 日誌顯示「✅ DeepSeek API 呼叫成功」

### 3. 快取機制
1. 第一次生成文章（會讀取檔案）
2. 立即再次生成（應該使用快取）

**檢查點：**
- [ ] 第二次生成更快
- [ ] 日誌顯示「✅ 使用快取的文章資料」

### 4. 前端輪詢
觀察瀏覽器 Network 面板的輪詢頻率

**檢查點：**
- [ ] 初始間隔 1 秒
- [ ] 逐漸增加到 5 秒
- [ ] 任務完成後停止輪詢

---

## 📊 日誌檢查

### 查看日誌檔案
```bash
tail -f app.log
```

**應該看到：**
- [ ] 資訊級別日誌（INFO）
- [ ] 模組名稱（webapp, services.database 等）
- [ ] 時間戳記
- [ ] 清晰的訊息

### 常見日誌訊息
```
✅ 資料庫連接池已初始化
✅ 資料表初始化/升級完成
✅ 已快取文章資料
✅ DeepSeek API 呼叫成功
✅ 已儲存 X 關鍵字快取
```

---

## ⚠️ 常見問題處理

### 問題 1: 缺少環境變數
**錯誤訊息：**
```
ValueError: 缺少必要的環境變數: DATABASE_URL, DEEPSEEK_API_KEY
```

**解決方案：**
1. 確認 `.env` 檔案存在
2. 檢查檔案內容格式正確
3. 重新啟動應用

### 問題 2: 資料庫連接失敗
**錯誤訊息：**
```
❌ 資料庫連接池初始化失敗
```

**解決方案：**
1. 檢查 PostgreSQL 是否運行
2. 確認 DATABASE_URL 格式正確
3. 測試資料庫連接：
   ```bash
   psql "postgresql://user:password@host:port/dbname"
   ```

### 問題 3: 導入錯誤
**錯誤訊息：**
```
ModuleNotFoundError: No module named 'flask_compress'
```

**解決方案：**
```bash
pip install -r requirements.txt --force-reinstall
```

### 問題 4: 爬蟲失敗
**錯誤訊息：**
```
❌ 爬蟲執行錯誤
```

**解決方案：**
1. 檢查網路連接
2. 確認目標網站可訪問
3. 查看詳細錯誤日誌：`tail -100 app.log`

---

## 📈 效能基準測試

### 建議的測試場景
1. **並發文章生成**
   - 選擇 10 個關鍵字
   - 觀察完成時間
   - 預期：約 60-80 秒（3 工作執行緒 + 速率限制）

2. **資料庫查詢**
   - 管理頁面載入時間
   - 預期：<500ms（有索引）

3. **快取效果**
   - 首次生成 vs 第二次生成
   - 預期：第二次快 80%

4. **記憶體使用**
   - 觀察長時間運行後的記憶體
   - 預期：穩定（快取管理器會定期清理）

---

## ✅ 最終檢查清單

### 功能完整性
- [ ] 所有路由正常工作
- [ ] 爬蟲功能正常
- [ ] 關鍵字提取正常
- [ ] 文章生成正常
- [ ] 資料庫操作正常

### 性能指標
- [ ] 資料庫連接池運作正常
- [ ] API 速率限制生效
- [ ] 快取機制運作
- [ ] 前端輪詢優化生效

### 程式碼品質
- [ ] 無明顯錯誤或警告
- [ ] 日誌訊息清晰
- [ ] 錯誤處理適當

### 文件完整性
- [ ] README_REFACTORING.md 存在
- [ ] REFACTORING_SUMMARY.md 存在
- [ ] .env.example 存在
- [ ] 此檢查清單完成

---

## 🎉 部署成功！

如果所有檢查項目都通過，恭喜！系統已成功重構並部署。

### 後續步驟
1. 監控日誌檔案 `app.log`
2. 定期檢查效能指標
3. 根據需要調整配置參數
4. 計劃未來的改進（見 README_REFACTORING.md）

### 遇到問題？
1. 查看 `app.log` 日誌
2. 參考 README_REFACTORING.md 的常見問題
3. 檢查 REFACTORING_SUMMARY.md 的技術細節
4. 回滾到 `app_old.py` 作為緊急備案

---

**日期**: 2026-01-31
**版本**: 2.0
**狀態**: ✅ 部署驗證完成
