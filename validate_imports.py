"""
簡單的導入驗證（不需要環境變數）
"""

import sys
import os

# 暫時移除環境變數驗證
os.environ.setdefault('DATABASE_URL', 'postgresql://dummy')
os.environ.setdefault('DEEPSEEK_API_KEY', 'dummy_key')

def test_basic_imports():
    """測試基本導入"""
    print("🔍 開始驗證模組導入...\n")

    errors = []

    # 測試配置
    try:
        from config import Config
        print("✅ config.py 載入成功")
    except Exception as e:
        print(f"❌ config.py 載入失敗: {e}")
        errors.append(e)

    # 測試模型
    try:
        from models import ProgressTracker
        print("✅ models 模組載入成功")
    except Exception as e:
        print(f"❌ models 模組載入失敗: {e}")
        errors.append(e)

    # 測試工具
    try:
        from utils import logger, RateLimiter, cache_manager
        print("✅ utils 模組載入成功")
    except Exception as e:
        print(f"❌ utils 模組載入失敗: {e}")
        errors.append(e)

    # 測試服務
    try:
        from services import normalize_source
        print("✅ services 模組載入成功")
    except Exception as e:
        print(f"❌ services 模組載入失敗: {e}")
        errors.append(e)

    # 測試主應用
    try:
        from app import app
        print("✅ app.py 載入成功")
        print(f"   路由數量: {len(list(app.url_map.iter_rules()))}")
    except Exception as e:
        print(f"❌ app.py 載入失敗: {e}")
        errors.append(e)

    print("\n" + "="*60)

    if errors:
        print(f"❌ 發現 {len(errors)} 個錯誤")
        return False
    else:
        print("✅ 所有模組載入成功！")
        return True


if __name__ == "__main__":
    print("="*60)
    print("模組導入驗證")
    print("="*60 + "\n")

    success = test_basic_imports()
    sys.exit(0 if success else 1)
