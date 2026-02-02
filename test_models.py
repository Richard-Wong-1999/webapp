"""
LLM 模型儲存測試腳本

測試不同 LLM 模型生成文章後能否正確儲存到資料庫。
用法: python test_models.py [--models MODEL1,MODEL2] [--keyword KEYWORD]
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Tuple

# 添加專案路徑
sys.path.insert(0, '.')

from config import Config
from services.llm_client import call_llm
from services.database import insert_article, get_article_by_id, init_connection_pool, delete_article
from utils.logger import logger


# 測試用的簡化 Prompt
TEST_PROMPT_TEMPLATE = """你是一位專業的內容撰寫專家。請根據以下關鍵詞生成一篇測試文章。

關鍵詞：{keyword}

請嚴格按照以下 JSON 格式輸出（不要添加任何其他文字）：
[
  {{
    "keywords": ["{keyword}"],
    "zh": {{
      "title": "中文標題（20-30字）",
      "body": "中文正文（100-200字的測試內容）",
      "meta_title": "SEO 標題",
      "meta_description": "SEO 描述"
    }},
    "en": {{
      "title": "English Title",
      "body": "English body content for testing (100-200 words).",
      "meta_title": "SEO Title",
      "meta_description": "SEO Description"
    }}
  }}
]

重要：只輸出 JSON，不要有任何其他說明文字。"""


class ModelTester:
    """模型測試器"""

    def __init__(self):
        self.results: List[Dict] = []
        self.test_article_ids: List[int] = []  # 記錄測試文章 ID，用於清理

    def get_all_models(self) -> List[Tuple[str, str]]:
        """獲取所有可用的模型"""
        models = []
        for provider, config in Config.LLM_PROVIDERS.items():
            for model_id in config.get("models", {}).keys():
                models.append((provider, model_id))
        return models

    def test_single_model(self, provider: str, model: str, keyword: str) -> Dict:
        """測試單個模型"""
        result = {
            "provider": provider,
            "model": model,
            "keyword": keyword,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "llm_call_success": False,
            "llm_output_length": 0,
            "json_parse_success": False,
            "json_parse_error": None,
            "db_save_success": False,
            "db_save_error": None,
            "db_verify_success": False,
            "article_id": None,
            "raw_output_snippet": "",
            "duration_seconds": 0
        }

        start_time = time.time()
        prompt = TEST_PROMPT_TEMPLATE.format(keyword=keyword)

        print(f"\n{'='*60}")
        print(f"測試: {provider}/{model}")
        print(f"關鍵字: {keyword}")
        print(f"{'='*60}")

        # Step 1: 呼叫 LLM
        print("📡 Step 1: 呼叫 LLM API...")
        try:
            output, metadata = call_llm(prompt, provider=provider, model=model)
            result["llm_output_length"] = len(output) if output else 0
            result["raw_output_snippet"] = output[:500] if output else ""

            if output:
                result["llm_call_success"] = True
                print(f"   ✅ LLM 回應成功 ({len(output)} 字元)")
            else:
                print(f"   ❌ LLM 回應為空")
                result["duration_seconds"] = time.time() - start_time
                return result

        except Exception as e:
            print(f"   ❌ LLM 呼叫失敗: {e}")
            result["json_parse_error"] = str(e)
            result["duration_seconds"] = time.time() - start_time
            return result

        # Step 2: 解析 JSON
        print("📋 Step 2: 解析 JSON...")
        try:
            # 嘗試匹配 JSON 數組
            match = re.search(r'\[.*\]', output, re.S)
            if match:
                parsed = json.loads(match.group(0))
                print(f"   ✅ 找到 JSON 數組並成功解析")
            else:
                # 嘗試直接解析
                parsed = json.loads(output)
                print(f"   ✅ 直接解析 JSON 成功")

            if not isinstance(parsed, list):
                parsed = [parsed]

            result["json_parse_success"] = True

        except json.JSONDecodeError as e:
            print(f"   ❌ JSON 解析失敗: {e}")
            print(f"   原始輸出前 300 字:")
            print(f"   {output[:300]}...")
            result["json_parse_error"] = str(e)
            result["duration_seconds"] = time.time() - start_time
            return result

        # Step 3: 儲存到資料庫
        print("💾 Step 3: 儲存到資料庫...")
        try:
            item = parsed[0]
            zh = item.get("zh") or {}
            en = item.get("en") or {}

            article_data = {
                "title_zh": (zh.get("title") or "").strip(),
                "body_zh": (zh.get("body") or "").strip(),
                "meta_title_zh": (zh.get("meta_title") or "").strip(),
                "meta_description_zh": (zh.get("meta_description") or "").strip(),
                "title_en": (en.get("title") or "").strip(),
                "body_en": (en.get("body") or "").strip(),
                "meta_title_en": (en.get("meta_title") or "").strip(),
                "meta_description_en": (en.get("meta_description") or "").strip(),
                "keywords": json.dumps(item.get("keywords", [keyword]), ensure_ascii=False),
                "timestamp": f"TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "title": (zh.get("title") or "").strip() or "測試文章",
                "body": (zh.get("body") or "").strip(),
                "meta_title": (zh.get("meta_title") or "").strip(),
                "meta_description": (zh.get("meta_description") or "").strip(),
                "llm_provider": provider,
                "llm_model": model,
                "prompt_zh": f"[TEST] {prompt[:200]}..."
            }

            db_result = insert_article(article_data)

            if db_result.get("success"):
                result["db_save_success"] = True
                result["article_id"] = db_result.get("id")
                self.test_article_ids.append(result["article_id"])
                print(f"   ✅ 儲存成功 (ID: {result['article_id']})")
            else:
                result["db_save_error"] = db_result.get("message", "未知錯誤")
                print(f"   ❌ 儲存失敗: {result['db_save_error']}")

        except Exception as e:
            result["db_save_error"] = str(e)
            print(f"   ❌ 儲存異常: {e}")

        # Step 4: 驗證資料庫記錄
        if result["article_id"]:
            print("🔍 Step 4: 驗證資料庫記錄...")
            try:
                article = get_article_by_id(result["article_id"])
                if article:
                    # 檢查關鍵欄位
                    checks = {
                        "title_zh": bool(article.get("title_zh")),
                        "body_zh": bool(article.get("body_zh")),
                        "title_en": bool(article.get("title_en")),
                        "body_en": bool(article.get("body_en")),
                        "llm_provider": article.get("llm_provider") == provider,
                        "llm_model": article.get("llm_model") == model
                    }

                    all_passed = all(checks.values())
                    result["db_verify_success"] = all_passed

                    if all_passed:
                        print(f"   ✅ 所有欄位驗證通過")
                    else:
                        failed = [k for k, v in checks.items() if not v]
                        print(f"   ⚠️ 部分欄位驗證失敗: {failed}")
                else:
                    print(f"   ❌ 無法讀取文章")

            except Exception as e:
                print(f"   ❌ 驗證異常: {e}")

        result["duration_seconds"] = round(time.time() - start_time, 2)
        print(f"\n⏱️ 測試耗時: {result['duration_seconds']} 秒")

        return result

    def run_all_tests(self, models: List[Tuple[str, str]] = None, keyword: str = "測試關鍵字") -> List[Dict]:
        """運行所有測試"""
        if models is None:
            models = self.get_all_models()

        print("\n" + "=" * 70)
        print("🧪 LLM 模型儲存測試")
        print(f"   測試模型數: {len(models)}")
        print(f"   測試關鍵字: {keyword}")
        print("=" * 70)

        for provider, model in models:
            result = self.test_single_model(provider, model, keyword)
            self.results.append(result)
            time.sleep(2)  # 避免 API 限流

        return self.results

    def print_report(self):
        """打印測試報告"""
        print("\n" + "=" * 70)
        print("📊 測試報告")
        print("=" * 70)

        # 統計
        total = len(self.results)
        llm_success = sum(1 for r in self.results if r["llm_call_success"])
        json_success = sum(1 for r in self.results if r["json_parse_success"])
        db_success = sum(1 for r in self.results if r["db_save_success"])
        verify_success = sum(1 for r in self.results if r["db_verify_success"])

        print(f"\n📈 總體統計:")
        print(f"   總測試數: {total}")
        print(f"   LLM 呼叫成功: {llm_success}/{total} ({llm_success/total*100:.1f}%)")
        print(f"   JSON 解析成功: {json_success}/{total} ({json_success/total*100:.1f}%)")
        print(f"   資料庫儲存成功: {db_success}/{total} ({db_success/total*100:.1f}%)")
        print(f"   完整驗證通過: {verify_success}/{total} ({verify_success/total*100:.1f}%)")

        # 詳細結果表格
        print(f"\n📋 詳細結果:")
        print("-" * 90)
        print(f"{'Provider':<12} {'Model':<18} {'LLM':<6} {'JSON':<6} {'DB':<6} {'驗證':<6} {'耗時':<8}")
        print("-" * 90)

        for r in self.results:
            llm = "✅" if r["llm_call_success"] else "❌"
            json_ok = "✅" if r["json_parse_success"] else "❌"
            db = "✅" if r["db_save_success"] else "❌"
            verify = "✅" if r["db_verify_success"] else "❌"
            duration = f"{r['duration_seconds']}s"

            print(f"{r['provider']:<12} {r['model']:<18} {llm:<6} {json_ok:<6} {db:<6} {verify:<6} {duration:<8}")

        print("-" * 90)

        # 失敗詳情
        failures = [r for r in self.results if not r["db_verify_success"]]
        if failures:
            print(f"\n⚠️ 失敗詳情:")
            for r in failures:
                print(f"\n   🔸 {r['provider']}/{r['model']}:")
                if not r["llm_call_success"]:
                    print(f"      - LLM 呼叫失敗")
                if r["llm_call_success"] and not r["json_parse_success"]:
                    print(f"      - JSON 解析失敗: {r['json_parse_error']}")
                    print(f"      - 原始輸出前 200 字: {r['raw_output_snippet'][:200]}...")
                if r["json_parse_success"] and not r["db_save_success"]:
                    print(f"      - 資料庫儲存失敗: {r['db_save_error']}")

        print("\n" + "=" * 70)

    def cleanup_test_articles(self):
        """清理測試文章"""
        if not self.test_article_ids:
            return

        print(f"\n🧹 清理測試文章 ({len(self.test_article_ids)} 篇)...")
        for article_id in self.test_article_ids:
            try:
                result = delete_article(article_id)
                if result.get("success"):
                    print(f"   ✅ 已刪除文章 ID: {article_id}")
                else:
                    print(f"   ⚠️ 刪除失敗 ID: {article_id}")
            except Exception as e:
                print(f"   ❌ 刪除異常 ID: {article_id} - {e}")

    def save_report(self, filename: str = None):
        """儲存測試報告為 JSON"""
        if filename is None:
            filename = f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        report = {
            "test_time": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "summary": {
                "llm_success": sum(1 for r in self.results if r["llm_call_success"]),
                "json_success": sum(1 for r in self.results if r["json_parse_success"]),
                "db_success": sum(1 for r in self.results if r["db_save_success"]),
                "verify_success": sum(1 for r in self.results if r["db_verify_success"])
            },
            "results": self.results
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n💾 測試報告已儲存: {filename}")


def main():
    parser = argparse.ArgumentParser(description="測試 LLM 模型文章生成和儲存")
    parser.add_argument("--models", type=str, help="要測試的模型，格式: provider/model,provider/model")
    parser.add_argument("--keyword", type=str, default="香港長者服務", help="測試用關鍵字")
    parser.add_argument("--cleanup", action="store_true", help="測試後刪除測試文章")
    parser.add_argument("--save-report", action="store_true", help="儲存測試報告為 JSON")

    args = parser.parse_args()

    # 初始化資料庫連接池
    print("🔌 初始化資料庫連接...")
    init_connection_pool()

    tester = ModelTester()

    # 解析指定的模型
    models = None
    if args.models:
        models = []
        for m in args.models.split(","):
            parts = m.strip().split("/")
            if len(parts) == 2:
                models.append((parts[0], parts[1]))
            else:
                print(f"⚠️ 無效的模型格式: {m}")

    # 運行測試
    tester.run_all_tests(models=models, keyword=args.keyword)
    tester.print_report()

    # 儲存報告
    if args.save_report:
        tester.save_report()

    # 清理測試文章
    if args.cleanup:
        tester.cleanup_test_articles()

    print("\n✅ 測試完成!")


if __name__ == "__main__":
    main()
