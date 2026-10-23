# Anki .apkg / collection.anki2 结构参考

本文件记录生成 `.apkg` 所需的权威 schema 与格式约定，来源为 Anki 官方仓库 `rslib/src/storage/schema11.sql` 与 genanki 的 `APKG_SCHEMA`（两者一致，且 genanki 产物可被新版 Anki 正常导入）。

## 一、.apkg 文件构成

`.apkg` 是一个 zip，至少含两个条目：

| 条目 | 说明 |
| --- | --- |
| `collection.anki2` | SQLite 数据库，核心数据 |
| `media` | JSON 文本，媒体清单。键为 zip 内的数字文件名，值为原始媒体名；无媒体时写 `{}` |

缺 `media` 时部分 Anki 版本会解析异常，因此即使无媒体也要写。

## 二、完整 schema（5 张表 + 7 个索引）

```sql
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
```

### 关键说明

- **`notes.sfld` 官方定义为 `integer`**，注释原文：「The use of type integer for sfld is deliberate, because it means that integer values in this field will sort numerically.」实际仍可存文本（SQLite 动态类型），但列类型必须写 integer。
- **`graves` 无主键列**，字段顺序为 `usn, oid, type`。它是删除记录表，Anki 23.10+ 导入时会查询，缺失即报 `no such table: graves`。
- **`revlog` 允许为空表**（无复习历史时）。

## 三、col 行的四个 JSON 字段

`col` 只有一行，其中 `conf`、`models`、`decks`、`dconf` 是 JSON 文本：

| 字段 | 内容 |
| --- | --- |
| `conf` | 集合配置：`activeDecks`、`curDeck`、`curModel`、`newSpread`、`schedVer` 等 |
| `models` | 笔记类型字典，键为 mid 字符串；含 `name`、`flds`（字段名与 ord）、`tmpls`（qfmt/afmt）、`css`、`req` |
| `decks` | 牌组字典，键为 did 字符串；含 `name`、`conf`、`dyn` 等 |
| `dconf` | 牌组配置字典，含 `new.perDay`、`rev.perDay`、`lapse` 等 |

`schedVer` 写 `1`（v2 调度器）或 `2`（v3）。本项目写 2。

## 四、cards 关键字段取值

| 字段 | 新卡导入时的值 | 含义 |
| --- | --- | --- |
| `type` | 0 | 0 新卡 / 1 学习中 / 2 复习中 |
| `queue` | 0 | 0 新卡 / 1 学习中 / 2 复习中 / 3 搁置 |
| `due` | 递增整数 | 新卡出现的先后次序 |
| `ivl` `factor` `reps` `lapses` `left` | 0 | 无历史 |
| `ord` | 0 | 卡片模板序号 |

## 五、notes 关键字段

| 字段 | 说明 |
| --- | --- |
| `flds` | 各字段用 `\x1f` 连接 |
| `sfld` | 排序字段，取第一个字段值 |
| `csum` | 第一个字段的 sha1 前 4 字节转整数 |
| `tags` | 空格分隔的标签串，如 `层级::认识级 词根::G07` |
| `mid` | 所属笔记类型 id，必须在 `models` 中有定义 |

## 六、本项目约定的 id 分配

| id | 用途 |
| --- | --- |
| 1607392319000 | 两字段通用模型 MID_2 |
| 1607392319005 | 三字段通用模型 MID_3 |
| 1607392319010 | 英语核心词模型（5 字段，含 TTS） |
| 1607392319020 | 英语衍生词模型（3 字段，含 TTS） |
| 1607392319001–9004 | 护理正常值、英语词汇、英语语法、语文默写 |
| 1607392319002 | 合并牌组「英语词汇」的 did（5 个词汇类源文件共用） |
| 1607392319015–9018 | 词根地图、衍生词、作文模板、高频词（现已并入 9002） |
| nid/cid 前缀 | `ts_ms + idx * 10_000_000`，idx 为源文件序号 |

合并打包时多个源文件共用同一个 did，因此 did 相同是预期行为；nid/cid 必须靠前缀区分。
