#!/usr/bin/env python3
"""verify_apkg.py —— 交付前自检 .apkg，替代人工逐项检查。

校验项：
  1. zip 内是否同时含 collection.anki2 与 media（media 内容须为合法 JSON）
  2. 5 张表是否齐全（col/notes/cards/revlog/graves）
  3. 7 个索引是否齐全
  4. notes.sfld 列类型是否为 integer
  5. nid / cid 是否全局唯一
  6. 是否存在孤立 cards（nid 不在 notes 中）
  7. notes.mid 是否都能在 col.models 中找到
  8. cards.did 是否都能在 col.decks 中找到
  9. TTS 模型字段数是否符合预期（含 TTS 的模型须有 Word 字段）
 10. 标签覆盖率与牌组/模型摘要

用法：
  python3 verify_apkg.py <文件或目录...>     # 缺省校验 Anki卡组 目录下全部 .apkg

退出码：全部通过为 0，存在 ERROR 为 1。
"""
import json
import os
import sqlite3
import sys
import tempfile
import zipfile

REQUIRED_TABLES = {"col", "notes", "cards", "revlog", "graves"}
REQUIRED_INDEXES = {
    "ix_notes_usn", "ix_cards_usn", "ix_revlog_usn", "ix_cards_nid",
    "ix_cards_sched", "ix_revlog_cid", "ix_notes_csum",
}
# 已知 TTS 模型及其预期字段数（须与 build_decks.py 中的 MID_* 保持一致）：
#   掌握级单词 5 字段（Word/IPA/Back/Example/SentenceEN）
#   衍生词     3 字段（Word/IPA/Back）
#   认识级单词 2 字段（Word/Back）——高频词/短语族，源文件无音标，读音只挂正面
EXPECTED_TTS_MODELS = {
    1607392319010: 5,
    1607392319020: 3,
    1607392319030: 2,
}

errors, warnings = [], []


def err(path, msg):
    errors.append("%s: %s" % (path, msg))


def warn(path, msg):
    warnings.append("%s: %s" % (path, msg))


def verify(path):
    name = os.path.basename(path)
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        err(name, "无法打开 zip：%s" % e)
        return

    names = z.namelist()
    if "collection.anki2" not in names:
        err(name, "zip 内缺少 collection.anki2")
        return
    if "media" not in names:
        err(name, "zip 内缺少 media 清单（apkg v2 要求，无媒体也应写 {}）")
    else:
        try:
            json.loads(z.read("media").decode("utf-8"))
        except Exception as e:
            err(name, "media 不是合法 JSON：%s" % e)

    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        tf.write(z.read("collection.anki2"))
        tf.close()
        c = sqlite3.connect(tf.name)

        tables = {r[0] for r in c.execute(
            "select name from sqlite_master where type='table'")}
        missing_tables = REQUIRED_TABLES - tables
        if missing_tables:
            err(name, "缺少表：%s（缺 graves 会导致 Anki 23.10+ 导入报 "
                      "no such table: graves）" % sorted(missing_tables))

        idx = {r[0] for r in c.execute(
            "select name from sqlite_master where type='index' "
            "and name not like 'sqlite_%'")}
        missing_idx = REQUIRED_INDEXES - idx
        if missing_idx:
            err(name, "缺少索引：%s" % sorted(missing_idx))

        # sfld 列类型
        try:
            col_type = c.execute(
                "select type from pragma_table_info('notes') where name='sfld'"
            ).fetchone()[0]
            if col_type.lower() != "integer":
                err(name, "notes.sfld 列类型为 %s，应为 integer" % col_type)
        except Exception as e:
            err(name, "无法读取 notes.sfld 列类型：%s" % e)

        # id 唯一性：notes.id 与 cards.id 由主键保证；
        # cards.nid 本就允许多张卡片共用同一笔记（一笔记多卡），不做唯一性检查
        for tbl, col in (("notes", "id"), ("cards", "id")):
            total = c.execute("select count(%s) from %s" % (col, tbl)).fetchone()[0]
            uniq = c.execute(
                "select count(distinct %s) from %s" % (col, tbl)).fetchone()[0]
            if total != uniq:
                err(name, "%s.%s 不唯一：%d 行 / %d 个不同值（合并时 id 前缀冲突）"
                    % (tbl, col, total, uniq))

        # 孤立 cards：nid 在 notes 中不存在
        orphan = c.execute(
            "select count(*) from cards where nid not in (select id from notes)"
        ).fetchone()[0]
        if orphan:
            err(name, "存在 %d 张孤立卡片（nid 在 notes 中不存在）" % orphan)

        # 孤立 notes：有笔记但没有任何卡片
        orphan_notes = c.execute(
            "select count(*) from notes where id not in (select nid from cards)"
        ).fetchone()[0]
        if orphan_notes:
            err(name, "存在 %d 条笔记没有任何卡片" % orphan_notes)

        # 一笔记多卡提示（本项目约定一笔记一卡，多卡说明该模型有多套模板）
        multi = c.execute(
            "select count(*) from (select nid from cards group by nid "
            "having count(*)>1)").fetchone()[0]
        if multi:
            warn(name, "%d 条笔记对应多张卡片（多模板模型），确认是否符合预期" % multi)

        # col JSON 引用完整性
        try:
            row = c.execute(
                "select conf, models, decks, dconf, ver from col").fetchone()
            if row is None:
                err(name, "col 表无数据行")
            else:
                models = json.loads(row[1] or "{}")
                decks = json.loads(row[2] or "{}")
                bad_mid = c.execute(
                    "select count(*) from notes where mid not in (%s)"
                    % ",".join(str(int(k)) for k in models) if models else "0"
                ).fetchone()[0] if models else c.execute(
                    "select count(*) from notes").fetchone()[0]
                if models and bad_mid:
                    err(name, "%d 条笔记的 mid 在 col.models 中无定义" % bad_mid)
                if not models:
                    err(name, "col.models 为空")
                if not decks:
                    err(name, "col.decks 为空")
                ver = row[4]
                if ver not in (11,):
                    warn(name, "col.ver=%s，本项目约定写 11 让 Anki 自行升级" % ver)

                # TTS 模型字段数
                for mid, m in models.items():
                    flds = [f["name"] for f in m.get("flds", [])]
                    has_tts = "{{tts" in json.dumps(
                        m.get("tmpls", []), ensure_ascii=False)
                    if has_tts and "Word" not in flds:
                        err(name, "模型 %s（%s）含 TTS 标签但没有 Word 字段"
                            % (mid, m.get("name")))
                    if has_tts and int(mid) in EXPECTED_TTS_MODELS:
                        expected = EXPECTED_TTS_MODELS[int(mid)]
                        if len(flds) != expected:
                            err(name, "模型 %s（%s）含 TTS 但字段数为 %d，预期 %d"
                                % (mid, m.get("name"), len(flds), expected))
                    elif has_tts:
                        warn(name, "模型 %s（%s）含 TTS 但不在 EXPECTED_TTS_MODELS "
                                   "白名单中，请确认其字段数符合设计"
                                   % (mid, m.get("name")))

                # 摘要
                n_notes = c.execute("select count(*) from notes").fetchone()[0]
                n_cards = c.execute("select count(*) from cards").fetchone()[0]
                n_tagged = c.execute(
                    "select count(*) from notes where tags<>''").fetchone()[0]
                deck_names = [d.get("name") for d in decks.values()]
                model_names = [m.get("name") for m in models.values()]
                print("  %-22s %5d 卡 / 牌组 %s / 模型 %s"
                      % (name, n_notes, deck_names, model_names))
                if n_notes != n_cards:
                    warn(name, "notes(%d) 与 cards(%d) 数量不一致"
                         % (n_notes, n_cards))
                if n_notes and n_tagged < n_notes * 0.9:
                    warn(name, "仅 %d/%d 张卡带标签，检查 @tag 注释是否遗漏"
                         % (n_tagged, n_notes))
        except Exception as e:
            err(name, "解析 col JSON 失败：%s" % e)
        finally:
            c.close()
    finally:
        os.unlink(tf.name)


def main():
    args = sys.argv[1:]
    if not args:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                            "复习计划", "Anki卡组")
        base = os.path.abspath(base)
        if not os.path.isdir(base):
            print("未找到默认目录：%s" % base)
            return 1
        args = [os.path.join(base, f) for f in sorted(os.listdir(base))
                if f.endswith(".apkg")]

    targets = []
    for a in args:
        if os.path.isdir(a):
            targets += [os.path.join(a, f) for f in sorted(os.listdir(a))
                        if f.endswith(".apkg")]
        else:
            targets.append(a)

    print("自检 %d 个 .apkg：" % len(targets))
    for t in targets:
        verify(t)

    print()
    for w in warnings:
        print("[WARN]", w)
    for e in errors:
        print("[ERROR]", e)
    print()
    if errors:
        print("结果：%d 个错误，%d 个警告 —— 不可交付" % (len(errors), len(warnings)))
        return 1
    print("结果：全部通过（%d 个警告）" % len(warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
