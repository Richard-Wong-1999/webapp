"""文字處理工具函數"""

import os
import json
import re
from datetime import datetime, date, timedelta
from typing import List, Tuple, Dict
from utils.logger import logger


def parse_ymd_date(s: str) -> date:
    """解析 YYYY-MM-DD 格式日期

    Args:
        s: 日期字串

    Returns:
        date 物件，失敗則返回 None
    """
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def make_safe_filename(s: str, max_len=180) -> str:
    """產生安全的檔案名稱

    Args:
        s: 原始字串
        max_len: 最大長度

    Returns:
        安全的檔案名稱
    """
    s = s or ""
    s = re.sub(r'[\\/*?:"<>|]', '', s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] if len(s) > max_len else s


def derive_date_from_text_zh(text: str) -> str:
    """從中文文本提取日期（YYYY年MM月DD日格式）

    Args:
        text: 中文文本

    Returns:
        YYYY-MM-DD 格式日期字串，失敗則返回空字串
    """
    if not text:
        return ""
    m = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日', text)
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def split_bilingual_block(block: str) -> Dict[str, str]:
    """將中英並列 block 拆成 {"zh": "...", "en": "..."}

    Args:
        block: 中英並列的文本塊

    Returns:
        包含 zh 和 en 的字典
    """
    block = (block or "").strip()
    if not block:
        return {"zh": "", "en": ""}

    # 允許 ZH/EN 任一不存在
    m_zh = re.search(r"(【ZH｜.*?】\s*\n.*?)(?=\n\s*\n【EN｜|\Z)", block, re.S)
    m_en = re.search(r"(【EN｜.*?】\s*\n.*?)(?=\Z)", block, re.S)

    zh_part = (m_zh.group(1).strip() if m_zh else "")
    en_part = (m_en.group(1).strip() if m_en else "")

    return {"zh": zh_part, "en": en_part}


# 單篇文章最大長度（超過則截斷）
MAX_SINGLE_ARTICLE_ZH = 10000
MAX_SINGLE_ARTICLE_EN = 10000


def build_reference_content_blocks_flexible(
    blocks: List[str],
    max_chars_zh: int = 10000,
    max_chars_en: int = 10000,
    prefer_bilingual: bool = True
) -> str:
    """組裝參考內容（不截斷段落，以完整文章為單位）

    Args:
        blocks: 文章塊列表
        max_chars_zh: 中文最大字元數
        max_chars_en: 英文最大字元數
        prefer_bilingual: 是否優先雙語文章

    Returns:
        組裝好的參考內容
    """
    blocks = blocks or []

    bilingual = []
    monolingual = []

    for b in blocks:
        parts = split_bilingual_block(b)
        zh_b = parts["zh"].strip()
        en_b = parts["en"].strip()

        # 截斷過長的單篇文章
        if zh_b and len(zh_b) > MAX_SINGLE_ARTICLE_ZH:
            zh_b = zh_b[:MAX_SINGLE_ARTICLE_ZH] + "..."
        if en_b and len(en_b) > MAX_SINGLE_ARTICLE_EN:
            en_b = en_b[:MAX_SINGLE_ARTICLE_EN] + "..."

        if zh_b and en_b:
            bilingual.append((zh_b, en_b))
        elif zh_b or en_b:
            monolingual.append((zh_b, en_b))

    ordered = (bilingual + monolingual) if prefer_bilingual else (bilingual + monolingual)

    zh_out, en_out = [], []

    for zh_b, en_b in ordered:
        # 直接添加所有文章（已在前面截斷過長文章）
        if zh_b:
            zh_out.append(zh_b)
        if en_b:
            en_out.append(en_b)

    # 以「ZH references」+「EN references」兩區塊輸出
    content_parts = []
    if zh_out:
        content_parts.append("\n\n---\n\n".join(zh_out))
    if en_out:
        content_parts.append("\n\n---\n\n".join(en_out))

    return "\n\n---\n\n".join(content_parts).strip()


def read_json_files_by_date(
    folder: str,
    source: str,
    cutoff_date: date,
    make_block_func
) -> List[str]:
    """讀取指定日期後的 JSON 檔案

    Args:
        folder: 資料夾路徑
        source: 資料來源 (swd/ha)
        cutoff_date: 截止日期
        make_block_func: 製作 block 的函數

    Returns:
        文章塊列表
    """
    blocks = []

    if not os.path.exists(folder):
        return blocks

    for fn in os.listdir(folder):
        if not fn.endswith(".json") or fn == "press_releases_recent.json":
            continue

        try:
            filepath = os.path.join(folder, fn)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 解析日期
            date_str = data.get("published" if source == "ha" else "date", "")
            d = parse_ymd_date(date_str)

            if not d or d < cutoff_date:
                continue

            block = make_block_func(source, data)
            if block:
                blocks.append(block)

        except Exception as e:
            logger.warning(f"讀取檔案 {fn} 錯誤: {e}")

    return blocks
