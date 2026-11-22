"""跨平台 TLS 配置。

macOS 上的 CPython 不带系统根证书，`ssl.create_default_context()` 会找不到
CA，导致访问 DeepSeek / QQ 开放平台时报 CERTIFICATE_VERIFY_FAILED。
这里统一优先使用 certifi 的证书包，两个平台行为一致；打包成 exe/app 后
证书文件也会被 PyInstaller 一起收进去。
"""

from __future__ import annotations

import logging
import ssl

log = logging.getLogger("bot.net")


def make_ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        log.warning("未安装 certifi，使用系统默认证书（macOS 上可能校验失败）")
        return None

    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as exc:  # noqa: BLE001 - 证书文件缺失之类
        log.warning("加载 certifi 证书失败（%s），退回系统默认", exc)
        return None
