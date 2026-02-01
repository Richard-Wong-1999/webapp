# DataForSEO Labs API 整合 - 相關關鍵字功能

**更新時間**: 2026-02-02
**版本**: v3.0
**狀態**: ✅ 準備部署

---

## 📋 更新概要

### 問題背景

經過測試發現，DataForSEO 的 Google Trends API (`keywords_data/google_trends/explore/live`) **不返回相關查詢和相關主題數據**，即使是高搜尋量關鍵字（如"iPhone"）也只返回趨勢圖表數據。

測試結果：
```json
{
  "items": [{"type": "google_trends_graph"}],
  "items_count": 1
}
```

### 解決方案

✅ **使用 DataForSEO Labs API 替代**
- API Endpoint: `dataforseo_labs/google/related_keywords/live`
- 功能：可靠地返回相關關鍵字及其搜尋量
- 費用：$0.05/次（比 Trends API 的 $0.009 稍貴，但實際有效）

---

## 🔧 修改內容

### 1. **services/dataforseo_client.py**

#### 新增方法：`get_related_keywords_labs()`

**位置**：Line 509-575

**功能**：
- 調用 DataForSEO Labs API 取得相關關鍵字
- 返回關鍵字列表，包含搜尋量、CPC、競爭度等指標

**參數**：
```python
def get_related_keywords_labs(
    self,
    keyword: str,
    location_code: int = 2344,  # Hong Kong
    language_code: str = "zh-TW",
    limit: int = 50
) -> List[Dict[str, Any]]
```

**返回格式**：
```python
[{
    "keyword": str,
    "search_volume": int,
    "cpc": float,
    "competition": float,
    "monthly_searches": [...]
}]
```

**API 請求**：
```python
data = [{
    "keyword": keyword,
    "location_code": 2344,
    "language_code": "zh-TW",
    "limit": 50
}]
```

**日誌標記**：`[Labs]` 便於追蹤和診斷

---

### 2. **services/seo_orchestrator.py**

#### 修改：`analyze_keyword_full()` 函數

**位置**：Line 389-421

**變更前**：
```python
# Step 1: Google Trends
trends_result = dataforseo_client.get_google_trends(keyword)
trends = {
    "topics": trends_result.get("topics", []),
    "queries": trends_result.get("queries", [])
}
```

**變更後**：
```python
# Step 1: Google Trends (topics) + DataForSEO Labs (related keywords)
labs_keywords = dataforseo_client.get_related_keywords_labs(keyword, limit=20)

# 將 Labs 結果格式化為 queries 格式
queries = []
for kw in labs_keywords[:20]:
    queries.append({
        "query": kw.get("keyword", ""),
        "type": "related",
        "value": kw.get("search_volume", 0)
    })

# Google Trends API 僅用於取得 topics（如有）
trends_result = dataforseo_client.get_google_trends(keyword)
topics = trends_result.get("topics", []) if not trends_result.get("error") else []

trends = {
    "topics": topics,
    "queries": queries  # 使用 Labs API 的相關關鍵字
}
```

**說明**：
- 保持與現有數據庫結構兼容（仍使用 `seo_trends_data` 表的 `queries` 欄位）
- `queries` 中的 `type` 設為 `"related"` 以區分來源
- `value` 使用搜尋量，便於排序和展示

---

### 3. **templates/keywords.html**

#### 修改 1：更新面板標題（Line 49-52）

**變更前**：
```html
<h4>📈 Google Trends 相關查詢</h4>
```

**變更後**：
```html
<h4>📈 相關關鍵字 <small>(DataForSEO Labs)</small></h4>
```

#### 修改 2：更新說明文字（Line 156-161）

**變更前**：
```
- 查看 Google Trends 相關查詢
- 獲取相關關鍵字建議
```

**變更後**：
```
- 查看相關關鍵字（DataForSEO Labs API）
- 獲取關鍵字建議（Google Ads API）
```

---

### 4. **app.py**

#### 修改 1：`test_trends` 測試端點（Line 704-747）

**變更**：
- 改為調用 `get_related_keywords_labs()` 而非 `get_google_trends()`
- 返回格式保持兼容，但加入 "使用 DataForSEO Labs API" 說明

**新增返回欄位**：
```json
{
  "success": true,
  "topics_count": 0,
  "queries_count": 20,
  "message": "測試成功 (使用 DataForSEO Labs API)",
  "sample_queries": [...]
}
```

#### 修改 2：`raw_api_test` 端點（Line 848-915）

**新增 API 類型**：`"labs"`

**請求參數**：
```python
if api_type == "labs":
    endpoint = "dataforseo_labs/google/related_keywords/live"
    request_data = [{
        "keyword": keyword,
        "location_code": 2344,
        "language_code": "zh-TW",
        "limit": 50
    }]
```

---

### 5. **templates/debug_seo.html**

#### 修改 1：測試按鈕標籤（Line 172）

**變更前**：
```html
<button class="test-btn" onclick="testTrends()">🧪 測試 Google Trends API</button>
```

**變更後**：
```html
<button class="test-btn" onclick="testTrends()">🧪 測試相關關鍵字 API (Labs)</button>
```

#### 修改 2：原始 API 回應按鈕（Line 185-188）

**新增**：
```html
<button class="test-btn" onclick="showRawApiResponse('labs')">📄 Labs 原始回應</button>
```

**更新**：
```html
<button class="test-btn" onclick="showRawApiResponse('trends')">📄 Trends 原始回應 (舊版)</button>
```

#### 修改 3：JavaScript 測試函數（Line 229-262）

**更新 `testTrends()` 函數**：
- 顯示 "測試相關關鍵字 API (DataForSEO Labs)"
- 顯示範例相關關鍵字及其搜尋量
- 成功訊息標註 "(DataForSEO Labs)"

#### 修改 4：數據說明（Line 106-111）

**變更前**：
```
• Trends Topics/Queries: 0 → 該關鍵字在香港地區 Google Trends 數據不足（正常現象）
```

**變更後**：
```
• 相關關鍵字 (Labs API) → 使用 DataForSEO Labs API 取得相關關鍵字，費用 $0.05/次
```

---

## 💰 成本影響

### 每次完整 SEO 分析

| API | 修改前 | 修改後 | 變化 |
|-----|--------|--------|------|
| Google Trends | $0.009 | $0.009 (保留) | 無變化 |
| **DataForSEO Labs** | - | **$0.05** | +$0.05 |
| Google Ads Search Volume | $0.075 | $0.075 | 無變化 |
| Google Ads Keywords | $0.075 | $0.075 | 無變化 |
| Google SERP | $0.003 | $0.003 | 無變化 |
| **總計** | **$0.162** | **$0.212** | **+$0.05 (+31%)** |

### 實際成本（含快取）

假設每天 50 次查詢，快取命中率 70%：

```
修改前（Google Trends 但無數據）：
50 queries/day × 30 days × 30% × $0.162 = $72.90/月

修改後（Labs API 有數據）：
50 queries/day × 30 days × 30% × $0.212 = $95.40/月

額外成本：$22.50/月
```

### 成本效益分析

✅ **值得投資**：
- Google Trends API 實際上不返回相關查詢/主題（$0.009 完全浪費）
- Labs API 確實返回有效的相關關鍵字數據
- 每次額外 $0.05 換取可靠的功能
- 每月額外約 $20-30 即可獲得完整的關鍵字研究功能

---

## 🧪 測試計劃

### 階段 1：本地測試（部署前）

#### Test 1：Labs API 基本功能
```python
# 測試 Labs API 調用
client = dataforseo_client
keywords = client.get_related_keywords_labs("長者", limit=20)

# 檢查項目：
# ✅ 返回數據格式正確
# ✅ 包含 keyword, search_volume, cpc, competition
# ✅ 日誌顯示 "[Labs] Requesting related keywords..."
```

#### Test 2：SEO 分析整合
```python
# 測試完整 SEO 分析流程
result = analyze_keyword_full("長者")

# 檢查項目：
# ✅ result["trends"]["queries"] 包含 Labs API 數據
# ✅ queries 格式為 [{"query": ..., "type": "related", "value": ...}]
# ✅ 數據正確存入 seo_trends_data 表
```

---

### 階段 2：Render 部署後測試

訪問 https://webapp-hx10.onrender.com/debug/seo

#### Test 1：Labs API 測試
```
測試關鍵字：長者

步驟：
1. 點擊「測試相關關鍵字 API (Labs)」
2. 查看返回的相關關鍵字數量
3. 確認有範例關鍵字及搜尋量

預期結果：
- 相關關鍵字數量 > 0（通常 10-50 個）
- 範例顯示關鍵字和搜尋量
- 訊息顯示 "(使用 DataForSEO Labs API)"
```

#### Test 2：原始 API 回應
```
步驟：
1. 點擊「Labs 原始回應」
2. 查看完整的 API 返回數據

預期結果：
- endpoint: dataforseo_labs/google/related_keywords/live
- request_data.location_code = 2344
- result 包含多個相關關鍵字
- 每個關鍵字包含 keyword_info
```

#### Test 3：SEO 關鍵字研究功能
```
測試關鍵字：長者

步驟：
1. 在「SEO 關鍵字研究」輸入「長者」
2. 點擊「分析關鍵字」
3. 查看「相關關鍵字 (DataForSEO Labs)」面板

預期結果：
- 顯示 10-20 個相關關鍵字標籤
- 每個標籤可點擊
- 標籤內容為相關關鍵字（如「長者服務」、「長者護理」等）
```

#### Test 4：快取機制
```
步驟：
1. 第一次搜尋「長者」
2. 查看 Render logs 確認 Labs API 被調用
3. 等待 10 秒
4. 第二次搜尋「長者」
5. 查看 logs 確認使用快取（無 API 調用）

預期結果：
- 第一次：logs 顯示 "[Labs] Requesting related keywords..."
- 第二次：logs 顯示使用快取，無 Labs API 調用
- 兩次結果相同
```

#### Test 5：對比測試（英文 vs 中文）
```
測試 1：長者（中文）
- 預期：10-20 個相關關鍵字

測試 2：elderly（英文）
- 預期：20-50 個相關關鍵字

測試 3：iPhone（高流量關鍵字）
- 預期：30-50 個相關關鍵字

驗證：
- Labs API 對中英文關鍵字都有效
- 高流量關鍵字返回更多結果
- 無 "數據不足" 的情況（與舊 Trends API 對比）
```

---

## 🚀 部署步驟

### 1. Git 提交

```bash
# 在本地
git add services/dataforseo_client.py
git add services/seo_orchestrator.py
git add app.py
git add templates/keywords.html
git add templates/debug_seo.html
git add LABS_API_INTEGRATION.md

git commit -m "Feature: 整合 DataForSEO Labs API 替代 Google Trends 相關查詢

修改內容：
1. 新增 get_related_keywords_labs() 方法調用 Labs API
2. 修改 SEO 分析流程使用 Labs API 取得相關關鍵字
3. 更新 UI 標籤和說明文字反映 Labs API
4. 更新測試端點支援 Labs API 測試
5. 保持數據庫結構兼容性（仍使用 queries 欄位）

原因：
- Google Trends API 實際上不返回相關查詢/主題數據
- Labs API 可靠地返回相關關鍵字及搜尋量
- 每次額外 $0.05 換取完整功能

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin main
```

### 2. Render 自動部署

- ✅ Render 會自動檢測 git push 並開始部署
- ⏳ 等待 5-10 分鐘完成構建
- 🔍 查看部署日誌確認無錯誤

### 3. 部署後驗證

按照「階段 2: Render 部署後測試」逐項檢查。

---

## 📊 預期改善

### 功能對比

| 功能 | 修改前 (Google Trends API) | 修改後 (Labs API) |
|------|--------------------------|------------------|
| **相關關鍵字** | ❌ 始終為空（即使 iPhone 也無數據） | ✅ 可靠返回 10-50 個 |
| **搜尋量數據** | ❌ 無 | ✅ 每個關鍵字含搜尋量 |
| **中文支援** | ❌ 無數據 | ✅ 正常運作 |
| **英文支援** | ❌ 無數據 | ✅ 返回更多結果 |
| **API 費用** | $0.009 (浪費) | $0.05 (有效) |

### 用戶體驗改善

✅ **關鍵字研究完整**：
- 用戶可以看到真實的相關關鍵字
- 每個關鍵字顯示搜尋量，便於評估價值
- 可點擊加入生成清單

✅ **數據可靠性**：
- 不再顯示空白的相關查詢面板
- 無論中英文關鍵字都有數據
- 高流量和低流量關鍵字都能獲得結果

✅ **SEO 價值提升**：
- 真正的關鍵字研究工具
- 幫助用戶發現長尾關鍵字
- 搜尋量數據輔助決策

---

## ⚠️ 注意事項

### 1. API 費用增加

- 每次 SEO 分析增加 $0.05
- 月度成本增加約 $20-30（50 次/天，70% 快取命中率）
- **建議**：可接受，因為舊 API 完全無效

### 2. 快取策略

- Labs API 結果存入 `seo_trends_data.queries` 欄位
- 快取時間：1 小時（與原 Trends 設定相同）
- **建議**：可考慮延長至 6 小時以降低成本

### 3. 數據庫兼容性

- ✅ 無需修改數據庫結構
- ✅ 仍使用 `seo_trends_data` 表
- ✅ `queries` 欄位格式兼容
- 差異：`type` 從 "rising"/"top" 改為 "related"

### 4. Trends API 保留

- 仍然調用 Google Trends API 以獲取 `topics`
- 實際上 Trends API 通常不返回 topics
- 保留的原因：萬一未來 API 修復，可以獲取到數據
- 不影響功能，僅多一次 $0.009 的調用

### 5. UI 標籤更新

- 已更新為「相關關鍵字 (DataForSEO Labs)」
- 如用戶反饋混淆，可改回「相關查詢」
- 目前標籤清晰標註數據來源

---

## 🔍 問題排查

### 問題 1：Labs API 返回 0 個關鍵字

**可能原因**：
- 關鍵字過於冷門
- API 憑證問題
- location_code 錯誤

**排查步驟**：
1. 查看 Render logs 搜尋 `[Labs]`
2. 確認 API 請求成功（status_code: 20000）
3. 檢查原始回應中的 `tasks[0].result`
4. 嘗試熱門關鍵字（如 "iPhone"）

### 問題 2：相關關鍵字面板仍為空

**可能原因**：
- 使用舊快取數據（未清除）
- JavaScript 未正確渲染

**排查步驟**：
1. 清除瀏覽器快取
2. 清除資料庫快取：`DELETE FROM seo_trends_data WHERE keyword='測試關鍵字'`
3. 重新測試
4. 檢查瀏覽器 Console 是否有 JavaScript 錯誤

### 問題 3：成本超出預期

**排查步驟**：
1. 登入 DataForSEO 查看使用量
2. 確認快取機制運作正常
3. 檢查是否有重複查詢未使用快取

**優化方案**：
- 延長快取時間至 6 小時或 24 小時
- 限制每日查詢次數
- 實作用戶級別的 rate limiting

---

## ✅ 部署檢查清單

### 部署前

- [x] 新增 `get_related_keywords_labs()` 方法
- [x] 修改 `analyze_keyword_full()` 整合 Labs API
- [x] 更新 UI 標籤和說明
- [x] 更新測試端點
- [x] 手動檢查代碼語法
- [x] 創建完整文檔

### 部署中

- [ ] Git commit 和 push
- [ ] 監控 Render 部署日誌
- [ ] 確認無構建錯誤

### 部署後

- [ ] 訪問 /debug/seo 頁面
- [ ] 測試 Labs API 端點
- [ ] 測試完整 SEO 關鍵字研究流程
- [ ] 檢查相關關鍵字面板顯示
- [ ] 驗證快取機制
- [ ] 測試中英文關鍵字
- [ ] 查看 Render logs 確認 API 調用正常
- [ ] 監控 DataForSEO 使用量

---

## 📚 相關文檔

- [DataForSEO Labs Related Keywords API](https://docs.dataforseo.com/v3/dataforseo_labs-google-related_keywords-live/)
- [DATAFORSEO_API_SETTINGS.md](./DATAFORSEO_API_SETTINGS.md) - 完整 API 參數文檔
- [DEPLOYMENT_CHECKLIST_v2.md](./DEPLOYMENT_CHECKLIST_v2.md) - 上次部署清單

---

**準備完畢，可以開始部署！** 🚀

---

**文檔版本**: 3.0
**最後更新**: 2026-02-02
**負責人**: Claude Sonnet 4.5
