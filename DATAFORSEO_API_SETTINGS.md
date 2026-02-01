# DataForSEO API 完整參數設定

**更新時間**: 2026-02-01
**系統**: webapp SEO 分析功能

---

## 📍 香港地區設定

**Location Code**: `2344`
- **地區**: 香港 (Hong Kong)
- **ISO 代碼**: HK
- **類型**: Region

**驗證來源**: [DataForSEO Locations API](https://docs.dataforseo.com/v3/keywords_data-google-locations/)

---

## 🔍 API 1: Google Trends

### Endpoint
```
POST /v3/keywords_data/google_trends/explore/live
```

### 當前參數設定
```json
{
  "keywords": ["關鍵字"],           // 數組格式，最多 5 個關鍵字
  "location_code": 2344             // 香港
}
```

### 參數說明

| 參數 | 值 | 類型 | 說明 |
|------|-----|------|------|
| `keywords` | `["長者"]` | Array | ✅ **必需**。搜尋關鍵字數組，最多 5 個 |
| `location_code` | `2344` | Integer | ✅ **必需**。2344 = 香港 |
| `time_range` | 未設置（預設） | String | ❌ 未使用。預設為過去 12 個月 |
| `language_code` | 未設置 | String | ❌ 不支援。API 不接受此參數 |

### 輸出結果結構

```json
{
  "tasks": [{
    "result": [{
      "items": [
        {
          "type": "google_trends_graph",        // 趨勢圖表數據
          "data": [{ "date_from": "...", "values": [59] }]
        },
        {
          "type": "google_trends_queries_list", // 相關查詢
          "data": {
            "top": [{ "query": "長者服務", "value": 100 }],
            "rising": [{ "query": "長者護理", "value": 50 }]
          }
        },
        {
          "type": "google_trends_topics_list",  // 相關主題
          "data": {
            "top": [{ "topic_title": "社會福利", "value": 80 }]
          }
        }
      ]
    }]
  }]
}
```

### 你會得到什麼

✅ **如果數據充足**：
- 趨勢圖表（過去 12 個月的搜尋熱度）
- 相關查詢（top 和 rising）
- 相關主題（top 和 rising）

⚠️ **如果數據不足**：
- 只有趨勢圖表，沒有相關查詢/主題
- 這是正常現象，表示該關鍵字在香港地區數據不足

### 費用
**$0.009/次**

---

## 📊 API 2: Google Ads Search Volume (關鍵字指標)

### Endpoint
```
POST /v3/keywords_data/google_ads/search_volume/live
```

### 當前參數設定
```json
{
  "keywords": ["關鍵字"],           // 數組格式，最多 1000 個
  "location_code": 2344             // 香港
}
```

### 參數說明

| 參數 | 值 | 類型 | 說明 |
|------|-----|------|------|
| `keywords` | `["長者"]` | Array | ✅ **必需**。搜尋關鍵字數組，最多 1000 個 |
| `location_code` | `2344` | Integer | ✅ **必需**。2344 = 香港 |
| `language_code` | 未設置 | String | ❌ 不支援。Google Ads API 不接受此參數 |

### 輸出結果結構

```json
{
  "tasks": [{
    "result": [{
      "keyword": "長者",
      "search_volume": 40500,              // 平均月搜尋量
      "competition": 0.1,                   // 競爭度 (0-1)
      "competition_level": "LOW",           // 競爭程度 (LOW/MEDIUM/HIGH)
      "cpc": 2.24,                         // 平均每次點擊成本 (USD)
      "low_top_of_page_bid": 0.38,        // 低端出價
      "high_top_of_page_bid": 1.87,       // 高端出價
      "monthly_searches": [                // 過去 12 個月的搜尋量
        { "year": 2025, "month": 12, "search_volume": 14800 },
        { "year": 2025, "month": 11, "search_volume": 18100 }
      ]
    }]
  }]
}
```

### 你會得到什麼

✅ **關鍵字指標**：
- 平均月搜尋量
- CPC（廣告點擊成本）
- 競爭程度（LOW/MEDIUM/HIGH）
- 過去 12 個月的每月搜尋量

### 費用
**$0.075/次**

---

## 💡 API 3: Google Ads Keywords For Keywords (關鍵字建議)

### Endpoint
```
POST /v3/keywords_data/google_ads/keywords_for_keywords/live
```

### 當前參數設定
```json
{
  "keywords": ["關鍵字"],           // 種子關鍵字
  "location_code": 2344,            // 香港
  "include_seed_keyword": false,    // 不包含種子關鍵字（優先）
  "limit": 50,                      // 最多返回 50 個建議
  "sort_by": "search_volume"        // 按搜尋量排序
}
```

### 參數說明

| 參數 | 值 | 類型 | 說明 |
|------|-----|------|------|
| `keywords` | `["長者"]` | Array | ✅ **必需**。種子關鍵字數組 |
| `location_code` | `2344` | Integer | ✅ **必需**。2344 = 香港 |
| `include_seed_keyword` | `false` | Boolean | ✅ 第一次嘗試 false（只要相關建議） |
| `limit` | `50` | Integer | 返回建議數量（最多 700） |
| `sort_by` | `"search_volume"` | String | 排序方式（按搜尋量） |
| `language_code` | 未設置 | String | ❌ 不支援。Google Ads API 不接受此參數 |

### 智能降級機制

```
第一次嘗試：include_seed_keyword = false
    ↓
如果返回 0 個建議
    ↓
自動降級：include_seed_keyword = true
    ↓
至少返回種子關鍵字本身的指標
```

### 輸出結果結構

```json
{
  "tasks": [{
    "result": [
      {
        "keyword": "長者服務",
        "search_volume": 5400,
        "cpc": 1.85,
        "competition": 0.15,
        "competition_level": "LOW"
      },
      {
        "keyword": "長者護理",
        "search_volume": 3200,
        "cpc": 2.10,
        "competition": 0.20,
        "competition_level": "LOW"
      }
    ]
  }]
}
```

### 你會得到什麼

✅ **理想情況（英文關鍵字）**：
- 10-50 個相關關鍵字建議
- 每個建議包含搜尋量、CPC、競爭度

⚠️ **中文關鍵字限制**：
- 可能只有 1-5 個建議（甚至 0 個）
- 原因：Google Ads 中文數據較少
- 降級機制確保至少返回 1 個（種子關鍵字）

### 費用
**$0.075/次**

---

## 🔍 API 4: Google SERP (搜尋結果)

### Endpoint
```
POST /v3/serp/google/organic/live/regular
```

### 當前參數設定
```json
{
  "keyword": "關鍵字",
  "location_code": 2344,            // 香港
  "language_code": "zh-TW",         // 繁體中文
  "device": "desktop",              // 桌面裝置
  "os": "windows",                  // Windows 系統
  "depth": 30                       // 獲取前 30 個項目
}
```

### 參數說明

| 參數 | 值 | 類型 | 說明 |
|------|-----|------|------|
| `keyword` | `"長者"` | String | ✅ **必需**。搜尋關鍵字 |
| `location_code` | `2344` | Integer | ✅ **必需**。2344 = 香港 |
| `language_code` | `"zh-TW"` | String | ✅ 繁體中文界面 |
| `device` | `"desktop"` | String | 桌面裝置（desktop/mobile） |
| `os` | `"windows"` | String | 作業系統 |
| `depth` | `30` | Integer | ✅ **重要**！獲取前 30 個項目以確保 10 個 organic |

### 為什麼 depth = 30？

```
Google SERP 結構示例：
位置 1-2:  廣告 (Ad)                → 不是 organic
位置 3:    Featured Snippet         → 不是 organic
位置 4:    Local Pack (地圖)       → 不是 organic
位置 5:    Organic Result #1       → ✅ 我們要的
位置 6:    Organic Result #2       → ✅ 我們要的
位置 7:    People Also Ask         → 不是 organic
位置 8:    Organic Result #3       → ✅ 我們要的
...

depth = 30 確保過濾後仍有 10 個 organic 結果
```

### 輸出結果結構

```json
{
  "tasks": [{
    "result": [{
      "items": [
        {
          "type": "organic",
          "rank_group": 1,
          "rank_absolute": 5,
          "title": "長者咭 - 社會福利署",
          "url": "https://www.swd.gov.hk/...",
          "description": "社會福利署為長者提供...",
          "domain": "www.swd.gov.hk"
        },
        {
          "type": "people_also_ask",
          "items": [
            { "title": "長者卡申請條件？", "snippet": "..." }
          ]
        },
        {
          "type": "related_searches",
          "items": [
            { "title": "長者服務" }
          ]
        }
      ],
      "se_results_count": 33300000  // 總搜尋結果數
    }]
  }]
}
```

### 你會得到什麼

✅ **Organic Results**（有機搜尋結果）：
- 約 10 個自然搜尋結果
- 包含標題、URL、描述、排名
- 過濾掉廣告、local pack 等

✅ **People Also Ask**（相關問題）：
- 用戶常問的問題
- 包含問題和簡短答案

✅ **Related Searches**（相關搜尋）：
- Google 底部的相關搜尋詞

### 費用
**$0.003-0.005/次**（取決於 depth）

---

## 📍 關於「香港」設定的說明

### ✅ Location Code 2344 是正確的

根據 [DataForSEO 官方文檔](https://docs.dataforseo.com/v3/keywords_data-google-locations/)：

```
Location Code: 2344
Country: HK (Hong Kong)
Location Name: Hong Kong
Location Type: Region
```

### 所有 API 都使用相同的 location_code

| API | Location Code | 說明 |
|-----|--------------|------|
| Google Trends | 2344 | ✅ 香港地區趨勢 |
| Google Ads Search Volume | 2344 | ✅ 香港地區搜尋量 |
| Google Ads Keywords | 2344 | ✅ 香港地區關鍵字建議 |
| Google SERP | 2344 | ✅ 香港地區搜尋結果 |

### SERP 的語言設定

```json
{
  "location_code": 2344,      // 香港（決定搜尋結果的地理位置）
  "language_code": "zh-TW"    // 繁體中文（決定 Google 界面語言）
}
```

**作用：**
- `location_code`: 模擬在香港進行搜尋
- `language_code`: Google 界面顯示繁體中文

**結果：**
- 搜尋結果會優先顯示香港相關的網站
- 本地商家、香港政府網站排名較前
- 語言偏好繁體中文內容

---

## 💰 總成本估算

### 每次完整 SEO 分析

```
Google Trends:              $0.009
Google Ads Search Volume:   $0.075
Google Ads Keywords:        $0.075
Google SERP:                $0.003
─────────────────────────────────
總計:                       $0.162
```

### 快取機制（當前設定）

| 數據類型 | 快取時間 | 說明 |
|---------|---------|------|
| Trends | 1 小時 | 趨勢數據變化較快 |
| Keywords | 24 小時 | 搜尋量較穩定 |
| SERP | 6 小時 | 排名有變化但不頻繁 |

### 實際月度成本估算

```
假設每天 50 次查詢，有重複關鍵字：

無快取：
50 queries/day × 30 days × $0.162 = $243/月

有快取（命中率 50%）：
50 × 30 × 50% × $0.162 = $121.50/月

有快取（命中率 70%）：
50 × 30 × 30% × $0.162 = $72.90/月
```

---

## 🎯 參數優化建議

### ✅ 已優化的設定

1. **Location Code 正確**：2344 = 香港
2. **SERP depth 足夠**：30 確保 10 個 organic 結果
3. **智能降級**：中文關鍵字建議有 fallback 機制
4. **移除無效參數**：language_code（Ads API 不支援）

### ⚠️ 潛在調整選項

#### 1. Trends Time Range（當前未使用）

可以添加時間範圍參數：
```json
{
  "date_from": "2025-01-01",
  "date_to": "2026-01-01"
}
```

**用途**：
- 分析特定時間段的趨勢
- 比較不同時期的熱度

#### 2. SERP Search Type（當前使用 organic）

可選類型：
- `organic`: 自然搜尋（當前）
- `paid`: 付費廣告
- `local_pack`: 本地商家

#### 3. Keywords Limit（當前 50）

可調整為：
- `20`: 節省成本，速度更快
- `100`: 獲取更多建議（需要更多 API 配額）

---

## 🔍 輸出結果驗證

### 如何檢查結果是否符合預期

#### 1. Google Trends

✅ **正確輸出**：
- `items` 數組包含 1-3 個元素
- 至少有 `google_trends_graph` 類型
- 如果有相關查詢，會有 `google_trends_queries_list`

❌ **異常輸出**：
- `items` 為空
- 只有錯誤訊息

#### 2. Google Ads 指標

✅ **正確輸出**：
- `search_volume > 0`（至少有一些搜尋量）
- `cpc > 0`（有廣告成本數據）
- `competition_level` 是 LOW/MEDIUM/HIGH

❌ **異常輸出**：
- 所有值都是 0
- `result` 數組為空

#### 3. Keywords 建議

✅ **正確輸出**：
- `result_count >= 1`（至少有種子關鍵字）
- 關鍵字與種子關鍵字相關

❌ **異常輸出**：
- `result_count = 0`（降級機制應該避免這種情況）

#### 4. SERP 結果

✅ **正確輸出**：
- `items_count > 0`
- 有 `type: "organic"` 的項目（約 10 個）
- URL 都是 `.hk` 或香港相關網站

❌ **異常輸出**：
- 沒有 organic 結果
- URL 都不是香港網站（location_code 可能錯誤）

---

## 📞 問題排查

### 問題 1: SERP 沒有香港網站

**檢查**：
```json
{
  "location_code": 2344,  // 確認是 2344
  "language_code": "zh-TW" // 確認是繁體中文
}
```

**驗證方法**：
在 `/debug/seo` 點擊「SERP 原始回應」，查看：
- `data.location_code` 應該是 2344
- `result.organic_results[].domain` 應該多數是 `.hk`

### 問題 2: 中文關鍵字沒有建議

**正常現象**，原因：
- Google Ads 中文數據較少
- 降級機制會返回至少 1 個（種子關鍵字本身）

**驗證方法**：
查看 Logs 是否有 `[Suggestions] Fallback successful`

### 問題 3: Trends 沒有相關查詢

**正常現象**，原因：
- 該關鍵字在香港地區數據不足
- API 只返回趨勢圖表

**驗證方法**：
查看原始回應中 `items` 的類型列表

---

## 📚 參考資料

- [DataForSEO Locations API](https://docs.dataforseo.com/v3/keywords_data-google-locations/)
- [Google Trends API Documentation](https://docs.dataforseo.com/v3/keywords_data-google_trends-explore-live/)
- [Google Ads Keywords API](https://docs.dataforseo.com/v3/keywords_data-google-ads-keywords_for_keywords-live/)
- [Google SERP API](https://docs.dataforseo.com/v3/serp-google-organic-live-regular/)

---

**文檔版本**: 1.0
**最後更新**: 2026-02-01
