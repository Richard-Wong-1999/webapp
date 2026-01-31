# Render 部署配置指南

## 問題診斷

如果 SEO 功能無法運作，請訪問：`https://your-app.onrender.com/debug/seo`

這個診斷頁面會顯示：
1. DataForSEO API 配置狀態
2. Selenium/Chrome 安裝狀態
3. 提供測試工具

---

## 1. DataForSEO API 配置（SEO 關鍵字研究）

### 在 Render Dashboard 中設置環境變數：

```
DATAFORSEO_LOGIN=your_dataforseo_login
DATAFORSEO_PASSWORD=your_dataforseo_password
```

### 獲取憑證：
1. 訪問 [DataForSEO](https://dataforseo.com/)
2. 註冊帳號
3. 在 Dashboard 中獲取 API 憑證

### 測試方法：
訪問 `/debug/seo` 頁面，點擊「測試 API 連接」按鈕

---

## 2. Google Trends 爬蟲配置（右側面板）

### 步驟 1：創建 `aptfile`

在專案根目錄創建 `aptfile` 文件（已包含在此專案中）：

```
chromium
chromium-driver
```

### 步驟 2：確認 `requirements.txt` 包含

```
selenium==4.16.0
webdriver-manager==4.0.1
```

### 步驟 3：修改 `crawler/google_trends.py`

將 Chrome 選項改為指向 Chromium：

```python
chrome_opts = Options()
chrome_opts.add_argument("--headless=new")
chrome_opts.add_argument("--no-sandbox")
chrome_opts.add_argument("--disable-dev-shm-usage")
chrome_opts.binary_location = "/usr/bin/chromium"  # 添加這行
```

並且修改 driver 初始化：

```python
from selenium.webdriver.chrome.service import Service

# 使用系統的 chromium-driver
driver = webdriver.Chrome(
    service=Service("/usr/bin/chromedriver"),
    options=chrome_opts
)
```

### 步驟 4：在 Render 重新部署

1. 提交 `aptfile` 到 Git
2. 推送到 GitHub
3. Render 會自動重新部署並安裝 Chromium

---

## 3. 驗證部署

部署完成後，訪問 `/debug/seo` 檢查：

### DataForSEO API 檢查：
- ✅ 已配置：Login 顯示前4碼和後4碼
- ✅ 測試成功：點擊「測試 API 連接」應該返回成功

### Selenium/Chrome 檢查：
- ✅ Selenium 已安裝
- ✅ Chrome/Chromium 顯示版本號
- ✅ 測試成功：點擊「測試 Selenium」應該返回成功

---

## 4. 常見問題

### 問題 1：DataForSEO API 返回 401
**原因**：憑證錯誤
**解決**：
1. 檢查 Render 環境變數是否正確
2. 確認 DataForSEO 帳號是否啟用
3. 訪問 DataForSEO Dashboard 確認憑證

### 問題 2：Selenium 找不到 Chrome
**原因**：未安裝 Chromium 或路徑錯誤
**解決**：
1. 確認 `aptfile` 已提交到 Git
2. 在 Render 重新部署
3. 檢查 Render 日誌是否有 apt 安裝錯誤

### 問題 3：Google Trends 返回空數據
**原因**：
- 該關鍵字在香港地區搜尋量過低
- API 限制或延遲

**解決**：
1. 嘗試更熱門的關鍵字（如：「長者」、「健康」）
2. 檢查 Render 日誌中的詳細錯誤訊息

---

## 5. 查看 Render 日誌

1. 登入 Render Dashboard
2. 選擇你的 Web Service
3. 點擊 "Logs" 標籤
4. 搜尋關鍵字：
   - `[Trends]` - Google Trends API 日誌
   - `[Metrics]` - 關鍵字指標日誌
   - `DataForSEO` - API 錯誤

---

## 6. 本地測試

在本地測試 SEO 功能：

```bash
# 設置環境變數
export DATAFORSEO_LOGIN=your_login
export DATAFORSEO_PASSWORD=your_password

# 啟動應用
python app.py

# 訪問診斷頁面
open http://localhost:5000/debug/seo
```

---

## 聯繫支援

如果問題仍未解決：
1. 截圖 `/debug/seo` 頁面
2. 複製 Render 日誌（最近 100 行）
3. 提供測試的關鍵字
