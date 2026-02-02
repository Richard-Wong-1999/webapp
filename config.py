import os
from dotenv import load_dotenv

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
    DEEPSEEK_MODEL = "deepseek-chat"
    DEEPSEEK_TIMEOUT = 120
    DEEPSEEK_TEMPERATURE = 0.7
    DEEPSEEK_MAX_TOKENS = 3500

    # Poe API (OpenAI 相容格式)
    POE_API_KEY = os.getenv("POE_API_KEY")
    POE_API_URL = "https://api.poe.com/v1/chat/completions"

    # LLM 模型配置
    LLM_PROVIDERS = {
        "deepseek": {
            "name": "DeepSeek（官方）",
            "api_url": "https://api.deepseek.com/chat/completions",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "deepseek-chat": {"name": "DeepSeek Chat", "desc": "通用對話，性價比極高", "has_thinking": False}
            }
        },
        "poe": {
            "name": "Poe API",
            "api_url": "https://api.poe.com/bot/",
            "api_key_env": "POE_API_KEY",
            "models": {
                "gpt-5.2": {"name": "GPT-5.2", "desc": "最新旗艦，能力最強", "has_thinking": False},
                "gpt-5-mini": {"name": "GPT-5 Mini", "desc": "輕量版 GPT-5，快速便宜", "has_thinking": False},
                "gpt-4.1": {"name": "GPT-4.1", "desc": "穩定可靠，廣泛應用", "has_thinking": False},
                "gpt-4.1-mini": {"name": "GPT-4.1 Mini", "desc": "輕量快速，適合簡單任務", "has_thinking": False},
                "gemini-3-pro": {"name": "Gemini 3 Pro", "desc": "Google 旗艦，多模態強", "has_thinking": False},
                "gemini-3-flash": {"name": "Gemini 3 Flash", "desc": "快速便宜，日常首選", "has_thinking": False}
            }
        }
    }

    DEFAULT_PROVIDER = "deepseek"
    DEFAULT_MODEL = "deepseek-chat"

    # Crawler directories
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    SWD_DIR = os.path.join(BASE_DIR, "crawler", "swd_press")
    HA_DIR = os.path.join(BASE_DIR, "crawler", "ha_press")

    # Cache configuration
    KEYWORD_CACHE_TTL = 3600  # 1 hour in seconds
    ARTICLE_CACHE_TTL = 3600  # 1 hour in seconds

    # Threading and rate limiting
    ARTICLE_GENERATION_WORKERS = 3  # 並發數
    API_RATE_LIMIT = 0.5  # Calls per second (1 call every 2 seconds)

    # Content limits
    MAX_CHARS_ZH = 3800
    MAX_CHARS_EN = 4200
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
    SCRAPE_MAX_CONCURRENT = 3

    # 香港位置代碼（DataForSEO）
    HK_LOCATION_CODE = 2344

    @classmethod
    def validate(cls):
        """驗證必要的配置是否存在"""
        required = ["DATABASE_URL", "DEEPSEEK_API_KEY"]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"缺少必要的環境變數: {', '.join(missing)}")
        return True
