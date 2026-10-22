"""非客观题的 AI 判分。

通过可配置的 OpenAI 兼容 /chat/completions 端点评判填空/解答/操作/面试题。
未配置或调用失败时，grade() 返回 correct=None，由上层标「待复核」。
配置优先级：环境变量 > web/config.json。
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
CONFIG_PATH = WEB_DIR / "config.json"

ERROR_TYPES = ["概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘"]


def _load_cfg() -> dict:
    cfg = {
        "enabled": os.environ.get("LLM_ENABLED", "").lower() == "true",
        "base_url": os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "timeout": int(os.environ.get("LLM_TIMEOUT", "30")),
    }
    if CONFIG_PATH.exists():
        try:
            j = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            llm = j.get("llm", {})
            cfg["enabled"] = str(llm.get("enabled", cfg["enabled"])).lower() == "true"
            cfg["base_url"] = llm.get("base_url", cfg["base_url"])
            cfg["api_key"] = llm.get("api_key", cfg["api_key"])
            cfg["model"] = llm.get("model", cfg["model"])
            cfg["timeout"] = int(llm.get("timeout", cfg["timeout"]))
        except Exception:
            pass
    return cfg


def _extract_json(text: str) -> dict:
    """从模型返回中尽量稳健地抽取 JSON。"""
    if not text:
        return {}
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(text[s : e + 1])
        except Exception:
            return {}
    return {}


def _call(messages: list, cfg: dict) -> str:
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def grade(question: dict, student_answer: str, key_entry: dict) -> dict:
    """返回 {correct: bool|None, 错因类型: str, 错因说明: str}。"""
    cfg = _load_cfg()
    if not cfg["enabled"] or not cfg["api_key"]:
        return {"correct": None, "错因类型": "待复核", "错因说明": "未配置 AI 端点，待复核"}

    opts = ""
    if question.get("options"):
        opts = "\n".join(f"{o['label']}. {o['text']}" for o in question["options"])
    stem = question.get("stem", "")
    answer = key_entry.get("answer", "")
    analysis = key_entry.get("analysis", "")

    sys_msg = (
        "你是河南省护理中专单招的严谨阅卷老师。"
        "请根据参考答案与解析，判断学生作答是否正确，并给出错因类型与一句说明。"
        "只输出 JSON，不要多余文字。"
    )
    user_msg = (
        f"【题目】\n{stem}\n{opts}\n\n"
        f"【参考答案】\n{answer}\n\n"
        f"【参考解析】\n{analysis}\n\n"
        f"【学生作答】\n{student_answer}\n\n"
        "请输出 JSON：\n"
        '{"correct": true或false, '
        f'"错因类型": "{"|".join(ERROR_TYPES)}", '
        '"错因说明": "一句话说明"}\n'
        "注意：填空/解答题只要核心结论与过程正确即可判对；明显概念或计算错误判错。"
    )

    try:
        content = _call(
            [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            cfg,
        )
        j = _extract_json(content)
        correct = j.get("correct")
        etype = j.get("错因类型", "待复核")
        if etype not in ERROR_TYPES:
            etype = "待复核"
        return {
            "correct": bool(correct) if isinstance(correct, bool) else None,
            "错因类型": etype,
            "错因说明": str(j.get("错因说明", "")),
        }
    except Exception:
        return {"correct": None, "错因类型": "待复核", "错因说明": "AI 判分调用失败，待人工复核"}
