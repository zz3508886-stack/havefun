---
name: anki-apkg
description: 在 havefun 项目（河南护理中专单招复习工程）中生成、修改或调试 Anki .apkg 卡包时使用本 skill。规定 collection.anki2 的 schema 硬性要求（5 张表、7 个索引、apkg v2 的 media 清单）、build_decks.py 的修改检查清单、以及导入前自检脚本。凡涉及 `复习计划/Anki卡组/` 下的 .txt 源文件、build_decks.py、.apkg 产物的增删改，卡组合并打包，笔记模型/字段/标签调整，或遇到 Anki 导入报错（典型如 `no such table: graves`、卡片重复、TTS 按钮消失）时，均应触发本 skill。
---

# Anki 卡包生成规范（anki-apkg）

## Overview

本项目用纯标准库（sqlite3 + zipfile）把 `复习计划/Anki卡组/*.txt` 编译成可直接导入的 `.apkg`，生成器为同目录 `build_decks.py`。本 skill 规定 schema 硬性要求、修改生成器时的检查清单、以及导入前的自检流程，避免重复踩坑。

## 何时使用

- 增删改 `复习计划/Anki卡组/` 下的 `.txt` 源文件或 `build_decks.py`
- 新增卡组、调整笔记模型 / 字段 / 标签 / 牌组合并方式
- 重新生成 `.apkg` 后交付给用户导入
- 用户反馈 Anki 导入报错、卡片重复、发音按钮消失、牌组数量异常

## 硬性规则（不可违反）

1. **collection.anki2 必须包含 5 张表**：`col`、`notes`、`cards`、`revlog`、`graves`。缺 `graves` 会让 Anki 23.10+ 导入时报 `500: DbError ... no such table: graves`。
2. **必须包含 7 个索引**：`ix_notes_usn`、`ix_cards_usn`、`ix_revlog_usn`、`ix_cards_nid`、`ix_cards_sched`、`ix_revlog_cid`、`ix_notes_csum`。
3. **`notes.sfld` 列类型必须是 `integer`**（Anki 官方刻意定义，便于整数字段按数值排序）。
4. **zip 内必须同时含 `collection.anki2` 与 `media`**，`media` 内容为 `{}`（apkg v2 格式的媒体清单，无媒体也要写）。
5. **`col.ver` 写 11**，让 Anki 自行升级到当前 schema；不要手写 18 及以上（那需要 protobuf 构造 decks/notetypes/deck_config/config 等独立表）。
6. **nid 与 cid 必须全局唯一**。合并多个源文件时，每个源文件用独立的 id 前缀（如 `ts + idx * 10_000_000`），否则合并后主键冲突、丢卡。
7. **notes.tags 与模型 id（mid）、牌组 id（did）必须能在 col 行的 JSON 里找到对应定义**，不得出现孤立引用。

完整 SQL 与字段含义见 `references/apkg-schema.md`。

## 修改 build_decks.py 时的检查清单

以下每一条都对应一次真实发生过的故障，改完逐条确认：

1. **`nfields` 按字段列表长度算，不按元组长度算**。`parse_txt` 返回 `(字段列表, 标签列表)` 后，须写 `max(len(item[0]) for item in cards)`；写成 `len(item)` 会恒为 2，导致英语词汇卡从 5 字段 TTS 模型静默降级成 2 字段普通模型（发音按钮消失）。
2. **模型选择依据源文件名，不依据牌组名**。多文件合并到同一牌组后，`deck_name` 已被 alias 改成统一名，用 `src_name = os.path.splitext(os.path.basename(txt_path))[0]` 判断。
3. **新增模型分支时必须同时初始化所有开关变量**（`use_en`、`use_lite`）。漏初始化会在后续 `if use_en:` 处抛 `UnboundLocalError`。
4. **同一文件的多处 replace 必须串行执行**。并行编辑同一文件会互相覆盖，表现为部分修改"报告成功但未落盘"。
5. **合并打包走 `build_data` + `write_apkg` 两段式**，不要在 `build_apkg` 里直接写文件，否则无法把多个源文件并进一个 apkg。
6. **改完 SCHEMA 后必须重新生成全部 apkg**，不要只生成其中一个。

## 交付前自检（必做）

```bash
python3 .codebuddy/skills/anki-apkg/scripts/verify_apkg.py 复习计划/Anki卡组/英语词汇.apkg
```

不带参数则校验目录下全部 `.apkg`。自检通过的标准：表与索引齐全、nid/cid 唯一、无孤立卡片、模型与牌组引用完整、TTS 模型字段数符合预期、标签覆盖率正常。

自检通过后再交付用户导入。若用户导入后仍有问题，先用自检排除产物问题，再排查其 Anki 版本。

## 已知陷阱

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 导入报 `no such table: graves` | schema 缺表 | 见硬性规则 1 |
| 发音按钮消失、卡片变朴素 | TTS 模型被降级 | 见检查清单 1、2 |
| 卡片数比预期少 | 合并时 nid/cid 冲突 | 见硬性规则 6 |
| 导入后出现重复卡片 | 上次失败导入有残留 | 让用户删除旧牌组后重新导入 |
| 某次修改"成功"但文件没变 | 并行编辑同文件 | 见检查清单 4 |

## 相关文件

- 生成器：`复习计划/Anki卡组/build_decks.py`
- 源文件：`复习计划/Anki卡组/*.txt`（制表符分隔，`#` 开头为注释，`# @tag 层级::X 词根::Gnn` 为标签声明）
- 词汇方案与配额：`英语/知识点梳理.md` 第六节
- 自检脚本：`.codebuddy/skills/anki-apkg/scripts/verify_apkg.py`
- schema 参考：`.codebuddy/skills/anki-apkg/references/apkg-schema.md`
