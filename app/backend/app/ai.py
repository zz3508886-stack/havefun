"""AI 取数通道（P7）：CLI + 一页纸快照 + 只读 API，三种形态同一份聚合。

对应《总体设计 · AI 取数通道》：
- CLI：``python -m app ai summary / weak / pending / recent / doubt / plan / snapshot``，
  默认输出 markdown（人/AI 可直接读），``--json`` 输出机器可读。
- 一页纸快照：``app/data/ai-snapshot.md``，每次交互（交卷/反馈/打卡）后自动刷新，
  AI 会话开始读一个文件拿全貌：总量、正确率、薄弱 Top、待复核、疑难点 Top、打卡进度。
- 只读 API：``/api/ai/*`` 同源聚合；配置了 ``config.ai_access_token`` 时要求
  Bearer 令牌（本机单用户默认不启用）。

所有数字来自 aggregate（与仪表盘 stats 同源），疑难点来自 错题本/疑难点.md，
节点来自 plan 模块——本模块不写文档、不写业务库，唯一写动作是快照文件自身。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from . import aggregate, indexer, mdview
from .config import DATA_DIR, load_config
from .plan import nodes_with_status

logger = logging.getLogger("app.ai")

SNAPSHOT_PATH = DATA_DIR / "ai-snapshot.md"
YND_REL = "错题本/疑难点.md"

router = APIRouter(prefix="/api/ai", tags=["ai"])


# --------------------------------------------------------------------------- #
# 令牌鉴权（未配置 ai_access_token 时不做限制——本机单用户默认形态）
# --------------------------------------------------------------------------- #
def require_ai_token(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> None:
    expected = (load_config().get("ai_access_token") or "").strip()
    if not expected:
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif token:
        supplied = token.strip()
    if supplied != expected:
        raise HTTPException(status_code=401, detail="AI 取数令牌无效（config.ai_access_token）")


# --------------------------------------------------------------------------- #
# 疑难点（markdown 表 → 结构化）
# --------------------------------------------------------------------------- #
def digest_doubt(limit: int = 10, repo_root: Optional[Path] = None) -> dict:
    """疑难点 Top（来自 错题本/疑难点.md，出现次数降序，占位行除外）。"""
    root = Path(repo_root) if repo_root else indexer.REPO_ROOT
    path = root / YND_REL
    if not path.is_file():
        return {"items": [], "open_count": 0, "total_count": 0}

    doc = mdview.parse_doc(path)
    rows = mdview.table_rows(mdview.find_table(doc, "疑难点记录", "专题"))
    items: list[dict] = []
    for r in rows:
        topic = r.get("专题", "")
        cnt = r.get("出现次数", "")
        if not topic or topic == "待填写" or not cnt or cnt == "待填写":
            continue
        try:
            times = int(cnt)
        except ValueError:
            continue
        items.append(
            {
                "topic": topic,
                "subject": r.get("学科", ""),
                "times": times,
                "first_seen": r.get("首次出现", ""),
                "last_seen": r.get("最近出现", ""),
                "summary": r.get("关联问题摘要", ""),
                "link": r.get("对应章节链接", ""),
                "status": r.get("状态", ""),
            }
        )
    items.sort(key=lambda x: (-x["times"], x["topic"]))
    open_count = sum(1 for i in items if "⬜" in i["status"])
    return {
        "items": items[: max(1, min(limit, 50))],
        "open_count": open_count,
        "total_count": len(items),
    }


# --------------------------------------------------------------------------- #
# 节点进度
# --------------------------------------------------------------------------- #
def digest_plan(repo_root: Optional[Path] = None) -> dict:
    """节点进度：各节点推导状态 + 完成度统计。"""
    try:
        nodes = nodes_with_status(repo_root)
    except FileNotFoundError:
        return {"nodes": [], "done": 0, "total": 0, "current": None}
    done = sum(1 for n in nodes if n["derived_status"] == "✅")
    current = next(
        (n for n in nodes if n["derived_status"] == "🟨"),
        next((n for n in nodes if n["derived_status"] == "⬜"), None),
    )
    return {
        "nodes": nodes,
        "done": done,
        "total": len(nodes),
        "current": current["node_id"] if current else None,
    }


# --------------------------------------------------------------------------- #
# 汇总 digest（CLI/快照/API 共用）
# --------------------------------------------------------------------------- #
def digest_summary(repo_root: Optional[Path] = None) -> dict:
    ov = aggregate.overview()
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overview": ov,
        "weak_sets": aggregate.weak(10)["sets"][:5],
        "weak_questions": aggregate.weak(10)["questions"][:5],
        "pending": aggregate.pending(10),
        "doubt": digest_doubt(5, repo_root),
        "plan": digest_plan(repo_root),
    }


# --------------------------------------------------------------------------- #
# markdown 渲染（CLI 默认输出 + 快照文件）
# --------------------------------------------------------------------------- #
def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _md_summary(d: dict) -> str:
    ov = d["overview"]
    q, fb, pl = ov["quiz"], ov["feedback"], ov["plan"]
    lines = [
        "# AI 学情快照",
        "",
        f"> 生成时间：{d['generated_at']} ｜ 由复习管理系统自动生成；AI 会话开始读此文件拿全貌。",
        "",
        "## 总量与正确率",
        "",
        f"- 累计答题 **{q['total']}** 题（{q['batches']} 卷 / {q['questions']} 题），"
        f"已判 {q['judged']} 题：对 {q['correct']}、错 {q['wrong']}，正确率 **{_pct(q['accuracy'])}**",
        f"- 待复核 {q['pending']} 题；反馈 {fb['total']} 条（解析没看懂 {fb['confused']} 次）",
        "",
        "## 薄弱 Top（套题，按错题数）",
        "",
    ]
    if d["weak_sets"]:
        lines += ["| 学科 | 套题 | 错题 | 待复核 |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {s['subject']} | {s['section_title']} | {s['wrong']} | {s['pending']} |"
            for s in d["weak_sets"]
        ]
    else:
        lines.append("（无错题/待复核套题）")
    lines += ["", "## 待复核 Top", ""]
    if d["pending"]:
        lines += ["| 学科 | 题号 | 题型 | 学生作答 |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {p['file_path'].split('/', 1)[0]} | {p['qid']} | {p['q_type'] or '—'} "
            f"| {(p['user_answer'] or '（空）')[:20]} |"
            for p in d["pending"]
        ]
    else:
        lines.append("（无待复核）")
    lines += ["", "## 疑难点 Top（错题本/疑难点.md）", ""]
    doubt = d["doubt"]
    if doubt["items"]:
        lines += ["| 专题 | 学科 | 出现次数 | 状态 |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {i['topic']} | {i['subject']} | {i['times']} | {i['status']} |"
            for i in doubt["items"]
        ]
        lines.append("")
        lines.append(f"未攻克 {doubt['open_count']} / 共 {doubt['total_count']} 条。")
    else:
        lines.append("（暂无疑难点记录）")
    lines += ["", "## 打卡进度", ""]
    lines.append(
        f"- 打卡 {pl['checkin_days']} 天，连续 {pl['streak_days']} 天"
        + (
            f"；最近：{pl['last_node']} {pl['last_status']}（{pl['last_checkin_at'][:10]}）"
            if pl["last_checkin_at"]
            else ""
        )
    )
    plan = d["plan"]
    if plan["nodes"]:
        marks = "、".join(
            f"{n['node_id']} {n['derived_status']}" for n in plan["nodes"]
        )
        lines.append(f"- 节点完成 {plan['done']}/{plan['total']}：{marks}")
    lines.append("")
    return "\n".join(lines)


def _md_weak(d: dict) -> str:
    lines = ["# 薄弱点榜单", ""]
    lines.append("## 薄弱套题（按错题数）")
    lines.append("")
    if d["sets"]:
        lines += ["| 学科 | 套题 | 错题 | 待复核 |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {s['subject']} | {s['section_title']} | {s['wrong']} | {s['pending']} |"
            for s in d["sets"]
        ]
    else:
        lines.append("（无）")
    lines += ["", "## 重复错题（出现次数）", ""]
    if d["questions"]:
        lines += ["| 学科 | 题号 | 题型 | 次数 | 题干 |", "| --- | --- | --- | --- | --- |"]
        lines += [
            f"| {q['subject']} | {q['qid']} | {q['q_type'] or '—'} | {q['times']} "
            f"| {(q['stem'] or '')[:30]} |"
            for q in d["questions"]
        ]
    else:
        lines.append("（无）")
    lines.append("")
    return "\n".join(lines)


def _md_rows(rows: list[dict], cols: list[tuple[str, str]], empty: str) -> list[str]:
    """通用表格渲染：cols = [(字段, 表头)]。"""
    if not rows:
        return [empty]
    out = ["| " + " | ".join(h for _, h in cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        cells = []
        for key, _ in cols:
            v = r.get(key)
            v = "" if v is None else str(v)
            cells.append(v[:40] if key in ("stem", "user_answer", "notes") else v)
        out.append("| " + " | ".join(cells) + " |")
    return out


def _md_pending(rows: list[dict]) -> str:
    return "\n".join(
        ["# 待复核作答", ""]
        + _md_rows(
            rows,
            [
                ("file_path", "题库"),
                ("qid", "题号"),
                ("q_type", "题型"),
                ("user_answer", "学生作答"),
                ("eval_state", "状态"),
                ("created_at", "时间"),
            ],
            "（无待复核）",
        )
        + [""]
    )


def _md_recent(rows: list[dict]) -> str:
    def verdict(r: dict) -> str:
        if r.get("is_correct") == 1:
            return "对"
        if r.get("is_correct") == 0:
            return "错"
        return "待判"

    lines = ["# 最近答题流水", ""]
    lines += _md_rows(
        [
            {
                "file_path": r["file_path"],
                "qid": r["qid"],
                "q_type": r.get("q_type") or "—",
                "user_answer": r.get("user_answer") or "（空）",
                "verdict": verdict(r),
                "error_type": r.get("error_type") or "—",
                "created_at": r.get("created_at") or "",
            }
            for r in rows
        ],
        [
            ("file_path", "题库"),
            ("qid", "题号"),
            ("q_type", "题型"),
            ("user_answer", "学生作答"),
            ("verdict", "判定"),
            ("error_type", "错因"),
            ("created_at", "时间"),
        ],
        "（无流水）",
    )
    lines.append("")
    return "\n".join(lines)


def _md_doubt(d: dict) -> str:
    lines = ["# 疑难点 Top", ""]
    lines += _md_rows(
        d["items"],
        [
            ("topic", "专题"),
            ("subject", "学科"),
            ("times", "出现次数"),
            ("last_seen", "最近出现"),
            ("status", "状态"),
            ("summary", "问题摘要"),
        ],
        "（暂无疑难点记录）",
    )
    lines += ["", f"未攻克 {d['open_count']} / 共 {d['total_count']} 条。", ""]
    return "\n".join(lines)


def _md_plan(d: dict) -> str:
    lines = ["# 复习计划进度", ""]
    lines.append(f"节点完成 {d['done']}/{d['total']}" + (f"；当前节点 {d['current']}" if d["current"] else ""))
    lines.append("")
    lines += _md_rows(
        d["nodes"],
        [
            ("node_id", "节点"),
            ("name", "名称"),
            ("date_range", "起止日期"),
            ("derived_status", "推导状态"),
            ("checkin_count", "打卡次数"),
        ],
        "（无节点）",
    )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 快照
# --------------------------------------------------------------------------- #
def write_snapshot(path: Optional[Path] = None, repo_root: Optional[Path] = None) -> Path:
    """生成一页纸快照并原子写入（默认 app/data/ai-snapshot.md）。"""
    target = Path(path) if path else SNAPSHOT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    text = _md_summary(digest_summary(repo_root))
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return target


def refresh_snapshot(repo_root: Optional[Path] = None) -> Optional[Path]:
    """交互后刷新快照（best-effort：失败只告警，绝不打断主流程）。"""
    try:
        return write_snapshot(repo_root=repo_root)
    except Exception as exc:  # noqa: BLE001 - 快照是派生数据，失败不应影响交互
        logger.warning("ai-snapshot 刷新失败（不影响主流程）: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# 只读 API
# --------------------------------------------------------------------------- #
@router.get("/summary", dependencies=[Depends(require_ai_token)])
def api_summary() -> dict:
    return digest_summary()


@router.get("/weak", dependencies=[Depends(require_ai_token)])
def api_weak(limit: int = 10) -> dict:
    return aggregate.weak(limit)


@router.get("/pending", dependencies=[Depends(require_ai_token)])
def api_pending(limit: int = 20) -> list[dict]:
    return aggregate.pending(limit)


@router.get("/recent", dependencies=[Depends(require_ai_token)])
def api_recent(limit: int = 20) -> list[dict]:
    return aggregate.recent(limit)


@router.get("/doubt", dependencies=[Depends(require_ai_token)])
def api_doubt(limit: int = 10) -> dict:
    return digest_doubt(limit)


@router.get("/plan", dependencies=[Depends(require_ai_token)])
def api_plan() -> dict:
    return digest_plan()


@router.get("/snapshot", dependencies=[Depends(require_ai_token)])
def api_snapshot(refresh: bool = False) -> dict:
    """快照内容（默认返回磁盘现值；refresh=1 先重新生成）。"""
    if refresh:
        write_snapshot()
    if SNAPSHOT_PATH.is_file():
        return {
            "path": str(SNAPSHOT_PATH),
            "exists": True,
            "updated_at": datetime.fromtimestamp(SNAPSHOT_PATH.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "content": SNAPSHOT_PATH.read_text(encoding="utf-8"),
        }
    return {"path": str(SNAPSHOT_PATH), "exists": False, "content": ""}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli_data(command: str, args) -> tuple[dict | list, str]:
    """命令 → (digest 数据, markdown 渲染)。"""
    if command == "summary":
        d = digest_summary()
        return d, _md_summary(d)
    if command == "weak":
        d = aggregate.weak(args.limit)
        return d, _md_weak(d)
    if command == "pending":
        rows = aggregate.pending(args.limit)
        return rows, _md_pending(rows)
    if command == "recent":
        rows = aggregate.recent(args.limit)
        return rows, _md_recent(rows)
    if command == "doubt":
        d = digest_doubt(args.limit)
        return d, _md_doubt(d)
    if command == "plan":
        d = digest_plan()
        return d, _md_plan(d)
    raise argparse.ArgumentTypeError(f"未知命令：{command}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app ai",
        description="复习管理系统 · AI 取数通道（默认输出 markdown，--json 输出机器可读）",
    )
    parser.add_argument(
        "command",
        choices=["summary", "weak", "pending", "recent", "doubt", "plan", "snapshot"],
        help="要取的数据",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 markdown")
    parser.add_argument("--limit", type=int, default=10, help="列表类命令的条数（默认 10）")
    args = parser.parse_args(argv)

    if args.command == "snapshot":
        path = write_snapshot()
        print(f"快照已生成：{path}")
        return 0

    data, markdown = _cli_data(args.command, args)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
