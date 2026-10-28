---
status: active
updated: 2026-10-23
---

# 复习管理系统 · 总体设计

> 代号说明：P0–P8 为实施分期编号，本文含义唯一；R17/R18/R19 为 danzhao-docs 校验器规则号（题库文档禁内联答案 / 套题须有五类错因订正反馈块 / 评估与反馈一致性）；L0/L1/L2 为三层模型层号。

## 定位

本系统是复习文档工程的「手脚」：不替代 AI 的思考，负责把学习结果呈现得更好、把用户反馈收集起来喂给 AI、并给 AI 留出获取数据的途径。AI 的交互与决策留在文档工程（markdown + skills），系统围绕文档运转。

设计原则：

1. 数据按类型各有唯一事实源：**内容数据**（题干、解析、知识点、政策、计划正文）以 markdown 为源，系统只读解析、按标准块回写，不擅自改内容；**过程数据**（答题流水、反馈、打卡、错题复盘）以 SQLite 为源，md 中对应区块是导出视图（见「导出契约」）。
2. 交互流水落 SQLite，汇总后供仪表盘与 AI 取数；内容侧仍按 danzhao-docs 契约回写标准块。
3. AI 取数是一等公民：CLI、只读 API、一页纸快照三种通道常驻。

## 技术选型

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 前端 | React 18 + Vite + TypeScript + antd + TanStack Query | 多模块 SPA；图表用 ECharts |
| 后端 | FastAPI + SQLAlchemy 2.x + Pydantic v2 | 自动 OpenAPI，契约即代码 |
| 数据库 | SQLite（WAL 模式） | 单机单人零运维；备份即拷贝文件 |
| 联调 | 开发期 Vite proxy `/api` → 8000；生产由 FastAPI 托管前端 dist | 不开 CORS，单命令起全栈 |

单机单人场景的显式简化：不做账号体系（表结构预留 `user_id` 备用）、不开 CORS、不上容器。React 的 Node 只是构建链，不常驻服务——编译产物由 Python 托管，省一套运行时运维。

Windows 落地要点：`start.py` 跨平台一键启动器（查找 Python → 建 venv → 装依赖 → 按需构建前端 → 起后端），普通用户双击 `启动服务.bat`（macOS/Linux 用 `启动服务.sh`），`start.ps1` 为兼容薄包装，用户引导见 `app/启动说明.md`；Python ≥ 3.11、Node LTS 20/22，版本由 `requirements.txt` 与 `package-lock.json` 锁定；所有文件读写显式 `utf-8`。

## 三层模型

```mermaid
flowchart TD
    subgraph L0["L0 文档层 markdown —— 内容事实源（过程数据区块为导出视图）"]
        Q["题库.md / 题库解析.md"]
        D["疑难点.md / 错题本"]
        P["知识点梳理.md / 节点安排.md / 政策资讯"]
    end
    subgraph L1["L1 系统层 app/"]
        IDX["解析 + 索引构建器（mtime + hash 双层校验）"]
        UI["React UI：呈现 + 采集反馈"]
        API["FastAPI"]
        DB[("SQLite：内容索引 + 交互流水")]
        WB["回写器：原子写入"]
    end
    subgraph L2["L2 AI 取数通道"]
        CLI["CLI：python -m app ai …"]
        SNAP["data/ai-snapshot.md 一页纸快照"]
        RO["只读 API /api/ai/*（localhost + token）"]
    end
    AI["AI（文档工程 skills）"]
    Q --> IDX --> DB
    P --> IDX
    D --> IDX
    UI --> API --> DB
    API --> WB --> Q
    WB --> D
    WB --> P
    DB --> CLI --> AI
    DB --> SNAP --> AI
    DB --> RO
    AI --> Q
    AI --> D
    IDX -. 哈希变才重建索引 .-> DB
```

反馈回路（系统如何「喂」AI）：

```mermaid
sequenceDiagram
    participant U as 用户
    participant S as 系统
    participant M as markdown 文档
    participant A as AI
    U->>S: 做题 / 打卡 / 点反馈按钮
    S->>S: 客观题即时判分；主观题异步 AI 判分
    S->>M: 回写标准块（内存过检 + 原子替换）
    S->>S: 刷新 ai-snapshot.md
    A->>M: 读文档（skills 直接读写）
    A->>S: CLI / API 取聚合数据
    A->>M: 产出讲解、疑点沉淀、计划校准
```

## 数据所有权划分

| 数据 | 事实源 | 系统职责 |
| --- | --- | --- |
| 题库、解析、知识点、政策、计划内容 | markdown | 只读解析 + 建索引；回写仅限标准块 |
| 答题流水 attempts / 反馈 quiz_feedback | SQLite | 高频追加（一次提交 = 同 batch_id 多行；写 md 会爆炸）；聚合后供仪表盘与 AI 快照 |
| 错题复盘 wrongbook_reviews | SQLite | 复盘登记（结果 + 正确思路要点）；错题本三表由其与流水汇总导出 |
| 打卡记录 plan_checkins | SQLite | 明细入 DB；节点总表「状态」列按 ⬜→🟨→✅ 规则由明细推导导出 |
| 疑难点频次 | `错题本/疑难点.md` | UI 反馈按钮按既有行格式累加，与 auto-discover 共用同一张表（AI 策展内容，维持 md 为源，不在试点范围） |

SQLite 定位分层：对**内容数据**是「索引 + 流水账」——删掉 `app/data/quiz.db` 只需跑一次全量重建，系统原地复活，题目、解析与笔记本体不受任何影响；对**过程数据**（答题流水、反馈、打卡、错题复盘）则是事实源——删库即丢失这些记录，靠关机时拷贝 `app/data/quiz.db` 备份（见「风险与对策」）。

## 关键技术契约

以下四约是「Markdown 事实源」落地为工程代码的地基，P1/P2 实现并配 pytest，先于 UI 与 CLI 完成。

### 题目标识（qid）

attempts 流水绑定 qid，**不绑章节名 + 物理序号**——在文档中间增删题目会导致后续题目的历史全部错位。

- 显式 ID 优先：题库既有题头格式已带 ID（`### 第 N 题（SX-001，选择题，……）`），直接沿用，与 `题库解析.md` 按 ID 对应的答案键映射天然对齐。
- 无显式 ID 时用内容指纹兜底：`MD5(所属学科 + 所属套题 + 题干纯文本前 30 字)[:12]`。
- 全局唯一化：显式 ID 在不同文件间可能重名，索引主键取 `(file_path, qid)`；attempts 侧同样存完整 `file_path + qid`。
- 已知代价：改题干前 30 字（如修 typo）会换指纹、孤立该题历史；显式 ID 题目不受影响，故以显式 ID 为主路径。

### 索引失效校验（mtime + hash 双层）

Windows 下 Git 切分支、IDE 后台格式化都会推 mtime，单纯 mtime 触发会频繁冗余全量解析。

- `mtime` 变化时先算文件 `sha256`，与 `doc_files.content_hash` 比对，**哈希不变则跳过解析**。
- 哈希变或新文件才执行正则切分与索引更新（按文件删旧插新，单事务）；`--rebuild` 提供全量重建兜底。

### 原子回写（写时复制三步法）

Windows 多进程（IDE 自动保存、AI 写入、系统回写）同写一文件，直接覆写会 `PermissionError` 或互相覆盖。回写固定三步：

1. **读前比对**：进入回写任务时记录目标文件哈希；执行前重读比对，不一致判定外部修改，放弃覆盖、转待同步队列并告警。
2. **临时文件 + 内存过检**：新内容写同目录 `.<原名>.tmp`；过检**不跑磁盘上的临时文件**——校验器 R17/R18/R19 按文件名命中，`题库.md.tmp` 这个名字会整体绕过规则。正确做法是 import `check_docs`，以目标文件的仓库相对路径作 `rel`，对内存中的新内容直接跑 `FILE_RULES`。
3. **原子替换**：ERROR 级问题为零才 `os.replace(临时文件, 目标文件)`，瞬时完成，不留半截文件。

另加文件锁兜底并发互斥。

### 判分解耦（主客观状态机）

客观题脚本判分 10ms 级，大模型判分 3–8s 且可能网络异常，两者不可绑在同一流程里阻塞交卷。

- 提交即状态机分流：客观题当场出分写库（`eval_state = done`）；主观题置 `evaluating`，由 FastAPI `BackgroundTasks` 异步判分。
- 前端先渲染客观题结果与得分，主观题位显示「评判中」，轮询到结果后原位更新。
- AI 超时或失败：降级为「待人工复核」（`is_correct = NULL`，`eval_state = pending_manual`），提供重试入口，不阻塞整卷。

## SQLite Schema 参考

四张表对应「只读索引 + 高频流水」职责分离；流水表预留可空 `user_id`，单用户暂不用。

```sql
-- 文档状态监控（防冗余重建）
CREATE TABLE doc_files (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_indexed_at DATETIME NOT NULL
);

-- 题目索引（纯只读缓存，来自 markdown 解析；answer_key 仅服务端可见，不下发前端）
CREATE TABLE questions_index (
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
CREATE TABLE quiz_attempts (
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
CREATE INDEX idx_attempts_qid ON quiz_attempts(qid, created_at);
CREATE INDEX idx_attempts_batch ON quiz_attempts(batch_id);

-- 节点打卡明细（定期汇总回写 节点安排.md 状态列）
CREATE TABLE plan_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,           -- ⬜ / 🟨 / ✅
    notes TEXT,
    user_id INTEGER,                -- 预留，单用户暂空
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## 模块划分

后端按 `app/modules/<模块>/` 分包，每模块 `router + schemas + service`；前端按模块分页面。

| 模块 | 职责 |
| --- | --- |
| quiz | 题型管理、组卷、服务端判分（答案键不下发前端；主客观状态机分流） |
| wrongbook | 错题自动收录、错因标签、1/3/7/15 天到期回顾 |
| plan | 节点计划、打卡、节点总表状态回写 |
| stats | 掌握度 / 薄弱点 / 趋势聚合（供仪表盘与 AI 快照） |
| knowledge | 知识点库 + Anki 卡组索引 |
| policy | 考试大纲、报名时间、志愿信息 |
| ai-access | 跨模块取数：CLI、快照、只读 API |

## AI 取数通道

| 通道 | 形态 | 用途 |
| --- | --- | --- |
| CLI | `python -m app ai summary / weak / pending / recent / doubt / plan`，默认输出 markdown、`--json` 输出机器可读 | IDE 内直接查询，替代手刷多个 md |
| 一页纸快照 | `app/data/ai-snapshot.md`，每次交互后自动刷新 | AI 会话开始读一个文件拿全貌：总量、正确率、薄弱 Top、待复核、疑难点 Top、打卡进度 |
| 只读 API | `/api/ai/*` 同源聚合，localhost + token | 给将来的 AI 客户端预留 |

反向同步：系统监听 markdown 的 mtime，变更经哈希比对确认后重建索引——AI 改了文档，系统无感跟进，不需要 AI 通知系统。

## 回写契约

回写是系统与文档工程之间对**内容侧**的唯一写接口，破坏契约即污染 AI 的输入，故为硬约束：

- **题库.md**：判分结果写入套题章节下的三块——作答记录、订正反馈（R18 要求的五类错因行：概念不清/计算失误/思路错误/审题偏差/知识遗忘）、评估（总体掌握与反馈「是否攻克」保持一致，即 R19）。答案与解析不内联（R17）。`web/lib.py` 的 `write_back` 已是合规样板，移植时保持其块级替换结构。
- **疑难点.md**：严格按既有 8 列行格式（专题/学科/出现次数/首次出现/最近出现/关联问题摘要/对应章节链接/状态）累加。
- **写入前过检**：过检在内存中的新内容上运行校验器规则函数（import `check_docs` 跑 `FILE_RULES`），ERROR 级不过即拒绝写入；规则随仓库演进，系统不复制规则。机制见「关键技术契约 · 原子回写」。
- **写入互斥**：AI 与系统可能同写一文件——按块级分离（AI 写内容块、系统写反馈块）+ 哈希比对 + 文件锁，机制见「关键技术契约 · 原子回写」。

## 导出契约（P9 试点：过程数据 DB 为源）

过程数据在 md 中的区块由系统从 SQLite **全量重生成**（`exporter` 模块），不是回写目标：

- **复习计划/节点安排.md**「一、节点总表」状态列 ← `plan_checkins` 明细推导（最近一次打卡，⬜/🟨/✅，允许复盘修正）；只改状态单元格，其余列与章节冻结。
- **错题本/README.md**「一、错题记录 / 二、按科目统计 / 三、高频错因 TOP」← `quiz_attempts` + `quiz_feedback` + `wrongbook_reviews` 汇总；错因取学生自选（反馈优先、判分兜底），复盘做满 4 次标记「已攻克」，正确思路取复盘要点；使用说明与章节结构冻结。
- **幂等**：内容与 DB 推导一致则不动文件；空库时保持模板原样（零 diff）。
- **冲突语义与回写相反**：外部（AI/手改）对导出区块的修改会被下次导出覆盖——过程数据以 DB 为源即此含义；导出每次读取最新文本后再变换，不做读前哈希比对（`writeback.atomic_replace`）。
- **触发点**：交卷 / 人工复核 / 反馈 / 复盘登记（`POST /api/quiz/wrong/review`）/ 打卡均 best-effort 导出，失败只返回降级标记、不丢流水；也可 CLI 手动重生成：`python -m app export plan|wrongbook|all`。
- **过检与原子替换**同回写器（R14/R17 阻断 + 临时文件 + `os.replace`）。
- **不在试点范围**：`错题本/疑难点.md`（AI 与系统共同累加的策展内容）与 `题库.md` 反馈块（AI 回填 + 系统初判混合），维持回写契约。

## 分期计划

| 期 | 内容 | 验收 |
| --- | --- | --- |
| P0 | 骨架：目录结构、`start.ps1`、FastAPI/Vite 联通、SQLite WAL 建库 | Windows 一键起全栈，health 通 |
| P1 ✅ | 文档解析层 + 索引构建器（移植 `web/lib.py`：qid 契约、mtime+hash 双层校验、全量重建） | 已实现：parser + indexer，单元测试 8 项通过；真实语料 24 文档受监控 / 20 题入索引（标准 `### 第N题` 格式；其余表格草稿形态待补标准格式） |
| P2 ✅ | 测验引擎：服务端判分 + AI 判简答 + R18 回写 + 原子写入 | 已实现：grading（主客观状态机分流）+ writeback（三步法原子回写，内存过检仅阻断 R14/R17）+ quiz 路由（答案键不下发、review 人工复核、错题卷）；29 项 pytest 覆盖判分正确性/冲突降级/过检门/R19 一致性；`web/` 主功能已被替代 |
| P3 ✅ | 错题本联动 + UI 反馈按钮（错因自选、「解析没看懂」→ 疑难点.md 累加） | 已实现：feedback 路由（quiz_feedback 落库 + 疑难点.md 同专题累加）+ GET /wrong 派生错题 + 前端 FeedbackRow/WrongBook；回写含「待复核」⬜ 行保持 R19 一致 |
| P4 ✅ | 复习计划打卡 + 节点状态回写 | 已实现：plan 模块（节点总表解析、plan_checkins 明细、状态=最近一次打卡⬜/🟨/✅、只改状态列原子回写）；13 项 pytest 覆盖解析边界/推导规则/冲突/过检/HTTP 降级；前端「复习计划」页（节点表 + 打卡表单 + 明细） |
| P5 ✅ | 学情仪表盘（ECharts 趋势 + 薄弱点） | 已实现：stats 模块（总览/每日趋势/学科掌握度/薄弱套题+重复错题榜/错因分布，只读聚合不写库；正确率口径=对/(对+错)，待复核不进分母；日期分组转 localtime）；9 项 pytest 以 HTTP 种子对齐聚合数字；前端「学情」页（ECharts 堆叠柱+正确率折线、错因环形图、榜单） |
| P6 ✅ | 资料库 + 政策资讯 | 已实现：mdview 结构化 markdown 读取器（标题树+表格/列表/段落块、R16 文档头 meta 提取）；knowledge 模块（知识点单元索引：四件套齐全度/索引层题型统计/自评标记计数；Anki 卡组索引：txt 卡片数/层级/apkg 对照/stale 过期标记；答案键不下发）；policy 模块（政策文档清单/结构化阅读/关键时间节点/目标院校，路径穿越防护）；前端「资料库」「政策资讯」两页；14 项 pytest 全覆盖 |
| P7 ✅ | AI 取数通道：CLI + 快照 + `/api/ai/*` | 已实现：aggregate.py 聚合层（stats 与 ai 同源，验收「仪表盘=快照」有 pytest 断言）；CLI `python -m app ai summary/weak/pending/recent/doubt/plan/snapshot`（markdown 默认 + `--json` + `--limit`，`app/__main__.py` 兼容两种入口）；一页纸快照 `app/data/ai-snapshot.md`（总量/正确率/薄弱 Top/待复核/疑难点 Top/打卡进度，交卷·反馈·打卡后 best-effort 自动刷新，失败不打断主流程）；只读 API `/api/ai/*`（`config.ai_access_token` 配了才启 Bearer/query 令牌鉴权，本机默认不启用）；11 项 pytest |
| P8 ✅ | `web/` 退役；README 与指导手册同步新结构 | 已完成：能力比对确认 app/ 全覆盖后删除 `web/`（历史流水归档 context/epics/…/web-results-archive.json）；README 目录树补 app//docs/ 条目、指导手册补 5.10 网页系统节并修正「不涉及代码」表述、启动说明删旧版章节改「页面里都能做什么」；main.py 缺 Node 指引页去除 web/ 兜底改 start.py 接口模式；check_docs 全仓通过 |
| P9 ✅ | 过程数据 DB 为源试点：打卡状态列与错题本三表改为导出视图 | 已实现：exporter 模块（`export_plan_status` / `export_wrongbook`，幂等、覆盖外部手改、R14/R17 过检阻断）+ wrongbook_reviews 复盘登记表与 `POST /api/quiz/wrong/review` + 交卷/复核/反馈/打卡 best-effort 触发 + CLI `python -m app export`；同步更新回写契约（新增「导出契约」）、数据所有权划分、study-session/review-coach 的写入约定；test_exporter 18 项 + test_plan 改造，全量 90 项通过 |

## 风险与对策

| 风险 | 对策 |
| --- | --- |
| 回写竞态 / 半截文件（Windows 多进程同写） | 原子回写三步法（哈希比对 + 内存过检 + `os.replace`）；P2 重点测试 |
| 索引与 markdown 不一致 | mtime + sha256 双层校验 + 全量重建兜底 |
| 题目增删导致历史错位 | qid 契约（显式 ID 优先 + 内容指纹兜底）；P1 pytest |
| 校验器规则演进破坏回写 | 调用仓库 `check_docs.py` 本体跑 `FILE_RULES`，不复制规则 |
| 判分逻辑迁移出错 | 判分是唯一「错一步全盘错」的模块，移植必须带 pytest 覆盖 |
| AI 判题失败 | 主客观状态机分流，失败降级为「待人工复核」并可重试 |
| SQLite 数据丢失 | 过程数据（P9 起为事实源）只能靠备份：关机时拷贝 `app/data/quiz.db`，或后端提供 backup 导出端点；内容数据不受影响，跑一次全量重建即可 |

## 与既有 web/ 的关系（已退役，P8）

初版网页刷题服务 `web/`（纯标准库单文件）的能力已全部由本系统覆盖，于 P8 删除：

- 判分/回写逻辑移植进 `grading.py` / `writeback.py`（parser 的 qid 契约同源），并有 76 项 pytest 覆盖；
- `results.json` 流水升级为 SQLite `quiz_attempts`（可聚合、可回放）；
- 仪表盘升级为 stats/ai 双通道；
- 唯一未覆盖项是「零依赖降级启动」（web/ 纯标准库，app/ 需 venv+pip，前端需 Node）——退役后该场景由 `start.py --skip-frontend` 接口模式承接，缺 Node 的引导页已同步改写；
- 历史流水一份已归档至 `context/epics/learning-platform-design/web-results-archive.json`，其余随目录删除。
