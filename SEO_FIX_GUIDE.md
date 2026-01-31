# SEO 功能快速修復指南

## 🚀 快速診斷

訪問：`https://your-app.onrender.com/debug/seo`

這個頁面會告訴你哪裡有問題！

---

## 📋 修復步驟

### 第 1 步：在 Render 添加環境變數

1. 登入 [Render Dashboard](https://dashboard.render.com/)
2. 選擇你的 Web Service
3. 點擊 "Environment" 標籤
4. 添加以下變數：

```
DATAFORSEO_LOGIN=你的登入帳號
DATAFORSEO_PASSWORD=你的密碼
```

**如何獲取憑證？**
- 訪問 https://dataforseo.com/
- 註冊並獲取 API 憑證

### 第 2 步：提交新文件到 Git

我已經為你創建了以下文件：
- ✅ `aptfile` - 告訴 Render 安裝 Chromium
- ✅ `RENDER_SETUP.md` - 詳細配置說明
- ✅ 修改了 `crawler/google_trends.py` - 支援 Render

**提交到 Git：**

```bash
git add aptfile RENDER_SETUP.md crawler/google_trends.py
git commit -m "Add Render configuration for SEO features"
git push origin main
```

### 第 3 步：等待 Render 重新部署

推送後，Render 會自動：
1. 檢測到 `aptfile`
2. 安裝 Chromium 和 ChromeDriver
3. 重新部署應用

部署時間：約 3-5 分鐘

### 第 4 步：測試

部署完成後，訪問 `/debug/seo` 並測試：

1. **測試 DataForSEO API**
   - 點擊「🧪 測試 API 連接」
   - 應該顯示 ✅ API 連接成功

2. **測試 Selenium**
   - 點擊「🧪 測試 Selenium」
   - 應該顯示 ✅ Selenium 正常運作

3. **測試關鍵字**
   - 輸入測試關鍵字（例如：長者）
   - 點擊各個測試按鈕

---

## 🔍 問題排查

### 問題：DataForSEO API 測試失敗

**檢查清單：**
- [ ] 環境變數是否正確設置？
- [ ] 憑證是否有效？（登入 DataForSEO 確認）
- [ ] Render 是否已重啟？（添加環境變數後需要重啟）

**如何重啟 Render：**
1. 在 Render Dashboard 中點擊 "Manual Deploy"
2. 選擇 "Clear build cache & deploy"

### 問題：Selenium 測試失敗

**檢查清單：**
- [ ] `aptfile` 是否已提交到 Git？
- [ ] Render 是否已重新部署？
- [ ] 查看 Render Logs 是否有錯誤

**查看 Render Logs：**
1. Render Dashboard → 你的 Service
2. 點擊 "Logs" 標籤
3. 搜尋關鍵字：`chromium`, `selenium`, `error`

### 問題：API 返回空數據

**可能原因：**
1. 測試的關鍵字在香港地區搜尋量過低
2. DataForSEO API 配額用完

**解決方法：**
1. 嘗試更熱門的關鍵字：
   - ✅ 「長者」、「健康」、「護理」
   - ❌ 過於專業或冷門的詞彙

2. 檢查 DataForSEO 配額：
   - 登入 DataForSEO Dashboard
   - 查看 API 使用量

---

## 📊 測試建議關鍵字

在 `/debug/seo` 測試以下關鍵字：

| 關鍵字 | 預期結果 |
|--------|---------|
| 長者 | ✅ 應該有數據 |
| 健康 | ✅ 應該有數據 |
| 護理 | ✅ 應該有數據 |
| 醫療服務 | ✅ 應該有數據 |

---

## 💡 提示

1. **第一次使用**：DataForSEO 通常會給新用戶免費額度測試
2. **日誌很重要**：如果遇到問題，查看 Render Logs
3. **測試頁面**：`/debug/seo` 是最好的診斷工具

---

## 📞 需要幫助？

如果問題仍未解決，請提供：
1. `/debug/seo` 頁面截圖
2. Render Logs（最近 50 行）
3. 測試的關鍵字

我會根據這些信息幫你診斷！
