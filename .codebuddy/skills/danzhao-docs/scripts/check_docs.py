"""文档规范校验器：对仓库内 Markdown 文档执行 danzhao-docs SKILL.md 定义的格式约定。

用法:
    python check_docs.py [路径...]      # 校验指定文件或目录，默认为整个仓库
    python check_docs.py --list         # 列出全部规则

退出码: 存在 ERROR 返回 1，否则返回 0。
输出格式面向 AI：每条问题含文件、行号、规则编号、说明与修复建议。
R14 黑话检测：命中黑话词表报 ERROR；新发现的疑似黑话（如拼音缩写型新梗）会自动登记到
scripts/data/slang-words.txt（替换词记为「待确认」，WARN），需人工确认后补替换词或改为「!词=>原因」忽略。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import Issue, SEVERITY_ERROR, SEVERITY_WARN, configure_utf8_output, print_report

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
REPO_ROOT = SKILL_DIR.parents[2]
FACTS_FILE = SKILL_DIR / "references" / "project-facts.md"
WORDS_FILE = SCRIPTS_DIR / "data" / "colloquial-words.txt"
SLANG_WORDS_FILE = SCRIPTS_DIR / "data" / "slang-words.txt"
SLANG_PENDING = "待确认"
SLANG_IGNORE_PREFIX = "!"
SLANG_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])[a-z]{2,6}(?![A-Za-z0-9])")
SLANG_IGNORE_WORDS = {"vs", "etc", "eg", "ie", "aka", "emoji", "pdf", "docx", "app", "wifi"}

SKIP_DIRS = {".git", ".codebuddy", "web"}
PLACEHOLDERS = ("待填写", "待添加", "待补充")
EMOJI_WHITELIST = {"⬜", "🟨", "✅", "🔴", "🟢", "⚠"}
EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x2B00, 0x2BFF))
EMPTY_ROW_EXEMPT = {"复习计划/总复习计划.md"}
POLICY_DIR = "政策资讯"
CATEGORY_DOC_NAMES = {"知识点梳理.md", "题库.md"}
MIN_CATEGORY_SECTIONS = 2
DOC_HEADER_FIELDS = ("状态", "创建时间", "学科", "分类")
CODE_TOKEN_RE = re.compile(r"\b([A-Z]{2})(?:-[A-Z0-9]+)+\b")
TREE_LINE_RE = re.compile(r"^((?:│   |    )*)(├── |└── )(.*)$")
SEPARATOR_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
READABILITY_DOC_NAMES = {"知识点梳理.md", "题库解析.md"}
LONG_SENTENCE_LIMIT = 60
SENTENCE_SPLIT_RE = re.compile(r"[。！？；]")
CONTENT_CHAR_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

RULES = [
    {"id": "R01", "name": "书面语检查", "severity": SEVERITY_ERROR,
     "desc": "文档中不得出现口语化词汇（口水词），词表见 scripts/data/colloquial-words.txt",
     "fix": "按词表中的替换建议改为书面表达"},
    {"id": "R02", "name": "文件类型", "severity": SEVERITY_ERROR,
     "desc": "仓库内（.git、.codebuddy 除外）只允许 .md 文档与 .gitignore",
     "fix": "删除该文件，或将其内容整理进 Markdown 文档"},
    {"id": "R03", "name": "标题与文件名一致", "severity": SEVERITY_ERROR,
     "desc": "非 README 文档的 H1 须以文件名主体结尾；目录 README 的 H1 须等于目录名；根 README 豁免",
     "fix": "将第一行改为与文件名对应的标题"},
    {"id": "R04", "name": "政策来源提示", "severity": SEVERITY_ERROR,
     "desc": "政策资讯/ 下的文档须在开头包含 ⚠️ 官方来源提示",
     "fix": "在 H1 之后添加 ⚠️ 提示，注明以官方简章为准"},
    {"id": "R05", "name": "表情符号白名单", "severity": SEVERITY_ERROR,
     "desc": "只允许使用约定标记 ⬜ 🟨 ✅ 🔴 🟢 ⚠️",
     "fix": "删除该表情，或改用约定标记"},
    {"id": "R06", "name": "表格占位符", "severity": SEVERITY_ERROR,
     "desc": "表格行不允许整行无占位符的空白单元格，每个模板行至少含一个占位符（复习计划日程表除外）",
     "fix": "在空白单元格填写 待填写 / 待添加 / 待补充"},
    {"id": "R07", "name": "表格分隔行", "severity": SEVERITY_ERROR,
     "desc": "每个表格的第二行必须是 | --- | 形式的分隔行",
     "fix": "在表头后补一行 | --- | --- |"},
    {"id": "R08", "name": "相对链接有效", "severity": SEVERITY_ERROR,
     "desc": "Markdown 链接指向的本地文件必须存在",
     "fix": "修正链接路径或创建目标文件"},
    {"id": "R09", "name": "章节编号", "severity": SEVERITY_ERROR,
     "desc": "非 README 文档的二级标题须为「## 一、」形式（README 除外）",
     "fix": "将 ## 标题改为中文数字编号"},
    {"id": "R10", "name": "编号前缀合法", "severity": SEVERITY_ERROR,
     "desc": "题库/错题本条目编号的前缀须登记在 references/project-facts.md 的前缀表中",
     "fix": "改用已登记前缀，或先在前缀表中登记新科目"},
    {"id": "R11", "name": "README 目录同步", "severity": SEVERITY_ERROR,
     "desc": "README.md 目录树须与实际文件一一对应",
     "fix": "在 README.md 目录树补充缺失文件，或删除不存在的条目"},
    {"id": "R12", "name": "标题层级", "severity": SEVERITY_WARN,
     "desc": "标题层级不得跳级（H1→H2→H3）",
     "fix": "补齐缺失的标题层级"},
    {"id": "R13", "name": "表格列数一致", "severity": SEVERITY_WARN,
     "desc": "同一表格各行列数应一致",
     "fix": "补齐缺失单元格"},
    {"id": "R14", "name": "黑话检测", "severity": SEVERITY_ERROR,
     "desc": "文档中不得出现网络黑话、梗、谐音用语及职场黑话，词表见 scripts/data/slang-words.txt",
     "fix": "按词表中的替换建议改为书面表达；疑似黑话会自动登记，需人工确认"},
    {"id": "R15", "name": "分类存放", "severity": SEVERITY_ERROR,
     "desc": "知识点梳理.md 与题库.md 须按分类组织内容：至少包含 2 个二级分类章节，且每个分类章节下须有内容，不允许存在空分类",
     "fix": "按章节/题型等维度建立分类章节，将内容归入对应分类；删除空分类章节"},
    {"id": "R16", "name": "文档头元数据", "severity": SEVERITY_ERROR,
     "desc": "非 README 的内容文档须在标题下方紧接文档头，含 状态、创建时间、学科、分类 四项元数据，便于检查与维护",
     "fix": "在标题后插入文档头表格，补齐 状态 / 创建时间 / 学科 / 分类 四行"},
    {"id": "R17", "name": "习题解析分文档", "severity": SEVERITY_ERROR,
     "desc": "题库类文档（题库.md）只收录题干，不得内联答案/解析标记，答案与详细解析须归入同名解析文档（如 题库解析.md）",
     "fix": "将内联的 **答案** / **解析** 内容迁移到同名解析文档，题库文档仅保留题干"},
    {"id": "R18", "name": "套题订正反馈", "severity": SEVERITY_ERROR,
     "desc": "题库.md 中每套含题目的试题（二级标题含 测验/专项/模拟卷/真题/自测 且该章节内含 ### 第 N 题）下方须有「### 订正反馈（套题名）」块，且块内表格须含 概念不清/计算失误/思路错误/审题偏差/知识遗忘 五类错因行",
     "fix": "在对应套题章节内添加订正反馈块，含上述 5 类错因行（模板见 danzhao-docs SKILL.md「套题订正反馈模板」）"},
    {"id": "R19", "name": "评估一致性", "severity": SEVERITY_WARN,
     "desc": "题库.md 中若某套题同时存在「### 订正反馈」与「### 评估」块，评估的「总体掌握」须与反馈的「是否攻克」一致：反馈全行 🟢 时总体掌握应标 ✅/🟢，否则不应标 ✅；评估结论含「验证未过」时跳过该检查（用户自评与验证结果不一致属预期）",
     "fix": "对齐评估「总体掌握」与订正反馈的「是否攻克」列"},
]


def iter_md_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path, rel.as_posix()


def iter_all_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path, rel.as_posix()


def strip_inline_code(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)


def iter_content_lines(lines):
    """逐行产出 (行号, 原始行)，跳过 ``` 代码块内部的行。"""
    in_fence = False
    for lineno, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield lineno, raw


def find_word_hits(line: str, words) -> list:
    """返回行内词命中 [(位置, 词)]，按位置排序，跳过被更长命中覆盖的词。

    纯 ASCII 词条（如 ky、emo）按整词匹配，避免误伤 keyword、emoji 等词；
    中文词条按子串匹配；同一行内同一词条的每次出现都会命中。
    """
    matches = []
    for word in words:
        if word.isascii():
            token_re = re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])")
            for match in token_re.finditer(line):
                matches.append((match.start(), word))
        else:
            start = line.find(word)
            while start >= 0:
                matches.append((start, word))
                start = line.find(word, start + 1)
    matches.sort(key=lambda item: (item[0], -len(item[1])))
    occupied = []
    hits = []
    for pos, word in matches:
        end = pos + len(word)
        if any(pos < taken_end and taken_start < end for taken_start, taken_end in occupied):
            continue
        occupied.append((pos, end))
        hits.append((pos, word))
    return hits


def load_slang_words(path: Path = None):
    """加载黑话词表，返回 (替换表, 忽略集)。

    格式：词=>替换词；替换词为「待确认」表示待人工确认；
    「!词=>原因」表示确认该词非黑话，后续忽略。
    """
    path = path or SLANG_WORDS_FILE
    words, ignored = {}, set()
    if not path.exists():
        return words, ignored
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        word, _, repl = line.partition("=>")
        word, repl = word.strip(), repl.strip()
        if word.startswith(SLANG_IGNORE_PREFIX):
            ignored.add(word[len(SLANG_IGNORE_PREFIX):].strip())
        elif word:
            words[word] = repl
    return words, ignored


def register_new_slang(candidates: dict, words: dict, ignored: set, path: Path = None) -> dict:
    """把新发现的疑似黑话追加进黑话词表（替换词记为待确认），返回本次新登记的 {词: 首现位置}。"""
    path = path or SLANG_WORDS_FILE
    new = {
        word: loc for word, loc in candidates.items()
        if word not in words and word not in ignored and word not in SLANG_IGNORE_WORDS
    }
    if not new:
        return new
    header = (
        "# 黑话词表：文档中不得出现的网络用语、梗、谐音黑话及职场黑话\n"
        "# 格式：词=>替换词；替换词为「待确认」表示待人工确认；!词=>原因 表示确认忽略\n"
        "# 自检时 check_docs.py 会自动追加新发现的疑似黑话（替换词记为待确认）\n"
    )
    text = path.read_text(encoding="utf-8") if path.exists() else header
    if not text.endswith("\n"):
        text += "\n"
    addition = "".join(f"{word}=>{SLANG_PENDING}\n" for word in sorted(new))
    path.write_text(text + addition, encoding="utf-8")
    return new


def load_colloquial_words() -> dict:
    words = {}
    if not WORDS_FILE.exists():
        return words
    for raw in WORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        word, _, repl = line.partition("=>")
        words[word.strip()] = repl.strip()
    return words


def load_prefixes() -> set:
    prefixes = set()
    if not FACTS_FILE.exists():
        return prefixes
    for line in FACTS_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*([A-Z]{2})\s*\|", line)
        if match:
            prefixes.add(match.group(1))
    return prefixes


def iter_table_blocks(lines):
    block = []
    start = 0
    for idx, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith("|"):
            if not block:
                start = idx
            block.append((idx, raw))
        else:
            if block:
                yield start, block
            block = []
    if block:
        yield start, block


def parse_readme_tree(text: str) -> set:
    """解析 README.md 中的目录树代码块，返回其中登记的 .md 文件路径集合。"""
    paths = set()
    stack = {}
    in_fence = False
    for raw in text.splitlines():
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        match = TREE_LINE_RE.match(raw)
        if not match:
            continue
        depth = len(match.group(1)) // 4
        name = match.group(3).split("#")[0].strip()
        if not name:
            continue
        if name.endswith("/"):
            parent = stack.get(depth - 1, "")
            stack[depth] = parent + name
            for level in [level for level in stack if level > depth]:
                del stack[level]
            continue
        parent = stack.get(depth - 1, "")
        paths.add(parent + name)
    return paths


def rule_r01_colloquial(rel, lines, ctx):
    words = ctx["words"]
    if not words:
        return []
    issues = []
    for lineno, raw in iter_content_lines(lines):
        line = strip_inline_code(raw)
        for _, word in find_word_hits(line, words):
            issues.append(Issue(
                SEVERITY_ERROR, rel, lineno, "R01", "书面语检查",
                f"出现口语化词汇「{word}」",
                f"改为「{words[word]}」"))
    return issues


def rule_r02_file_types(root, ctx):
    issues = []
    for path, rel in iter_all_files(root):
        if path.suffix == ".md" or path.name == ".gitignore":
            continue
        issues.append(Issue(
            SEVERITY_ERROR, rel, 0, "R02", "文件类型",
            f"存在非文档文件（{path.suffix or '无扩展名'}）",
            "删除该文件，或将其内容整理进 Markdown 文档"))
    return issues


def rule_r03_title(rel, lines, ctx):
    if not lines:
        return []
    title = lines[0][2:].strip() if lines[0].startswith("# ") else ""
    name = Path(rel).name
    if name == "README.md":
        parent = Path(rel).parent
        if parent == Path("."):
            return []
        expected = parent.name
        if title != expected:
            return [Issue(SEVERITY_ERROR, rel, 1, "R03", "标题与文件名一致",
                          f"H1「{title}」与目录名「{expected}」不一致",
                          f"改为「# {expected}」")]
        return []
    stem = Path(rel).stem
    if not title.endswith(stem):
        return [Issue(SEVERITY_ERROR, rel, 1, "R03", "标题与文件名一致",
                      f"H1「{title}」未以文件名主体「{stem}」结尾",
                      f"将第一行改为以「{stem}」结尾的标题")]
    return []


def rule_r04_policy(rel, lines, ctx):
    if not rel.startswith(POLICY_DIR + "/"):
        return []
    head = "\n".join(lines[:15])
    if "⚠" in head and "官方" in head:
        return []
    return [Issue(
        SEVERITY_ERROR, rel, 1, "R04", "政策来源提示",
        "缺少官方来源提示",
        "在 H1 之后添加:\n> ⚠️ 以下内容需以当年河南省教育考试院 / 目标院校官方发布的单独招生简章与考试大纲为准。")]


def rule_r05_emoji(rel, lines, ctx):
    issues = []
    in_fence = False
    for lineno, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for char in strip_inline_code(raw):
            code = ord(char)
            if code == 0xFE0F or char in EMOJI_WHITELIST:
                continue
            if any(low <= code <= high for low, high in EMOJI_RANGES):
                issues.append(Issue(
                    SEVERITY_ERROR, rel, lineno, "R05", "表情符号白名单",
                    f"出现非约定表情「{char}」",
                    "删除该表情，或改用约定标记 ⬜/🟨/✅/🔴/🟢/⚠️"))
    return issues


def rule_r06_placeholder(rel, lines, ctx):
    if rel in EMPTY_ROW_EXEMPT:
        return []
    issues = []
    for _, block in iter_table_blocks(lines):
        for idx, raw in block[2:]:
            cells = raw.strip().strip("|").split("|")
            if not any(cell.strip() == "" for cell in cells):
                continue
            if any(token in raw for token in PLACEHOLDERS):
                continue
            issues.append(Issue(
                SEVERITY_ERROR, rel, idx, "R06", "表格占位符",
                "表格行存在空白单元格且整行无占位符",
                "在空白单元格填写 待填写 / 待添加 / 待补充"))
    return issues


def rule_r07_separator(rel, lines, ctx):
    issues = []
    for _, block in iter_table_blocks(lines):
        if len(block) < 2:
            continue
        separator = block[1][1]
        if "---" not in separator or not SEPARATOR_RE.match(separator):
            issues.append(Issue(
                SEVERITY_ERROR, rel, block[1][0], "R07", "表格分隔行",
                "表格第二行不是 | --- | 形式的分隔行",
                "在表头后补一行 | --- | --- |"))
    return issues


def rule_r08_links(rel, lines, ctx):
    issues = []
    base = ctx["root"] / Path(rel).parent
    in_fence = False
    for lineno, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", strip_inline_code(raw)):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#")[0]
            if not path_part or not path_part.endswith(".md"):
                continue
            if not (base / path_part).exists():
                issues.append(Issue(
                    SEVERITY_ERROR, rel, lineno, "R08", "相对链接有效",
                    f"链接目标不存在: {target}",
                    "修正链接路径或创建目标文件"))
    return issues


def rule_r09_sections(rel, lines, ctx):
    if Path(rel).name == "README.md":
        return []
    issues = []
    for lineno, raw in enumerate(lines, start=1):
        if raw.startswith("## ") and not re.match(r"^##\s+[一二三四五六七八九十]+\s*、", raw):
            issues.append(Issue(
                SEVERITY_ERROR, rel, lineno, "R09", "章节编号",
                f"二级标题「{raw[3:].strip()}」不是「## 一、」形式",
                "改为中文数字编号，如「## 一、xxx」"))
    return issues


def rule_r10_prefixes(rel, lines, ctx):
    prefixes = ctx["prefixes"]
    if not prefixes:
        return []
    issues = []
    for lineno, raw in enumerate(lines, start=1):
        for match in CODE_TOKEN_RE.finditer(strip_inline_code(raw)):
            prefix = match.group(1)
            if prefix not in prefixes:
                issues.append(Issue(
                    SEVERITY_ERROR, rel, lineno, "R10", "编号前缀合法",
                    f"编号「{match.group(0)}」的前缀「{prefix}」未登记",
                    "改用已登记前缀，或先在 references/project-facts.md 前缀表中登记"))
    return issues


def rule_r11_readme(root, ctx):
    readme = root / "README.md"
    if not readme.exists():
        return [Issue(SEVERITY_ERROR, "README.md", 1, "R11", "README 目录同步",
                      "缺少 README.md", "创建工程总览 README.md")]
    tree_paths = parse_readme_tree(readme.read_text(encoding="utf-8"))
    actual = {rel for _, rel in iter_md_files(root)}
    issues = []
    for rel in sorted(actual - tree_paths):
        issues.append(Issue(
            SEVERITY_ERROR, rel, 1, "R11", "README 目录同步",
            "文件未登记在 README.md 目录树中",
            "在 README.md 目录树补充该文件"))
    for rel in sorted(tree_paths - actual):
        issues.append(Issue(
            SEVERITY_ERROR, "README.md", 1, "R11", "README 目录同步",
            f"目录树中的 {rel} 不存在",
            "更新目录树或创建该文件"))
    return issues


def rule_r12_heading_levels(rel, lines, ctx):
    issues = []
    previous = 0
    for lineno, raw in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+", raw)
        if not match:
            continue
        level = len(match.group(1))
        if previous and level > previous + 1:
            issues.append(Issue(
                SEVERITY_WARN, rel, lineno, "R12", "标题层级",
                f"标题从 H{previous} 跳级到 H{level}",
                "补齐缺失的标题层级"))
        previous = level
    return issues


def rule_r13_table_columns(rel, lines, ctx):
    issues = []
    for _, block in iter_table_blocks(lines):
        expected = None
        for idx, raw in block:
            cells = raw.strip().strip("|").split("|")
            if expected is None:
                expected = len(cells)
            elif len(cells) != expected:
                issues.append(Issue(
                    SEVERITY_WARN, rel, idx, "R13", "表格列数一致",
                    f"该行有 {len(cells)} 列，表头为 {expected} 列",
                    "补齐缺失单元格"))
    return issues


def rule_r14_slang(rel, lines, ctx):
    words = ctx["slang_words"]
    ignored = ctx["slang_ignored"]
    issues = []
    for lineno, raw in iter_content_lines(lines):
        line = strip_inline_code(raw)
        for _, word in find_word_hits(line, words):
            if word in ignored or word in SLANG_IGNORE_WORDS:
                continue
            repl = words[word]
            if repl == SLANG_PENDING:
                issues.append(Issue(
                    SEVERITY_WARN, rel, lineno, "R14", "黑话检测",
                    f"出现疑似黑话「{word}」，词表替换词待确认",
                    "确认是否黑话：是则在 scripts/data/slang-words.txt 填写书面替换并改写本文档；"
                    "否则将该行改为「!词=>保留」"))
            else:
                issues.append(Issue(
                    SEVERITY_ERROR, rel, lineno, "R14", "黑话检测",
                    f"出现黑话「{word}」",
                    f"改为「{repl}」"))
        # 候选扫描：拼音缩写型新梗（如 yyds、xswl 一类），链接目标与裸 URL 先剔除避免误报
        scan_line = re.sub(r"https?://\S+", "", re.sub(r"\]\([^)]*\)", "]", line))
        for match in SLANG_CANDIDATE_RE.finditer(scan_line):
            word = match.group(0)
            if word in words or word in ignored or word in SLANG_IGNORE_WORDS:
                continue
            ctx["slang_candidates"].setdefault(word, (rel, lineno))
    return issues


def rule_r15_categories(rel, lines, ctx):
    if Path(rel).name not in CATEGORY_DOC_NAMES:
        return []
    sections = []
    current = None
    for lineno, raw in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+", raw)
        if match:
            level = len(match.group(1))
            if level == 2:
                if current is not None:
                    sections.append(current)
                current = [lineno, raw.strip(), False]
            elif current is not None and level <= 2:
                sections.append(current)
                current = None
            continue
        if current is not None and raw.strip():
            current[2] = True
    if current is not None:
        sections.append(current)
    issues = []
    if len(sections) < MIN_CATEGORY_SECTIONS:
        issues.append(Issue(
            SEVERITY_ERROR, rel, 1, "R15", "分类存放",
            f"本文档仅含 {len(sections)} 个二级分类章节，少于要求的 {MIN_CATEGORY_SECTIONS} 个",
            "按章节/题型等维度建立分类章节，将内容分门别类归入对应分类"))
    for lineno, title, has_content in sections:
        if not has_content:
            issues.append(Issue(
                SEVERITY_ERROR, rel, lineno, "R15", "分类存放",
                f"分类章节「{title}」下没有内容",
                "将该分类的内容补入章节，或删除空分类章节"))
    return issues


def rule_r16_doc_header(rel, lines, ctx):
    if Path(rel).name == "README.md":
        return []
    h1 = next((i for i, raw in enumerate(lines) if raw.startswith("# ")), None)
    if h1 is None:
        return []
    h2 = len(lines)
    for j in range(h1 + 1, len(lines)):
        if re.match(r"^##\s", lines[j]):
            h2 = j
            break
    region = "\n".join(lines[h1 + 1:h2])
    issues = []
    for field in DOC_HEADER_FIELDS:
        if field not in region:
            issues.append(Issue(
                SEVERITY_ERROR, rel, h1 + 2, "R16", "文档头元数据",
                f"文档头缺少「{field}」字段",
                "在标题下方紧接的文档头中补充 状态 / 创建时间 / 学科 / 分类 四项，"
                "格式见 SKILL.md「格式约定」第 9 条"))
    return issues


ANSWER_PARSING_RE = re.compile(r"\*\*(答案|解析)\*\*")
FEEDBACK_HEADING_RE = re.compile(r"^###\s*订正反馈")
SET_KEYWORDS_RE = re.compile(r"测验|专项|模拟卷|真题|自测|练习")
QUESTION_SUBSECTION_RE = re.compile(r"^###\s*第\s*[一二三四五六七八九十0-9]+\s*题")
REQUIRED_ERROR_TYPES = ("概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘")


def rule_r17_exercise_separation(rel, lines, ctx):
    if Path(rel).name != "题库.md":
        return []
    issues = []
    for lineno, raw in enumerate(lines, start=1):
        if ANSWER_PARSING_RE.search(raw):
            issues.append(Issue(
                SEVERITY_ERROR, rel, lineno, "R17", "习题解析分文档",
                "题库文档中出现了内联的答案 / 解析标记",
                "将 **答案** / **解析** 内容迁移到同名解析文档（如 题库解析.md），"
                "本题库文档仅保留题干"))
    return issues


def _parse_feedback_error_types(lines, start):
    """解析「### 订正反馈」块内的错因类型（表格首列标签），返回集合。"""
    labels = set()
    n = len(lines)
    i = start
    while i < n and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("#"):
            return labels
        i += 1
    while i < n and lines[i].lstrip().startswith("|"):
        cells = lines[i].strip().strip("|").split("|")
        first = cells[0].strip()
        if set(first) <= set("-: "):
            i += 1
            continue
        if first and first != "问题类型":
            labels.add(first)
        i += 1
    return labels


def rule_r18_feedback_block(rel, lines, ctx):
    if Path(rel).name != "题库.md":
        return []
    sections = []
    cur = None
    for lineno, raw in enumerate(lines, start=1):
        if raw.startswith("## "):
            if cur is not None:
                sections.append(cur)
            cur = {"lineno": lineno, "title": raw[3:].strip(), "has_q": False, "fb": None}
        elif raw.startswith("### ") and cur is not None:
            if QUESTION_SUBSECTION_RE.match(raw):
                cur["has_q"] = True
            elif FEEDBACK_HEADING_RE.match(raw):
                cur["fb"] = lineno
    if cur is not None:
        sections.append(cur)
    issues = []
    for sec in sections:
        if not (SET_KEYWORDS_RE.search(sec["title"]) and sec["has_q"]):
            continue
        if sec["fb"] is None:
            issues.append(Issue(
                SEVERITY_ERROR, rel, sec["lineno"], "R18", "套题订正反馈",
                f"套题「{sec['title']}」含题目但缺少「订正反馈」块",
                "在该套题章节内添加「### 订正反馈（套题名）」块，含 5 类错因行（模板见 danzhao-docs SKILL.md）"))
            continue
        labels = _parse_feedback_error_types(lines, sec["fb"])
        missing = [t for t in REQUIRED_ERROR_TYPES if t not in labels]
        if missing:
            issues.append(Issue(
                SEVERITY_ERROR, rel, sec["fb"], "R18", "套题订正反馈",
                f"「订正反馈」块缺少错因类型行：{', '.join(missing)}",
                "在该块表格中补齐 概念不清/计算失误/思路错误/审题偏差/知识遗忘 五行"))
    return issues


EVAL_HEADING_RE = re.compile(r"^###\s*评估")
OVERALL_MARK_RE = re.compile(r"总体掌握")


def _parse_conquered_cells(lines, start):
    """解析订正反馈块每行「是否攻克」列（最后一列）的值。"""
    cells = []
    n = len(lines)
    i = start
    while i < n and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("#"):
            return cells
        i += 1
    while i < n and lines[i].lstrip().startswith("|"):
        row = lines[i].strip().strip("|").split("|")
        if set(row[0].strip()) <= set("-: "):
            i += 1
            continue
        if row[0].strip() in ("问题类型", ""):
            i += 1
            continue
        if len(row) >= 4:
            cells.append(row[-1].strip())
        i += 1
    return cells


def _parse_overall_mastery(lines, start):
    """解析评估块中「总体掌握」行对应的评级。"""
    n = len(lines)
    i = start
    while i < n and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("#"):
            return None
        i += 1
    while i < n and lines[i].lstrip().startswith("|"):
        row = lines[i].strip().strip("|").split("|")
        if row and OVERALL_MARK_RE.search(row[0].strip()):
            return row[1].strip() if len(row) >= 2 else None
        i += 1
    return None


def _section_text(lines, start):
    """取从 start 行起到下一个标题行（不含）为止的文本，用于块级关键词判断。"""
    out = []
    for raw in lines[start:]:
        if raw.startswith("#"):
            break
        out.append(raw)
    return "\n".join(out)


def rule_r19_assessment_block(rel, lines, ctx):
    if Path(rel).name != "题库.md":
        return []
    cur_fb = None
    issues = []
    for lineno, raw in enumerate(lines, start=1):
        if raw.startswith("## "):
            cur_fb = None
        elif raw.startswith("### "):
            if FEEDBACK_HEADING_RE.match(raw):
                cur_fb = lineno
            elif EVAL_HEADING_RE.match(raw):
                if cur_fb is not None and "验证未过" not in _section_text(lines, lineno):
                    conquered = _parse_conquered_cells(lines, cur_fb)
                    overall = _parse_overall_mastery(lines, lineno)
                    if overall is not None and conquered:
                        all_green = all("🟢" in c for c in conquered)
                        any_unconquered = any("⬜" in c for c in conquered)
                        overall_green = ("✅" in overall) or ("🟢" in overall)
                        if all_green and not overall_green:
                            issues.append(Issue(
                                SEVERITY_WARN, rel, lineno, "R19", "评估一致性",
                                "「订正反馈」全部已攻克，但「评估」总体掌握仍为「%s」" % overall,
                                "将评估「总体掌握」更新为 ✅ 或 🟢"))
                        elif any_unconquered and ("✅" in overall):
                            issues.append(Issue(
                                SEVERITY_WARN, rel, lineno, "R19", "评估一致性",
                                "「订正反馈」仍有未攻克项，但「评估」总体掌握已标 ✅",
                                "将总体掌握调回 🟨/⬜，或先攻克未攻克项"))
                cur_fb = None
    return issues


def rule_r20_long_sentences(rel, lines, ctx):
    if Path(rel).name not in READABILITY_DOC_NAMES:
        return []
    issues = []
    for lineno, raw in iter_content_lines(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith(("|", "#", ">")):
            continue
        text = strip_inline_code(raw)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        for sentence in SENTENCE_SPLIT_RE.split(text):
            if not sentence.strip():
                continue
            count = len(CONTENT_CHAR_RE.findall(sentence))
            if count > LONG_SENTENCE_LIMIT:
                issues.append(Issue(
                    SEVERITY_WARN, rel, lineno, "R20", "长句检查",
                    f"单句约 {count} 字，超过 {LONG_SENTENCE_LIMIT} 字上限",
                    "拆成 2–3 个短句，一句一个意思；术语首次出现时用白话解释"))
                break
    return issues


FILE_RULES = (
    rule_r01_colloquial,
    rule_r03_title,
    rule_r04_policy,
    rule_r05_emoji,
    rule_r06_placeholder,
    rule_r07_separator,
    rule_r08_links,
    rule_r09_sections,
    rule_r10_prefixes,
    rule_r12_heading_levels,
    rule_r13_table_columns,
    rule_r14_slang,
    rule_r15_categories,
    rule_r16_doc_header,
    rule_r17_exercise_separation,
    rule_r18_feedback_block,
    rule_r19_assessment_block,
    rule_r20_long_sentences,
)


def collect_files(targets):
    files = []
    for target in targets:
        if target.is_file():
            files.append((target, target.name))
        elif target.is_dir():
            files.extend(iter_md_files(target))
    return files


def main() -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(description="文档规范校验器")
    parser.add_argument("paths", nargs="*", help="待校验的文件或目录，默认为整个仓库")
    parser.add_argument("--list", action="store_true", help="列出全部规则")
    args = parser.parse_args()

    if args.list:
        for rule in RULES:
            print(f"{rule['id']}  [{rule['severity']}]  {rule['name']}")
            print(f"    说明: {rule['desc']}")
            print(f"    修复: {rule['fix']}")
        return 0

    root = REPO_ROOT
    targets = [Path(path) for path in args.paths] or [root]
    files = collect_files(targets)

    ctx = {"root": root, "words": load_colloquial_words(), "prefixes": load_prefixes()}
    ctx["slang_words"], ctx["slang_ignored"] = load_slang_words()
    ctx["slang_candidates"] = {}
    issues = list(rule_r02_file_types(root, ctx))
    issues.extend(rule_r11_readme(root, ctx))
    for path, rel in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(Issue(SEVERITY_ERROR, rel, 0, "R02", "文件类型",
                                f"无法读取: {exc}", "确认文件存在且为 UTF-8 编码"))
            continue
        for rule in FILE_RULES:
            issues.extend(rule(rel, lines, ctx))

    registered = register_new_slang(ctx["slang_candidates"], ctx["slang_words"], ctx["slang_ignored"])
    for word in sorted(registered):
        rel, lineno = registered[word]
        issues.append(Issue(
            SEVERITY_WARN, rel, lineno, "R14", "黑话检测",
            f"发现疑似黑话「{word}」，已自动登记到黑话词表",
            "确认是否黑话：是则填写书面替换词并改写文档；否则将该行改为「!词=>保留」"))

    return print_report(issues, "文档规范校验")


if __name__ == "__main__":
    sys.exit(main())
