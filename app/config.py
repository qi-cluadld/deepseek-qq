"""配置加载：YAML 文件 + 环境变量覆盖 + 默认值。"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------- 默认配置

DEFAULTS: dict[str, Any] = {
    "backend": "onebot",  # onebot | qqofficial
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "temperature": 1.0,
        "max_tokens": 2048,
        "timeout": 60,
        "retries": 2,
        "system_prompt": (
            "你是一个通过 QQ 聊天的 AI 助手。回答要简洁、口语化，"
            "适合在手机屏幕上阅读：多用短句和分点，避免长篇大论，"
            "不要输出 Markdown 表格和复杂格式。"
        ),
    },
    "chat": {
        "history_turns": 10,      # 每个会话保留的对话轮数（1 轮 = 用户 + 助手）
        "session_ttl_minutes": 30,  # 会话闲置多久后清空上下文
        "max_sessions": 500,        # 最多同时保留多少个会话
        "cooldown_seconds": 1.5,    # 同一会话的最小提问间隔
        "max_concurrent": 4,        # 同时请求 DeepSeek 的最大并发数
        "max_reply_chars": 1500,    # 单条 QQ 消息最大字符数，超出自动分条
        "busy_reply": "当前排队的人有点多，请稍等几秒再问~",
        "cooldown_reply": "问得太快啦，缓一缓再发~",
        "error_reply": "我这会儿有点故障（{reason}），稍后再试吧。",
    },
    "onebot": {
        "host": "0.0.0.0",
        "port": 6700,
        "path": "/onebot",
        "access_token": "",
        "group_need_at": True,       # 群里是否需要 @机器人 才回复
        "group_prefix": "#",         # 群里没 @ 时，用这个前缀也能触发（留空则关闭）
        "private_enabled": True,
    },
    "qqofficial": {
        "app_id": "",
        "client_secret": "",
        "sandbox": False,
        "intents": 1107296256,  # 1<<25 (群/C2C 消息) | 1<<30 (频道 @ 消息)
        "ws_url": "",
        "api_base": "https://api.sgroup.qq.com",
        "token_url": "https://bots.qq.com/app/getAppAccessToken",
        "group_need_at": True,
        "max_reply_chars": 1800,
    },
}

# 环境变量：DEEPSEEK_API_KEY 之类，方便不写进配置文件
ENV_OVERRIDES: dict[str, str] = {
    "DEEPSEEK_API_KEY": "deepseek.api_key",
    "DEEPSEEK_BASE_URL": "deepseek.base_url",
    "DEEPSEEK_MODEL": "deepseek.model",
    "QQ_BACKEND": "backend",
    "QQ_APP_ID": "qqofficial.app_id",
    "QQ_CLIENT_SECRET": "qqofficial.client_secret",
    "ONEBOT_ACCESS_TOKEN": "onebot.access_token",
    "ONEBOT_PORT": "onebot.port",
}

EXAMPLE_NAME = "config.example.yaml"


# ---------------------------------------------------------------- 路径工具

def app_dir() -> Path:
    """exe（或脚本）所在目录，配置文件就放在这儿。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundled_example() -> Path:
    """打包时塞进 exe 的示例配置。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", app_dir()))
    else:
        base = app_dir()
    return base / EXAMPLE_NAME


# ---------------------------------------------------------------- 工具函数

def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _coerce(value: str) -> Any:
    """环境变量一律是字符串，这里尽量转成 bool/int/float。"""
    low = value.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low.isdigit() or (low.startswith("-") and low[1:].isdigit()):
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value


class Config:
    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path
        self.warnings: list[str] = []
        self.created = False  # 是不是本次运行才生成的配置

    # 点号取值：cfg.get("deepseek.model")
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def masked(self) -> dict:
        """打印用：把密钥打码。"""
        data = copy.deepcopy(self.data)
        for key in ("deepseek.api_key", "qqofficial.client_secret", "onebot.access_token"):
            value = str(self.get(key, "") or "")
            if value:
                self.set_masked(data, key, value[:4] + "*" * 8)
        return data

    @staticmethod
    def set_masked(data: dict, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


def load_config(path: str | None = None, verbose: bool = True) -> Config:
    """加载配置；文件不存在时自动从示例复制一份出来。"""
    created = False
    cfg_path: Path
    if path:
        cfg_path = Path(path).expanduser().resolve()
        if not cfg_path.exists():
            raise SystemExit(f"[配置] 找不到配置文件：{cfg_path}")
    else:
        cfg_path = app_dir() / "config.yaml"
        if not cfg_path.exists():
            example = bundled_example()
            if example.exists():
                cfg_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
                created = True
            else:
                raise SystemExit(
                    "[配置] 找不到 config.yaml，也没有内置示例。\n"
                    "       请把 config.example.yaml 复制为 config.yaml 并填写。"
                )

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"[配置] {cfg_path} 格式不对，顶层应该是键值对。")

    data = _deep_merge(DEFAULTS, raw)

    for env_key, dotted in ENV_OVERRIDES.items():
        value = os.environ.get(env_key)
        if value:
            data = _deep_merge(data, _nest(dotted, _coerce(value)))

    cfg = Config(data, cfg_path)
    cfg.created = created
    _validate(cfg, verbose)
    return cfg


def _nest(dotted: str, value: Any) -> dict:
    parts = dotted.split(".")
    out: dict[str, Any] = {}
    node = out
    for part in parts[:-1]:
        node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    return out


def _validate(cfg: Config, verbose: bool) -> None:
    backend = cfg.get("backend")
    if backend not in ("onebot", "qqofficial"):
        cfg.warnings.append(f"backend={backend!r} 不认识，只能是 onebot 或 qqofficial")

    if not cfg.get("deepseek.api_key"):
        cfg.warnings.append("deepseek.api_key 为空：机器人会回复“未配置 API Key”")

    if backend == "qqofficial":
        if not cfg.get("qqofficial.app_id") or not cfg.get("qqofficial.client_secret"):
            cfg.warnings.append("qqofficial 需要填 app_id 和 client_secret")

    if backend == "onebot":
        port = cfg.get("onebot.port")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            cfg.warnings.append(f"onebot.port={port!r} 不是合法端口")

    if verbose:
        for warning in cfg.warnings:
            print(f"[配置] 注意：{warning}")
