import os
from dotenv import load_dotenv
from prompts.llm_models import (
    LLM_PROVIDERS as _LLM_PROVIDERS,
    DEFAULT_PROVIDER as _DEFAULT_PROVIDER,
    DEFAULT_MODEL as _DEFAULT_MODEL,
    KEYWORD_MODEL as _KEYWORD_MODEL,
    DOMAIN_SUMMARY_MODEL as _DOMAIN_SUMMARY_MODEL,
    SCORING_MODEL as _SCORING_MODEL,
)

load_dotenv()

class Config:
    """集中管理所有配置項目"""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    DEBUG = os.getenv("DEBUG", "False") == "True"

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

    # DeepSeek API
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
    DEEPSEEK_MODEL = _DEFAULT_MODEL
    DEEPSEEK_TIMEOUT = 120
    DEEPSEEK_TEMPERATURE = 0.7
    DEEPSEEK_MAX_TOKENS = 8000  # Increased for article generation with HTML content

    # Poe API (OpenAI 相容格式)
    POE_API_KEY = os.getenv("POE_API_KEY")
    POE_API_URL = "https://api.poe.com/v1/chat/completions"

    # LLM 模型配置
    LLM_PROVIDERS = _LLM_PROVIDERS

    DEFAULT_PROVIDER = _DEFAULT_PROVIDER
    DEFAULT_MODEL = _DEFAULT_MODEL
    KEYWORD_MODEL = _KEYWORD_MODEL
    SCORING_MODEL = _SCORING_MODEL

    # Crawler directories
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    SWD_DIR = os.path.join(BASE_DIR, "crawler", "swd_press")
    HA_DIR = os.path.join(BASE_DIR, "crawler", "ha_press")

    # Cache configuration
    KEYWORD_CACHE_TTL = 3600  # 1 hour in seconds
    ARTICLE_CACHE_TTL = 3600  # 1 hour in seconds

    # Threading and rate limiting
    ARTICLE_GENERATION_WORKERS = 5  # 並發數
    API_RATE_LIMIT = 0.5  # Calls per second (1 call every 2 seconds)

    # Content limits
    MAX_CHARS_ZH = 10000
    MAX_CHARS_EN = 10000
    DEFAULT_RECENT_DAYS = 30

    # Crawler settings
    SWD_CRAWL_DAYS = 30
    HA_CRAWL_DAYS = 30
    HA_MAX_PAGES = 200
    HA_MAX_ITEMS = 500
    HA_SLEEP = 0.8

    # InfoGov settings
    INFOGOV_HOST = "www.info.gov.hk"

    # DataForSEO API
    DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
    DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")
    DATAFORSEO_RATE_LIMIT = 0.5  # 請求/秒

    # SEO 快取 TTL（秒）
    SEO_TRENDS_CACHE_TTL = 3600       # 1 小時
    SEO_KEYWORD_CACHE_TTL = 86400     # 24 小時
    SEO_SERP_CACHE_TTL = 21600        # 6 小時

    # 爬蟲設定
    SCRAPE_TIMEOUT = 10
    SCRAPE_MAX_CONCURRENT = 5

    # 深度爬取設定
    DEEP_CRAWL_ENABLED = True              # 是否啟用深度爬取
    DEEP_CRAWL_MAX_DEPTH = 2               # 最大深度（SERP 頁面 + 內部連結）
    DEEP_CRAWL_MAX_PAGES_PER_DOMAIN = 5    # 每個域名最多頁數
    DEEP_CRAWL_MAX_TOTAL_PAGES = 30        # 總頁面上限
    DEEP_CRAWL_MIN_RELEVANCE = 0.3         # 最低相關性分數
    DEEP_CRAWL_TIMEOUT = 300               # 深度爬取總超時（秒）

    # 香港位置代碼（DataForSEO）
    HK_LOCATION_CODE = 2344

    # 分層摘要設定
    HIERARCHICAL_SUMMARY_ENABLED = True       # 是否啟用分層摘要
    HIERARCHICAL_SUMMARY_THRESHOLD = 5        # 超過多少頁才啟用分層摘要
    DOMAIN_SUMMARY_MAX_LENGTH = 800           # 每個域名摘要最大長度（字）
    DOMAIN_SUMMARY_MODEL = _DOMAIN_SUMMARY_MODEL    # 摘要用的模型
    DOMAIN_SUMMARY_MAX_WORKERS = 3            # 並行生成摘要的最大線程數
    DOMAIN_SUMMARY_CACHE_TTL = 21600          # 域名摘要快取 TTL（6小時，與 SERP 快取相同）

    # Wix Blog API 配置
    WIX_CLIENT_ID = os.getenv("WIX_CLIENT_ID")
    WIX_CLIENT_SECRET = os.getenv("WIX_CLIENT_SECRET")
    WIX_INSTANCE_ID = os.getenv("WIX_INSTANCE_ID")
    WIX_REFRESH_TOKEN = os.getenv("WIX_REFRESH_TOKEN")
    WIX_MEMBER_ID = os.getenv("WIX_MEMBER_ID")  # Blog Writer 的 Member ID
    WIX_API_BASE_URL = "https://www.wixapis.com"

    @classmethod
    def validate(cls):
        """驗證必要的配置是否存在"""
        required = ["DATABASE_URL", "DEEPSEEK_API_KEY"]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"缺少必要的環境變數: {', '.join(missing)}")
        return True
