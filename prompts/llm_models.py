"""
所有 LLM provider/model 設定的單一來源。
config.py 從這裡 import LLM_PROVIDERS。
新增或更換模型只需修改此檔案。
"""

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
                "ui_visible": True,
            },
            "deepseek-v4-flash": {
                "name": "DeepSeek V4 Flash",
                "desc": "快速輕量，適合關鍵字提取",
                "has_thinking": False,
                "ui_visible": False,  # 內部用，不顯示於文章生成 UI
            },
        },
    },
    "poe": {
        "name": "Poe API",
        "api_url": "https://api.poe.com/v1/chat/completions",
        "api_key_env": "POE_API_KEY",
        "models": {
            "claude-opus-4.7": {
                "name": "Claude Opus 4.7",
                "desc": "Anthropic 旗艦推理模型",
                "has_thinking": True,
                "ui_visible": True,
            },
            "gpt-5.5": {
                "name": "GPT-5.5",
                "desc": "OpenAI 最新一代模型",
                "has_thinking": False,
                "ui_visible": True,
            },
            "gemini-3.1-pro": {
                "name": "Gemini 3.1 Pro",
                "desc": "Google DeepMind 旗艦模型",
                "has_thinking": False,
                "ui_visible": True,
            },
            "grok-4.20-multi-agent": {
                "name": "Grok 4.20 Multi-Agent",
                "desc": "xAI 多智能體推理模型",
                "has_thinking": False,
                "ui_visible": True,
            },
        },
    },
}


# 各功能使用的模型設定（修改此處即可切換）
DEFAULT_PROVIDER    = "deepseek"
DEFAULT_MODEL       = "deepseek-v4-pro"   # 文章生成預設
KEYWORD_MODEL       = "deepseek-v4-flash"  # 關鍵字提取
DOMAIN_SUMMARY_MODEL = "deepseek-v4-flash" # SEO 結構化摘要
SCORING_PROVIDER    = "deepseek"
SCORING_MODEL       = "deepseek-v4-pro"    # 文章評分


def get_ui_models():
    """返回所有 ui_visible=True 的模型，供前端選擇器使用。"""
    result = []
    for provider_key, provider in LLM_PROVIDERS.items():
        for model_key, model in provider["models"].items():
            if model.get("ui_visible", True):
                result.append({
                    "value": f"{provider_key}:{model_key}",
                    "label": model["name"],
                    "desc": model.get("desc", ""),
                    "group": provider["name"],
                    "has_thinking": model.get("has_thinking", False),
                })
    return result
