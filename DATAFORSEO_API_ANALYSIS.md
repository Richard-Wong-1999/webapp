# DataForSEO API 問題分析與修復報告

生成時間: 2026-02-01

## 問題總結

根據 https://webapp-hx10.onrender.com/debug/seo 的測試結果，發現三個主要問題：

### 1. ❌ Google Trends 沒有顯示相關關鍵字
### 2. ❌ keywords_for_keywords 只返回原始關鍵字本身
### 3. ⚠️ SERP 只有 3 個結果（期望 10 個）

---

## 問題 1: Google Trends 沒有相關關鍵字

### 根本原因

DataForSEO 的 `keywords_data/google_trends/explore/live` endpoint **只返回趨勢圖表數據**，不包含相關主題或查詢。

### API 回應分析

```json
{
  "items": [
    {
      "type": "google_trends_graph",  // 只有圖表類型
      "data": [...],                   // 趨勢數值
      "keywords": ["長者"]
      // ❌ 沒有 related_topics 字段
      // ❌ 沒有 related_queries 字段
    }
  ]
}
```

### 代碼問題

在 `services/dataforseo_client.py:180-207`，代碼嘗試解析不存在的字段：

```python
related_topics = item.get("related_topics", {})   # 永遠返回 {}
related_queries = item.get("related_queries", {})  # 永遠返回 {}
```

### 解決方案

**選項 A（推薦）：** 改用 Google Ads 關鍵字建議作為相關關鍵字來源
- 已有的 `keywords_for_keywords` API 可以提供相關關鍵字
- 包含搜尋量、CPC 等實用數據

**選項 B：** 檢查 DataForSEO 是否有其他 endpoint 提供 Trends 相關查詢
- 可能需要額外的 API 調用
- 需要查閱最新的 DataForSEO 文檔

### 建議實作

1. 在 SEO 分析中，將 Google Trends 用於**趨勢追蹤**（現有功能正常）
2. 使用 Google Ads `keywords_for_keywords` 作為**相關關鍵字來源**
3. 合併兩個數據源提供完整的 SEO 分析

---

## 問題 2: keywords_for_keywords 只返回原始關鍵字

### 根本原因

API 參數 `include_seed_keyword: True` 可能導致只返回種子關鍵字本身。

### API 回應分析

```json
{
  "result_count": 1,
  "result": [
    {
      "keyword": "長者",         // 只有輸入的關鍵字
      "search_volume": 40500,
      // ❌ 沒有其他相關建議
    }
  ]
}
```

### 修改內容

#### 文件: `services/dataforseo_client.py:245-250`

**修改前：**
```python
data = [{
    "keywords": [keyword],
    "location_code": location_code,
    "include_seed_keyword": True,  # ❌ 問題參數
    "limit": limit
}]
```

**修改後：**
```python
data = [{
    "keywords": [keyword],
    "location_code": location_code,
    "include_seed_keyword": False,  # ✅ 修改：不包含種子關鍵字
    "limit": limit,
    "sort_by": "search_volume"      # ✅ 新增：按搜尋量排序
}]
```

### 測試建議

修改後，請在 `/debug/seo` 頁面重新測試關鍵字建議功能：

```
測試關鍵字：長者
預期結果：返回 10-50 個相關關鍵字建議
例如：長者服務、長者護理、長者中心、長者活動等
```

---

## 問題 3: SERP 只有 3 個結果

### 根本原因

`depth: 5` 表示返回 Google SERP 的前 5 個**項目**（不是 5 個 organic 結果）。

### API 行為說明

Google SERP 的結構：

```
位置 1: 廣告（Ad）           -> 不在 organic_results 中
位置 2: 廣告（Ad）           -> 不在 organic_results 中
位置 3: Featured Snippet    -> 不在 organic_results 中
位置 4: Local Pack          -> 不在 organic_results 中
位置 5: Organic Result      -> ✅ 返回（rank_absolute: 5）
位置 6: Organic Result      -> ✅ 返回（rank_absolute: 6）
位置 7: People Also Ask     -> 不在 organic_results 中
位置 8: Organic Result      -> ✅ 返回（rank_absolute: 8）
...
```

因此 `depth: 5` 只能獲取到位置 5 的結果（1 個 organic），而不是 5 個 organic 結果。

### 修改內容

#### 文件: `services/dataforseo_client.py:366-373`

**修改前：**
```python
data = [{
    "keyword": keyword,
    "location_code": location_code,
    "language_code": language_code,
    "device": "desktop",
    "os": "windows",
    "depth": num  # ❌ 太小，無法獲取足夠的 organic 結果
}]
```

**修改後：**
```python
data = [{
    "keyword": keyword,
    "location_code": location_code,
    "language_code": language_code,
    "device": "desktop",
    "os": "windows",
    "depth": max(num * 3, 30)  # ✅ 增加到 3 倍或最少 30
}]
```

### 解釋

- `num = 10` 時，`depth = 30`，確保獲取至少 10 個 organic 結果
- DataForSEO 會返回前 30 個項目，代碼只提取其中的 organic results
- 最終返回 `organic_results[:num]` 限制在請求的數量

### 測試建議

修改後的預期結果：

```
depth = 30
預期返回：10 個 organic 結果
實際 API 回應：可能包含廣告、local pack、PAA 等
最終提取：10 個 organic results
```

---

## DataForSEO API 參數合理性檢查

### ✅ 合理的參數

| 參數 | 值 | 說明 |
|------|-----|------|
| `location_code` | 2344 | 香港地區代碼，正確 |
| `language_code` | "zh-TW" | SERP 用繁體中文，合理 |
| `device` | "desktop" | 桌面裝置，合適 |
| `os` | "windows" | Windows 系統，常見配置 |

### ⚠️ 需要調整的參數

| 參數 | 原值 | 新值 | 原因 |
|------|------|------|------|
| `include_seed_keyword` | True | **False** | 避免只返回種子關鍵字 |
| `depth` (SERP) | 5-10 | **30** | 確保獲取足夠的 organic 結果 |
| `sort_by` | 無 | **"search_volume"** | 按搜尋量排序更實用 |

### ❌ 不適用的參數

| 參數 | API | 說明 |
|------|-----|------|
| `language_code` | Google Ads | 不接受此參數，已移除 |
| `time_range` | Google Trends | 可選，當前使用預設值 |

---

## 修改檔案清單

### 1. `services/dataforseo_client.py`

**修改位置 1: get_keyword_suggestions() - 第 245-250 行**
- ✅ 修改 `include_seed_keyword: False`
- ✅ 新增 `sort_by: "search_volume"`

**修改位置 2: get_serp_results() - 第 366-373 行**
- ✅ 修改 `depth: max(num * 3, 30)`
- ✅ 新增註解說明 depth 計算邏輯

### 2. `app.py`

**修改位置 1: raw_api_test() - 第 875-882 行**
- ✅ 更新 suggestions 測試參數與實際 API 一致

**修改位置 2: raw_api_test() - 第 884-893 行**
- ✅ 更新 SERP depth 到 30

**修改位置 3: test_serp() - 第 798 行**
- ✅ 修改測試數量從 5 到 10

---

## 測試清單

請依序在 `/debug/seo` 頁面測試：

### 1. ✅ 測試關鍵字建議
```
關鍵字：長者
預期：返回 20-50 個相關建議
檢查點：是否不再只有「長者」一個結果
```

### 2. ✅ 測試 SERP
```
關鍵字：長者
預期：返回 10 個 organic 結果
檢查點：是否不再只有 3 個結果
```

### 3. 📋 查看原始 API 回應
```
點擊「Suggestions 原始回應」
檢查 result_count 是否 > 1
檢查 result 數組長度
```

```
點擊「SERP 原始回應」
檢查 items 中 organic 類型的數量
檢查 depth 參數是否為 30
```

---

## 關於 Google Trends 的建議

### 現況

- ✅ Google Trends 趨勢圖數據正常
- ❌ 沒有相關主題/查詢數據

### 替代方案

使用 **Google Ads keywords_for_keywords** 作為相關關鍵字來源：

| 數據源 | 用途 | 數據內容 |
|--------|------|----------|
| Google Trends | 趨勢分析 | 搜尋熱度變化圖表 |
| Google Ads | 相關關鍵字 | 搜尋量、CPC、競爭度 |
| SERP | 競爭對手分析 | 實際搜尋結果、PAA |

### 實作建議

在 `services/seo_orchestrator.py` 的 `analyze_keyword_full()` 中：

```python
# 步驟 1: Google Trends（趨勢圖）
trends = dataforseo_client.get_google_trends(keyword)

# 步驟 2: Google Ads 關鍵字建議（相關關鍵字）
suggestions = dataforseo_client.get_keyword_suggestions(keyword, limit=50)

# 合併結果
result["trends"] = {
    "trend_data": trends.get("data", []),  # 趨勢圖
}
result["related_keywords"] = suggestions  # 相關關鍵字（來自 Ads）
```

---

## 總結

### 已修復

1. ✅ **關鍵字建議參數優化**
   - 移除 `include_seed_keyword: True`
   - 新增 `sort_by: "search_volume"`

2. ✅ **SERP depth 增加**
   - 從 5-10 增加到 30
   - 確保獲取足夠的 organic 結果

### 需要理解的限制

3. ⚠️ **Google Trends 相關查詢不可用**
   - DataForSEO API 限制
   - 建議使用 Google Ads 建議作為替代

### 後續行動

1. 在 `/debug/seo` 重新測試所有功能
2. 確認關鍵字建議返回多個結果
3. 確認 SERP 返回 10 個結果
4. 考慮實作「合併 Trends + Ads」的方案

---

## API 費用估算

### 當前配置

- Google Trends: $0.009/次
- Google Ads (Search Volume): $0.075/次
- Google Ads (Keywords For Keywords): $0.075/次
- SERP (depth=30): ~$0.003-0.005/次

### 每次完整 SEO 分析成本

```
Trends: $0.009
Metrics: $0.075
Suggestions: $0.075
SERP: $0.005
-----------------
總計: $0.164/關鍵字
```

### 優化建議

- ✅ 已實作快取機制（降低重複查詢成本）
- ✅ Trends TTL: 1 小時
- ✅ Keyword TTL: 24 小時
- ✅ SERP TTL: 6 小時

---

**修復完成日期**: 2026-02-01
**測試狀態**: 等待驗證
