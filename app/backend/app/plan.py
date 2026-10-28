"""复习计划模块：节点打卡 + 节点安排.md 状态列导出（P4 建立，P9 改为导出）。

职责（对应《总体设计 · 分期计划》P4/P9）：
- 节点解析：只读解析 复习计划/节点安排.md「一、节点总表」，产出节点清单
  （node_id / 名称 / 起止日期 / 阶段 / 状态）；状态列之外一律冻结。
- 打卡明细：每次打卡落 plan_checkins（node_id + status + notes），**明细是
  过程数据的事实源**。
- 状态规则：节点状态 = 该节点**最近一次打卡状态**（⬜ 未开始 / 🟨 进行中 /
  ✅ 已完成）。与文档约定的 ⬜→🟨→✅ 推进一致，且允许复盘时改回（如误标
  ✅ 后修正为 🟨）。
- 状态列是**导出视图**（P9 试点）：打卡后由 exporter.export_plan_status 按
  明细全量重生成，外部手改会被下次导出覆盖；导出失败（冲突/过检）时打卡
  明细已落库，接口返回降级标记而非崩溃。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from . import indexer
from .db import connect
from .parser import _split_sections
from .writeback import PreCheckError

router = APIRouter(prefix="/api/plan", tags=["plan"])

PLAN_REL = "复习计划/节点安排.md"
NODE_SECTION_KEYWORD = "节点总表"
STATUSES = ("⬜", "🟨", "✅")  # 未开始 / 进行中 / 已完成
NODE_ID_RE = re.compile(r"^N\d{2}$")


class CheckinRequest(BaseModel):
    node_id: str
    status: str
    notes: Optional[str] = None

    @field_validator("node_id")
    @classmethod
    def _chk_node_id(cls, v: str) -> str:
        v = (v or "").strip()
        if not NODE_ID_RE.match(v):
            raise ValueError(f"node_id 须为 N01–N99 形式，收到：{v!r}")
        return v

    @field_validator("status")
    @classmethod
    def _chk_status(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in STATUSES:
            raise ValueError(f"status 必须是 {' / '.join(STATUSES)} 之一")
        return v


def _split_row(line: str) -> list[str]:
    return [p.strip() for p in line.strip().strip("|").split("|")]


def parse_nodes(path: Path) -> list[dict]:
    """解析 节点安排.md 的「一、节点总表」，返回节点列表（含行号，供回写定位）。

    只认首列为 ``Nxx`` 的数据行；表头/分隔行/章节外表格一律忽略，
    避免把「三、官方事项节点」等其他表格误判为节点。
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    nodes: list[dict] = []
    for title, s, e in _split_sections(lines):
        if NODE_SECTION_KEYWORD not in title:
            continue
        for i in range(s, e):
            line = lines[i]
            if not line.strip().startswith("|"):
                continue
            cells = _split_row(line)
            if len(cells) < 7 or not NODE_ID_RE.match(cells[0]):
                continue
            nodes.append(
                {
                    "node_id": cells[0],
                    "name": cells[1],
                    "date_range": cells[2],
                    "stage": cells[3],
                    "goal": cells[4],
                    "output": cells[5],
                    "status": cells[6],
                    "line_no": i,  # 0-based，回写定位用
                }
            )
        break  # 节点总表唯一，取到即止
    return nodes


def derive_status(latest_status: Optional[str]) -> str:
    """由最近一次打卡状态推导节点状态；无打卡 → ⬜ 未开始。"""
    if latest_status in STATUSES:
        return latest_status
    return "⬜"


def _recent_checkins() -> list:
    """全部打卡明细（id 倒序，新的在前）。"""
    conn = connect()
    try:
        return conn.execute(
            "SELECT node_id, status, created_at FROM plan_checkins ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()


def latest_checkins() -> dict[str, str]:
    """每节点最近一次打卡状态（过程数据事实源的读接口）。

    exporter.export_plan_status 与本模块的推导共用；无打卡的节点不在表内，
    由 derive_status 兜底为 ⬜。
    """
    out: dict[str, str] = {}
    for r in _recent_checkins():
        out.setdefault(r["node_id"], r["status"])
    return out


def nodes_with_status(repo_root: Path | None = None) -> list[dict]:
    """节点清单：文档状态列（最近一次导出的 DB 推导值）+ DB 明细推导状态
    + 打卡次数（路由与 AI 通道共用）。"""
    root = Path(repo_root) if repo_root else indexer.REPO_ROOT
    path = root / PLAN_REL
    if not path.exists():
        raise FileNotFoundError(f"未找到 {PLAN_REL}")

    nodes = parse_nodes(path)
    rows = _recent_checkins()
    latest: dict[str, str] = {}
    counts: dict[str, int] = {}
    last_at: dict[str, str] = {}
    for r in rows:  # id 倒序：首个即最近一次
        latest.setdefault(r["node_id"], r["status"])
        counts[r["node_id"]] = counts.get(r["node_id"], 0) + 1
        last_at.setdefault(r["node_id"], r["created_at"])

    out = []
    for n in nodes:
        derived = derive_status(latest.get(n["node_id"]))
        out.append(
            {
                **{k: n[k] for k in ("node_id", "name", "date_range", "stage", "status")},
                "derived_status": derived,
                "checkin_count": counts.get(n["node_id"], 0),
                "last_checkin_at": last_at.get(n["node_id"]),
            }
        )
    return out


@router.get("/nodes")
def list_nodes() -> list[dict]:
    """节点清单：文档状态列 + DB 明细推导状态 + 打卡次数。"""
    try:
        return nodes_with_status()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/checkin")
def checkin(req: CheckinRequest) -> dict:
    """节点打卡：明细落 plan_checkins → 触发状态列导出（DB 为源，md 为视图）。

    导出失败（过检/异常）不丢打卡：返回降级标记，与 quiz/submit 同构。
    """
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO plan_checkins (node_id, status, notes) VALUES (?,?,?)",
            (req.node_id, req.status, (req.notes or "").strip() or None),
        )
        conn.commit()
        checkin_id = cur.lastrowid
    finally:
        conn.close()

    from .exporter import export_plan_status  # 延迟导入：exporter 依赖本模块

    try:
        writeback = export_plan_status()["status"]  # written / unchanged
        warning = None
    except PreCheckError:
        writeback = "precheck_failed"
        warning = "导出内容未通过校验器检查，已跳过写入"
    except Exception as exc:  # noqa: BLE001 - 视图是派生数据，失败不丢打卡
        writeback = "export_failed"
        warning = str(exc)

    # P7：交互后刷新 AI 一页纸快照（best-effort，失败不影响打卡落库）
    from .ai import refresh_snapshot

    refresh_snapshot()
    return {
        "ok": True,
        "id": checkin_id,
        "node_id": req.node_id,
        "status": req.status,
        "writeback": writeback,
        "warning": warning,
    }


@router.get("/checkins")
def list_checkins(limit: int = 50) -> list[dict]:
    """最近打卡明细（新的在前）。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, node_id, status, notes, created_at FROM plan_checkins "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
