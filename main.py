"""DeepSeek QQ 机器人 —— 程序入口。

用法：
    deepseek-qq.exe                 # 用 exe 同目录的 config.yaml 启动
    deepseek-qq.exe --config x.yaml
    deepseek-qq.exe --check         # 只检查配置，不启动
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
from pathlib import Path

import yaml

from app import __version__
from app.chat import ChatService
from app.config import app_dir, load_config
from app.deepseek import DeepSeekClient
from app.log import setup_logging

BANNER = r"""
  ____                 _     ____   ___  ____
 |  _ \  ___  ___  ___| | __/ ___| / _ \/ ___|
 | | | |/ _ \/ _ \/ __| |/ /\___ \| | | \___ \
 | |_| |  __/  __/\__ \   <  ___) | |_| |___) |
 |____/ \___|\___||___/_|\_\|____/ \__\_\____/
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepseek-qq",
        description="把 DeepSeek 接到 QQ 上（支持 NapCat/OneBot 和 QQ 官方机器人）",
    )
    parser.add_argument("-c", "--config", help="配置文件路径，默认用 exe 同目录的 config.yaml")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--check", action="store_true", help="只校验配置并打印，不启动")
    parser.add_argument("-v", "--version", action="version", version=f"deepseek-qq {__version__}")
    return parser


async def _run(cfg, logger) -> None:
    client = DeepSeekClient(
        api_key=cfg.get("deepseek.api_key", ""),
        base_url=cfg.get("deepseek.base_url", "https://api.deepseek.com"),
        model=cfg.get("deepseek.model", "deepseek-chat"),
        temperature=cfg.get("deepseek.temperature", 1.0),
        max_tokens=cfg.get("deepseek.max_tokens", 2048),
        timeout=cfg.get("deepseek.timeout", 60),
        retries=cfg.get("deepseek.retries", 2),
    )
    chat = ChatService(cfg, client)
    backend = cfg.get("backend", "onebot")

    try:
        if backend == "onebot":
            from app.onebot import OneBotServer

            logger.info("后端：OneBot v11（NapCat / Lagrange），模型：%s", client.model)
            await OneBotServer(cfg, chat).run()
        elif backend == "qqofficial":
            from app.qqofficial import QQOfficialBot

            logger.info("后端：QQ 官方机器人，模型：%s", client.model)
            await QQOfficialBot(cfg, chat).run()
        else:
            raise SystemExit(f"backend={backend!r} 不支持，只能是 onebot 或 qqofficial")
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    logger = setup_logging(app_dir() / "logs", args.log_level)

    if args.check:
        print(f"配置文件：{cfg.path}")
        print(yaml.safe_dump(cfg.masked(), allow_unicode=True, sort_keys=False))
        print("配置加载完成。")
        return 0

    if cfg.created:
        print(f"\n[配置] 已生成默认配置：{cfg.path}")
        print("[配置] 请用记事本打开它，至少填好两处：")
        print("       1) deepseek.api_key —— DeepSeek 的 API Key（sk- 开头）")
        print("       2) onebot.access_token 或 qqofficial 的 app_id/secret")
        print("[配置] 改完后再运行本程序即可。")
        return 0

    print(BANNER)
    print(f"  deepseek-qq {__version__}  |  Python {platform.python_version()}  "
          f"{platform.system()}  |  配置：{cfg.path}")
    print(f"  后端：{cfg.get('backend')}  模型：{cfg.get('deepseek.model')}")
    print("  按 Ctrl+C 退出\n")

    try:
        asyncio.run(_run(cfg, logger))
    except KeyboardInterrupt:
        print("\n已退出。")
    except SystemExit as exc:
        if exc.code:
            print(f"\n[错误] {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
