# -*- coding: utf-8 -*-
"""
build_decks.py —— 把 Anki卡组/*.txt 直接编译成 .apkg 卡包。
纯标准库实现（sqlite3 + zipfile），无需联网或第三方依赖。

数据源：同目录下每个 .txt 文件（制表符分隔，# 开头为注释）。
  - 两字段：正面 <Tab> 背面（英语单词类两字段：英语高频词/英语单词短语，
      正面挂 TTS 读音——凡"一个单词一张卡"的都发音，词汇方案见
      英语/知识点梳理.md 第六节；词根地图是框架卡，正面是词根符号，不发音）
  - 三字段（英语词汇）：单词+音标 <Tab> 释义 <Tab> 例句（含中文）
      生成时会自动拆出干净单词与纯英文例句，挂上 Anki TTS 标签，
      导入后正面点一下读单词、背面点一下读例句英文（需手机装英文 TTS 语音）。
  - 其他三字段：正面 <Tab> 背面 <Tab> 拓展
输出：同目录下每个 <原名>.apkg，可直接导入 Anki 桌面端 / AnkiDroid / AnkiMobile。

用法：
    python3 build_decks.py
"""
import os
import re
import sqlite3
import zipfile
import hashlib
import random
import string
import time
import json

HERE = os.path.dirname(os.path.abspath(__file__))

# 不同模型用不同 id，避免导入时模型冲突。
MID_2 = 1607392319000          # 两字段：Front, Back
MID_3 = 1607392319005          # 三字段（通用）：Front, Back, Extra
EN_MID = 1607392319010         # 英语单词（带 TTS）：Word, IPA, Back, Example, SentenceEN
ENL_MID = 1607392319020        # 英语衍生词（认识级，带 TTS）：Word, IPA, Back
ENR_MID = 1607392319030        # 认识级单词（带 TTS，无音标）：Word, Back（高频词/短语族用）

DECK_IDS = {
    "护理正常值与概念": 1607392319001,
    "英语词汇": 1607392319002,
    "英语语法": 1607392319003,
    "语文默写与实词": 1607392319004,
    "英语词根地图": 1607392319015,
    "英语衍生词": 1607392319016,
    "英语作文模板": 1607392319017,
    "英语高频词": 1607392319018,
}

DEFAULT_CSS = (
    ".card {\n"
    " font-family: arial;\n"
    " font-size: 20px;\n"
    " text-align: center;\n"
    " color: black;\n"
    " background-color: white;\n"
    "}\n"
    ".ipa { font-size: 18px; color: #2563eb; }\n"
    ".extra { font-size: 16px; color: #444; text-align: left; }\n"
)

LATEX_PRE = (
    "\\documentclass[12pt]{article}\n"
    "\\special{papersize=3in,5in}\n"
    "\\usepackage{amssymb,amsmath}\n"
    "\\pagestyle{empty}\n"
    "\\setlength{\\parindent}{0in}\n"
    "\\begin{document}\n"
)
LATEX_POST = "\\end{document}"


def guid() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=12))


def csum(sfld: str) -> int:
    return int.from_bytes(hashlib.sha1(sfld.encode("utf-8")).digest()[:4], "big")


def build_model(mid: int, fields, qfmt: str, afmt: str, ts: int) -> dict:
    flds = [{"name": name, "ord": i, "sticky": False, "rtl": False,
             "font": "微软雅黑", "size": 20, "description": "",
             "plainText": False, "collapsed": False,
             "excludeFromSearch": False, "id": None}
            for i, name in enumerate(fields)]
    return {
        "id": mid,
        "name": "基础(单词·带发音)" if mid == EN_MID else
                ("基础(衍生词·认识级)" if mid == ENL_MID else
                 ("基础(认识词·带发音)" if mid == ENR_MID else
                  ("基础(单词·三字段)" if len(fields) == 3 else "基础 (havefun)"))),
        "type": 0,
        "mod": ts,
        "usn": -1,
        "sortf": 0,
        "did": None,
        "tmpls": [
            {"name": "正面", "ord": 0, "qfmt": qfmt,
             "afmt": afmt, "bafmt": "", "bqfmt": "",
             "bfont": "微软雅黑", "bsize": 20}
        ],
        "flds": flds,
        "css": DEFAULT_CSS,
        "latexPre": LATEX_PRE,
        "latexPost": LATEX_POST,
        "latexsvg": False,
        "req": [[0, "all", [0]]],
    }


def build_deck(did: int, name: str, ts: int) -> dict:
    return {
        "id": did, "name": name, "desc": "", "usn": -1, "mod": ts,
        "collapsed": False, "browserCollapsed": False,
        "newToday": [0, 0], "revToday": [0, 0], "lrnToday": [0, 0],
        "timeToday": [0, 0], "conf": 1, "extendNew": 0, "extendRev": 0,
        "dyn": 0,
    }


def build_dconf(ts: int) -> dict:
    return {
        "1": {
            "id": 1, "name": "Default", "usn": -1, "mod": ts,
            "maxTaken": 60, "autoplay": True, "timer": 0, "replayq": True,
            "new": {"perDay": 40, "delays": [1, 10], "separate": True,
                    "ints": [1, 4, 7], "initialFactor": 2500,
                    "bury": True, "order": 1, "addToCur": True},
            "rev": {"perDay": 250, "ease4": 1.3, "fuzz": 0.05, "minSpace": 1,
                    "bury": True, "ivlFct": 1, "maxIvl": 36500, "hardFactor": 1.2},
            "lapse": {"leechFails": 8, "minInt": 1, "delays": [10],
                      "leechAction": 0, "mult": 0.0},
            "dyn": False,
        }
    }


def build_conf(did: int, mid: int, ts: int) -> dict:
    return {
        "activeDecks": [did], "curDeck": did, "newSpread": 0,
        "collapseTime": 1200, "timeLim": 0, "estTimes": True, "dueCounts": True,
        "curModel": mid, "nextPos": 1, "sortType": "noteFld",
        "sortBackwards": False, "addToCur": True, "dayLearnFirst": False,
        "dayOffset": 0, "schedVer": 2,
    }


def parse_txt(path: str):
    """解析 txt，返回 [(字段列表, 标签列表), ...]。

    支持在注释行写 ``# @tag 层级::认识级 词根::G07`` 为后续所有卡片打标签，
    直到遇到下一个 @tag 行为止。这样无需改字段结构即可给卡片分类。
    """
    cards = []
    tags = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#"):
                m = re.match(r"#\s*@tag\s+(.+)$", line)
                if m:
                    tags = m.group(1).split()
                continue
            if not line.strip():
                continue
            parts = line.split("\t")
            parts = [p.strip() for p in parts if p.strip() != ""]
            if len(parts) < 2 or not parts[0]:
                continue
            cards.append((parts, list(tags)))
    return cards


def expand_english(cols):
    """把 [单词+音标, 释义, 例句(中英)] 拆成 5 字段，方便挂 TTS。"""
    word_ipa = cols[0]
    meaning = cols[1] if len(cols) > 1 else ""
    example = cols[2] if len(cols) > 2 else ""
    m = re.search(r"/([^/]+)/", word_ipa)
    if m:
        ipa = m.group(1)
        word = word_ipa.replace(m.group(0), "").strip()
    else:
        ipa = ""
        word = word_ipa.strip()
    # 取例句英文部分（首个中文字符之前）
    en = re.split(r"(?=[\u4e00-\u9fff])", example)[0].strip()
    return [word, ipa, meaning, example, en]


def expand_lite(cols):
    """认识级衍生词：把 [单词+音标, 释义｜词根] 拆成 [Word, IPA, Back]。"""
    word_ipa = cols[0]
    meaning = cols[1] if len(cols) > 1 else ""
    m = re.search(r"/([^/]+)/", word_ipa)
    if m:
        ipa = m.group(1)
        word = word_ipa.replace(m.group(0), "").strip()
    else:
        ipa = ""
        word = word_ipa.strip()
    return [word, ipa, meaning]


# 表结构与索引对齐 genanki（APKG_SCHEMA）与 Anki schema11.sql。
# 关键：graves 表与 revlog 表、ix_revlog_usn / ix_cards_sched / ix_revlog_cid 索引
# 缺一不可——Anki 23.10+ 导入时会查询 graves，缺失即报
# 500: DbError ... no such table: graves。notes.sfld 官方定义为 integer（刻意为之）。
SCHEMA = """
        CREATE TABLE col (
            id integer primary key, crt integer not null, mod integer not null,
            scm integer not null, ver integer not null, dty integer not null,
            usn integer not null, ls integer not null, conf text not null,
            models text not null, decks text not null, dconf text not null,
            tags text not null
        );
        CREATE TABLE notes (
            id integer primary key, guid text not null, mid integer not null,
            mod integer not null, usn integer not null, tags text not null,
            flds text not null, sfld integer not null, csum integer not null,
            flags integer not null, data text not null
        );
        CREATE TABLE cards (
            id integer primary key, nid integer not null, did integer not null,
            ord integer not null, mod integer not null, usn integer not null,
            type integer not null, queue integer not null, due integer not null,
            ivl integer not null, factor integer not null, reps integer not null,
            lapses integer not null, left integer not null, odue integer not null,
            odid integer not null, flags integer not null, data text not null
        );
        CREATE TABLE revlog (
            id integer primary key, cid integer not null, usn integer not null,
            ease integer not null, ivl integer not null, lastIvl integer not null,
            factor integer not null, time integer not null, type integer not null
        );
        CREATE TABLE graves (
            usn integer not null, oid integer not null, type integer not null
        );
        CREATE INDEX ix_notes_usn    ON notes   (usn);
        CREATE INDEX ix_cards_usn    ON cards   (usn);
        CREATE INDEX ix_revlog_usn   ON revlog  (usn);
        CREATE INDEX ix_cards_nid    ON cards   (nid);
        CREATE INDEX ix_cards_sched  ON cards   (did, queue, due);
        CREATE INDEX ix_revlog_cid   ON revlog  (cid);
        CREATE INDEX ix_notes_csum   ON notes   (csum);
        """


def build_data(txt_path: str, did: int, deck_name: str, base: int):
    """构建一个源文件的牌组数据（不写文件）。

    返回 (models, decks, notes, cards, dconf, 卡片数, 是否含TTS)，
    其中 notes/cards 是待插入的行元组列表，nid/cid 以 base 为前缀保证全局唯一。
    """
    cards = parse_txt(txt_path)
    if not cards:
        print("跳过（无卡片）:", txt_path)
        return {}, {}, [], [], {}, 0, False

    nfields = max(len(item[0]) for item in cards)

    # 模型选择依据「源文件名」而非牌组名（多个源文件已合并到同一牌组）
    src_name = os.path.splitext(os.path.basename(txt_path))[0]
    # 新增模型分支时必须同时初始化所有开关变量（漏初始化会抛 UnboundLocalError）
    use_en = False
    use_lite = False
    has_tts = False
    if src_name == "英语衍生词" and nfields == 2:
        mid = ENL_MID
        fields = ["Word", "IPA", "Back"]
        qfmt = "{{tts en_US:Word}}<br>{{Word}}<br><span class='ipa'>/{{IPA}}/</span>"
        afmt = "{{FrontSide}}<hr id=answer>{{Back}}"
        use_lite = True
        has_tts = True
        nf = 3
    elif src_name == "英语词汇" and nfields == 3:
        mid = EN_MID
        fields = ["Word", "IPA", "Back", "Example", "SentenceEN"]
        qfmt = "{{tts en_US:Word}}<br>{{Word}}<br><span class='ipa'>/{{IPA}}/</span>"
        afmt = ("{{FrontSide}}<hr id=answer>{{Back}}"
                "<br><br><div class='extra'>{{Example}}</div>"
                "<br>{{tts en_US:SentenceEN}}")
        use_en = True
        has_tts = True
        nf = 5
    elif src_name in ("英语高频词", "英语单词短语") and nfields == 2:
        # 认识级单词：正面单词 + TTS 读音，背面中文/搭配。
        # 只要是"一个单词一张卡"就都该有读音——TTS 由 Anki 用系统语音
        # 本地合成，不占卡包体积，词汇方案见 英语/知识点梳理.md 第六节。
        mid = ENR_MID
        fields = ["Word", "Back"]
        qfmt = "{{tts en_US:Word}}<br>{{Word}}"
        afmt = "{{FrontSide}}<hr id=answer>{{Back}}"
        has_tts = True
        nf = 2
    elif nfields == 2:
        mid = MID_2
        fields = ["Front", "Back"]
        qfmt = "{{Front}}"
        afmt = "{{FrontSide}}<hr id=answer>{{Back}}"
        use_en = False
        nf = 2
    elif nfields == 3:
        mid = MID_3
        fields = ["Front", "Back", "Extra"]
        qfmt = "{{Front}}"
        afmt = "{{FrontSide}}<hr id=answer>{{Back}}<br><br>{{Extra}}"
        use_en = False
        nf = 3
    else:
        nfields = 3
        mid = MID_3
        fields = ["Front", "Back", "Extra"]
        qfmt = "{{Front}}"
        afmt = "{{FrontSide}}<hr id=answer>{{Back}}<br><br>{{Extra}}"
        use_en = False
        nf = 3

    ts_ms = int(time.time() * 1000)
    models = {str(mid): build_model(mid, fields, qfmt, afmt, ts_ms)}
    decks = {str(did): build_deck(did, deck_name, ts_ms)}
    dconf = build_dconf(ts_ms)

    notes, cards_rows = [], []
    for i, item in enumerate(cards, start=1):
        raw, ctags = item
        if use_en:
            vals = expand_english(raw)
        elif use_lite:
            vals = expand_lite(raw)
        else:
            vals = (raw + [""] * nf)[:nf]
        nid = base + i
        cid = base + 1_000_000 + i
        flds = "\x1f".join(vals)
        notes.append((nid, guid(), mid, ts_ms, -1, " ".join(ctags), flds,
                      vals[0], csum(vals[0]), 0, ""))
        cards_rows.append((cid, nid, did, 0, ts_ms, -1,
                           0, 0, i, 0, 0, 0, 0, 0, 0, 0, 0, ""))
    return models, decks, notes, cards_rows, dconf, len(cards), has_tts


def write_apkg(models, decks, notes, cards, dconf, out_path):
    """把合并后的牌组数据写成单个 .apkg 文件。"""
    ts_ms = int(time.time() * 1000)
    ts_s = int(time.time())
    if not notes:
        print("跳过（无卡片）:", out_path)
        return 0
    conf = build_conf(next(iter(decks)), next(iter(models)), ts_ms)

    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    cur.execute(
        "INSERT INTO col VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, ts_s, ts_ms, 1700000000000, 11, 0, 0, 0,
         json.dumps(conf, ensure_ascii=False),
         json.dumps(models, ensure_ascii=False),
         json.dumps(decks, ensure_ascii=False),
         json.dumps(dconf, ensure_ascii=False), "{}"),
    )
    cur.executemany("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)", notes)
    cur.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cards)
    conn.commit()

    tmp_db = out_path + ".tmp.db"
    out = sqlite3.connect(tmp_db)
    conn.backup(out)
    out.close()
    conn.close()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "collection.anki2")
        # apkg v2 要求的媒体清单（本卡组无媒体，写空对象）
        z.writestr("media", "{}")
    os.remove(tmp_db)
    print("生成: %s （%d 张卡）" % (out_path, len(notes)))
    return len(notes)


def build_apkg(txt_path: str, apkg_path: str, did: int, deck_name: str):
    """单源文件 → 单个 apkg（非合并牌组用）。"""
    ts_ms = int(time.time() * 1000)
    models, decks, notes, cards, dconf, count, _ = build_data(
        txt_path, did, deck_name, ts_ms)
    if not notes:
        return 0
    write_apkg(models, decks, notes, cards, dconf, apkg_path)
    return count


def build_merged_apkg(entries, out_path):
    """多个源文件 → 单个 apkg（合并牌组用）。

    entries: [(txt_path, src_name), ...]
    """
    ts = int(time.time() * 1000)
    all_models, all_decks, all_notes, all_cards = {}, {}, [], []
    all_dconf = {}
    total = 0
    for idx, (txt_path, _src) in enumerate(entries):
        # 每个源文件用独立的 nid/cid 前缀，避免合并后主键冲突
        base = ts + idx * 10_000_000
        models, decks, notes, cards, dconf, count, tts = build_data(
            txt_path, MERGED_DECK_ID, MERGED_DECK_NAME, base)
        if not notes:
            continue
        for k, v in models.items():
            all_models.setdefault(k, v)
        for k, v in decks.items():
            all_decks.setdefault(k, v)
        all_notes.extend(notes)
        all_cards.extend(cards)
        if not all_dconf:
            all_dconf = dconf
        total += count
        print("  并入 %-14s %4d 张%s" % (
            os.path.basename(txt_path), count, "（含TTS）" if tts else ""))
    write_apkg(all_models, all_decks, all_notes, all_cards, all_dconf, out_path)
    return total


# 合并打包：这些源文件合成一个 .apkg、一个牌组，卡片用标签区分。
MERGED_SOURCES = ["英语词汇", "英语高频词", "英语衍生词", "英语词根地图", "英语单词短语"]
MERGED_DECK_ID = 1607392319002
MERGED_DECK_NAME = "英语词汇"
MERGED_OUTPUT = "英语词汇.apkg"


def main():
    ts_ms = int(time.time() * 1000)
    total = 0

    # 1) 四个词汇类源文件合并成单个 apkg
    entries = [(os.path.join(HERE, n + ".txt"), n) for n in MERGED_SOURCES]
    entries = [(p, n) for p, n in entries if os.path.exists(p)]
    if entries:
        print("合并打包（%d 个源文件 → %s）：" % (len(entries), MERGED_OUTPUT))
        total += build_merged_apkg(entries, os.path.join(HERE, MERGED_OUTPUT))

    # 2) 其余源文件各自单独打包
    for fn in sorted(os.listdir(HERE)):
        if not fn.endswith(".txt"):
            continue
        name = fn[:-4]
        if name in MERGED_SOURCES:
            continue
        deck_name = name
        did = DECK_IDS.get(deck_name)
        if did is None:
            did = 1607392319000 + abs(hash(deck_name)) % 100000
        txt_path = os.path.join(HERE, fn)
        apkg_path = os.path.join(HERE, name + ".apkg")
        total += build_apkg(txt_path, apkg_path, did, deck_name)

    print("全部完成，共 %d 张卡。" % total)
    print("说明：%s 已把 %s 合并为一个牌组「%s」，导入一次即可，无需切换。" % (
        MERGED_OUTPUT, "、".join(MERGED_SOURCES), MERGED_DECK_NAME))


if __name__ == "__main__":
    main()
