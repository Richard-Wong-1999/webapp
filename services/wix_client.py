"""
Wix Blog API Client
負責將文章以草稿形式發送到 Wix Blog

功能：
1. OAuth 2.0 Token 管理（自動刷新）
2. HTML → Ricos Document 格式轉換
3. Draft Post 創建
"""

import re
import time
import requests
from html.parser import HTMLParser
from typing import Optional, Dict, Any, List, Tuple
from config import Config
from utils import logger


class HTMLToRicosConverter(HTMLParser):
    """將 HTML 轉換為 Wix Ricos Document 格式"""

    def __init__(self):
        super().__init__()
        self.nodes: List[Dict[str, Any]] = []
        self.current_text = ""
        self.current_decorations: List[Dict[str, Any]] = []
        self.list_stack: List[str] = []  # 'ul' or 'ol'
        self.list_item_nodes: List[Dict[str, Any]] = []
        self.in_list_item = False
        self.heading_level = 0
        self.link_url = ""
        self.node_id_counter = 0

    def _generate_node_id(self) -> str:
        """生成唯一節點 ID"""
        self.node_id_counter += 1
        return f"node_{self.node_id_counter}"

    def _flush_text(self) -> Optional[Dict[str, Any]]:
        """將累積的文字輸出為節點"""
        if not self.current_text.strip():
            self.current_text = ""
            self.current_decorations = []
            return None

        # 使用 textData 格式（Wix Ricos v3 要求）
        text_data = {"textData": {"text": self.current_text}}
        if self.current_decorations:
            text_data["textData"]["decorations"] = self.current_decorations.copy()

        self.current_text = ""
        self.current_decorations = []
        return text_data

    def _create_paragraph_node(self, text_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """創建段落節點"""
        node = {
            "type": "PARAGRAPH",
            "id": self._generate_node_id(),
            "nodes": []
        }
        if text_data:
            text_node = {"type": "TEXT", "id": self._generate_node_id()}
            text_node.update(text_data)
            node["nodes"].append(text_node)
        return node

    def _create_heading_node(self, level: int, text_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """創建標題節點"""
        node = {
            "type": "HEADING",
            "id": self._generate_node_id(),
            "headingData": {
                "level": level
            },
            "nodes": []
        }
        if text_data:
            text_node = {"type": "TEXT", "id": self._generate_node_id()}
            text_node.update(text_data)
            node["nodes"].append(text_node)
        return node

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag = tag.lower()
        attrs_dict = dict(attrs)

        if tag in ('p', 'div'):
            text_data = self._flush_text()
            if text_data and not self.in_list_item:
                self.nodes.append(self._create_paragraph_node(text_data))

        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            text_data = self._flush_text()
            if text_data and not self.in_list_item:
                self.nodes.append(self._create_paragraph_node(text_data))
            self.heading_level = int(tag[1])

        elif tag == 'ul':
            text_data = self._flush_text()
            if text_data and not self.in_list_item:
                self.nodes.append(self._create_paragraph_node(text_data))
            self.list_stack.append('ul')

        elif tag == 'ol':
            text_data = self._flush_text()
            if text_data and not self.in_list_item:
                self.nodes.append(self._create_paragraph_node(text_data))
            self.list_stack.append('ol')

        elif tag == 'li':
            text_data = self._flush_text()
            self.in_list_item = True

        elif tag in ('strong', 'b'):
            self.current_decorations.append({"type": "BOLD"})

        elif tag in ('em', 'i'):
            self.current_decorations.append({"type": "ITALIC"})

        elif tag == 'a':
            href = attrs_dict.get('href', '')
            if href:
                self.link_url = href
                self.current_decorations.append({
                    "type": "LINK",
                    "linkData": {
                        "link": {
                            "url": href
                        }
                    }
                })

        elif tag == 'br':
            self.current_text += "\n"

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if tag in ('p', 'div'):
            text_data = self._flush_text()
            if text_data and not self.in_list_item:
                self.nodes.append(self._create_paragraph_node(text_data))

        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            text_data = self._flush_text()
            if text_data:
                self.nodes.append(self._create_heading_node(self.heading_level, text_data))
            self.heading_level = 0

        elif tag == 'ul':
            if self.list_stack and self.list_stack[-1] == 'ul':
                self.list_stack.pop()
                if self.list_item_nodes:
                    self.nodes.append({
                        "type": "BULLETED_LIST",
                        "id": self._generate_node_id(),
                        "nodes": self.list_item_nodes.copy()
                    })
                    self.list_item_nodes = []

        elif tag == 'ol':
            if self.list_stack and self.list_stack[-1] == 'ol':
                self.list_stack.pop()
                if self.list_item_nodes:
                    self.nodes.append({
                        "type": "ORDERED_LIST",
                        "id": self._generate_node_id(),
                        "nodes": self.list_item_nodes.copy()
                    })
                    self.list_item_nodes = []

        elif tag == 'li':
            text_data = self._flush_text()
            if text_data:
                list_item = {
                    "type": "LIST_ITEM",
                    "id": self._generate_node_id(),
                    "nodes": [self._create_paragraph_node(text_data)]
                }
                self.list_item_nodes.append(list_item)
            self.in_list_item = False

        elif tag in ('strong', 'b'):
            # Remove BOLD decoration
            self.current_decorations = [d for d in self.current_decorations if d.get("type") != "BOLD"]

        elif tag in ('em', 'i'):
            # Remove ITALIC decoration
            self.current_decorations = [d for d in self.current_decorations if d.get("type") != "ITALIC"]

        elif tag == 'a':
            # Remove LINK decoration
            self.current_decorations = [d for d in self.current_decorations if d.get("type") != "LINK"]
            self.link_url = ""

    def handle_data(self, data: str):
        # 清理多餘的空白
        cleaned = re.sub(r'\s+', ' ', data)
        if cleaned.strip():
            self.current_text += cleaned

    def get_ricos_document(self) -> Dict[str, Any]:
        """返回完整的 Ricos Document"""
        # 處理剩餘的文字
        text_data = self._flush_text()
        if text_data:
            if self.heading_level > 0:
                self.nodes.append(self._create_heading_node(self.heading_level, text_data))
            else:
                self.nodes.append(self._create_paragraph_node(text_data))

        # 清理空節點（Wix 不接受空節點）
        cleaned_nodes = []
        for node in self.nodes:
            # 檢查節點是否有實際內容
            if node.get("nodes"):
                # 過濾掉空的子節點
                valid_children = []
                for child in node["nodes"]:
                    if child.get("type") == "TEXT":
                        text_content = child.get("textData", {}).get("text", "")
                        if text_content.strip():
                            valid_children.append(child)
                    else:
                        valid_children.append(child)

                if valid_children:
                    node["nodes"] = valid_children
                    cleaned_nodes.append(node)
            else:
                # 沒有子節點的節點（如某些特殊類型）也保留
                cleaned_nodes.append(node)

        # 如果沒有任何節點，添加一個包含空格的段落（避免完全空）
        if not cleaned_nodes:
            cleaned_nodes.append({
                "type": "PARAGRAPH",
                "id": self._generate_node_id(),
                "nodes": [{
                    "type": "TEXT",
                    "id": self._generate_node_id(),
                    "textData": {"text": " "}
                }]
            })

        return {"nodes": cleaned_nodes}


def html_to_ricos(html_content: str) -> Dict[str, Any]:
    """將 HTML 轉換為 Ricos Document 格式

    Args:
        html_content: HTML 格式的文章內容

    Returns:
        Ricos Document JSON 結構
    """
    if not html_content:
        return {
            "nodes": [{"type": "PARAGRAPH", "id": "empty_1", "nodes": []}]
        }

    converter = HTMLToRicosConverter()
    converter.feed(html_content)
    return converter.get_ricos_document()


class WixClient:
    """Wix Blog API 客戶端"""

    def __init__(self):
        self.client_id = Config.WIX_CLIENT_ID
        self.client_secret = Config.WIX_CLIENT_SECRET
        self.instance_id = Config.WIX_INSTANCE_ID
        self.refresh_token = Config.WIX_REFRESH_TOKEN
        self.member_id = getattr(Config, 'WIX_MEMBER_ID', None)  # Blog Writer Member ID
        self.base_url = Config.WIX_API_BASE_URL

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    def is_configured(self) -> bool:
        """檢查 Wix API 是否已配置"""
        return all([
            self.client_id,
            self.client_secret,
            self.refresh_token
        ])

    def _get_access_token(self) -> str:
        """獲取或刷新 Access Token

        Returns:
            有效的 Access Token

        Raises:
            Exception: Token 獲取失敗
        """
        # 如果 token 還有效（提前 60 秒刷新）
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        logger.info("正在刷新 Wix Access Token...")

        url = "https://www.wixapis.com/oauth/access"

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            self._access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)  # 預設 1 小時
            self._token_expires_at = time.time() + expires_in

            logger.info(f"Wix Access Token 刷新成功，有效期 {expires_in} 秒")
            return self._access_token

        except requests.exceptions.RequestException as e:
            logger.error(f"Wix Token 刷新失敗: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise Exception(f"Wix Token 刷新失敗: {str(e)}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        retry_count: int = 2
    ) -> Dict[str, Any]:
        """發送 API 請求

        Args:
            method: HTTP 方法
            endpoint: API 端點
            data: 請求數據
            retry_count: 重試次數

        Returns:
            API 響應
        """
        url = f"{self.base_url}{endpoint}"

        for attempt in range(retry_count + 1):
            try:
                access_token = self._get_access_token()

                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "wix-site-id": self.instance_id
                }

                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    timeout=60
                )

                # 如果是 401，嘗試刷新 token
                if response.status_code == 401 and attempt < retry_count:
                    logger.warning("Wix API 返回 401，嘗試刷新 Token...")
                    self._access_token = None
                    self._token_expires_at = 0
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                if attempt < retry_count:
                    logger.warning(f"Wix API 請求失敗（嘗試 {attempt + 1}/{retry_count + 1}）: {e}")
                    time.sleep(1)  # 等待 1 秒後重試
                    continue

                logger.error(f"Wix API 請求失敗: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                raise

    def create_draft_post(
        self,
        title: str,
        content_html: str,
        excerpt: Optional[str] = None,
        category_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """創建草稿文章

        Args:
            title: 文章標題
            content_html: HTML 格式的文章內容
            excerpt: 文章摘要（可選）
            category_ids: 分類 ID 列表（可選）

        Returns:
            創建結果
        """
        if not self.is_configured():
            raise Exception("Wix API 未配置")

        # 將 HTML 轉換為 Ricos 格式
        ricos_content = html_to_ricos(content_html)

        # 構建請求數據
        draft_post = {
            "title": title,
            "richContent": ricos_content
        }

        # 添加 memberId（Blog Writer ID，必填）
        if self.member_id:
            draft_post["memberId"] = self.member_id
        else:
            logger.warning("WIX_MEMBER_ID 未設定，草稿創建可能會失敗")

        if excerpt:
            draft_post["excerpt"] = excerpt

        if category_ids:
            draft_post["categoryIds"] = category_ids

        payload = {
            "draftPost": draft_post
        }

        logger.info(f"正在創建 Wix 草稿文章: {title}")
        # 診斷日誌
        import json
        logger.info(f"Wix memberId: {self.member_id}")
        logger.info(f"Wix instance_id: {self.instance_id}")
        logger.info(f"Wix richContent nodes 數量: {len(ricos_content.get('nodes', []))}")
        logger.info(f"Wix Payload 結構: title={bool(draft_post.get('title'))}, memberId={bool(draft_post.get('memberId'))}, richContent={bool(draft_post.get('richContent'))}")

        result = self._make_request(
            method="POST",
            endpoint="/blog/v3/draft-posts",
            data=payload
        )

        logger.info(f"Wix 草稿文章創建成功: {result.get('draftPost', {}).get('id', 'unknown')}")
        return result

    def get_categories(self) -> List[Dict[str, Any]]:
        """獲取所有文章分類

        Returns:
            分類列表
        """
        if not self.is_configured():
            raise Exception("Wix API 未配置")

        result = self._make_request(
            method="GET",
            endpoint="/blog/v3/categories"
        )

        return result.get("categories", [])


# 全域客戶端實例
wix_client = WixClient()
