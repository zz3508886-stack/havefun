"""P6 测试：政策资讯纯读解析（文档清单/结构化大纲/时间节点/目标院校）。

样例仓库(tmp) + 路径穿越防护；不写库不写文档。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.main import create_app
from fastapi.testclient import TestClient

SYLLABUS = """# 考试大纲
| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 创建时间 | 2026-10-22 |
| 学科 | 政策资讯 |
| 分类 | 考试大纲 |

> 以官方简章为准。

## 一、考试基本信息

| 项目 | 内容 |
| --- | --- |
| 招生对象 | 河南中职应/往届毕业生 |
| 文化素质科目 | 语文、数学、英语 |

## 二、各科考试范围

### 数学

- 数与式、方程与不等式
- 函数

## 三、目标院校

| 院校 | 层次 | 简章链接 | 简章是否已核对 | 关注状态 |
| --- | --- | --- | --- | --- |
| 某护理职业学院 | 专科 | https://example.edu | ✅ | ⬜ |
"""

ENROLL = """# 报名与志愿填报
| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 创建时间 | 2026-10-22 |
| 学科 | 政策资讯 |
| 分类 | 报名与志愿 |

## 一、关键时间节点

| 事项 | 预计时间 | 确认状态 |
| --- | --- | --- |
| 高考/单招报名 | 2026-11 | ⬜ |
| 考试 | 2027-04-15 | ✅ |

## 二、报名流程

1. 完成当年高考报名
2. 填报院校及专业志愿
"""


@pytest.fixture()
def policy_repo(tmp_path: Path, monkeypatch) -> Path:
    import app.indexer as idx

    d = tmp_path / "政策资讯"
    d.mkdir(parents=True)
    (d / "考试大纲.md").write_text(SYLLABUS, encoding="utf-8")
    (d / "报名与志愿填报.md").write_text(ENROLL, encoding="utf-8")
    # 非政策目录的文档不应被列出/可读
    (tmp_path / "数学").mkdir()
    (tmp_path / "数学" / "题库.md").write_text("# 题库\n| 学科 | 数学 |\n", encoding="utf-8")
    monkeypatch.setattr(idx, "REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def policy_client(policy_repo: Path) -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# 文档清单与元信息
# --------------------------------------------------------------------------- #
def test_list_docs_with_meta(policy_client):
    docs = {d["name"]: d for d in policy_client.get("/api/policy/docs").json()}
    assert set(docs) == {"考试大纲", "报名与志愿填报"}
    syl = docs["考试大纲"]
    assert syl["path"] == "政策资讯/考试大纲.md"
    assert syl["status"] == "🟨 整理中"      # R16 文档头元信息提取
    assert syl["category"] == "考试大纲"
    assert syl["title"] == "考试大纲"


# --------------------------------------------------------------------------- #
# 结构化大纲
# --------------------------------------------------------------------------- #
def test_get_doc_outline(policy_client):
    body = policy_client.get("/api/policy/doc", params={"path": "政策资讯/考试大纲.md"}).json()
    assert body["meta"]["学科"] == "政策资讯"
    titles = [n["title"] for n in body["outline"]]
    assert "一、考试基本信息" in titles and "三、目标院校" in titles

    # 基本信息表：项目/内容两列表（分隔行不泄漏进行）
    basic = next(n for n in body["outline"] if n["title"] == "一、考试基本信息")
    tables = [b for b in basic["blocks"] if b["type"] == "table"]
    assert tables and tables[0]["header"] == ["项目", "内容"]
    rows = {r[0]: r[1] for r in tables[0]["rows"]}
    assert rows["招生对象"] == "河南中职应/往届毕业生"
    assert all("---" not in r for r in tables[0]["rows"])

    # 列表块
    math_sec = next(n for n in body["outline"] if n["title"] == "数学")
    lst = next(b for b in math_sec["blocks"] if b["type"] == "list")
    assert lst["ordered"] is False
    assert [i["text"] for i in lst["items"]] == ["数与式、方程与不等式", "函数"]


def test_get_doc_ordered_list(policy_client):
    body = policy_client.get(
        "/api/policy/doc", params={"path": "政策资讯/报名与志愿填报.md"}
    ).json()
    flow = next(n for n in body["outline"] if n["title"] == "二、报名流程")
    lst = next(b for b in flow["blocks"] if b["type"] == "list")
    assert lst["ordered"] is True
    assert len(lst["items"]) == 2


# --------------------------------------------------------------------------- #
# 便利端点
# --------------------------------------------------------------------------- #
def test_key_dates(policy_client):
    rows = policy_client.get("/api/policy/key-dates").json()
    assert rows == [
        {"item": "高考/单招报名", "time": "2026-11", "confirmed": "⬜"},
        {"item": "考试", "time": "2027-04-15", "confirmed": "✅"},
    ]


def test_schools(policy_client):
    rows = policy_client.get("/api/policy/schools").json()
    assert rows == [
        {
            "school": "某护理职业学院",
            "level": "专科",
            "link": "https://example.edu",
            "checked": "✅",
            "following": "⬜",
        }
    ]


def test_key_dates_empty_when_doc_missing(tmp_path: Path, monkeypatch):
    import app.indexer as idx

    monkeypatch.setattr(idx, "REPO_ROOT", tmp_path)  # 无 政策资讯/
    client = TestClient(create_app())
    assert client.get("/api/policy/docs").json() == []
    assert client.get("/api/policy/key-dates").json() == []
    assert client.get("/api/policy/schools").json() == []


# --------------------------------------------------------------------------- #
# 路径安全
# --------------------------------------------------------------------------- #
def test_doc_rejects_outside_policy_dir(policy_client):
    r = policy_client.get("/api/policy/doc", params={"path": "数学/题库.md"})
    assert r.status_code == 400


def test_doc_rejects_traversal(policy_client):
    r = policy_client.get("/api/policy/doc", params={"path": "../数学/题库.md"})
    assert r.status_code in (400, 404)


def test_doc_404_for_missing(policy_client):
    r = policy_client.get("/api/policy/doc", params={"path": "政策资讯/不存在.md"})
    assert r.status_code == 404
