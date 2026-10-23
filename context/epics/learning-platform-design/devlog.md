---
dev-loop: devlog
format: v1
epic: learning-platform-design
total-merged: 0
last-merge: none
---

（开发过程日志按行追加：[变更]/[验证]/[note]/[SSOT 修正]；≥5 条自动归并进 memory.md——dev-loop §2）
- [2026-10-23] [验证]: pytest 4 passed（backend）；python -m py_compile 全过；from app.main import app 路由含 /api/health；npm run build exit 0（tsc+vite）；docs-lint 通过；check_docs 全仓通过（0 错误）
- [2026-10-23] [变更]: P0 骨架落地：app/ 前后端分离骨架（FastAPI + Vite/React/TS）、start.ps1 一键启动、SQLite WAL 四表 schema、/api/health 探活 + dist 静态托管；设计文档转 active 并修正数据路径为 app/data/；danzhao-docs 校验器声明 docs/ 与 app/ 例外（SKIP_DIRS）
- [2026-10-23] [验证]: pytest 4 passed（backend）；py_compile 全过；app import 路由含 /api/health；npm run build exit 0（tsc+vite）；docs-lint 通过；check_docs 全仓通过（0 错误）
- [2026-10-23] [变更]: P1 文档解析层+索引构建器落地：parser.py（移植 web/lib.py 正则 + qid 契约：显式ID优先、无ID走 MD5(学科+套题+题干前30字)[:12]、主键(file_path,qid)）；indexer.py（mtime+sha256 双层校验、四类文档入 doc_files 监控、题库.md 落 questions_index、--rebuild 全量兜底、CLI）；design doc P1 标记完成。附带修正：check_docs.py SKIP_DIRS 增 context（dev-loop 过程记忆目录，非复习文档）
- [2026-10-23] [验证]: pytest 12 passed（P1 8 项：qid 显式/兜底/位置无关/答案键/哈希跳过/表格容错/重建/契约）；python -m app.indexer 真实仓库 indexed=24 skipped=24 questions=20；py_compile 全过；docs-lint ✓；check_docs 全部通过（0错误0警告）
