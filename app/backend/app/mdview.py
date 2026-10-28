"""结构化 markdown 读取器：把文档解析成「标题树 + 内容块」，供 policy/knowledge 共用。

只读解析，不改内容。块类型：
- table：{header: [...], rows: [[...]]}（跳过分隔行）
- list：{ordered: bool, items: [...]}（含 `- [ ]` 复选框项）
- p：{text}
- code：{text}（``` 围栏内容）

文档头元信息（标题下「| 项目 | 内容 |」表中的 状态/创建时间/学科/分类）单独提取，
与 danzhao-docs 的 R16 文档头约定对齐。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
META_ROW_RE = re.compile(r"^\|\s*(状态|创建时间|学科|分类)\s*\|\s*(.*?)\s*\|\s*$")
LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$")
CHECKBOX_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
FENCE_RE = re.compile(r"^\s*```")


def _split_row(line: str) -> list[str]:
    return [p.strip() for p in line.strip().strip("|").split("|")]


def _is_sep_row(line: str) -> bool:
    s = line.strip().strip("|").replace(" ", "").replace("|", "")
    return bool(s) and set(s) <= set("-:")


def parse_doc(path: Path) -> dict:
    """解析单个 markdown 文档 → {title, meta, outline}。

    outline: [{level, title, blocks: [...]}]；文档开头（首个标题前）的内容
    归入 level=0 的根节点（title 为空）。
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    title = ""
    meta: dict[str, str] = {}
    outline: list[dict] = []
    current_blocks: list[dict] = []  # 根节点（标题前内容）
    seen_meta_table = False

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        m = HEADING_RE.match(line)
        if m and not FENCE_RE.match(line):
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and not title:
                title = text
            current_blocks = []
            outline.append({"level": level, "title": text, "blocks": current_blocks})
            i += 1
            continue

        mm = META_ROW_RE.match(line)
        if mm and not seen_meta_table:
            meta[mm.group(1)] = mm.group(2)
            i += 1
            continue

        if line.strip().startswith("|"):
            # 表格：连续 | 行
            rows: list[list[str]] = []
            header: Optional[list[str]] = None
            while i < n and lines[i].strip().startswith("|"):
                if _is_sep_row(lines[i]):
                    i += 1
                    continue
                cells = _split_row(lines[i])
                if header is None:
                    header = cells
                else:
                    rows.append(cells)
                i += 1
            if header is not None:
                # 「| 项目 | 内容 |」是文档头元信息表（R16）：仅首个（seen_meta_table 前）
                # 作 meta 提取；正文里的同形表格（如「考试基本信息」）是正常内容块
                if header[:2] == ["项目", "内容"] and not seen_meta_table:
                    seen_meta_table = True
                    for r in rows:
                        if len(r) >= 2 and r[0] in ("状态", "创建时间", "学科", "分类"):
                            meta[r[0]] = r[1]
                else:
                    current_blocks.append({"type": "table", "header": header, "rows": rows})
            continue

        lm = LIST_ITEM_RE.match(line)
        if lm:
            ordered = bool(re.match(r"^\s*\d+\.", line))
            items: list[dict] = []
            while i < n:
                lm2 = LIST_ITEM_RE.match(lines[i])
                if not lm2:
                    break
                raw = lm2.group(2).strip()
                cm = CHECKBOX_RE.match(raw)
                if cm:
                    items.append(
                        {"text": cm.group(2).strip(), "checked": cm.group(1).lower() == "x"}
                    )
                else:
                    items.append({"text": raw, "checked": None})
                i += 1
            current_blocks.append({"type": "list", "ordered": ordered, "items": items})
            continue

        if FENCE_RE.match(line):
            # 代码块：原样收录
            buf = []
            i += 1
            while i < n and not FENCE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过收尾 ```
            current_blocks.append({"type": "code", "text": "\n".join(buf)})
            continue

        if line.strip():
            # 段落：连续非空、非结构行
            buf = [line.strip()]
            i += 1
            while i < n:
                nxt = lines[i]
                if (
                    not nxt.strip()
                    or HEADING_RE.match(nxt)
                    or nxt.strip().startswith("|")
                    or LIST_ITEM_RE.match(nxt)
                    or FENCE_RE.match(nxt)
                    or META_ROW_RE.match(nxt)
                ):
                    break
                buf.append(nxt.strip())
                i += 1
            current_blocks.append({"type": "p", "text": " ".join(buf)})
            continue

        i += 1

    return {"title": title, "meta": meta, "outline": outline}


def find_table(doc: dict, section_title: str, first_header: str) -> Optional[dict]:
    """在指定章节块里找首列匹配的表格（政策时间节点/目标院校等便利提取）。"""
    for node in doc["outline"]:
        if section_title and section_title not in node["title"]:
            continue
        for b in node["blocks"]:
            if b["type"] == "table" and b["header"] and b["header"][0] == first_header:
                return b
    return None


def table_rows(b: Optional[dict]) -> list[dict]:
    """表格块 → [{列名: 值}] 列表。"""
    if not b:
        return []
    keys = b["header"]
    out = []
    for r in b["rows"]:
        r = list(r) + [""] * (len(keys) - len(r))
        out.append({k: v for k, v in zip(keys, r)})
    return out
