"""文档规范校验器：对仓库内 Markdown 文档执行 danzhao-docs SKILL.md 定义的格式约定。

用法:
    python check_docs.py [路径...]      # 校验指定文件或目录，默认为整个仓库
    python check_docs.py --list         # 列出全部规则

退出码: 存在 ERROR 返回 1，否则返回 0。
输出格式面向 AI：每条问题含文件、行号、规则编号、说明与修复建议。
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

SKIP_DIRS = {".git", ".codebuddy"}
PLACEHOLDERS = ("待填写", "待添加", "待补充")
EMOJI_WHITELIST = {"⬜", "🟨", "✅", "🔴", "🟢", "⚠"}
EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x2B00, 0x2BFF))
EMPTY_ROW_EXEMPT = {"复习计划/总复习计划.md"}
POLICY_DIR = "政策资讯"
CODE_TOKEN_RE = re.compile(r"\b([A-Z]{2})(?:-[A-Z0-9]+)+\b")
TREE_LINE_RE = re.compile(r"^((?:│   |    )*)(├── |└── )(.*)$")
SEPARATOR_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")

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
    in_fence = False
    for lineno, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = strip_inline_code(raw)
        matches = []
        for word in words:
            pos = line.find(word)
            if pos >= 0:
                matches.append((pos, word))
        matches.sort(key=lambda item: (item[0], -len(item[1])))
        occupied = []
        for pos, word in matches:
            end = pos + len(word)
            if any(pos < taken_end and taken_start < end for taken_start, taken_end in occupied):
                continue
            occupied.append((pos, end))
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

    return print_report(issues, "文档规范校验")


if __name__ == "__main__":
    sys.exit(main())
