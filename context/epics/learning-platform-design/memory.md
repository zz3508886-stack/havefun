---
dev-loop: memory
format: v1
epic: learning-platform-design
total-merged: 0
last-merge: none
---

# learning-platform-design

- [挂载] docs/architecture/learning-platform-design.md

## 状态
- [完成] P0–P8 全部完成（2026-10-23 ~ 10-24）：骨架/解析索引/测验引擎/反馈错题本/计划打卡/学情仪表盘/资料库政策/AI 取数通道/web 退役；76 项 pytest 全过，check_docs 全绿。web/ 已删，历史流水归档 context/epics/learning-platform-design/web-results-archive.json

## 断点
- [断点] 史诗完成，无进行中任务。后续可选增强（未排期）：AI 判分真实端点实现（ai_grader 契约已留）、stats 前端补「打卡热力图」、错题本 1/3/7/15 到期提醒推送

## 约定
- [约定] AI 取数三通道同源：CLI（python -m app ai …）/ 快照（app/data/ai-snapshot.md，交互后 best-effort 刷新）/ API（/api/ai/*）全部走 aggregate.py；stats 路由是 aggregate 的薄封装——改口径只改 aggregate 一处
- [约定] 前端布局：侧边栏=模块主导航（Menu 六项，折叠成图标 persisted 'sider-collapsed'）；套题树只在做题模块内（QuizModule 页内 Sider，persisted 'quiz-tree-collapsed'）；跨模块启动做题的状态（set/resp/wrongPaper）提升在 App.tsx——加新模块就在 MODULES 数组加一项 + Content 加一个分支
- [约定] mdview：文档头 meta 只取首个「项目/内容」表；正文同形表（如考试基本信息）是正常内容块；mastery 计数排除 META_ROW_RE 行（状态行的 🟨 不是自评标记）
- [约定] stats 口径：正确率 = 对/(对+错)，待复核（is_correct NULL）不进分母；日期分组一律 strftime localtime（SQLite CURRENT_TIMESTAMP 是 UTC）；学科 = file_path 顶层目录
- [约定] 节点状态规则：节点总表状态列 = 该节点最近一次打卡状态（⬜/🟨/✅），允许复盘修正（✅ 后可改回 🟨）；plan.py 的 write_node_status 只替换目标行末列，其余逐字冻结
- [约定] 回写「订正反馈」块时：有 pending_manual 题目必须带「待复核」⬜ 行，否则 R19 告警（反馈全 🟢 vs 评估 🟨）
- [约定] check_docs.py 已登记 SKIP_FILES={.degrade-whitelist}（有意降级登记簿，非文档）；回写内存过检仅阻断 R14/R17，其余 ERROR 告警不阻断
- [教训] 外部 AI skills 新增题库后，R11（README 目录树）与 R14（英文词自动登记待确认）会集中爆——每轮验证前先跑 manage.py all，R14 候选按 !词=>原因 约定批量确认；README 树随新四件套同步补登
