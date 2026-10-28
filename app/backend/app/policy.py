"""政策资讯模块（P6）：考试大纲 / 报名时间节点 / 目标院校，纯读解析。

数据源是 政策资讯/*.md（markdown 仍是内容事实源），经 mdview 结构化读取；
AI 改文档后由索引层的 mtime+hash 反向同步跟进，本模块不缓存、不写库。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import indexer
from .mdview import find_table, parse_doc, table_rows

router = APIRouter(prefix="/api/policy", tags=["policy"])

POLICY_DIR_REL = "政策资讯"
SYLLABUS_REL = "政策资讯/考试大纲.md"
ENROLL_REL = "政策资讯/报名与志愿填报.md"


def _policy_root() -> Path:
    return indexer.REPO_ROOT


def _safe_policy_path(rel: str) -> Path:
    """只允许读 政策资讯/ 下的 .md，防路径穿越。"""
    root = _policy_root()
    p = (root / rel).resolve()
    if p.suffix != ".md" or not str(p).startswith(str((root / POLICY_DIR_REL).resolve())):
        raise HTTPException(status_code=400, detail="只允许读取 政策资讯/ 下的 .md 文档")
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文档不存在：{rel}")
    return p


@router.get("/docs")
def list_docs() -> list[dict]:
    """政策文档清单（名称/路径/状态/分类）。"""
    d = _policy_root() / POLICY_DIR_REL
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        doc = parse_doc(p)
        out.append(
            {
                "name": p.stem,
                "path": p.relative_to(_policy_root()).as_posix(),
                "status": doc["meta"].get("状态", ""),
                "category": doc["meta"].get("分类", ""),
                "title": doc["title"] or p.stem,
            }
        )
    return out


@router.get("/doc")
def get_doc(path: str) -> dict:
    """单篇政策文档的结构化内容（标题树 + 表格/列表/段落块）。"""
    p = _safe_policy_path(path)
    doc = parse_doc(p)
    return {
        "path": path,
        "title": doc["title"],
        "meta": doc["meta"],
        "outline": doc["outline"],
    }


@router.get("/key-dates")
def key_dates() -> list[dict]:
    """报名关键时间节点（来自 报名与志愿填报.md「一、关键时间节点」）。"""
    p = _policy_root() / ENROLL_REL
    if not p.is_file():
        return []
    doc = parse_doc(p)
    rows = table_rows(find_table(doc, "关键时间节点", "事项"))
    return [
        {
            "item": r.get("事项", ""),
            "time": r.get("预计时间", ""),
            "confirmed": r.get("确认状态", ""),
        }
        for r in rows
    ]


@router.get("/schools")
def schools() -> list[dict]:
    """目标院校简章核对表（来自 考试大纲.md「三、目标院校」）。"""
    p = _policy_root() / SYLLABUS_REL
    if not p.is_file():
        return []
    doc = parse_doc(p)
    rows = table_rows(find_table(doc, "目标院校", "院校"))
    return [
        {
            "school": r.get("院校", ""),
            "level": r.get("层次", ""),
            "link": r.get("简章链接", ""),
            "checked": r.get("简章是否已核对", ""),
            "following": r.get("关注状态", ""),
        }
        for r in rows
    ]
