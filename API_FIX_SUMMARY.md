# 🎯 DataForSEO API 修復總結

## 問題根源

從原始 API 回應發現：

### 1. Google Trends API 錯誤
```json
"status_code": 40501,
"status_message": "Invalid Field: 'keywords'."
```
**原因**：API 不接受我們發送的某些參數

### 2. Google Ads API 錯誤
```json
"status_code": 40501,
"status_message": "Invalid Field: 'language_code'."
```
**原因**：此 API **明確不接受** `language_code` 參數

### 3. SERP API ✅
**正常工作**，返回了 3 個有機結果

---

## ✅ 已修復

### 修改文件：`services/dataforseo_client.py`

#### 1. Google Trends API
**移除前**：
```python
topics_data = [{
    "keyword": keyword,
    "location_code": location_code,
    "language_code": "zh-TW"  # ❌ 可能導致問題
}]
```

**修復後**：
```python
topics_data = [{
    "keyword": keyword,
    "location_code": location_code  # ✅ 只保留基本參數
}]
```

#### 2. Google Ads Search Volume API
**移除前**：
```python
data = [{
    "keywords": keywords,
    "location_code": location_code,
    "language_code": language_code  # ❌ API 不接受此參數
}]
```

**修復後**：
```python
data = [{
    "keywords": keywords,
    "location_code": location_code  # ✅ 移除 language_code
}]
```

#### 3. Google Ads Keywords Suggestions API
**移除前**：
```python
data = [{
    "keyword": keyword,
    "location_code": location_code,
    "language_code": language_code,  # ❌ API 不接受
    "include_seed_keyword": True,
    "limit": limit
}]
```

**修復後**：
```python
data = [{
    "keyword": keyword,
    "location_code": location_code,  # ✅ 移除 language_code
    "include_seed_keyword": True,
    "limit": limit
}]
```

---

## 🎯 預期結果

修復後，API 應該能夠：

### Google Trends API
- ✅ 返回相關主題（related topics）
- ✅ 返回相關查詢（related queries）
- ✅ 區分 rising 和 top 數據

### Google Ads API
- ✅ 返回關鍵字搜尋量（search_volume）
- ✅ 返回 CPC（每次點擊成本）
- ✅ 返回競爭度（competition/competition_level）
- ✅ 返回相關關鍵字建議

### SERP API
- ✅ 繼續正常工作（已經成功）

---

## 📋 測試步驟

### 步驟 1：提交修復

```bash
git add services/dataforseo_client.py API_FIX_SUMMARY.md
git commit -m "Fix: Remove invalid API parameters (language_code)"
git push origin main
```

### 步驟 2：等待 Render 部署（1-2 分鐘）

### 步驟 3：測試

訪問：https://webapp-hx10.onrender.com/debug/seo

1. **輸入關鍵字**：「長者」

2. **點擊「🧪 測試 Google Trends API」**
   - 應該顯示：✅ Topics: 10-20, Queries: 10-20

3. **點擊「🧪 測試關鍵字指標」**
   - 應該顯示：✅ 搜尋量: XXX, CPC: $X.XX, 競爭: LOW/MEDIUM/HIGH

4. **點擊「🧪 測試 SERP API」**
   - 應該繼續顯示：✅ 有機結果: 3-10

---

## 🔍 如果還是返回 0 數據

如果修復後仍然返回 0：

1. **查看原始回應**：
   - 點擊「📄 Trends 原始回應」
   - 檢查 `status_code` 是否為 20000
   - 檢查 `result` 欄位是否有數據

2. **可能原因**：
   - 該關鍵字在香港地區確實沒有足夠的 Trends 數據
   - 嘗試更熱門的關鍵字（健康、醫療、護理）

3. **查看 Render Logs**：
   - 搜尋 `[DataForSEO]`
   - 查看 API 回應狀態

---

## 💡 關鍵發現

1. **DataForSEO API 參數非常嚴格**
   - 不接受無效或多餘的參數
   - 不同的 endpoint 有不同的參數要求

2. **Google Ads API 不需要語言代碼**
   - 只使用 location_code 來確定地區
   - 語言由地區自動推斷

3. **SERP API 可以接受 language_code**
   - 這就是為什麼它一直正常工作

---

## 📚 參考文檔

- [DataForSEO Google Trends API](https://docs.dataforseo.com/v3/keywords_data/google_trends/explore/live/)
- [DataForSEO Google Ads Search Volume](https://docs.dataforseo.com/v3/keywords_data/google_ads/search_volume/live/)
- [DataForSEO SERP API](https://docs.dataforseo.com/v3/serp/google/organic/live/regular/)

---

## 🎉 下一步

提交代碼 → 部署 → 測試 → 享受完整的 SEO 功能！

**關鍵字「長者」應該會返回豐富的數據！** 🚀
