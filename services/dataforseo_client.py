"""DataForSEO API 統一客戶端

處理：
- Google Trends API
- Google Ads Keywords API（搜尋量、CPC、競爭度）
- SERP API（香港搜尋結果）
"""

import time
import json
import base64
import requests
from typing import List, Dict, Optional, Any
from config import Config
from utils.logger import logger


class DataForSEOClient:
    """DataForSEO API 客戶端"""

    BASE_URL = "https://api.dataforseo.com/v3"

    def __init__(self):
        self.login = Config.DATAFORSEO_LOGIN
        self.password = Config.DATAFORSEO_PASSWORD
        self.rate_limit = getattr(Config, 'DATAFORSEO_RATE_LIMIT', 0.5)
        self._last_request_time = 0

        if not self.login or not self.password:
            logger.warning("DataForSEO credentials not configured")

    def _get_auth_header(self) -> Dict[str, str]:
        """取得 Basic Auth header"""
        credentials = f"{self.login}:{self.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json"
        }

    def _rate_limit_wait(self):
        """速率限制等待"""
        if self.rate_limit > 0:
            elapsed = time.time() - self._last_request_time
            min_interval = 1.0 / self.rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """發送 API 請求

        Args:
            method: HTTP 方法 (GET/POST)
            endpoint: API endpoint
            data: 請求資料

        Returns:
            API 回應
        """
        if not self.login or not self.password:
            return {"error": "DataForSEO credentials not configured"}

        self._rate_limit_wait()

        url = f"{self.BASE_URL}/{endpoint}"
        headers = self._get_auth_header()

        try:
            if method.upper() == "POST":
                try:
                    data_str = json.dumps(data, ensure_ascii=False)[:300] if data else "None"
                    logger.info(f"[DataForSEO] POST {endpoint} with data: {data_str}")
                except Exception as e:
                    logger.info(f"[DataForSEO] POST {endpoint} (data serialization error: {e})")
                response = requests.post(url, headers=headers, json=data, timeout=60)
            else:
                logger.info(f"[DataForSEO] GET {endpoint}")
                response = requests.get(url, headers=headers, timeout=60)

            response.raise_for_status()
            result = response.json()

            # 記錄完整回應（用於診斷）
            logger.info(f"[DataForSEO] Response status_code: {result.get('status_code')}")
            try:
                result_str = json.dumps(result, ensure_ascii=False)[:500]
                logger.info(f"[DataForSEO] Response: {result_str}")
            except Exception as e:
                logger.info(f"[DataForSEO] Response (serialization error: {e})")

            if result.get("status_code") != 20000:
                error_msg = result.get("status_message", "Unknown error")
                logger.error(f"DataForSEO API error: {error_msg}")
                return {"error": error_msg}

            # 檢查是否返回空結果
            tasks = result.get("tasks", [])
            if tasks:
                task_result = tasks[0].get("result")
                if not task_result:
                    logger.warning(f"[DataForSEO] API returned empty result for endpoint: {endpoint}")
                else:
                    logger.info(f"[DataForSEO] Task result count: {len(task_result) if isinstance(task_result, list) else 'N/A'}")

            return result

        except requests.exceptions.Timeout:
            logger.error(f"DataForSEO request timeout: {endpoint}")
            return {"error": "Request timeout"}
        except requests.exceptions.RequestException as e:
            logger.error(f"DataForSEO request error: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"DataForSEO unexpected error: {e}")
            return {"error": str(e)}

    def get_google_trends(
        self,
        keyword: str,
        geo: str = "HK",
        time_range: str = "past_12_months"
    ) -> Dict[str, Any]:
        """取得 Google Trends 數據

        Args:
            keyword: 搜尋關鍵字
            geo: 地區代碼（預設香港）
            time_range: 時間範圍

        Returns:
            {
                "topics": [{"topic_title": str, "type": str, "value": int}],
                "queries": [{"query": str, "type": str, "value": int}],
                "error": str (if failed)
            }
        """
        logger.info(f"[Trends] Requesting keyword: {keyword}, geo: {geo}")

        # 地區代碼映射
        location_code = 2344 if geo == "HK" else None  # Hong Kong

        # 取得相關主題
        # 注意：Google Trends API 需要 "keywords" (複數) 參數，格式為數組
        # 最多支援 5 個關鍵字
        topics_data = [{
            "keywords": [keyword],  # 修正：使用複數形式，數組格式
            "location_code": location_code
        }]

        topics_result = self._make_request(
            "POST",
            "keywords_data/google_trends/explore/live",
            topics_data
        )

        logger.info(f"[Trends] Raw response status: {topics_result.get('status_code', 'N/A')}")

        topics = []
        queries = []

        def parse_trends_result(result: Dict) -> tuple:
            """解析 Trends API 回應

            正確的數據結構：
            result[0].items[] 包含多種類型：
              - type: "google_trends_graph" (趨勢圖)
              - type: "google_trends_queries_list" (相關查詢)
              - type: "google_trends_topics_list" (相關主題)
            """
            parsed_topics = []
            parsed_queries = []

            if result.get("error"):
                return parsed_topics, parsed_queries

            try:
                tasks = result.get("tasks", [])
                if tasks and tasks[0].get("result"):
                    for result_item in tasks[0]["result"]:
                        # 遍歷 items 數組，尋找相關查詢和主題
                        items = result_item.get("items", [])

                        for item in items:
                            item_type = item.get("type", "")

                            # 處理相關主題 (google_trends_topics_list)
                            if item_type == "google_trends_topics_list":
                                data = item.get("data", {})

                                # Rising topics
                                for topic in data.get("rising", []) or []:
                                    parsed_topics.append({
                                        "topic_title": topic.get("topic_title", ""),
                                        "topic_type": topic.get("topic_type", ""),
                                        "type": "rising",
                                        "value": topic.get("value", 0)
                                    })

                                # Top topics
                                for topic in data.get("top", []) or []:
                                    parsed_topics.append({
                                        "topic_title": topic.get("topic_title", ""),
                                        "topic_type": topic.get("topic_type", ""),
                                        "type": "top",
                                        "value": topic.get("value", 0)
                                    })

                            # 處理相關查詢 (google_trends_queries_list)
                            elif item_type == "google_trends_queries_list":
                                data = item.get("data", {})

                                # Rising queries
                                for query in data.get("rising", []) or []:
                                    parsed_queries.append({
                                        "query": query.get("query", ""),
                                        "type": "rising",
                                        "value": query.get("value", 0)
                                    })

                                # Top queries
                                for query in data.get("top", []) or []:
                                    parsed_queries.append({
                                        "query": query.get("query", ""),
                                        "type": "top",
                                        "value": query.get("value", 0)
                                    })

                        # 記錄診斷信息
                        item_types = [item.get("type") for item in items]
                        logger.info(f"[Trends] Found item types: {item_types}")

            except Exception as e:
                logger.error(f"Error parsing trends data: {e}", exc_info=True)

            return parsed_topics, parsed_queries

        # 解析主要語言結果
        topics, queries = parse_trends_result(topics_result)
        logger.info(f"[Trends] Parsed topics: {len(topics)}, queries: {len(queries)}")

        # 注意：移除了語言備選邏輯，因為 API 不接受 language_code 參數

        return {
            "keyword": keyword,
            "topics": topics[:20],  # 限制數量
            "queries": queries[:20],
            "error": topics_result.get("error")
        }

    def get_keyword_suggestions(
        self,
        keyword: str,
        location_code: int = 2344,  # Hong Kong
        language_code: str = None,  # 不再使用
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """取得關鍵字建議（支持智能降級）

        Args:
            keyword: 種子關鍵字
            location_code: 位置代碼（2344 = 香港）
            language_code: （已廢棄）此 API 不接受此參數
            limit: 返回數量限制

        Returns:
            [{"keyword": str, "search_volume": int, "cpc": float, "competition": float}]

        行為說明：
        - 優先嘗試 include_seed_keyword=False（只返回相關建議）
        - 如果沒有結果，降級為 include_seed_keyword=True（包含原始關鍵字）
        - 適用於中文關鍵字在 Google Ads 數據較少的情況
        """
        # 第一次嘗試：不包含種子關鍵字，只獲取相關建議
        data = [{
            "keywords": [keyword],
            "location_code": location_code,
            "include_seed_keyword": False,  # 優先嘗試：不包含種子關鍵字
            "limit": limit,
            "sort_by": "search_volume"
        }]

        result = self._make_request(
            "POST",
            "keywords_data/google_ads/keywords_for_keywords/live",
            data
        )

        suggestions = []

        if result.get("error"):
            logger.error(f"[Suggestions] API error: {result['error']}")
            return suggestions

        try:
            tasks = result.get("tasks", [])
            if tasks and tasks[0].get("result"):
                for item in tasks[0]["result"]:
                    suggestions.append({
                        "keyword": item.get("keyword", ""),
                        "search_volume": item.get("search_volume", 0),
                        "cpc": item.get("cpc", 0),
                        "competition": item.get("competition", 0),
                        "competition_level": item.get("competition_level", ""),
                        "monthly_searches": item.get("monthly_searches", [])
                    })
        except Exception as e:
            logger.error(f"[Suggestions] Parsing error: {e}")

        # 智能降級：如果沒有建議，重試並包含種子關鍵字
        if not suggestions:
            logger.warning(f"[Suggestions] No results for '{keyword}' with include_seed_keyword=False, retrying with True")

            data_fallback = [{
                "keywords": [keyword],
                "location_code": location_code,
                "include_seed_keyword": True,  # 降級：包含種子關鍵字
                "limit": limit,
                "sort_by": "search_volume"
            }]

            result_fallback = self._make_request(
                "POST",
                "keywords_data/google_ads/keywords_for_keywords/live",
                data_fallback
            )

            if not result_fallback.get("error"):
                try:
                    tasks = result_fallback.get("tasks", [])
                    if tasks and tasks[0].get("result"):
                        for item in tasks[0]["result"]:
                            suggestions.append({
                                "keyword": item.get("keyword", ""),
                                "search_volume": item.get("search_volume", 0),
                                "cpc": item.get("cpc", 0),
                                "competition": item.get("competition", 0),
                                "competition_level": item.get("competition_level", ""),
                                "monthly_searches": item.get("monthly_searches", []),
                                "is_seed": item.get("keyword") == keyword  # 標記是否為種子關鍵字
                            })
                        logger.info(f"[Suggestions] Fallback successful, got {len(suggestions)} result(s)")
                except Exception as e:
                    logger.error(f"[Suggestions] Fallback parsing error: {e}")

        logger.info(f"[Suggestions] Final count for '{keyword}': {len(suggestions)}")
        return suggestions

    def get_keyword_metrics(
        self,
        keywords: List[str],
        location_code: int = 2344,  # Hong Kong
        language_code: str = None  # 不再使用，保留參數以向後兼容
    ) -> List[Dict[str, Any]]:
        """取得關鍵字指標（搜尋量、CPC、競爭度）

        Args:
            keywords: 關鍵字列表
            location_code: 位置代碼
            language_code: （已廢棄）Google Ads API 不接受此參數

        Returns:
            [{"keyword": str, "search_volume": int, "cpc": float, "competition": float, "competition_level": str}]
        """
        if not keywords:
            return []

        # DataForSEO 限制每次最多 1000 個關鍵字
        keywords = keywords[:1000]

        # 注意：Google Ads API 不接受 language_code 參數
        data = [{
            "keywords": keywords,
            "location_code": location_code
        }]

        result = self._make_request(
            "POST",
            "keywords_data/google_ads/search_volume/live",
            data
        )

        metrics = []

        if result.get("error"):
            logger.error(f"[Metrics] Keyword metrics error: {result['error']}")
            return metrics

        logger.info(f"[Metrics] Fetching metrics for {len(keywords)} keywords")

        try:
            tasks = result.get("tasks", [])
            if tasks and tasks[0].get("result"):
                for item in tasks[0]["result"]:
                    metrics.append({
                        "keyword": item.get("keyword", ""),
                        "search_volume": item.get("search_volume", 0),
                        "cpc": item.get("cpc", 0),
                        "competition": item.get("competition", 0),
                        "competition_level": item.get("competition_level", "")
                    })
        except Exception as e:
            logger.error(f"Error parsing keyword metrics: {e}")

        # 如果沒有數據，記錄警告
        if not metrics:
            logger.warning(f"[Metrics] No data returned for keywords: {keywords[:3]}...")

        return metrics

    def get_serp_results(
        self,
        keyword: str,
        location_code: int = 2344,  # Hong Kong
        language_code: str = "zh-TW",
        num: int = 10
    ) -> Dict[str, Any]:
        """取得 Google SERP 搜尋結果

        Args:
            keyword: 搜尋關鍵字
            location_code: 位置代碼
            language_code: 語言代碼
            num: 返回結果數量（organic results）

        Returns:
            {
                "organic_results": [{"title": str, "url": str, "description": str, "position": int}],
                "people_also_ask": [{"question": str, "answer": str}],
                "related_searches": [str],
                "error": str (if failed)
            }
        """
        # depth 需要設置更大以確保獲取足夠的 organic 結果
        # 因為前面的位置可能被廣告、local pack 等佔據
        # 設置 depth = num * 3 以確保有足夠的結果
        data = [{
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
            "device": "desktop",
            "os": "windows",
            "depth": max(num * 3, 30)  # 修改：增加 depth 以獲取更多 organic 結果
        }]

        result = self._make_request(
            "POST",
            "serp/google/organic/live/regular",
            data
        )

        organic_results = []
        people_also_ask = []
        related_searches = []

        if result.get("error"):
            return {
                "keyword": keyword,
                "organic_results": [],
                "people_also_ask": [],
                "related_searches": [],
                "error": result["error"]
            }

        try:
            tasks = result.get("tasks", [])
            if tasks and tasks[0].get("result"):
                for result_item in tasks[0]["result"]:
                    items = result_item.get("items", [])

                    for item in items:
                        item_type = item.get("type", "")

                        if item_type == "organic":
                            organic_results.append({
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "description": item.get("description", ""),
                                "position": item.get("rank_group", 0)
                            })

                        elif item_type == "people_also_ask":
                            for question_item in item.get("items", []):
                                people_also_ask.append({
                                    "question": question_item.get("title", ""),
                                    "answer": question_item.get("snippet", "")
                                })

                        elif item_type == "related_searches":
                            for related_item in item.get("items", []):
                                related_searches.append(related_item.get("title", ""))

        except Exception as e:
            logger.error(f"Error parsing SERP results: {e}")

        return {
            "keyword": keyword,
            "organic_results": organic_results[:num],
            "people_also_ask": people_also_ask[:10],
            "related_searches": related_searches[:10],
            "error": None
        }

    def is_configured(self) -> bool:
        """檢查是否已配置 API 憑證"""
        return bool(self.login and self.password)


# 全域客戶端實例
dataforseo_client = DataForSEOClient()
