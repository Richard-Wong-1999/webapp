# SEO 文章自動生成平台 - 專案報告

**課程名稱**：[請填入課程名稱]
**學生姓名**：[請填入姓名]
**學號**：[請填入學號]
**提交日期**：2026年2月

---

## 目錄

1. [引言](#1-引言)
2. [系統架構](#2-系統架構)
3. [主要功能模組](#3-主要功能模組)
4. [涉及的技術](#4-涉及的技術)
5. [技術決策與取捨](#5-技術決策與取捨)
6. [遇到的困難與解決方法](#6-遇到的困難與解決方法)
7. [系統演變歷程](#7-系統演變歷程)
8. [結論與未來展望](#8-結論與未來展望)
9. [參考資料](#9-參考資料)

---

## 1. 引言

### 1.1 專案背景

隨著數位行銷的發展，內容行銷已成為企業推廣的重要策略。然而，高品質的 SEO 文章撰寫需要大量人力和時間。本專案旨在開發一個自動化的 SEO 文章生成平台，結合人工智慧技術與搜尋引擎優化策略，為香港長者服務領域提供專業的雙語（中英文）內容生成解決方案。

### 1.2 專案目標

1. **自動化內容生成**：利用大型語言模型（LLM）自動生成高品質的 SEO 優化文章
2. **多來源數據整合**：整合政府新聞稿、搜尋引擎數據、競爭對手分析等多元資料來源
3. **端到端工作流程**：從關鍵字研究、內容生成到自動發布的完整流程
4. **多模型支援**：支援多種 AI 模型（GPT-5.2、DeepSeek 等），可根據需求切換

### 1.3 專案範圍

本系統專注於香港長者服務與安老政策領域，主要用戶包括：
- 社會福利機構的內容行銷團隊
- 長者服務相關的非營利組織
- 健康與社會政策領域的媒體工作者

---

## 2. 系統架構

### 2.1 整體架構圖

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          前端介面層 (Frontend)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ 關鍵字頁面  │  │ 文章生成頁  │  │ 文章管理頁  │  │ 模型測試頁  │    │
│  │ keywords    │  │ generate    │  │ manage      │  │ test_models │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         應用層 (Flask Application)                       │
│                              app.py (1553 行)                            │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ 路由處理：爬蟲控制 / 文章生成 / SEO 分析 / 模型切換 / Wix 整合  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            服務層 (Services)                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐               │
│  │ article_      │  │ keyword_      │  │ seo_          │               │
│  │ generator.py  │  │ extractor.py  │  │ orchestrator  │               │
│  │ (1143 行)     │  │ (348+ 行)     │  │ (587+ 行)     │               │
│  └───────────────┘  └───────────────┘  └───────────────┘               │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐               │
│  │ llm_client.py │  │ dataforseo_   │  │ deep_crawler  │               │
│  │ (163 行)      │  │ client (744行)│  │ (758 行)      │               │
│  └───────────────┘  └───────────────┘  └───────────────┘               │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐               │
│  │ wix_client.py │  │ database.py   │  │ serp_scraper  │               │
│  │ (475 行)      │  │ (467 行)      │  │ (337 行)      │               │
│  └───────────────┘  └───────────────┘  └───────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         外部服務層 (External APIs)                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐               │
│  │  Poe API      │  │ DataForSEO    │  │   Wix API     │               │
│  │  (GPT-5.2)    │  │   API         │  │   (Blog)      │               │
│  └───────────────┘  └───────────────┘  └───────────────┘               │
│  ┌───────────────┐  ┌───────────────┐                                   │
│  │ DeepSeek API  │  │  PostgreSQL   │                                   │
│  │               │  │   Database    │                                   │
│  └───────────────┘  └───────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 目錄結構

```
webapp/
├── app.py                      # 主應用程式入口 (Flask)
├── config.py                   # 集中配置管理
├── gunicorn.conf.py            # 生產環境 WSGI 配置
│
├── services/                   # 服務層模組
│   ├── __init__.py             # 服務層統一導出
│   ├── article_generator.py    # 文章生成核心邏輯
│   ├── keyword_extractor.py    # 關鍵字提取服務
│   ├── seo_orchestrator.py     # SEO 流程協調器
│   ├── dataforseo_client.py    # DataForSEO API 客戶端
│   ├── llm_client.py           # 統一 LLM 調用介面
│   ├── deepseek_client.py      # DeepSeek API 客戶端
│   ├── poe_client.py           # Poe API 客戶端
│   ├── deep_crawler.py         # 智能深度爬蟲
│   ├── serp_scraper.py         # SERP 結果爬蟲
│   ├── wix_client.py           # Wix Blog API 客戶端
│   └── database.py             # 資料庫操作層
│
├── crawler/                    # 爬蟲模組
│   └── ha_press_spider.py      # 醫管局新聞稿爬蟲
│
├── utils/                      # 工具類
│   ├── __init__.py
│   ├── logger.py               # 日誌系統
│   ├── cache_manager.py        # 快取管理器
│   ├── text_processing.py      # 文字處理工具
│   ├── rate_limiter.py         # API 速率限制
│   └── retry.py                # 重試機制
│
├── models/                     # 資料模型
│   ├── __init__.py
│   └── progress.py             # 進度追蹤器
│
├── templates/                  # HTML 模板
│   ├── index.html              # 首頁
│   ├── keywords.html           # 關鍵字研究頁
│   ├── generate.html           # 文章生成頁
│   ├── manage_articles.html    # 文章管理頁
│   ├── view_article.html       # 文章詳情頁
│   └── test_models.html        # 模型測試頁
│
└── static/                     # 靜態資源
    └── style.css
```

### 2.3 設計模式

本專案採用以下設計模式：

| 設計模式 | 應用場景 | 實現檔案 |
|---------|---------|---------|
| **MVC 模式** | 整體架構分離 | app.py (Controller), templates/ (View), services/ (Model) |
| **單例模式** | 全域客戶端實例 | `dataforseo_client`, `wix_client` |
| **工廠模式** | LLM 模型切換 | `llm_client.py` 的 `call_llm()` 函數 |
| **裝飾器模式** | 資料庫連接管理 | `database.py` 的 `@with_db_connection` |
| **策略模式** | 多種參考資料來源 | `article_generator.py` 根據來源切換策略 |
| **觀察者模式** | 進度回調機制 | `ProgressTracker` 類別 |

---

## 3. 主要功能模組

### 3.1 關鍵字提取模組 (Keyword Extractor)

#### 功能描述
從政府新聞稿中自動提取與長者服務相關的關鍵字，作為文章生成的主題來源。

#### 技術實現
```python
# services/keyword_extractor.py

def extract_keywords_from_deepseek(summaries: List[str]) -> List[str]:
    """使用 GPT-5.2 提取關鍵字"""
    prompt = (
        "你是一位香港社會政策與福利新聞分析專家...\n"
        "請仔細閱讀以下新聞摘要，提取20個最能反映近期香港社會"
        "在長者相關領域的代表性關鍵詞..."
    )

    output, metadata = call_llm(prompt, provider="poe", model="gpt-5.2")
    keywords = [kw.strip() for kw in output.split(",")]
    return keywords[:20]
```

#### 資料來源
- **SWD (社會福利署)**：政府新聞稿
- **HA (醫院管理局)**：醫療相關公告

#### 快取機制
- TTL (Time-To-Live)：1 小時
- 使用 `threading.Lock` 確保線程安全

---

### 3.2 SEO 數據研究模組 (DataForSEO Client)

#### 功能描述
整合 DataForSEO API，提供完整的 SEO 關鍵字研究功能。

#### API 整合

| API 端點 | 功能 | 費用 |
|---------|------|------|
| Labs API (Related Keywords) | 獲取相關關鍵字、搜尋量、CPC | $0.0109/次 |
| SERP API | 獲取 Google 搜尋結果 | 按次計費 |
| Google Trends API | 趨勢數據（已棄用） | - |

#### 關鍵實現
```python
# services/dataforseo_client.py

def get_related_keywords_labs_full(self, keyword: str, limit: int = 50):
    """使用 Labs API 取得完整關鍵字數據

    Returns:
        {
            "seed_keyword_metrics": {
                "keyword": str,
                "search_volume": int,
                "cpc": float,
                "competition_level": str,
                "keyword_difficulty": int,
                "search_intent": str
            },
            "related_keywords": [...]
        }
    """
```

#### 決策背景
最初嘗試使用 Google Trends API 獲取相關查詢，但發現該 API 僅返回趨勢圖表，不返回相關關鍵字數據。經測試後改用 Labs API，雖每次額外增加 $0.05 成本，但能可靠獲取完整數據。

---

### 3.3 深度爬蟲模組 (Deep Crawler)

#### 功能描述
智能深度爬取競爭對手網站，提取關鍵內容作為文章生成的參考資料。

#### 核心演算法

**1. 相關性評分機制**
```python
def _calculate_link_relevance(self, url, anchor_text, context, parent_url):
    """
    評分標準：
    - +0.4: 關鍵字出現在 URL 中
    - +0.2: 符合優選 URL 模式 (/article/, /blog/, /guide/)
    - +0.1: 連結深度不超過父頁面 +1
    - +0.2: 關鍵字出現在錨點文字中
    - +0.1: 關鍵字出現在上下文中
    """
    score = 0.0
    # ... 評分邏輯
    return min(score, 1.0)
```

**2. 內容質量評分**
```python
def _calculate_quality_score(self, title, meta_description, content, word_count):
    """
    評分標準：
    - +0.3: 字數 >= 100
    - +0.2: 字數 >= 500
    - +0.1: 字數 >= 1000
    - +0.2: 內容長度 >= 200 字元
    - +0.1: 有標題
    - +0.1: 有 meta description
    """
```

**3. 爬取策略**
- 最大深度：2 層（SERP 頁面 + 內部連結）
- 每域名上限：5 頁
- 總頁面上限：30 頁
- 最低相關性分數：0.3
- 總超時：300 秒

#### 配置參數
```python
# config.py

DEEP_CRAWL_ENABLED = True
DEEP_CRAWL_MAX_DEPTH = 2
DEEP_CRAWL_MAX_PAGES_PER_DOMAIN = 5
DEEP_CRAWL_MAX_TOTAL_PAGES = 30
DEEP_CRAWL_MIN_RELEVANCE = 0.3
DEEP_CRAWL_TIMEOUT = 300
```

---

### 3.4 文章生成模組 (Article Generator)

#### 功能描述
核心模組，負責調用 LLM 生成 SEO 優化的雙語文章。

#### Prompt 工程

本專案採用精心設計的 Prompt 模板：

```python
def build_article_prompt(main_keyword, reference_content, seo_context):
    prompt = f"""你是一位香港地區的專業 Blog 內容寫作顧問與 SEO 專家，
    專注於長者服務與安老政策領域。

    ## 任務目標
    根據提供的參考資料，以「{main_keyword}」為主題，撰寫一篇高品質的雙語 Blog 文章。

    ## Rich Text 格式要求
    body 內容必須使用 HTML 格式輸出：
    - 使用 <h2> 作為主要小標題
    - 使用 <p> 包裹每個段落
    - 使用 <ul>/<ol> 製作列表
    - 使用 <strong> 強調重要內容

    ## 輸出格式
    請嚴格按照以下 JSON 格式輸出：
    [
      {{
        "zh": {{"title": "...", "body": "...", "meta_title": "...", "meta_description": "..."}},
        "en": {{"title": "...", "body": "...", "meta_title": "...", "meta_description": "..."}},
        "keywords": [...]
      }}
    ]
    """
    return prompt
```

#### 生成流程

```
┌─────────────────┐
│ 1. 接收關鍵字   │
└────────┬────────┘
         ▼
┌─────────────────┐     ┌─────────────────┐
│ 2. 判斷來源類型 │────▶│  SWD/HA 新聞稿  │
└────────┬────────┘     └─────────────────┘
         │
         ▼              ┌─────────────────┐
┌─────────────────┐────▶│ SEO/Trends 爬蟲 │
│ 3. 取得參考資料 │     └─────────────────┘
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. 建構 Prompt  │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 5. 呼叫 LLM API │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 6. 解析 JSON    │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 7. 儲存到資料庫 │
└─────────────────┘
```

#### 並發處理
使用 `ThreadPoolExecutor` 實現並發文章生成：

```python
with ThreadPoolExecutor(max_workers=Config.ARTICLE_GENERATION_WORKERS) as executor:
    futures = [
        executor.submit(generate_single_article_by_source, ...)
        for i in range(total_articles)
    ]
    for future in as_completed(futures):
        results.append(future.result())
```

---

### 3.5 LLM 統一介面 (LLM Client)

#### 功能描述
抽象化多種 AI 模型的調用，提供統一的介面。

#### 支援的模型

| 提供者 | 模型 | 特點 |
|--------|------|------|
| Poe | GPT-5.2 | 最新旗艦，能力最強 |
| Poe | GPT-5.2 Instant | 極速版，速度最快 |
| Poe | GPT-5 Mini | 輕量版，快速便宜 |
| Poe | GPT-4.1 | 穩定可靠 |
| Poe | Gemini 3 Flash | 快速便宜，日常首選 |
| DeepSeek | deepseek-chat | 性價比極高 |

#### 實現方式
```python
# services/llm_client.py

def call_llm(prompt_text: str, provider: str = None, model: str = None):
    """統一 LLM 呼叫介面"""

    if provider == "deepseek":
        content = call_deepseek(prompt_text, model=model)
    elif provider == "poe":
        content, tokens = call_poe(prompt_text, model=model)

    return content, metadata
```

---

### 3.6 Wix 整合模組 (Wix Client)

#### 功能描述
將生成的文章自動發布到 Wix Blog 平台（作為草稿）。

#### OAuth 2.0 Token 管理
```python
def _get_access_token(self) -> str:
    """獲取或刷新 Access Token"""

    # 如果 token 還有效（提前 60 秒刷新）
    if self._access_token and time.time() < (self._token_expires_at - 60):
        return self._access_token

    # 使用 Refresh Token 獲取新的 Access Token
    payload = {
        "grant_type": "refresh_token",
        "client_id": self.client_id,
        "client_secret": self.client_secret,
        "refresh_token": self.refresh_token
    }
    # ...
```

#### HTML → Ricos 格式轉換

Wix Blog 使用自定義的 Ricos Document 格式。本專案實現了 HTML 到 Ricos 的轉換器：

```python
class HTMLToRicosConverter(HTMLParser):
    """將 HTML 轉換為 Wix Ricos Document 格式"""

    def handle_starttag(self, tag, attrs):
        if tag in ('h1', 'h2', 'h3'):
            self.heading_level = int(tag[1])
        elif tag == 'ul':
            self.list_stack.append('ul')
        # ...

    def get_ricos_document(self) -> Dict[str, Any]:
        return {"nodes": self.nodes}
```

---

### 3.7 資料庫模組 (Database)

#### 技術選型
- **資料庫**：PostgreSQL
- **連接池**：`psycopg2.pool.ThreadedConnectionPool`

#### 資料表結構

**主表：articles**
```sql
CREATE TABLE articles (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    meta_title VARCHAR(200),
    meta_description TEXT,
    keywords TEXT,
    timestamp VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- 雙語欄位
    title_zh VARCHAR(500),
    title_en VARCHAR(500),
    body_zh TEXT,
    body_en TEXT,
    -- LLM 追蹤
    llm_provider VARCHAR(50),
    llm_model VARCHAR(100),
    prompt_zh TEXT
);
```

**SEO 快取表**
```sql
-- 關鍵字數據快取
CREATE TABLE seo_keyword_data (
    keyword VARCHAR(500) PRIMARY KEY,
    search_volume INTEGER,
    cpc DECIMAL(10, 4),
    competition DECIMAL(5, 4),
    related_keywords JSONB,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SERP 結果快取
CREATE TABLE seo_serp_cache (
    keyword VARCHAR(500) PRIMARY KEY,
    organic_results JSONB,
    people_also_ask JSONB,
    related_searches JSONB,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 爬蟲任務追蹤
CREATE TABLE seo_crawl_tasks (
    keyword VARCHAR(500) PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'pending',
    pages_crawled INTEGER DEFAULT 0,
    crawl_result JSONB,
    completed_at TIMESTAMP
);
```

#### 連接池設計
```python
def init_connection_pool():
    """初始化資料庫連接池（線程安全版本）"""
    db_pool = pool.ThreadedConnectionPool(
        minconn=Config.DB_POOL_MIN,  # 最小連接數：2
        maxconn=Config.DB_POOL_MAX,  # 最大連接數：10
        dsn=Config.DATABASE_URL
    )
```

---

## 4. 涉及的技術

### 4.1 後端技術棧

| 技術 | 用途 | 版本 |
|------|------|------|
| Python | 主要程式語言 | 3.x |
| Flask | Web 框架 | - |
| Gunicorn | WSGI 服務器 | - |
| PostgreSQL | 關係型資料庫 | - |
| psycopg2 | PostgreSQL 驅動 | - |

### 4.2 AI/ML 技術

| 技術 | 用途 |
|------|------|
| GPT-5.2 | 文章生成、關鍵字提取 |
| DeepSeek | 備選文章生成模型 |
| Prompt Engineering | 優化 AI 輸出品質 |

### 4.3 網頁爬蟲技術

| 技術 | 用途 |
|------|------|
| BeautifulSoup | HTML 解析 |
| Requests | HTTP 請求 |
| 相關性評分算法 | 篩選高質量頁面 |

### 4.4 API 整合

| API | 用途 |
|-----|------|
| DataForSEO Labs API | 關鍵字研究 |
| DataForSEO SERP API | 搜尋結果分析 |
| Poe API | LLM 模型調用 |
| DeepSeek API | 備選 LLM |
| Wix Blog API | 文章發布 |

### 4.5 前端技術

| 技術 | 用途 |
|------|------|
| HTML5 / CSS3 | 頁面結構與樣式 |
| JavaScript | 互動功能 |
| Jinja2 | 模板引擎 |
| AJAX | 非同步請求 |

---

## 5. 技術決策與取捨

### 5.1 API 策略：Google Trends → Labs API

**問題**：最初使用 DataForSEO 的 Google Trends API 獲取相關查詢，但發現即使高流量關鍵字（如「iPhone」）也只返回趨勢圖表數據，不返回相關查詢和主題。

**決策**：改用 DataForSEO Labs API (`related_keywords/live`)

**取捨分析**：
| 面向 | Google Trends API | Labs API |
|------|------------------|----------|
| 費用 | 較低 | $0.0109/次 |
| 數據完整性 | 僅趨勢圖表 | 完整關鍵字指標 |
| 可靠性 | 不穩定 | 穩定 |
| **結論** | ❌ 棄用 | ✅ 採用 |

**相關提交**：`376fd65` (2026-02-02)

---

### 5.2 AI 模型選擇：多模型支援

**問題**：單一模型無法滿足所有場景需求（成本、速度、品質的平衡）

**決策**：實現統一的 LLM 介面，支援多種模型切換

**模型比較**：
| 模型 | 優點 | 缺點 | 適用場景 |
|------|------|------|---------|
| GPT-5.2 | 品質最高 | 成本較高、較慢 | 重要文章 |
| GPT-5.2 Instant | 速度極快 | 品質略低 | 批量生成 |
| DeepSeek | 性價比極高 | 中文稍弱 | 日常使用 |

**演變歷程**：
- 刪除 Gemini 3 Pro（`4de2692`）：可能因效能或成本問題
- 新增 GPT-5.2 Instant（`98b1c9d`）：滿足速度需求

---

### 5.3 架構重構：單體 → 模組化

**問題**：初始版本將所有功能寫在單一 `app.py` 檔案（1500+ 行），難以維護和測試

**決策**：進行模組化重構，將功能拆分為獨立的服務模組

**重構前後對比**：
| 面向 | 重構前 | 重構後 |
|------|--------|--------|
| app.py 行數 | 1500+ 行 | ~500 行（路由） |
| 模組數量 | 1 個 | 12+ 個服務模組 |
| 可測試性 | 差 | 良好 |
| 可維護性 | 差 | 良好 |

**相關提交**：`3c63670` (2026-01-31) - "Optimization"

---

### 5.4 爬蟲策略：淺層 → 深度爬取

**問題**：僅爬取 SERP 第一層結果，內容參考資料不足

**決策**：實現智能深度爬蟲，追蹤頁面內的相關內部連結

**策略對比**：
| 策略 | 頁面數 | 內容豐富度 | 時間成本 |
|------|--------|----------|---------|
| 淺層爬取 | ~10 頁 | 低 | 快 |
| 深度爬取 | ~30 頁 | 高 | 中等 |

**風險控制**：
- 相關性評分過濾（最低 0.3）
- 每域名頁數限制（最多 5 頁）
- 總超時設置（300 秒）

---

### 5.5 內容摘要：截斷 → 分層摘要

**問題**：當爬取頁面超過 5 頁時，簡單截斷會丟失重要資訊

**決策**：實現分層摘要機制
1. 先按域名分組
2. 每個域名生成摘要
3. 合併所有域名摘要

**配置**：
```python
HIERARCHICAL_SUMMARY_ENABLED = True
HIERARCHICAL_SUMMARY_THRESHOLD = 5  # 超過 5 頁才啟用
DOMAIN_SUMMARY_MAX_LENGTH = 800     # 每域名摘要上限
```

---

## 6. 遇到的困難與解決方法

### 6.1 DataForSEO API 參數格式錯誤

**問題描述**：
調用 Google Ads Keywords API 時返回空結果。

**根本原因**：
API 要求 `keywords` 參數為陣列格式，但我們傳遞了單一字串。

**錯誤程式碼**：
```python
data = [{"keyword": keyword, "location_code": 2344}]  # ❌ 錯誤
```

**修正後**：
```python
data = [{"keywords": [keyword], "location_code": 2344}]  # ✅ 正確
```

**相關提交**：`2897eb5` (2026-02-01)

---

### 6.2 中文關鍵字搜尋建議不足

**問題描述**：
中文關鍵字在 Google Ads 數據庫中的覆蓋率較低，經常返回空結果。

**解決方案**：
實現智能降級機制：
```python
def get_keyword_suggestions(self, keyword, ...):
    # 第一次嘗試：不包含種子關鍵字
    data = [{"keywords": [keyword], "include_seed_keyword": False}]
    result = self._make_request(...)

    # 如果沒有結果，降級為包含種子關鍵字
    if not suggestions:
        data = [{"keywords": [keyword], "include_seed_keyword": True}]
        result = self._make_request(...)
```

---

### 6.3 LLM JSON 輸出格式問題

**問題描述**：
LLM 有時會在 JSON 外添加 Markdown 代碼塊標記（```json），導致解析失敗。

**解決方案**：
多重清理機制：
```python
# 1. 嘗試提取代碼塊內容
code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', output)
if code_block_match:
    cleaned_output = code_block_match.group(1).strip()

# 2. 直接移除標記
cleaned_output = re.sub(r'```(?:json)?', '', cleaned_output)

# 3. 修復尾隨逗號（LLM 常見錯誤）
cleaned_output = re.sub(r',(\s*[}\]])', r'\1', cleaned_output)
```

---

### 6.4 Wix Ricos 格式相容性問題

**問題描述**：
發送文章到 Wix 時遇到多個格式錯誤：
1. "Expected a string" 錯誤
2. 空段落導致解析失敗
3. metadata 欄位不被接受

**解決歷程**：

| 提交 | 問題 | 解決方案 |
|------|------|---------|
| `7bb3e63` | 空段落格式錯誤 | 修復空段落的 nodes 結構 |
| `38cf98f` | 'Expected a string' | 移除 metadata 欄位 |
| `dd87940` | 空節點問題 | 清除文檔中的空節點 |

**最終解決方案**：
```python
def get_ricos_document(self) -> Dict[str, Any]:
    # 清理空節點
    cleaned_nodes = []
    for node in self.nodes:
        if node.get("nodes"):
            valid_children = [
                child for child in node["nodes"]
                if child.get("textData", {}).get("text", "").strip()
            ]
            if valid_children:
                node["nodes"] = valid_children
                cleaned_nodes.append(node)

    # 確保至少有一個節點
    if not cleaned_nodes:
        cleaned_nodes.append({
            "type": "PARAGRAPH",
            "nodes": [{"type": "TEXT", "textData": {"text": " "}}]
        })

    return {"nodes": cleaned_nodes}
```

---

### 6.5 資料庫連接池線程安全問題

**問題描述**：
在多線程環境下使用 `SimpleConnectionPool` 導致連接阻塞。

**解決方案**：
改用 `ThreadedConnectionPool`：
```python
# 修改前（不安全）
db_pool = pool.SimpleConnectionPool(...)

# 修改後（線程安全）
db_pool = pool.ThreadedConnectionPool(
    minconn=Config.DB_POOL_MIN,
    maxconn=Config.DB_POOL_MAX,
    dsn=Config.DATABASE_URL
)
```

---

### 6.6 PostgreSQL NUL 字符問題

**問題描述**：
爬取的網頁內容包含 NUL 字符（\x00），導致 PostgreSQL 插入失敗。

**解決方案**：
實現遞迴清理函數：
```python
def sanitize_for_postgres(text: str) -> str:
    """清理 PostgreSQL 不支援的字符"""
    if not text:
        return text
    return text.replace('\x00', '').replace('\u0000', '')

def sanitize_dict_for_postgres(data: Any) -> Any:
    """遞迴清理字典/列表中的 NUL 字符"""
    if isinstance(data, str):
        return sanitize_for_postgres(data)
    elif isinstance(data, dict):
        return {k: sanitize_dict_for_postgres(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_dict_for_postgres(item) for item in data]
    return data
```

---

## 7. 系統演變歷程

### 7.1 開發時間線

```
2026-01-14 ──────────────────────────────────────────────────────────
    │
    ├─ 專案初建
    │   - 上傳初始檔案
    │   - 建立 Flask 框架
    │   - 建立 HA 新聞稿爬蟲
    │   - 建立關鍵字頁面 UI
    │
2026-01-15 ──────────────────────────────────────────────────────────
    │
    ├─ 錯誤處理與穩定性
    │   - 新增錯誤頁面模板
    │   - 改進異常處理機制
    │
2026-01-31 ──────────────────────────────────────────────────────────
    │
    ├─ 重大重構（Optimization）
    │   - 從單體 1500+ 行精簡
    │   - 拆分為模組化架構
    │   - 建立 services/ 目錄
    │   - 建立 utils/ 工具類
    │
2026-02-01 ──────────────────────────────────────────────────────────
    │
    ├─ SEO API 整合
    │   - 整合 DataForSEO API
    │   - 建立 SEO 協調器
    │   - 修復 API 參數問題
    │   - 實現快取機制
    │
2026-02-02 ──────────────────────────────────────────────────────────
    │
    ├─ AI 模型與 Labs API
    │   - 改用 Labs API 替代 Trends
    │   - 實現多模型選擇功能
    │   - 建立統一 LLM 介面
    │   - 整合 SEO 工作流程
    │
2026-02-03 ──────────────────────────────────────────────────────────
    │
    ├─ 深度爬蟲與優化
    │   - 實現深度爬蟲功能
    │   - 新增 GPT-5.2 Instant
    │   - 實現 10000 字限制
    │   - 速度優化
    │
2026-02-04 ──────────────────────────────────────────────────────────
    │
    └─ Wix 整合
        - 建立 Wix API 客戶端
        - 實現 HTML → Ricos 轉換
        - 修復多個格式問題
        - 診斷能力改進
```

### 7.2 程式碼統計

| 模組 | 行數 | 功能 |
|------|------|------|
| app.py | 1,553 | 主應用程式 |
| article_generator.py | 1,143 | 文章生成 |
| deep_crawler.py | 758 | 深度爬蟲 |
| dataforseo_client.py | 744 | SEO API |
| seo_orchestrator.py | 587+ | SEO 協調 |
| wix_client.py | 475 | Wix 整合 |
| database.py | 467 | 資料庫操作 |
| keyword_extractor.py | 348+ | 關鍵字提取 |
| llm_client.py | 163 | LLM 統一介面 |
| **總計** | **~6,000+** | |

### 7.3 Git 提交統計

- **總提交數**：93 次
- **開發週期**：2026-01-14 至 2026-02-04（22 天）
- **主要貢獻者**：WONG Ka Yi Richard
- **AI 協作**：Claude Sonnet 4.5 (Co-Authored-By)

---

## 8. 結論與未來展望

### 8.1 專案成果

本專案成功實現了一個完整的 SEO 文章自動生成平台，主要成果包括：

1. **自動化工作流程**：從關鍵字研究到文章發布的端到端自動化
2. **多模型支援**：靈活切換不同 AI 模型以平衡成本與品質
3. **智能爬蟲**：基於相關性評分的深度爬取機制
4. **平台整合**：與 Wix Blog 的無縫整合
5. **模組化架構**：易於維護和擴展的程式碼結構

### 8.2 未來改進方向

1. **多語言支援**：擴展支援更多語言（如簡體中文、英文）
2. **圖片生成**：整合 AI 圖像生成，自動為文章配圖
3. **SEO 評分**：文章發布前的 SEO 品質評分
4. **A/B 測試**：不同標題、內容的效果比較
5. **使用者認證**：多用戶支援與權限管理
6. **更多發布平台**：支援 WordPress、Medium 等平台

### 8.3 學習心得

在本專案的開發過程中，我們獲得了以下寶貴經驗：

1. **API 整合的複雜性**：不同 API 有不同的參數格式和返回結構，需要仔細閱讀文檔並進行充分測試
2. **AI 輸出的不確定性**：LLM 的輸出格式可能不穩定，需要實現健壯的解析和錯誤處理機制
3. **架構設計的重要性**：初期的模組化設計可以大幅降低後期維護成本
4. **快取策略的平衡**：在數據新鮮度和 API 成本之間找到平衡點

---

## 9. 參考資料

1. Flask 官方文檔：https://flask.palletsprojects.com/
2. DataForSEO API 文檔：https://docs.dataforseo.com/
3. Wix Blog API 文檔：https://dev.wix.com/api/rest/wix-blog/
4. PostgreSQL 官方文檔：https://www.postgresql.org/docs/
5. Beautiful Soup 文檔：https://www.crummy.com/software/BeautifulSoup/bs4/doc/
6. Poe API 文檔：https://creator.poe.com/docs/api

---

## 附錄 A：環境配置

### 必要環境變數

```bash
# 資料庫
DATABASE_URL=postgresql://user:password@host:5432/dbname

# AI 模型
DEEPSEEK_API_KEY=your_deepseek_key
POE_API_KEY=your_poe_key

# DataForSEO
DATAFORSEO_LOGIN=your_login
DATAFORSEO_PASSWORD=your_password

# Wix (可選)
WIX_CLIENT_ID=your_client_id
WIX_CLIENT_SECRET=your_client_secret
WIX_REFRESH_TOKEN=your_refresh_token
WIX_INSTANCE_ID=your_site_id
WIX_MEMBER_ID=your_member_id
```

### 安裝依賴

```bash
pip install -r requirements.txt
```

### 啟動應用

```bash
# 開發環境
python app.py

# 生產環境
gunicorn -c gunicorn.conf.py app:app
```

---

## 附錄 B：API 端點列表

| 端點 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 首頁 |
| `/keywords` | GET/POST | 關鍵字頁面 |
| `/keywords_json` | GET | 關鍵字 JSON API |
| `/generate_articles` | POST | 生成文章 |
| `/progress` | GET | 生成進度 |
| `/manage_articles` | GET | 文章管理頁 |
| `/view_article/<id>` | GET | 查看文章 |
| `/delete_article/<id>` | POST | 刪除文章 |
| `/api/seo/keyword_research` | POST | SEO 關鍵字研究 |
| `/api/seo/analyze_serp` | POST | SERP 分析 |
| `/api/seo/start_crawl` | POST | 啟動爬蟲 |
| `/api/set_model` | POST | 設定 AI 模型 |
| `/api/wix/status` | GET | Wix 狀態 |
| `/send_to_wix/<id>` | POST | 發送到 Wix |

---

*報告完*
