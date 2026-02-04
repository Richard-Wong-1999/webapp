"""
Test the fixed Wix client (standalone)
"""

import requests
import json
import os
import sys
import re
import time
from html.parser import HTMLParser

sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

CLIENT_ID = os.getenv("WIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("WIX_CLIENT_SECRET")
INSTANCE_ID = os.getenv("WIX_INSTANCE_ID")
REFRESH_TOKEN = os.getenv("WIX_REFRESH_TOKEN")
MEMBER_ID = os.getenv("WIX_MEMBER_ID")

print("=" * 60)
print("Test Fixed Wix Client")
print("=" * 60)

print("\n[Config Check]")
print(f"  CLIENT_ID: {CLIENT_ID[:20] if CLIENT_ID else 'NOT SET'}...")
print(f"  INSTANCE_ID: {INSTANCE_ID or 'NOT SET'}")
print(f"  MEMBER_ID: {MEMBER_ID or 'NOT SET'}")
print(f"  REFRESH_TOKEN: {'SET' if REFRESH_TOKEN else 'NOT SET'}")

# HTML to Ricos converter (same as wix_client.py)
class HTMLToRicosConverter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.current_text = ""
        self.current_decorations = []
        self.list_stack = []
        self.list_item_nodes = []
        self.in_list_item = False
        self.heading_level = 0
        self.node_id_counter = 0

    def _generate_node_id(self):
        self.node_id_counter += 1
        return f"node_{self.node_id_counter}"

    def _flush_text(self):
        if not self.current_text.strip():
            self.current_text = ""
            self.current_decorations = []
            return None
        text_data = {"textData": {"text": self.current_text}}
        if self.current_decorations:
            text_data["textData"]["decorations"] = self.current_decorations.copy()
        self.current_text = ""
        self.current_decorations = []
        return text_data

    def _create_paragraph_node(self, text_data=None):
        node = {"type": "PARAGRAPH", "id": self._generate_node_id(), "nodes": []}
        if text_data:
            text_node = {"type": "TEXT", "id": self._generate_node_id()}
            text_node.update(text_data)
            node["nodes"].append(text_node)
        return node

    def _create_heading_node(self, level, text_data=None):
        node = {"type": "HEADING", "id": self._generate_node_id(), "headingData": {"level": level}, "nodes": []}
        if text_data:
            text_node = {"type": "TEXT", "id": self._generate_node_id()}
            text_node.update(text_data)
            node["nodes"].append(text_node)
        return node

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
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
            self._flush_text()
            self.in_list_item = True
        elif tag in ('strong', 'b'):
            self.current_decorations.append({"type": "BOLD"})
        elif tag in ('em', 'i'):
            self.current_decorations.append({"type": "ITALIC"})

    def handle_endtag(self, tag):
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
                    self.nodes.append({"type": "BULLETED_LIST", "id": self._generate_node_id(), "nodes": self.list_item_nodes.copy()})
                    self.list_item_nodes = []
        elif tag == 'ol':
            if self.list_stack and self.list_stack[-1] == 'ol':
                self.list_stack.pop()
                if self.list_item_nodes:
                    self.nodes.append({"type": "ORDERED_LIST", "id": self._generate_node_id(), "nodes": self.list_item_nodes.copy()})
                    self.list_item_nodes = []
        elif tag == 'li':
            text_data = self._flush_text()
            if text_data:
                self.list_item_nodes.append({"type": "LIST_ITEM", "id": self._generate_node_id(), "nodes": [self._create_paragraph_node(text_data)]})
            self.in_list_item = False
        elif tag in ('strong', 'b'):
            self.current_decorations = [d for d in self.current_decorations if d.get("type") != "BOLD"]
        elif tag in ('em', 'i'):
            self.current_decorations = [d for d in self.current_decorations if d.get("type") != "ITALIC"]

    def handle_data(self, data):
        cleaned = re.sub(r'\s+', ' ', data)
        if cleaned.strip():
            self.current_text += cleaned

    def get_ricos_document(self):
        text_data = self._flush_text()
        if text_data:
            if self.heading_level > 0:
                self.nodes.append(self._create_heading_node(self.heading_level, text_data))
            else:
                self.nodes.append(self._create_paragraph_node(text_data))
        if not self.nodes:
            self.nodes.append(self._create_paragraph_node({"textData": {"text": ""}}))
        return {"nodes": self.nodes}

def html_to_ricos(html_content):
    converter = HTMLToRicosConverter()
    converter.feed(html_content)
    return converter.get_ricos_document()

# Test HTML to Ricos
print("\n[Test HTML to Ricos]")
test_html = "<h2>Test Title</h2><p>This is a <strong>test</strong> paragraph.</p>"
ricos = html_to_ricos(test_html)
print(f"  Ricos output:")
print(json.dumps(ricos, indent=2, ensure_ascii=False)[:600])

# Get access token
print("\n[Get Access Token]")
token_url = "https://www.wixapis.com/oauth/access"
token_payload = {
    "grant_type": "refresh_token",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "refresh_token": REFRESH_TOKEN
}
resp = requests.post(token_url, json=token_payload, timeout=30)
if resp.status_code != 200:
    print(f"  [ERROR] {resp.text}")
    exit(1)
access_token = resp.json().get("access_token")
print(f"  [OK] Got access token")

# Create draft
print("\n[Create Draft with Fixed Format]")
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "wix-site-id": INSTANCE_ID
}

test_content = html_to_ricos("<h2>Test Heading</h2><p>This is a test article from the <strong>fixed</strong> Wix client.</p><p>If you see this in drafts, the fix is working!</p>")

payload = {
    "draftPost": {
        "title": "[API Test] Fixed Client - Can Delete",
        "memberId": MEMBER_ID,
        "richContent": test_content,
        "excerpt": "Test from fixed client"
    }
}

draft_url = "https://www.wixapis.com/blog/v3/draft-posts"
resp = requests.post(draft_url, headers=headers, json=payload, timeout=60)
print(f"  Status: {resp.status_code}")

if resp.status_code == 200:
    result = resp.json()
    print(f"  [SUCCESS] Draft created!")
    print(f"  Draft ID: {result.get('draftPost', {}).get('id')}")
    print(f"  Status: {result.get('draftPost', {}).get('status')}")
else:
    print(f"  [ERROR] {resp.text}")

# List drafts
print("\n[List All Drafts]")
resp = requests.get(draft_url, headers=headers, timeout=30)
if resp.status_code == 200:
    drafts = resp.json().get("draftPosts", [])
    print(f"  Found {len(drafts)} drafts:")
    for d in drafts[:5]:
        print(f"    - {d.get('title')}")

print("\n" + "=" * 60)
print("Done! Check your Wix Blog drafts.")
