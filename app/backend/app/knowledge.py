"""资料库模块（P6）：知识点单元索引 + Anki 卡组索引，纯读。

- 知识点单元：扫描仓库内 知识点梳理.md（排除非内容目录），汇总四件套齐全度、
  索引层题目数、梳理文档内的自评标记（⬜/🟨/✅）计数，作为掌握度概览。
- Anki 卡组：读 复习计划/Anki卡组/*.txt 源文件（卡片数 = 非注释非空行），
  与同名 .apkg 对照；txt 比 apkg 新时标记 stale=1，提醒跑 build_decks.py 重新打包。

答案键绝不下发（与 quiz 契约一致）：单元详情只回题型统计，不回 answer_key。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import indexer
from .db import connect
from .mdview import META_ROW_RE, parse_doc

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# 与 check_docs.SKIP_DIRS 对齐的非内容目录（代码/过程记忆/旧服务等）
SKIP_DIRS = {".git", ".codebuddy", "web", "Anki卡组", "docs", "app", "context"}
DECKS_DIR_REL = "复习计划/Anki卡组"
TAG_RE = re.compile(r"^#\s*@tag\s+层级::(\S+)")
MARKERS = ("⬜", "🟨", "✅")


def _scan_units(root: Path) -> list[dict]:
    out: list[dict] = []
    for p in sorted(root.rglob("知识点梳理.md")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        folder = p.parent
        out.append(
            {
                "subject": rel.parts[0],
                "unit": rel.parts[-2] if len(rel.parts) > 1 else p.stem,
                "path": rel_posix,
                "has_qbank": (folder / "题库.md").is_file(),
                "has_analysis": (folder / "题库解析.md").is_file(),
                "has_catalog": (folder / "知识点目录.md").is_file(),
                "mastery": _mastery_counts(p),
            }
        )
    return out


def _mastery_counts(path: Path) -> dict:
    """梳理文档内自评标记计数（⬜ 未掌握 / 🟨 部分 / ✅ 已掌握）。

    排除文档头元信息行（如「| 状态 | 🟨 整理中 |」的 🟨 是文档状态，不是自评标记）。
    """
    counts = {m: 0 for m in MARKERS}
    for line in path.read_text(encoding="utf-8").splitlines():
        if META_ROW_RE.match(line):
            continue
        for m in MARKERS:
            counts[m] += line.count(m)
    return counts


def _question_stats(qbank_rel: str) -> dict:
    """某 题库.md 的题型统计（不含答案键）。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT q_type, count(*) AS n FROM questions_index WHERE file_path=? GROUP BY q_type",
            (qbank_rel,),
        ).fetchall()
    finally:
        conn.close()
    by_type = {r["q_type"]: r["n"] for r in rows}
    return {"total": sum(by_type.values()), "by_type": by_type}


@router.get("/units")
def list_units() -> list[dict]:
    """知识点单元清单（四件套齐全度 + 自评标记概览）。"""
    return _scan_units(indexer.REPO_ROOT)


@router.get("/unit")
def get_unit(path: str) -> dict:
    """单元详情：知识点梳理的结构化大纲 + 题库题型统计（无答案键）。"""
    root = indexer.REPO_ROOT
    p = (root / path).resolve()
    if p.suffix != ".md" or not str(p).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="非法文档路径")
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文档不存在：{path}")

    doc = parse_doc(p)
    folder = p.parent
    qbank_rel = (folder / "题库.md").relative_to(root).as_posix()
    return {
        "path": path,
        "title": doc["title"],
        "meta": doc["meta"],
        "outline": doc["outline"],
        "qbank": _question_stats(qbank_rel) if (folder / "题库.md").is_file() else None,
        "mastery": _mastery_counts(p),
    }


def _deck_of(txt: Path) -> dict:
    """单个 .txt 卡组源 → 索引记录（卡片数/层级/apkg 对照/stale 标记）。"""
    cards = 0
    levels: list[str] = []
    for line in txt.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            m = TAG_RE.match(s)
            if m and m.group(1) not in levels:
                levels.append(m.group(1))
            continue
        cards += 1  # 非注释非空行即一张卡（Tab 分隔字段）
    apkg = txt.with_suffix(".apkg")
    return {
        "name": txt.stem,
        "txt_path": txt.name,
        "cards": cards,
        "levels": levels,
        "has_apkg": apkg.is_file(),
        "apkg_size": apkg.stat().st_size if apkg.is_file() else 0,
        # txt 比 apkg 新 → 改过源未重新打包
        "stale": apkg.is_file() and txt.stat().st_mtime > apkg.stat().st_mtime,
        "txt_mtime": txt.stat().st_mtime,
        "apkg_mtime": apkg.stat().st_mtime if apkg.is_file() else None,
    }


@router.get("/decks")
def list_decks() -> list[dict]:
    """Anki 卡组索引（txt 源 + apkg 对照 + 过期标记）。"""
    d = indexer.REPO_ROOT / DECKS_DIR_REL
    if not d.is_dir():
        return []
    return [_deck_of(p) for p in sorted(d.glob("*.txt"))]
