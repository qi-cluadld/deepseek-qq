"""日志：控制台 + 滚动文件（logs/bot.log，UTF-8）。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _SafeStreamHandler(logging.StreamHandler):
    """Windows 控制台默认 GBK，遇到 emoji 会炸 —— 这里降级成替代字符。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                encoding = getattr(self.stream, "encoding", None) or "utf-8"
                self.stream.write(msg.encode(encoding, "replace").decode(encoding))
                self.stream.write(self.terminator)
                self.stream.flush()
            except Exception:  # noqa: BLE001 - 日志不能反过来把程序搞崩
                pass
        except Exception:  # noqa: BLE001
            self.handleError(record)


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)-10s %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    console = _SafeStreamHandler(stream=sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "bot.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:  # 只读目录之类，不致命
        print(f"[日志] 无法写入日志文件（{exc}），只输出到控制台。")

    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    return logging.getLogger("bot")
