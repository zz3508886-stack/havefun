"""P6 测试：资料库纯读索引（知识点单元 + Anki 卡组）。

样例仓库(tmp)：单元四件套齐全度、索引层题型统计、自评标记计数、
卡组卡片数与 stale 过期标记；不写库不写文档（索引由夹具跑一次）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SAMPLE_KBANK = """# 数学·一次函数 题库
| 项目 | 内容 |
| --- | --- |
| 学科 | 数学 |
| 分类 | 题库 |

## 一、使用说明
- 说明

## 三、一次函数专项测验

### 第 1 题（SX-001，选择题，【基础｜难度 2】）
题干A：
- A. x
- B. y

### 第 2 题（SX-002，填空题，【基础｜难度 2】）
题干B：
"""

SAMPLE_SUMMARY = """# 一次函数 知识点梳理
| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 学科 | 数学 |
| 分类 | 知识点梳理 |

## 一、函数概念

概念讲解 ✅

## 二、图像与性质

性质讲解 🟨

## 三、待补章节

⬜
"""

DECK_GOOD = """# 注释头
# @tag 层级::掌握级 主题::核心
school\t学校
class\t班级
"""

DECK_STALE = """# 认识级补充
word\t单词
"""


@pytest.fixture()
def kb_repo(tmp_path: Path, db_path: Path, monkeypatch) -> Path:
    import app.indexer as idx

    # 知识点单元：四件套齐全（数学）+ 缺题库（英语，只应列出不应崩）
    math = tmp_path / "数学" / "函数" / "一次函数"
    math.mkdir(parents=True)
    (math / "知识点梳理.md").write_text(SAMPLE_SUMMARY, encoding="utf-8")
    (math / "题库.md").write_text(SAMPLE_KBANK, encoding="utf-8")
    (math / "题库解析.md").write_text("# 解析\n", encoding="utf-8")
    (math / "知识点目录.md").write_text("# 目录\n", encoding="utf-8")

    eng = tmp_path / "英语"
    eng.mkdir()
    (eng / "知识点梳理.md").write_text("# 英语 知识点梳理\n| 学科 | 英语 |\n", encoding="utf-8")

    # 应被跳过的非内容目录
    web = tmp_path / "web"
    web.mkdir()
    (web / "知识点梳理.md").write_text("# 旧服务\n", encoding="utf-8")

    # Anki 卡组：一个最新打包、一个改了源未打包（stale）
    decks = tmp_path / "复习计划" / "Anki卡组"
    decks.mkdir(parents=True)
    (decks / "英语词汇.txt").write_text(DECK_GOOD, encoding="utf-8")
    (decks / "英语词汇.apkg").write_bytes(b"PK\x03\x04fake-apkg")
    (decks / "英语高频词.txt").write_text(DECK_STALE, encoding="utf-8")
    (decks / "英语高频词.apkg").write_bytes(b"PK\x03\x04old-apkg")
    # 让 txt 明显新于 apkg → stale
    old = time.time() - 3600
    os.utime(decks / "英语高频词.apkg", (old, old))

    monkeypatch.setattr(idx, "REPO_ROOT", tmp_path)
    from app.indexer import run_index

    run_index(tmp_path)
    return tmp_path


@pytest.fixture()
def kb_client(kb_repo: Path) -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# 知识点单元
# --------------------------------------------------------------------------- #
def test_list_units(kb_client):
    units = {u["path"]: u for u in kb_client.get("/api/knowledge/units").json()}
    # web/ 下的旧文件被跳过
    assert set(units) == {"数学/函数/一次函数/知识点梳理.md", "英语/知识点梳理.md"}

    math = units["数学/函数/一次函数/知识点梳理.md"]
    assert math["subject"] == "数学" and math["unit"] == "一次函数"
    assert math["has_qbank"] and math["has_analysis"] and math["has_catalog"]
    # 自评标记计数（✅ 1 / 🟨 1 / ⬜ 1）
    assert math["mastery"] == {"⬜": 1, "🟨": 1, "✅": 1}

    eng = units["英语/知识点梳理.md"]
    assert eng["has_qbank"] is False and eng["unit"] == "英语"


def test_unit_detail_with_qbank_stats(kb_client):
    body = kb_client.get(
        "/api/knowledge/unit", params={"path": "数学/函数/一次函数/知识点梳理.md"}
    ).json()
    assert body["title"] == "一次函数 知识点梳理"
    assert body["meta"]["学科"] == "数学"
    # 题型统计来自索引层；绝不外泄 answer_key
    assert body["qbank"]["total"] == 2
    assert body["qbank"]["by_type"] == {"选择题": 1, "填空题": 1}
    assert "answer_key" not in body and "answer_key" not in str(body["qbank"])
    assert body["mastery"]["✅"] == 1


def test_unit_detail_without_qbank(kb_client):
    body = kb_client.get(
        "/api/knowledge/unit", params={"path": "英语/知识点梳理.md"}
    ).json()
    assert body["qbank"] is None


def test_unit_detail_404(kb_client):
    r = kb_client.get("/api/knowledge/unit", params={"path": "数学/不存在.md"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Anki 卡组
# --------------------------------------------------------------------------- #
def test_list_decks(kb_client):
    decks = {d["name"]: d for d in kb_client.get("/api/knowledge/decks").json()}
    assert set(decks) == {"英语词汇", "英语高频词"}

    good = decks["英语词汇"]
    assert good["cards"] == 2               # 注释行不计卡
    assert good["levels"] == ["掌握级"]      # @tag 层级提取
    assert good["has_apkg"] is True
    assert good["stale"] is False           # apkg 比 txt 新

    stale = decks["英语高频词"]
    assert stale["cards"] == 1
    assert stale["levels"] == []
    assert stale["stale"] is True           # txt 新于 apkg → 提醒重新打包
