"""题目反馈：错因自选 + 「解析没看懂」→ 疑难点.md 累加；错题本联动。

反馈持久化进 quiz_feedback 表（可靠、可聚合）；confused(解析没看懂) 时按 auto-discover
约定累加 错题本/疑难点.md：同「专题+学科」累加出现次数，新专题插入一行，状态 ⬜。
疑难点.md 的写入复用 writeback.atomic_write_text（读前比对 + os.replace），不跑校验器、
不污染黑话表。错题本联动由 GET /wrong 从 quiz_attempts(is_correct=0) 派生，零额外存储。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from . import indexer
from .db import connect
from .writeback import _sha256_text, atomic_write_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

# R18 五类错因（与 错题本/README.md 错因类型一致）
ERROR_TYPES = ["概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘"]

YND_REL = "错题本/疑难点.md"
YND_SECTION = "## 一、疑难点记录"


class FeedbackRequest(BaseModel):
    file_path: str
    section_title: str
    qid: str
    error_type: Optional[str] = None
    confused: bool = False

    @field_validator("error_type")
    @classmethod
    def _chk_error_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ERROR_TYPES:
            raise ValueError(f"error_type 必须是五类错因之一：{ERROR_TYPES}")
        return v


def _split_row(line: str) -> list[str]:
    return [p.strip() for p in line.strip().strip("|").split("|")]


def _make_row(cols: list[str]) -> str:
    return "| " + " | ".join(cols) + " |"


def append_ynd(
    section_title: str,
    subject: str,
    qid: str,
    file_path: str,
    repo_root: Optional[Path] = None,
) -> None:
    """在 疑难点.md 的「一、疑难点记录」表格累加一行（同专题+学科计数 +1）。"""
    root = Path(repo_root) if repo_root else indexer.REPO_ROOT
    path = root / YND_REL
    text = path.read_text(encoding="utf-8")
    expected_hash = _sha256_text(text)
    lines = text.splitlines()

    si = next((i for i, l in enumerate(lines) if l.startswith(YND_SECTION)), None)
    if si is None:
        raise RuntimeError(f"{YND_REL} 缺少「{YND_SECTION}」章节")

    header_idx: Optional[int] = None
    sep_idx: Optional[int] = None
    data: list[tuple[int, list[str]]] = []  # (原始行号, 列)
    for i in range(si, len(lines)):
        ln = lines[i]
        if i > si and ln.startswith("## "):
            break
        if ln.startswith("|") and "专题" in ln:
            header_idx = i
        elif ln.startswith("|") and set(ln.replace("|", "").replace(" ", "")) <= set("-:"):
            sep_idx = i
        elif (
            ln.startswith("|")
            and header_idx is not None
            and sep_idx is not None
            and i > sep_idx
        ):
            data.append((i, _split_row(ln)))

    if header_idx is None or sep_idx is None:
        raise RuntimeError(f"{YND_REL} 的「一、疑难点记录」缺少表格")

    today = date.today().isoformat()

    # 命中同专题+学科行 → 出现次数 +1、更新最近出现
    matched = next(
        (k for k, (_, c) in enumerate(data) if len(c) >= 2 and c[0] == section_title and c[1] == subject),
        None,
    )
    if matched is not None:
        cols = data[matched][1]
        try:
            cnt = int(cols[2]) + 1
        except (ValueError, IndexError):
            cnt = 1
        if len(cols) > 4:
            cols[4] = today  # 最近出现
        cols[2] = str(cnt)
        data[matched] = (data[matched][0], cols)
    else:
        new_cols = [section_title, subject, "1", today, today, f"{file_path}#{qid}", file_path, "⬜"]
        placeholder = next((k for k, (_, c) in enumerate(data) if c and c[0] == "待填写"), None)
        if placeholder is not None:
            data[placeholder] = (data[placeholder][0], new_cols)
        else:
            # 追加到表格末尾（行号取最后一行的下一行）
            last_oi = data[-1][0] if data else sep_idx
            data.append((last_oi + 1, new_cols))

    data.sort(key=lambda x: x[0])
    end = max(oi for oi, _ in data)
    new_rows = [_make_row(c) for _, c in data]
    new_lines = lines[:header_idx] + [lines[header_idx], lines[sep_idx]] + new_rows + lines[end + 1:]
    new_text = "\n".join(new_lines) + "\n"
    atomic_write_text(path, new_text, expected_hash)


@router.post("/feedback")
def post_feedback(req: FeedbackRequest) -> dict:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO quiz_feedback (file_path, section_title, qid, error_type, confused) "
            "VALUES (?,?,?,?,?)",
            (req.file_path, req.section_title, req.qid, req.error_type, int(req.confused)),
        )
        conn.commit()
        fb_id = cur.lastrowid
    finally:
        conn.close()

    ynd_appended = False
    if req.confused:
        subject = req.file_path.split("/", 1)[0].strip()
        try:
            append_ynd(req.section_title, subject, req.qid, req.file_path)
            ynd_appended = True
        except Exception as exc:  # noqa: BLE001 - 累加失败不应阻断反馈落库
            logger.warning("疑难点.md 累加失败（反馈已落库）: %s", exc)
    return {"id": fb_id, "ynd_appended": ynd_appended}


@router.get("/wrong")
def list_wrong() -> list[dict]:
    """错题本联动：从 quiz_attempts(is_correct=0) 派生去重错题（最近一次在前）。"""
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT a.file_path AS file_path, a.qid AS qid, q.section_title AS section_title,
                   q.stem AS stem, q.q_type AS q_type,
                   MAX(a.created_at) AS last_at, COUNT(*) AS times
            FROM quiz_attempts a
            LEFT JOIN questions_index q ON q.file_path = a.file_path AND q.qid = a.qid
            WHERE a.is_correct = 0
            GROUP BY a.file_path, a.qid
            ORDER BY last_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
