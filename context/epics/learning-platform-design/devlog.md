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
- [2026-10-23] [变更]: 一键启动体系落地：app/start.py 跨平台启动器（Python≥3.11 探测修复 py 启动器对 python3/python.exe 的误判、venv、pip 依赖、前端按需构建/无 Node 降级提示、端口占用检测、探活后开浏览器、Ctrl+C 优雅停止）；双击入口 启动服务.bat（Windows，逐行单命令 if 规避 LF 下括号块与 goto 风险）与 启动服务.sh（macOS/Linux），start.ps1 改为薄包装；app/启动说明.md 普通用户引导；web/ 旧版补双击入口；README 与设计文档同步；.degrade-whitelist 登记 start.py 浏览器兜底
- [2026-10-23] [验证]: py_compile 与 bash -n 全过；manage.py all 0 错误 0 警告；实跑 app/start.py --skip-frontend --no-browser --port 8123：venv 检测→pip 装依赖→uvicorn 启动，/api/health 返回 {"status":"ok","db":"ok"}、首页 200（dist 托管）；未执行：venv 全新创建路径（本机缺 python3.12-venv 的 ensurepip，报错引导按预期呈现，普通用户 python.org 安装包含 venv）；dscan 本轮增量仅 start.py:129（有注释有意降级，已登记白名单）
