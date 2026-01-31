#!/usr/bin/env python3
"""
DataForSEO API 本地測試腳本
用於快速測試 API 並查看原始回應
"""

import os
import json
import base64
import requests
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 從環境變數獲取憑證
LOGIN = os.getenv("DATAFORSEO_LOGIN")
PASSWORD = os.getenv("DATAFORSEO_PASSWORD")

if not LOGIN or not PASSWORD:
    print("❌ 錯誤：請在 .env 文件中設置 DATAFORSEO_LOGIN 和 DATAFORSEO_PASSWORD")
    exit(1)

print(f"✅ 使用憑證：{LOGIN[:4]}****{LOGIN[-4:]}")
print()

# API 基礎 URL
BASE_URL = "https://api.dataforseo.com/v3"

def make_request(endpoint, data=None):
    """發送 API 請求"""
    url = f"{BASE_URL}/{endpoint}"

    # 建立 Basic Auth header
    credentials = f"{LOGIN}:{PASSWORD}"
    encoded = base64.b64encode(credentials.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json"
    }

    print(f"📡 請求: POST {endpoint}")
    if data:
        print(f"📤 參數: {json.dumps(data, ensure_ascii=False, indent=2)}")
    print()

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()

        print(f"📥 回應狀態碼: {result.get('status_code')}")
        print(f"📥 回應訊息: {result.get('status_message')}")
        print()
        print("=" * 80)
        print("完整回應:")
        print("=" * 80)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("=" * 80)
        print()

        return result

    except requests.exceptions.RequestException as e:
        print(f"❌ 請求錯誤: {e}")
        return None
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return None

def test_connection():
    """測試 API 連接"""
    print("🔧 測試 1: API 連接")
    print("-" * 80)
    result = make_request("appendix/user_data")
    if result and result.get("status_code") == 20000:
        print("✅ API 連接成功！")
    else:
        print("❌ API 連接失敗")
    print()
    input("按 Enter 繼續...")
    print()

def test_google_trends(keyword="長者"):
    """測試 Google Trends API"""
    print(f"🔧 測試 2: Google Trends API（關鍵字：{keyword}）")
    print("-" * 80)

    data = [{
        "keyword": keyword,
        "location_code": 2344,  # 香港
        "language_code": "zh-TW"
    }]

    result = make_request("keywords_data/google_trends/explore/live", data)

    if result:
        # 分析結果
        tasks = result.get("tasks", [])
        if tasks and tasks[0].get("result"):
            task_result = tasks[0]["result"]
            print(f"✅ 返回 {len(task_result)} 個結果")

            for i, item in enumerate(task_result, 1):
                print(f"\n結果 {i}:")
                related_topics = item.get("related_topics", {})
                related_queries = item.get("related_queries", {})

                rising_topics = related_topics.get("rising", [])
                top_topics = related_topics.get("top", [])
                rising_queries = related_queries.get("rising", [])
                top_queries = related_queries.get("top", [])

                print(f"  Rising Topics: {len(rising_topics)}")
                print(f"  Top Topics: {len(top_topics)}")
                print(f"  Rising Queries: {len(rising_queries)}")
                print(f"  Top Queries: {len(top_queries)}")
        else:
            print("⚠️ 結果為空")

    print()
    input("按 Enter 繼續...")
    print()

def test_keyword_metrics(keyword="長者"):
    """測試關鍵字指標 API"""
    print(f"🔧 測試 3: 關鍵字指標 API（關鍵字：{keyword}）")
    print("-" * 80)

    data = [{
        "keywords": [keyword],
        "location_code": 2344,  # 香港
        "language_code": "zh-TW"
    }]

    result = make_request("keywords_data/google_ads/search_volume/live", data)

    if result:
        # 分析結果
        tasks = result.get("tasks", [])
        if tasks and tasks[0].get("result"):
            task_result = tasks[0]["result"]
            print(f"✅ 返回 {len(task_result)} 個結果")

            for item in task_result:
                print(f"\n關鍵字: {item.get('keyword')}")
                print(f"  搜尋量: {item.get('search_volume')}")
                print(f"  CPC: ${item.get('cpc')}")
                print(f"  競爭度: {item.get('competition')}")
                print(f"  競爭等級: {item.get('competition_level')}")
        else:
            print("⚠️ 結果為空")

    print()
    input("按 Enter 繼續...")
    print()

def test_serp(keyword="長者"):
    """測試 SERP API"""
    print(f"🔧 測試 4: SERP API（關鍵字：{keyword}）")
    print("-" * 80)

    data = [{
        "keyword": keyword,
        "location_code": 2344,  # 香港
        "language_code": "zh-TW",
        "device": "desktop",
        "os": "windows",
        "depth": 5
    }]

    result = make_request("serp/google/organic/live/regular", data)

    if result:
        # 分析結果
        tasks = result.get("tasks", [])
        if tasks and tasks[0].get("result"):
            task_result = tasks[0]["result"]
            print(f"✅ 返回 {len(task_result)} 個結果")

            for item in task_result:
                items = item.get("items", [])
                organic = [i for i in items if i.get("type") == "organic"]
                paa = [i for i in items if i.get("type") == "people_also_ask"]

                print(f"\n有機結果: {len(organic)}")
                print(f"常問問題: {len(paa)}")

                if organic:
                    print("\n前 3 個有機結果:")
                    for i, org in enumerate(organic[:3], 1):
                        print(f"  {i}. {org.get('title')}")
                        print(f"     {org.get('url')}")
        else:
            print("⚠️ 結果為空")

    print()

def main():
    """主函數"""
    print("=" * 80)
    print("DataForSEO API 本地測試")
    print("=" * 80)
    print()

    keyword = input("請輸入測試關鍵字（直接按 Enter 使用預設值「長者」）: ").strip()
    if not keyword:
        keyword = "長者"

    print()
    print(f"使用關鍵字: {keyword}")
    print()

    # 運行所有測試
    test_connection()
    test_google_trends(keyword)
    test_keyword_metrics(keyword)
    test_serp(keyword)

    print("=" * 80)
    print("測試完成！")
    print("=" * 80)
    print()
    print("💡 提示:")
    print("1. 如果 Google Trends 或關鍵字指標返回空結果，可能是:")
    print("   - 帳號權限不足")
    print("   - 該關鍵字在香港地區數據不足")
    print("   - API 配額已用完")
    print()
    print("2. 請將上面的完整回應複製並提供給開發者進行分析")
    print()

if __name__ == "__main__":
    main()
