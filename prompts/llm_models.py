"""
所有 LLM provider/model 設定的單一來源。
新增或更換模型只需修改此檔案，config.py 從這裡 import。
"""

# ── Provider 清單 ──────────────────────────────────────────
LLM_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek（官方）",
        "api_url": "https://api.deepseek.com/chat/completions",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": {
            "deepseek-v4-pro": {
                "name": "DeepSeek V4 Pro",
                "desc": "通用對話，性價比極高",
                "has_thinking": False,
            },
            "deepseek-v4-flash": {
                "name": "DeepSeek V4 Flash",
                "desc": "快速輕量，適合關鍵字提取與摘要",
                "has_thinking": False,
            },
        },
    },
}

# ── 各功能使用的模型（修改這裡即可切換）──────────────────
DEFAULT_PROVIDER     = "deepseek"
DEFAULT_MODEL        = "deepseek-v4-pro"    # 文章生成
KEYWORD_MODEL        = "deepseek-v4-flash"  # 關鍵字提取
DOMAIN_SUMMARY_MODEL = "deepseek-v4-flash"  # SEO 結構化摘要
SCORING_MODEL        = "deepseek-v4-flash"  # 文章評分
