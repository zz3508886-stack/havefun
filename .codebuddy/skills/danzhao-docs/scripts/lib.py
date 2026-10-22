"""共享工具：统一的问题记录与报告输出格式。

供 check_docs.py（文档规范校验）与 manage.py（脚本管理器）复用。
输出面向 AI 使用：每条问题给出文件、行号、规则编号、说明与修复建议，便于直接定位并修正。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

SEVERITY_ERROR = "ERROR"
SEVERITY_WARN = "WARN"


@dataclass
class Issue:
    severity: str
    file: str
    line: int
    rule_id: str
    rule_name: str
    message: str
    fix: str = ""


def configure_utf8_output() -> None:
    """Windows 控制台默认 GBK，统一切换为 UTF-8 输出，避免表情符号导致报错。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def format_issue(issue: Issue) -> str:
    lines = [
        f"[{issue.severity}] {issue.file}:{issue.line} {issue.rule_id} {issue.rule_name}",
        f"    说明: {issue.message}",
    ]
    if issue.fix:
        lines.append(f"    修复: {issue.fix}")
    return "\n".join(lines)


def print_report(issues: list, title: str) -> int:
    """打印报告并返回退出码：存在 ERROR 返回 1，否则返回 0。"""
    errors = [i for i in issues if i.severity == SEVERITY_ERROR]
    warns = [i for i in issues if i.severity == SEVERITY_WARN]
    if issues:
        for issue in issues:
            print(format_issue(issue))
        print()
    if errors:
        print(f"结果: {len(errors)} 个错误, {len(warns)} 个警告（{title}）")
        print("请逐条修复上述 ERROR 后重新运行校验。")
        return 1
    if warns:
        print(f"结果: 0 个错误, {len(warns)} 个警告（{title}）")
        return 0
    print(f"结果: 全部通过（{title}）")
    return 0
