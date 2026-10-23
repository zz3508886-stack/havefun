"""索引构建器：mtime + sha256 双层校验，仅哈希变才重解析。

职责（L1 索引层）：
- 发现仓库内四类文档（题库 / 疑难点 / 知识点梳理 / 节点安排），全部写入 doc_files
  做哈希监控，使 AI 改文档后的反向同步有统一基线。
- 仅 题库.md 落 questions_index；题库解析.md 的答案键并入索引。
- mtime 变化只算 sha256，哈希不变则跳过昂贵的解析（Windows Git/IDE 推 mtime 不误触发）。
- --rebuild 全量清空重建兜底。

用法：
    python -m app.indexer            # 增量
    python -m app.indexer --rebuild  # 全量重建
    python -m app.indexer --stats    # 打印计数
    python -m app.indexer --check    # 干跑：报告将索引/跳过的文件
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import APP_ROOT
from .db import connect, init_db
from .parser import answer_key_for, parse_file

# 四类被索引/监控的文档（不含 题库解析.md，它是 题库.md 的附庸）
DOC_FILE_NAMES = {"题库.md", "疑难点.md", "知识点梳理.md", "节点安排.md"}

REPO_ROOT = APP_ROOT.parent  # havefun/app -> havefun

Q_INSERT = (
    "INSERT OR REPLACE INTO questions_index "
    "(file_path, qid, section_title, q_type, stem, options_json, answer_key, "
    "difficulty, tags_json) VALUES (?,?,?,?,?,?,?,?,?)"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_doc_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for name in DOC_FILE_NAMES:
        out.extend(sorted(root.rglob(name)))
    return out


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def index_file(conn: sqlite3.Connection, path: Path, root: Path) -> str:
    """单文件索引：返回 'skip'（哈希未变）或 'index'（已重解析）。"""
    rel = _rel(path, root)
    content_hash = _sha256(path)
    row = conn.execute(
        "SELECT content_hash FROM doc_files WHERE file_path=?", (rel,)
    ).fetchone()
    if row is not None and row["content_hash"] == content_hash:
        # mtime 可能变（Git/IDE），但内容没变——跳过解析
        return "skip"

    n_questions = 0
    if path.name == "题库.md":
        questions = parse_file(path, root)
        key = answer_key_for(path)
        conn.execute("DELETE FROM questions_index WHERE file_path=?", (rel,))
        for q in questions:
            q.answer_key = key.get(q.qid, "")
            conn.execute(Q_INSERT, q.to_row())
        n_questions = len(questions)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO doc_files (file_path, content_hash, last_indexed_at) "
        "VALUES (?,?,?)",
        (rel, content_hash, now),
    )
    return "index" if n_questions or path.name == "题库.md" else "index"


def _purge_missing(conn, root: Path) -> int:
    """清理已删除文件遗留的索引/监控记录，避免僵尸套题出现在列表里。

    索引器原本只增不删：磁盘文件被移除后，questions_index / doc_files 仍保留旧行，
    导致前端能打开到内容缺失的占位套题。这里对比当前受监控文件集合，删除已不存在者。
    """
    live = {_rel(p, root) for p in discover_doc_files(root)}
    gone = [
        r["file_path"]
        for r in conn.execute("SELECT file_path FROM doc_files").fetchall()
        if r["file_path"] not in live
    ]
    for rel in gone:
        conn.execute("DELETE FROM questions_index WHERE file_path=?", (rel,))
        conn.execute("DELETE FROM doc_files WHERE file_path=?", (rel,))
    return len(gone)


def run_index(root: Path = REPO_ROOT, rebuild: bool = False) -> dict:
    init_db()
    conn = connect()
    stats = {"indexed": 0, "skipped": 0, "questions": 0, "purged": 0}
    try:
        if rebuild:
            conn.execute("DELETE FROM questions_index")
            conn.execute("DELETE FROM doc_files")
        for path in discover_doc_files(root):
            result = index_file(conn, path, root)
            if result == "skip":
                stats["skipped"] += 1
            else:
                stats["indexed"] += 1
                if path.name == "题库.md":
                    stats["questions"] += conn.execute(
                        "SELECT count(*) FROM questions_index WHERE file_path=?",
                        (_rel(path, root),),
                    ).fetchone()[0]
        stats["purged"] = _purge_missing(conn, root)
        conn.commit()
    finally:
        conn.close()
    return stats


def print_stats(root: Path = REPO_ROOT) -> None:
    conn = connect()
    try:
        n_doc = conn.execute("SELECT count(*) FROM doc_files").fetchone()[0]
        n_q = conn.execute("SELECT count(*) FROM questions_index").fetchone()[0]
        print(f"doc_files(受监控文档): {n_doc}")
        print(f"questions_index(题目索引): {n_q}")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="复习管理系统 · 文档索引构建器")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="仓库根目录")
    parser.add_argument("--rebuild", action="store_true", help="全量清空重建")
    parser.add_argument("--stats", action="store_true", help="打印计数后退出")
    parser.add_argument("--check", action="store_true", help="干跑，报告将索引/跳过的文件")
    args = parser.parse_args(argv)

    if args.stats:
        print_stats(args.root)
        return 0

    if args.check:
        conn = connect()
        try:
            for path in discover_doc_files(args.root):
                rel = _rel(path, args.root)
                row = conn.execute(
                    "SELECT content_hash FROM doc_files WHERE file_path=?", (rel,)
                ).fetchone()
                cur = _sha256(path)
                state = "skip" if (row and row["content_hash"] == cur) else "index"
                print(f"[{state}] {rel}")
        finally:
            conn.close()
        return 0

    stats = run_index(args.root, rebuild=args.rebuild)
    print(
        f"索引完成：indexed={stats['indexed']} skipped={stats['skipped']} "
        f"questions={stats['questions']}"
        + ("（全量重建）" if args.rebuild else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
