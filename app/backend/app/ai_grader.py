"""AI 判分器工厂：按配置决定是否启用大模型初判简答/解答题。

P2 默认 config.ai.enabled=False，故 make_ai_grader 返回 None —— 主观题统一降级为
「待人工复核（pending_manual）」，不阻塞交卷。配置端点后返回可调用的判分函数；
真实 HTTP 调用在生产态实现（见下方 TODO），P2 仅保留接口与契约。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .grading import AI_Grader
from .parser import Question

logger = logging.getLogger("app.ai_grader")


def make_ai_grader(config: dict) -> Optional[AI_Grader]:
    """根据配置返回 AI 判分函数；未启用或缺少端点时返回 None。"""
    ai = (config or {}).get("ai", {}) or {}
    if not ai.get("enabled") or not ai.get("base_url"):
        return None

    # TODO(生产态): 用 urllib/requests 调 base_url，传入题干+学生作答+参考答案，
    # 解析 JSON 得到 {correct, 错因类型, 错因说明}。P2 不实现真实网络调用，
    # 端点启用前此分支不可达。
    def _grader(question: Question, student: str, answer_key: str) -> dict:
        # UNCERTAIN: 真实端点调用逻辑未在本部署实现；启用前不会进入此函数。
        logger.warning("AI 判分端点已配置但未实现本部署的调用逻辑，降级待复核")
        return {"correct": None, "错因类型": "待复核", "错因说明": "AI 端点未实现"}

    return _grader
