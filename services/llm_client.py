"""統一 LLM 客戶端"""

from config import Config
from services.deepseek_client import call_deepseek
from services.poe_client import call_poe, filter_thinking_content
from utils.logger import logger


def call_llm(prompt_text: str, provider: str = None, model: str = None, session: dict = None) -> tuple:
    """
    統一 LLM 呼叫介面

    Args:
        prompt_text: 提示文本
        provider: LLM 提供者（deepseek 或 poe）
        model: 模型名稱
        session: Flask session 物件（可選，用於取得預設值）

    Returns:
        tuple: (回應內容, 元資料 dict 包含 provider, model, tokens_used 等)
    """
    # 從 session 獲取預設值（如未指定）
    if session:
        provider = provider or session.get('selected_provider', Config.DEFAULT_PROVIDER)
        model = model or session.get('selected_model', Config.DEFAULT_MODEL)
    else:
        provider = provider or Config.DEFAULT_PROVIDER
        model = model or Config.DEFAULT_MODEL

    metadata = {
        "provider": provider,
        "model": model,
        "tokens_used": 0
    }

    try:
        if provider == "deepseek":
            content = call_deepseek(prompt_text, model=model)
            # DeepSeek API 不返回 tokens，設為 0
            metadata["tokens_used"] = 0

        elif provider == "poe":
            content, tokens = call_poe(prompt_text, model=model)
            metadata["tokens_used"] = tokens

        else:
            logger.error(f"❌ 未知的 LLM provider: {provider}")
            content = ""

        return content, metadata

    except Exception as e:
        logger.error(f"❌ LLM 呼叫失敗 ({provider}/{model}): {e}")
        return "", metadata


def get_current_model(session: dict = None) -> dict:
    """
    獲取當前選擇的模型資訊

    Args:
        session: Flask session 物件

    Returns:
        dict: 包含 provider, model, name, has_thinking 的字典
    """
    if session:
        provider = session.get('selected_provider', Config.DEFAULT_PROVIDER)
        model = session.get('selected_model', Config.DEFAULT_MODEL)
    else:
        provider = Config.DEFAULT_PROVIDER
        model = Config.DEFAULT_MODEL

    # 取得模型詳細資訊
    provider_config = Config.LLM_PROVIDERS.get(provider, {})
    model_info = provider_config.get("models", {}).get(model, {})

    return {
        "provider": provider,
        "model": model,
        "name": model_info.get("name", model),
        "has_thinking": model_info.get("has_thinking", False),
        "provider_name": provider_config.get("name", provider)
    }


def get_available_models() -> dict:
    """
    獲取所有可用的模型清單

    Returns:
        dict: LLM_PROVIDERS 配置
    """
    return Config.LLM_PROVIDERS


def set_model(session: dict, provider: str, model: str) -> bool:
    """
    設定當前使用的模型

    Args:
        session: Flask session 物件
        provider: LLM 提供者
        model: 模型名稱

    Returns:
        bool: 是否設定成功
    """
    # 驗證 provider 和 model 是否有效
    if provider not in Config.LLM_PROVIDERS:
        logger.warning(f"⚠️ 無效的 provider: {provider}")
        return False

    if model not in Config.LLM_PROVIDERS[provider].get("models", {}):
        logger.warning(f"⚠️ 無效的 model: {model} (provider: {provider})")
        return False

    session['selected_provider'] = provider
    session['selected_model'] = model

    logger.info(f"✅ 已切換 LLM 模型: {provider}/{model}")
    return True


def accumulate_poe_points(session: dict, tokens_used: int) -> int:
    """
    累計 Poe API 使用點數

    Args:
        session: Flask session 物件
        tokens_used: 本次使用的 tokens 數

    Returns:
        int: 累計的總點數
    """
    current_points = session.get('poe_points_used', 0)
    new_total = current_points + tokens_used
    session['poe_points_used'] = new_total
    return new_total


def get_poe_points(session: dict) -> int:
    """
    獲取目前累計的 Poe 點數

    Args:
        session: Flask session 物件

    Returns:
        int: 累計的 Poe 點數
    """
    return session.get('poe_points_used', 0) if session else 0
