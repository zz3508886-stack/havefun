"""SQLite 连接与 schema 初始化（WAL 模式）。

表结构与设计文档「SQLite Schema 参考」一节一致：doc_files /
questions_index / quiz_attempts / plan_checkins / quiz_feedback /
wrongbook_reviews。P0 仅建空 schema，P1 起由索引构建器按 mtime + hash
双层校验填充。

定位（P9 试点后）：内容事实源是 markdown；**过程数据**（答题流水、反馈、
打卡、错题复盘）的事实源是 SQLite，对应 md 区块由 exporter 重生成
（见《总体设计 · 数据所有权划分》）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
-- 文档状态监控（防冗余重建）
CREATE TABLE IF NOT EXISTS doc_files (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_indexed_at DATETIME NOT NULL
);

-- 题目索引（纯只读缓存，来自 markdown 解析；answer_key 仅服务端可见，不下发前端）
CREATE TABLE IF NOT EXISTS questions_index (
    file_path TEXT NOT NULL,
    qid TEXT NOT NULL,              -- 显式 ID 优先，内容指纹兜底
    section_title TEXT NOT NULL,    -- 所属套题/章节
    q_type TEXT NOT NULL,
    stem TEXT NOT NULL,
    options_json TEXT,
    answer_key TEXT NOT NULL,
    difficulty TEXT,
    tags_json TEXT,
    PRIMARY KEY (file_path, qid)
);

-- 做题流水（一次提交 = 同 batch_id 的多行）
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    qid TEXT NOT NULL,
    user_answer TEXT,
    is_correct BOOLEAN,             -- 1 对 / 0 错 / NULL 待判
    eval_type TEXT NOT NULL,        -- auto / ai / manual
    eval_state TEXT NOT NULL DEFAULT 'done',  -- done / evaluating / pending_manual
    cost_seconds INTEGER,
    error_type TEXT,                -- R18 五类错因
    user_id INTEGER,                -- 预留，单用户暂空
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_attempts_qid ON quiz_attempts(qid, created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_batch ON quiz_attempts(batch_id);

-- 节点打卡明细（定期汇总回写 节点安排.md 状态列）
CREATE TABLE IF NOT EXISTS plan_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,           -- ⬜ / 🟨 / ✅
    notes TEXT,
    user_id INTEGER,                -- 预留，单用户暂空
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 题目反馈（错因自选 / 解析没看懂；confused 时累加 疑难点.md）
CREATE TABLE IF NOT EXISTS quiz_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    section_title TEXT NOT NULL,
    qid TEXT NOT NULL,
    error_type TEXT,                -- R18 五类错因（可空）
    confused BOOLEAN NOT NULL DEFAULT 0,  -- 1 = 解析没看懂
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feedback_qid ON quiz_feedback(qid, created_at);

-- 错题复盘流水（P9 试点：错题本过程数据的事实源之一）
-- 复盘次数 = result=1 的次数；最近连续做对满 MASTERY_REVIEWS(4) 次标记已攻克
CREATE TABLE IF NOT EXISTS wrongbook_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    qid TEXT NOT NULL,
    result INTEGER NOT NULL,           -- 1 复盘做对 / 0 仍错
    note TEXT,                         -- 复盘时记录的正确思路/要点（可选）
    user_id INTEGER,                   -- 预留，单用户暂空
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reviews_qid ON wrongbook_reviews(file_path, qid, created_at);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """打开 SQLite 连接并启用 WAL；目录不存在时自动创建。"""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """建表（IF NOT EXISTS，可重复执行）；供启动与测试共用。"""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
