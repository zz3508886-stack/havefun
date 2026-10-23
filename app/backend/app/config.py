"""运行时配置：读取 app/config.json，不存在或损坏时回退默认值。

配置分层（design doc「技术选型」）：config.example.json 为入库模板，
config.json 为本机实际配置（gitignore，AI 密钥等只进这里）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("app.config")

APP_ROOT = Path(__file__).resolve().parents[2]  # app/
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "quiz.db"
CONFIG_PATH = APP_ROOT / "config.json"

DEFAULTS: dict = {
    "server": {"host": "127.0.0.1", "port": 8000},
    "ai": {
        "enabled": False,
        "base_url": "",
        "api_key": "",
        "model": "",
        "timeout": 30,
    },
    # AI 取数通道（/api/ai/*）的本地访问令牌，空串表示不启用鉴权
    "ai_access_token": "",
}


def load_config() -> dict:
    """深拷贝默认值并用 config.json 覆盖；损坏时保留默认值。"""
    cfg = json.loads(json.dumps(DEFAULTS))
    if not CONFIG_PATH.exists():
        return cfg
    try:
        user_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # DEGRADE: 配置损坏时静默回退默认值，保证服务可启动；
        # 调用方应经 /api/health 之外的手段提示用户修复配置文件
        logger.warning("config.json 读取失败，回退默认配置: %s", exc)
        return cfg
    if not isinstance(user_cfg, dict):
        logger.warning("config.json 顶层不是对象，回退默认配置")
        return cfg
    for section, values in user_cfg.items():
        if isinstance(values, dict) and isinstance(cfg.get(section), dict):
            cfg[section].update(values)
        else:
            cfg[section] = values
    return cfg
