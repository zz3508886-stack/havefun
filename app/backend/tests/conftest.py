"""公共夹具：临时数据库 + TestClient + P2 测验样例仓库 + P4 计划样例仓库。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

# 标准格式样例：一套含客观题(选择/判断)与主观题(填空/解答)，并有同名解析文档
SAMPLE_QBANK = """# 数学·一次函数 题库
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

### 第 3 题（SX-003，判断题，【基础｜难度 1】）
题干C：

### 第 4 题（SX-004，解答题，【基础｜难度 3】）
题干D：
"""

SAMPLE_ANALYSIS = """# 解析
## 一、一次函数专项测验解析
### SX-001（选择题）
**答案：A**
**解析：** 略
### SX-002（填空题）
**答案：x**
### SX-003（判断题）
**答案：正确**
### SX-004（解答题）
**答案：y**
"""


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch) -> Path:
    """把 DB_PATH 指到临时目录并建好 schema，避免污染真实 data/quiz.db。

    不走 HTTP 的测试（直接用 repo 夹具 + connect()）也依赖这里的 init_db。
    """
    path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", path)
    from app.db import init_db

    init_db(path)
    return path


@pytest.fixture()
def client(db_path: Path) -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def quiz_repo(tmp_path: Path) -> Path:
    """标准格式样例仓库（含 题库.md 与同名 题库解析.md）。"""
    sub = tmp_path / "数学" / "一次函数"
    sub.mkdir(parents=True)
    (sub / "题库.md").write_text(SAMPLE_QBANK, encoding="utf-8")
    (sub / "题库解析.md").write_text(SAMPLE_ANALYSIS, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def api_client(db_path: Path, quiz_repo: Path, monkeypatch) -> TestClient:
    """REPO_ROOT 指向样例仓库并种子化 DB 后再建客户端。"""
    import app.indexer as idx
    import app.quiz as qz
    import app.writeback as wb

    monkeypatch.setattr(idx, "REPO_ROOT", quiz_repo)
    monkeypatch.setattr(wb, "REPO_ROOT", quiz_repo)
    monkeypatch.setattr(qz, "REPO_ROOT", quiz_repo)
    from app.indexer import run_index

    run_index(quiz_repo)
    return TestClient(create_app())


# 计划样例：节点总表两节点 + 两个不含「状态列」语义的其他表格（验证解析只认节点表）
SAMPLE_PLAN = """# 节点安排
| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 创建时间 | 2026-10-22 |
| 学科 | 复习计划 |
| 分类 | 节点安排 |

> 依据事实文档生成。

## 一、节点总表

| 节点 | 名称 | 起止日期 | 阶段 | 目标 | 产出 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 完成各科摸底自测 | 自测记录 | ⬜ |
| N02 | 基础梳理 | 2026-10-26 至 2026-11-22 | 基础梳理 | 通读知识点 | 掌握标记 | ⬜ |

## 二、各节点科目侧重

| 节点 | 语文 | 数学 |
| --- | --- | --- |
| N01 | 摸底自测 | 摸底自测 |

## 三、官方事项节点

| 事项 | 预计时间 | 确认状态 | 说明 |
| --- | --- | --- | --- |
| 高考/单招报名 | 2026-11 至 2026-12 | ⬜ | 流程见文档 |
"""


@pytest.fixture()
def plan_repo(tmp_path: Path, db_path: Path, monkeypatch) -> Path:
    """计划样例仓库（含 复习计划/节点安排.md），REPO_ROOT 指向它，DB 走临时库。"""
    import app.indexer as idx

    sub = tmp_path / "复习计划"
    sub.mkdir(parents=True)
    (sub / "节点安排.md").write_text(SAMPLE_PLAN, encoding="utf-8")
    monkeypatch.setattr(idx, "REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def plan_client(db_path: Path, plan_repo: Path) -> TestClient:
    return TestClient(create_app())


# 错题本样例：与仓库 错题本/README.md 结构一致（使用说明 + 三张表）
SAMPLE_WRONGBOOK = """# 错题本

## 使用说明

- 每道错题记录：题目来源、错因类型、正确思路、复盘日期。
- 按 1/3/7/15 天间隔回顾：录入或订正后的第 1 天、第 3 天、第 7 天、第 15 天各复盘一次，四次均做对才标记「已攻克」。
- 错因类型参考：概念不清 / 计算失误 / 思路错误 / 审题偏差 / 知识遗忘。

## 一、错题记录

| 编号 | 科目 | 题目来源 | 题目摘要 | 错因类型 | 正确思路 | 录入日期 | 复盘次数 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CT-001 | 待填写 | | | | | | 0 | 🔴 未攻克 |

## 二、按科目统计

| 科目 | 错题数 | 未攻克 | 已攻克 |
| --- | --- | --- | --- |
| 语文 | 待填写 | 待填写 | 待填写 |
| 数学 | 待填写 | 待填写 | 待填写 |
| 英语 | 待填写 | 待填写 | 待填写 |
| 解剖学基础 | 待填写 | 待填写 | 待填写 |
| 生理学基础 | 待填写 | 待填写 | 待填写 |
| 护理学基础 | 待填写 | 待填写 | 待填写 |

## 三、高频错因 TOP

| 错因类型 | 出现次数 | 整改措施 |
| --- | --- | --- |
| 待填写 | 待填写 | 待填写 |
"""


@pytest.fixture()
def wrongbook_repo(tmp_path: Path, db_path: Path, monkeypatch) -> Path:
    """错题本样例仓库：quiz_repo 基础上补 错题本/README.md，REPO_ROOT 指向它，DB 走临时库。"""
    sub = tmp_path / "数学" / "一次函数"
    sub.mkdir(parents=True)
    (sub / "题库.md").write_text(SAMPLE_QBANK, encoding="utf-8")
    (sub / "题库解析.md").write_text(SAMPLE_ANALYSIS, encoding="utf-8")
    d = tmp_path / "错题本"
    d.mkdir(parents=True)
    (d / "README.md").write_text(SAMPLE_WRONGBOOK, encoding="utf-8")
    import app.indexer as idx
    import app.writeback as wb
    import app.quiz as qz

    monkeypatch.setattr(idx, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(wb, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(qz, "REPO_ROOT", tmp_path)
    from app.indexer import run_index

    run_index(tmp_path)
    return tmp_path


@pytest.fixture()
def wrongbook_client(db_path: Path, wrongbook_repo: Path) -> TestClient:
    return TestClient(create_app())


# 摸底卷样例：章节名靠「摸底」命中 SET_RE；解析文档用裸题头（无括号后缀）
SAMPLE_MOPQ = """# 护理学基础 题库
| 项目 | 内容 |
| --- | --- |
| 状态 | 🟨 整理中 |
| 创建时间 | 2026-10-22 |
| 学科 | 护理专业 |
| 分类 | 题库

## 一、使用说明

- 说明

## 二、护理概念摸底（A卷）

### 第 1 题（HL-MP-001，单项选择，【基础｜难度 2】）
现代护理学研究的对象是：
- A. 仅病人
- B. 人与健康
- C. 仅生物
- D. 仅医院

### 第 2 题（HL-MP-002，选择题，【基础｜难度 2】）
基础护理工作的核心是：
- A. 打针
- B. 用药
- C. 满足人的需要
- D. 化验
"""

SAMPLE_MOPQ_ANALYSIS = """# 解析

### HL-MP-001

**答案：B**

**解析：** 现代护理学研究的对象是人，既包括病人，也包括健康人。

### HL-MP-002

**答案：C**

**解析：** 基础护理工作以满足人的基本需要为核心。
"""


@pytest.fixture()
def mopq_repo(tmp_path: Path, db_path: Path, monkeypatch) -> Path:
    """摸底卷样例仓库（测验/摸底/… + 裸题头解析），REPO_ROOT 指向它，DB 走临时库。"""
    sub = tmp_path / "测验" / "摸底" / "护理学基础"
    sub.mkdir(parents=True)
    (sub / "题库.md").write_text(SAMPLE_MOPQ, encoding="utf-8")
    (sub / "题库解析.md").write_text(SAMPLE_MOPQ_ANALYSIS, encoding="utf-8")
    import app.indexer as idx
    import app.writeback as wb
    import app.quiz as qz

    monkeypatch.setattr(idx, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(wb, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(qz, "REPO_ROOT", tmp_path)
    from app.indexer import run_index

    run_index(tmp_path)
    return tmp_path


@pytest.fixture()
def mopq_client(db_path: Path, mopq_repo: Path) -> TestClient:
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _isolate_snapshot(tmp_path: Path, monkeypatch) -> None:
    """所有测试默认把 AI 快照写进 tmp，避免污染真实 app/data/ 目录。

    交互钩子（submit/feedback/checkin → refresh_snapshot）照常执行，
    只是落点被改到临时目录。
    """
    import app.ai as ai_mod

    monkeypatch.setattr(ai_mod, "SNAPSHOT_PATH", tmp_path / "ai-snapshot.md")
