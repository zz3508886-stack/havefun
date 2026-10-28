"""P7 测试：AI 取数通道——CLI / 一页纸快照 / 只读 API / 令牌鉴权 / 与 stats 同源。

种子经 HTTP 接口产生；快照落点由 conftest 的 autouse 夹具改到 tmp。
"""

from __future__ import annotations

import json
from pathlib import Path

import app.ai as ai_mod
from app.ai import digest_doubt, digest_summary, main as ai_main

SET = ("数学/一次函数/题库.md", "三、一次函数专项测验")

SAMPLE_PLAN = """# 节点安排
| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 创建时间 | 2026-10-22 |
| 学科 | 复习计划 |
| 分类 | 节点安排 |

## 一、节点总表

| 节点 | 名称 | 起止日期 | 阶段 | 目标 | 产出 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 摸底自测 | 自测记录 | ⬜ |
| N02 | 基础梳理 | 2026-10-26 至 2026-11-22 | 基础梳理 | 通读知识点 | 掌握标记 | ⬜ |
"""

SAMPLE_YND = """# 疑难点

| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 创建时间 | 2026-10-22 |
| 学科 | 错题本 |
| 分类 | 疑难点 |

## 一、疑难点记录

| 专题 | 学科 | 出现次数 | 首次出现 | 最近出现 | 关联问题摘要 | 对应章节链接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | ⬜ |
| 一次函数图像平移 | 数学 | 3 | 2026-10-20 | 2026-10-23 | 左右平移分不清 | 数学/函数/一次函数/题库.md | ⬜ |
| 英语虚拟语气 | 英语 | 5 | 2026-10-18 | 2026-10-22 | if 条件句混淆 | 英语/题库.md | ✅ |
"""


def _seed_all(api_client, quiz_repo: Path) -> None:
    """两份卷 + 一条反馈 + 疑难点 + 节点打卡（先落文档再发交互）。"""
    # 疑难点.md + 节点安排.md 先落到样例仓库（feedback/checkin 的回写目标）
    (quiz_repo / "错题本").mkdir(parents=True, exist_ok=True)
    (quiz_repo / "错题本" / "疑难点.md").write_text(SAMPLE_YND, encoding="utf-8")
    (quiz_repo / "复习计划").mkdir(parents=True, exist_ok=True)
    (quiz_repo / "复习计划" / "节点安排.md").write_text(SAMPLE_PLAN, encoding="utf-8")

    api_client.post(
        "/api/quiz/submit",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "answers": {"SX-001": "A", "SX-003": "正确", "SX-002": "x", "SX-004": "y"},
        },
    )
    api_client.post(
        "/api/quiz/submit",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "answers": {"SX-001": "B", "SX-003": "错误", "SX-002": "x", "SX-004": "y"},
        },
    )
    api_client.post(
        "/api/quiz/feedback",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "qid": "SX-001",
            "error_type": "概念不清",
            "confused": True,
        },
    )
    api_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "✅"})


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_summary_markdown(api_client, quiz_repo, capsys):
    _seed_all(api_client, quiz_repo)
    assert ai_main(["summary"]) == 0
    out = capsys.readouterr().out
    assert "# AI 学情快照" in out
    assert "## 总量与正确率" in out and "## 薄弱 Top" in out
    assert "## 疑难点 Top" in out and "## 打卡进度" in out
    assert "50.0%" in out            # 2/4 已判正确率
    assert "英语虚拟语气" in out      # 疑难点 Top 按次数降序（5 > 3）
    assert "N01 ✅" in out            # 节点进度


def test_cli_summary_json_matches_stats(api_client, quiz_repo, capsys):
    """验收点：AI 快照数字与仪表盘 stats 同源一致。"""
    _seed_all(api_client, quiz_repo)
    assert ai_main(["summary", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    overview = api_client.get("/api/stats/overview").json()
    assert data["overview"]["quiz"] == overview["quiz"]
    assert data["overview"]["plan"]["checkin_days"] == overview["plan"]["checkin_days"]

    weak_http = api_client.get("/api/stats/weak").json()
    assert data["weak_sets"] == weak_http["sets"][:5]


def test_cli_other_commands(api_client, quiz_repo, capsys):
    _seed_all(api_client, quiz_repo)
    for cmd in ("weak", "pending", "recent", "doubt", "plan"):
        assert ai_main([cmd, "--limit", "5"]) == 0
        out = capsys.readouterr().out
        assert out.strip(), cmd
    assert ai_main(["recent", "--json", "--limit", "5"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 5 and rows[0]["qid"]  # 新的在前


def test_cli_snapshot_command(api_client, quiz_repo, tmp_path, monkeypatch, capsys):
    _seed_all(api_client, quiz_repo)
    target = tmp_path / "snap.md"
    monkeypatch.setattr(ai_mod, "SNAPSHOT_PATH", target)
    assert ai_main(["snapshot"]) == 0
    assert f"快照已生成：{target}" in capsys.readouterr().out
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# AI 学情快照")
    assert "英语虚拟语气" in text


# --------------------------------------------------------------------------- #
# 交互后自动刷新快照
# --------------------------------------------------------------------------- #
def test_snapshot_refreshed_after_submit(api_client, quiz_repo, tmp_path, monkeypatch):
    target = tmp_path / "ai-snapshot.md"
    monkeypatch.setattr(ai_mod, "SNAPSHOT_PATH", target)
    api_client.post(
        "/api/quiz/submit",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "answers": {"SX-001": "A"},
        },
    )
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "# AI 学情快照" in text and "## 打卡进度" in text


def test_snapshot_refresh_failure_does_not_break_submit(api_client, monkeypatch):
    """快照是派生数据：刷新失败不能影响交卷主流程。"""
    import app.ai as ai_mod

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ai_mod, "write_snapshot", _boom)
    resp = api_client.post(
        "/api/quiz/submit",
        json={"file_path": SET[0], "section_title": SET[1], "answers": {"SX-001": "A"}},
    )
    assert resp.status_code == 200
    assert resp.json()["writeback"] == "written"


# --------------------------------------------------------------------------- #
# 只读 API
# --------------------------------------------------------------------------- #
def test_api_endpoints(api_client, quiz_repo):
    _seed_all(api_client, quiz_repo)

    s = api_client.get("/api/ai/summary").json()
    assert s["overview"]["quiz"]["total"] == 8
    assert s["plan"]["done"] == 1 and s["plan"]["current"] == "N02"
    # confused 反馈已把「三、一次函数专项测验」累加进疑难点.md（次数 1，排最后）
    assert [i["topic"] for i in s["doubt"]["items"]] == [
        "英语虚拟语气",
        "一次函数图像平移",
        "三、一次函数专项测验",
    ]

    pending_rows = api_client.get("/api/ai/pending", params={"limit": 3}).json()
    assert len(pending_rows) == 3 and all(r["is_correct"] is None for r in pending_rows)

    recent_rows = api_client.get("/api/ai/recent", params={"limit": 5}).json()
    assert len(recent_rows) == 5

    doubt = api_client.get("/api/ai/doubt").json()
    assert doubt["open_count"] == 2 and doubt["total_count"] == 3  # 待填写行不计

    plan = api_client.get("/api/ai/plan").json()
    assert plan["nodes"][0]["derived_status"] == "✅"

    snap = api_client.get("/api/ai/snapshot").json()
    assert snap["exists"] is True and "AI 学情快照" in snap["content"]


def test_api_token_auth(api_client, monkeypatch):
    monkeypatch.setattr("app.ai.load_config", lambda: {"ai_access_token": "secret"})

    # 无令牌 → 401
    assert api_client.get("/api/ai/summary").status_code == 401
    # 错误令牌 → 401
    r = api_client.get("/api/ai/summary", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    # Bearer 正确 → 200
    r = api_client.get("/api/ai/summary", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    # query 参数正确 → 200
    assert api_client.get("/api/ai/summary", params={"token": "secret"}).status_code == 200

    # 未配置令牌 → 不启用鉴权
    monkeypatch.setattr("app.ai.load_config", lambda: {"ai_access_token": ""})
    assert api_client.get("/api/ai/summary").status_code == 200


# --------------------------------------------------------------------------- #
# 疑难点 digest 单测
# --------------------------------------------------------------------------- #
def test_doubt_digest_sorted_and_skips_placeholder(quiz_repo):
    (quiz_repo / "错题本").mkdir(parents=True, exist_ok=True)
    (quiz_repo / "错题本" / "疑难点.md").write_text(SAMPLE_YND, encoding="utf-8")
    d = digest_doubt(10, repo_root=quiz_repo)
    assert [i["topic"] for i in d["items"]] == ["英语虚拟语气", "一次函数图像平移"]
    assert d["items"][0]["times"] == 5
    assert d["open_count"] == 1 and d["total_count"] == 2


def test_doubt_digest_missing_file(quiz_repo):
    d = digest_doubt(10, repo_root=quiz_repo)
    assert d == {"items": [], "open_count": 0, "total_count": 0}


def test_digest_summary_structure(quiz_repo):
    d = digest_summary(repo_root=quiz_repo)
    assert set(d) >= {"generated_at", "overview", "weak_sets", "weak_questions", "pending", "doubt", "plan"}
    assert d["plan"]["total"] == 0  # 样例仓库无 节点安排.md → 空节点不崩
