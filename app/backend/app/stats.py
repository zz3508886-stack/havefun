"""学情统计路由（P5）：聚合逻辑已下沉 aggregate.py，本模块只做 HTTP 薄封装。

stats（人看，仪表盘）与 ai（AI 看，CLI/快照/API）共用 aggregate 同一组函数，
保证两边数字永远一致。
"""

from __future__ import annotations

from fastapi import APIRouter

from . import aggregate

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def overview() -> dict:
    """一页纸总览：做题总量与正确率、反馈、打卡连续性。"""
    return aggregate.overview()


@router.get("/trend")
def trend(days: int = 30) -> dict:
    """最近 N 天每日答题趋势（缺失日补零，保证折线 x 轴连续）。"""
    return aggregate.trend(days)


@router.get("/subjects")
def subjects() -> list[dict]:
    """各学科（一级目录）掌握度：已判正确率 + 错题/待复核量，错误多的排前。"""
    return aggregate.subjects()


@router.get("/weak")
def weak(limit: int = 10) -> dict:
    """薄弱套题榜 + 重复错题榜（错题本「出现次数」的流水版）。"""
    return aggregate.weak(limit)


@router.get("/error-types")
def error_types() -> dict:
    """R18 五类错因分布（attempts 的 error_type + feedback 的自选错因）+ 疑难点计数。"""
    return aggregate.error_types()
