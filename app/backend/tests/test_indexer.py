"""P1 索引层测试：qid 契约、mtime/hash 双层校验、解析容错、全量重建。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import connect
from app.indexer import DOC_FILE_NAMES, run_index
from app.parser import parse_answer_key, parse_file

QBANK = """# 数学·一次函数 题库
| 项目 | 内容 |
| --- | --- |
| 学科 | 数学 |
| 分类 | 题库 |

## 一、使用说明
- 说明

## 二、按章节收录
| 编号 | 章节 | 题型 |
| --- | --- | --- |
| SX-001 | 一次函数 | 选择题 |

## 三、一次函数专项测验

### 第 1 题（SX-001，选择题，【基础｜难度 2】）
题干A：
- A. x
- B. y

### 第 2 题（SX-002，填空题，【基础｜难度 2】）
题干B：

### 第 3 题（SX-003，解答题，【基础｜难度 3】）
题干C：

### 第 4 题（，解答题，【基础｜难度 3】）
题干D（无显式ID走指纹兜底）：
"""

QBANK_ANALYSIS = """# 解析
## 一、一次函数专项测验解析
### SX-001（选择题）
**答案：A**
**解析：** 略
### SX-002（填空题）
**答案：x**
### SX-003（解答题）
**答案：y**
"""

# 纯表格、无标准题目的题库（验证解析容错，不崩）
TABLE_ONLY = """# 生理学基础 题库
| 项目 | 内容 |
| --- | --- |
| 学科 | 护理专业 |
| 分类 | 题库 |

## 三、高频考点自测
| 考点 | 自测问题 |
| --- | --- |
| 血液 | 血浆渗透压分类？ |
"""


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    sub = tmp_path / "数学" / "函数" / "一次函数"
    sub.mkdir(parents=True)
    (sub / "题库.md").write_text(QBANK, encoding="utf-8")
    (sub / "题库解析.md").write_text(QBANK_ANALYSIS, encoding="utf-8")
    (tmp_path / "护理专业" / "生理学基础").mkdir(parents=True)
    (tmp_path / "护理专业" / "生理学基础" / "题库.md").write_text(
        TABLE_ONLY, encoding="utf-8"
    )
    return tmp_path


def test_parse_explicit_and_fallback_ids(sample_repo):
    qs = parse_file(sample_repo / "数学/函数/一次函数/题库.md", sample_repo)
    qids = [q.qid for q in qs]
    assert qids[0] == "SX-001"
    assert qids[1] == "SX-002"
    assert qids[2] == "SX-003"
    # 第 4 题无显式 ID → 12 位 hex 指纹兜底
    assert len(qids[3]) == 12
    assert all(c in "0123456789abcdef" for c in qids[3])


def test_qid_position_independent(sample_repo):
    """在文档中间插入新题，既有显式 ID 题的 qid 不得随位置漂移。"""
    base = sample_repo / "数学/函数/一次函数/题库.md"
    before = {q.qid for q in parse_file(base, sample_repo)}
    # 在 SX-001 与 SX-002 之间插入一道新题
    text = base.read_text(encoding="utf-8")
    inserted = text.replace(
        "### 第 2 题（SX-002",
        "### 第 2 题（SX-050，填空题，【进阶｜难度 5】）\n中间插入题：\n\n### 第 2 题（SX-002",
        1,
    )
    base.write_text(inserted, encoding="utf-8")
    after = {q.qid for q in parse_file(base, sample_repo)}
    # 既有显式 ID 全部保留，且 qid 字符串不变（插入新题不改变历史 qid）
    assert {"SX-001", "SX-002", "SX-003"} <= after
    assert before & {"SX-001", "SX-002", "SX-003"} == after & {"SX-001", "SX-002", "SX-003"}


def test_answer_key_parsed(sample_repo):
    key = parse_answer_key(sample_repo / "数学/函数/一次函数/题库解析.md")
    assert key["SX-001"] == "A"
    assert key["SX-002"] == "x"
    assert key["SX-003"] == "y"


def test_hash_skip_on_unchanged(db_path, sample_repo):
    stats1 = run_index(sample_repo)
    stats2 = run_index(sample_repo)
    assert stats2["indexed"] == 0
    assert stats2["skipped"] == stats1["indexed"] + stats1["skipped"]
    conn = connect()
    n = conn.execute("SELECT count(*) FROM questions_index").fetchone()[0]
    conn.close()
    assert n == 4


def test_parse_tolerance_table_only(sample_repo):
    qs = parse_file(sample_repo / "护理专业/生理学基础/题库.md", sample_repo)
    assert qs == []


def test_run_index_questions_and_monitoring(db_path, sample_repo):
    stats = run_index(sample_repo)
    assert stats["questions"] == 4
    conn = connect()
    n_doc = conn.execute("SELECT count(*) FROM doc_files").fetchone()[0]
    conn.close()
    # 两个 题库.md 均进入 doc_files 监控
    assert n_doc == 2


def test_rebuild_clears_and_repopulates(db_path, sample_repo):
    run_index(sample_repo)
    p = sample_repo / "数学/函数/一次函数/题库.md"
    p.write_text(
        p.read_text(encoding="utf-8")
        + "\n### 第 5 题（SX-005，填空题）\n新增题干：\n",
        encoding="utf-8",
    )
    run_index(sample_repo)  # 增量：仅变的那一个文件重解析
    conn = connect()
    n1 = conn.execute("SELECT count(*) FROM questions_index").fetchone()[0]
    conn.close()
    assert n1 == 5
    run_index(sample_repo, rebuild=True)  # 全量清空再建
    conn = connect()
    n2 = conn.execute("SELECT count(*) FROM questions_index").fetchone()[0]
    n_doc = conn.execute("SELECT count(*) FROM doc_files").fetchone()[0]
    conn.close()
    assert n2 == 5
    assert n_doc == 2


def test_doc_file_names_contract():
    # 四类文档必须纳入监控（与《总体设计》一致）
    assert DOC_FILE_NAMES == {"题库.md", "疑难点.md", "知识点梳理.md", "节点安排.md"}
