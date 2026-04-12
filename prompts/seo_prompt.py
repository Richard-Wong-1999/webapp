def build_seo_domain_prompt(keyword: str, domain: str, page_contents: list) -> str:
    combined_content = "\n\n---\n\n".join(page_contents)
    return f"""你是一位 SEO 內容分析專家。請分析以下來自同一網站的多個頁面，提取與「{keyword}」相關的重要資訊。

網站來源：{domain}
頁面數量：{len(page_contents)}

---
{combined_content}
---

請提取並輸出以下內容（用繁體中文）：

1. **核心觀點**：該網站對「{keyword}」的主要論述（2-3 句）
2. **關鍵數據**：具體數字、統計、日期等不可遺漏的資訊（列表）
3. **獨特見解**：其他競爭對手可能沒有提到的觀點
4. **實用建議**：對讀者有價值的具體建議

請用 400-600 字輸出結構化摘要，保留重要細節但去除冗餘資訊。"""
