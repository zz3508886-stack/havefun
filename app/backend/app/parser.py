"""题库 markdown 解析：产出题目结构与答案键。

移植自初版网页刷题服务（web/，已于 P8 退役，归档见 context/epics）的正则切分逻辑，
并落实《总体设计》的 qid 契约：

- 显式 ID 优先：题头 ``### 第 N 题（SX-001，选择题，……）`` 中的 ID 直接作 qid，
  与 题库解析.md 按 ID 对应的答案键天然对齐（现有题库已普遍带 SX-/SL- 式 ID）。
- 无显式 ID（题头内 ID 位为空）用内容指纹兜底：
  ``MD5(学科 + 套题 + 题干纯文本前 30 字)[:12]``。
- 主键取 (file_path, qid)：显式 ID 在不同文件间可能重名，跨文件安全。

解析只产出题目内容与答案键，不判分、不回写——这是 L1 索引层的纯只读职责。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# --- 题头 / 章节 / 选项 / 答案键 正则（沿用初版服务已被真实语料验证的写法） ---
# 套题章节识别：章节名含这些关键词的二级章节才纳入做题系统
# （「摸底」覆盖 测验/摸底/ 下的概念摸底 A/B/C 卷）
SET_RE = re.compile(r"测验|专项|模拟卷|真题|自测|练习|摸底")
QH_RE = re.compile(r"^###\s*第\s*([0-9]+)\s*题\s*[（(](.*?)[）)]\s*$")
HEAD_RE = re.compile(r"^#{2,3}\s*(.*?)\s*$")
OPT_RE = re.compile(r"^\s*[-*]\s*([A-Za-z])\s*[.、]\s*(.*)$")
ANS_RE = re.compile(r"答案[:：]\s*(.+)")
ANALYSIS_RE = re.compile(r"解析[:：]")
ID_INSIDE_RE = re.compile(r"^\s*([A-Za-z0-9\-]+)\s*[，,]\s*([^，,]+?)\s*[，,]\s*(.+)$")
SUBJECT_RE = re.compile(r"^\|\s*学科\s*\|\s*(.+?)\s*\|\s*$")
# 解析文档题头：``### SX-MP-001（选择题，【基础｜难度 2】）`` 或裸 ``### HL-MP-001``
# （括号后缀可选——摸底卷解析多为裸题头，两种形态都要能提出答案键与解析）
ANALYSIS_HEAD_RE = re.compile(r"^###\s*([A-Za-z0-9\-]+)\s*(?:[（(][^）)]*[）)])?\s*$")

OBJECTIVE_TYPES = {"选择题", "判断题"}
ERROR_TYPES = ["概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘"]


def is_objective_question(q: Question) -> bool:
    """是否按客观题判分（脚本精确比对答案键）。

    两类算客观题：
    1. 标准题型名：选择题 / 判断题；
    2. 非标准题型名但形态是单选——带 ≥2 个标准选项（A/B/C/D 列表）且答案键
       为单个字母。摸底卷的「单项选择」「字音·多音字」等细分题型实为单选，
       按选项比对即可判分；无选项的填空/解答/写作不受影响（答案非单字母
       或无选项，仍走主观分流）。
    """
    if q.q_type in OBJECTIVE_TYPES:
        return True
    if len(q.options) < 2:
        return False
    return bool(re.fullmatch(r"[A-Z]", (q.answer_key or "").strip()))


@dataclass
class Question:
    qid: str
    file_path: str  # 仓库相对路径（posix）
    section_title: str
    q_type: str
    stem: str
    options: list = field(default_factory=list)  # [{"label": "A", "text": "..."}]
    answer_key: str = ""
    difficulty: str = ""
    tags_json: str = "[]"

    def to_row(self) -> tuple:
        return (
            self.file_path,
            self.qid,
            self.section_title,
            self.q_type,
            self.stem,
            json.dumps(self.options, ensure_ascii=False),
            self.answer_key,
            self.difficulty,
            self.tags_json,
        )


# --------------------------------------------------------------------------- #
# 元信息
# --------------------------------------------------------------------------- #
def subject_of(path: Path, lines, root: Path) -> str:
    """从文档头表格取「学科」；缺省回退到仓库相对路径顶层目录名。"""
    for line in lines[:40]:
        m = SUBJECT_RE.match(line.strip())
        if m:
            return m.group(1).strip()
    try:
        return path.resolve().relative_to(root.resolve()).parts[0]
    except (ValueError, IndexError):
        return ""


# --------------------------------------------------------------------------- #
# 题库解析
# --------------------------------------------------------------------------- #
def _split_sections(lines):
    """按二级标题切分，返回 [(title, start_idx, end_idx)]。"""
    sections = []
    cur = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("### "):
            if cur is not None:
                sections.append((cur[0], cur[1], i))
            cur = (line[3:].strip(), i, len(lines))
        elif cur is None and line.startswith("# "):
            cur = ("", 0, len(lines))
    if cur is not None:
        sections.append((cur[0], cur[1], len(lines)))
    return sections


def _parse_header_inside(inside: str):
    """从「SX-001，选择题，【基础｜难度 2】」拆出 (id, type, difficulty)。"""
    m = ID_INSIDE_RE.match(inside)
    if not m:
        return None, None, None
    return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()


def _parse_questions_in_section(sec_lines):
    questions = []
    i = 0
    n = len(sec_lines)
    while i < n:
        m = QH_RE.match(sec_lines[i])
        if m:
            qindex = int(m.group(1))
            explicit_id, q_type, q_diff = _parse_header_inside(m.group(2))
            if explicit_id is None:
                qindex = None  # 标记：走内容指纹兜底，稍后补 qid
            body = []
            options = []
            j = i + 1
            while j < n and not HEAD_RE.match(sec_lines[j]):
                om = OPT_RE.match(sec_lines[j])
                if om:
                    options.append({"label": om.group(1), "text": om.group(2).strip()})
                else:
                    body.append(sec_lines[j])
                j += 1
            stem = "\n".join(l.strip() for l in body).strip()
            questions.append(
                {
                    "explicit_id": explicit_id,
                    "index": qindex,
                    "type": q_type or "",
                    "difficulty": q_diff or "",
                    "stem": stem,
                    "options": options,
                }
            )
            i = j
        else:
            i += 1
    return questions


def parse_file(path: Path, root: Path) -> list[Question]:
    """解析单个 题库.md，返回 Question 列表（落实 qid 契约）。"""
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    lines = path.read_text(encoding="utf-8").splitlines()
    subject = subject_of(path, lines, root)
    out: list[Question] = []
    for title, s, e in _split_sections(lines):
        if not SET_RE.search(title):
            continue
        for q in _parse_questions_in_section(lines[s:e]):
            if q["explicit_id"] is not None:
                qid = q["explicit_id"]
            else:
                raw = f"{subject}\u0001{title}\u0001{q['stem'][:30]}"
                qid = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
            out.append(
                Question(
                    qid=qid,
                    file_path=rel,
                    section_title=title,
                    q_type=q["type"],
                    stem=q["stem"],
                    options=q["options"],
                    difficulty=q["difficulty"],
                )
            )
    return out


def parse_answer_key(analysis_path: Path) -> dict:
    """读取同名 题库解析.md，返回 {qid: answer}。"""
    if not analysis_path.exists():
        return {}
    lines = analysis_path.read_text(encoding="utf-8").splitlines()
    key: dict = {}
    i = 0
    n = len(lines)
    cur_id = None
    cur_answer = ""
    while i < n:
        m = ANALYSIS_HEAD_RE.match(lines[i])
        if m and lines[i].startswith("###"):
            if cur_id is not None:
                key[cur_id] = cur_answer
            cur_id = m.group(1)
            cur_answer = ""
            i += 1
            continue
        if cur_id is not None:
            am = ANS_RE.search(lines[i])
            if am and not cur_answer:
                cur_answer = am.group(1).replace("**", "").strip()
        i += 1
    if cur_id is not None:
        key[cur_id] = cur_answer
    return key


def answer_key_for(path: Path) -> dict:
    analysis = path.with_name(path.name.replace("题库", "题库解析"))
    return parse_answer_key(analysis)


def parse_explanations(analysis_path: Path) -> dict:
    """读取同名 题库解析.md，返回 {qid: 解析文本}（不含「答案：」行本身）。

    解析段落在 ``### <qid>（…）`` 之后、首个「答案：」行之后，直到下一个
    ``###``/``##`` 或文件末尾。供交卷结果页回显完整试题（题干+选项+答案+解析）。
    """
    if not analysis_path.exists():
        return {}
    lines = analysis_path.read_text(encoding="utf-8").splitlines()
    expl: dict = {}
    cur_id = None
    buf: list = []
    in_expl = False
    for line in lines:
        m = ANALYSIS_HEAD_RE.match(line)
        if m:
            if cur_id is not None:
                expl[cur_id] = _clean_expl("\n".join(buf).strip())
            cur_id = m.group(1)
            buf = []
            in_expl = False
            continue
        if cur_id is not None:
            am = ANS_RE.search(line)
            if am and not in_expl:
                in_expl = True  # 跳过「答案：」行本身，其后文本即解析
                continue
            if in_expl:
                buf.append(line)
    if cur_id is not None:
        expl[cur_id] = _clean_expl("\n".join(buf).strip())
    return expl


def _clean_expl(text: str) -> str:
    """去掉解析文本里的 Markdown 粗体标记与冗余「解析：」前缀，便于前端直接展示。"""
    text = text.replace("**", "")
    # 若首行以「解析：/解析:」开头则去掉，避免与前端「解析」标题重复
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith(("解析：", "解析:")):
        lines[0] = lines[0].lstrip()[3:].lstrip()
    return "\n".join(lines).strip()
