"""脚本管理器：校验 scripts/ 下的脚本本身，并调度文档规范校验。

用法:
    python manage.py scripts      # 校验脚本自身（语法 + 编写约定）
    python manage.py docs [路径]  # 校验文档规范（转发给 check_docs.py）
    python manage.py all          # 先校验脚本，再校验文档（默认）
    python manage.py list         # 列出文档校验规则

退出码: 任一校验存在 ERROR 返回 1，否则返回 0。
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import Issue, SEVERITY_ERROR, configure_utf8_output, print_report

SCRIPTS_DIR = Path(__file__).resolve().parent
CHECK_DOCS = SCRIPTS_DIR / "check_docs.py"
DATA_FILE = SCRIPTS_DIR / "data" / "colloquial-words.txt"

SCRIPT_RULES = [
    ("S01", "语法可编译", "ast.parse 解析通过"),
    ("S02", "UTF-8 编码", "文件可以 UTF-8 解码"),
    ("S03", "模块文档字符串", "文件包含模块级 docstring"),
    ("S04", "main 保护", "包含 if __name__ == \"__main__\": 入口保护"),
    ("S05", "依赖白名单", "仅导入标准库与本地模块 lib"),
    ("S06", "无硬编码绝对路径", "不包含 Windows/Unix 绝对路径字面量"),
    ("S07", "行尾换行", "文件以换行符结尾"),
    ("S08", "数据文件存在", "scripts/data/colloquial-words.txt 存在"),
]

ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|(?<![\w.])/(?:home|Users|tmp)/")
MAIN_GUARD_RE = re.compile(r"if\s+__name__\s*==\s*[\"']__main__[\"']")


def _literal_spans(source: str) -> list:
    """返回字符串与注释字面量的字符区间，S06 扫描时跳过，避免正则字面量误报。"""
    line_offsets = [0]
    for line in source.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    spans = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type in (tokenize.STRING, tokenize.COMMENT):
                start = line_offsets[token.start[0] - 1] + token.start[1]
                end = line_offsets[token.end[0] - 1] + token.end[1]
                spans.append((start, end))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    return spans


def check_script(path: Path) -> list:
    """校验单个脚本文件，返回问题列表。"""
    rel = path.name
    issues = []
    raw = path.read_bytes()
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(Issue(SEVERITY_ERROR, rel, 0, "S02", "UTF-8 编码",
                            f"无法按 UTF-8 解码: {exc}", "将文件转换为 UTF-8 编码"))
        return issues

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        issues.append(Issue(SEVERITY_ERROR, rel, exc.lineno or 0, "S01", "语法可编译",
                            f"语法错误: {exc.msg}", "修正语法后重新校验"))
        return issues

    if ast.get_docstring(tree) is None:
        issues.append(Issue(SEVERITY_ERROR, rel, 1, "S03", "模块文档字符串",
                            "缺少模块级 docstring", "在文件开头添加说明用途的 docstring"))

    if path.name != "lib.py" and not MAIN_GUARD_RE.search(source):
        issues.append(Issue(SEVERITY_ERROR, rel, 1, "S04", "main 保护",
                            "缺少 if __name__ == \"__main__\": 入口保护",
                            "将入口调用放入 main 保护块中"))

    allowed = set(getattr(sys, "stdlib_module_names", ())) | {"lib"}
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules = [node.module.split(".")[0]]
        for module in modules:
            if module not in allowed:
                issues.append(Issue(SEVERITY_ERROR, rel, node.lineno, "S05", "依赖白名单",
                                    f"导入了非标准库模块「{module}」",
                                    "改用标准库实现，或将其登记为允许的本地模块"))

    spans = _literal_spans(source)
    for match in ABSOLUTE_PATH_RE.finditer(source):
        if any(start <= match.start() < end for start, end in spans):
            continue
        line = source[: match.start()].count("\n") + 1
        issues.append(Issue(SEVERITY_ERROR, rel, line, "S06", "无硬编码绝对路径",
                            f"出现绝对路径字面量「{match.group(0)}」",
                            "改用基于 __file__ 的相对路径计算"))
        break

    if not source.endswith("\n"):
        issues.append(Issue(SEVERITY_ERROR, rel, len(source.splitlines()), "S07", "行尾换行",
                            "文件未以换行符结尾", "在文件末尾添加换行"))
    return issues


def cmd_scripts() -> int:
    issues = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        issues.extend(check_script(path))
    if not DATA_FILE.exists():
        issues.append(Issue(SEVERITY_ERROR, "data/colloquial-words.txt", 0, "S08", "数据文件存在",
                            "缺少口水词词表", "创建 scripts/data/colloquial-words.txt"))
    return print_report(issues, "脚本自身校验")


def cmd_docs(paths: list) -> int:
    command = [sys.executable, str(CHECK_DOCS), *paths]
    return subprocess.run(command).returncode


def cmd_list() -> int:
    command = [sys.executable, str(CHECK_DOCS), "--list"]
    return subprocess.run(command).returncode


def main() -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(description="脚本管理器：校验脚本自身并调度文档规范校验")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("scripts", help="校验 scripts/ 下的脚本本身")
    docs_parser = sub.add_parser("docs", help="校验文档规范")
    docs_parser.add_argument("paths", nargs="*")
    sub.add_parser("all", help="先校验脚本，再校验文档")
    sub.add_parser("list", help="列出文档校验规则")
    args = parser.parse_args()

    command = args.command or "all"
    if command == "scripts":
        return cmd_scripts()
    if command == "docs":
        return cmd_docs(getattr(args, "paths", []))
    if command == "list":
        return cmd_list()

    result = cmd_scripts()
    print("-" * 60)
    return result or cmd_docs([])


if __name__ == "__main__":
    sys.exit(main())
