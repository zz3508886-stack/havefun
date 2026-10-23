"""公共夹具：临时数据库 + TestClient + P2 测验样例仓库。"""

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
    """把 DB_PATH 指到临时目录，避免污染真实 data/quiz.db。"""
    path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", path)
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
