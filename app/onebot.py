"""OneBot v11 反向 WebSocket 适配器（NapCat / Lagrange / LLOneBot 通用）。"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from typing import Any

from aiohttp import WSMsgType, web

from .chat import ChatService, split_text

log = logging.getLogger("bot.onebot")

_CQ_RE = re.compile(r"\[CQ:[^\]]*\]")


class OneBotServer:
    def __init__(self, cfg, chat: ChatService):
        self.cfg = cfg
        self.chat = chat
        self.host = str(cfg.get("onebot.host", "0.0.0.0"))
        self.port = int(cfg.get("onebot.port", 6700))
        path = str(cfg.get("onebot.path", "/onebot") or "/onebot")
        self.path = path if path.startswith("/") else "/" + path
        self.access_token = str(cfg.get("onebot.access_token", "") or "")
        self.group_need_at = bool(cfg.get("onebot.group_need_at", True))
        self.group_prefix = str(cfg.get("onebot.group_prefix", "#") or "")
        self.private_enabled = bool(cfg.get("onebot.private_enabled", True))
        self.max_reply_chars = int(cfg.get("chat.max_reply_chars", 1500))

        self._echo = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._conns: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------ 生命周期

    async def run(self) -> None:
        app = web.Application()
        app.router.add_get(self.path, self._handle_ws)
        app.router.add_get("/", self._handle_root)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await site.start()
        except OSError as exc:
            raise SystemExit(
                f"[OneBot] 端口 {self.port} 监听失败（{exc}）。"
                f"改一下 config.yaml 里的 onebot.port，或关掉占用该端口的程序。"
            ) from exc

        log.info("OneBot 反向 WS 已启动：ws://%s:%d%s", self.host, self.port, self.path)
        log.info("在 NapCat 里把它配成「反向 WebSocket 服务器」，地址填上面这个 URL。")
        try:
            await asyncio.Event().wait()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        for ws in list(self._conns):
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._runner is not None:
            await self._runner.cleanup()

    async def _handle_root(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "service": "deepseek-qq (onebot v11)",
                "ws": self.path,
                "connections": len(self._conns),
            }
        )

    # ------------------------------------------------------------ WS 连接

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        if not self._authorized(request):
            log.warning("拒绝连接：访问令牌不匹配（来自 %s）", request.remote)
            return web.Response(status=401, text="unauthorized")

        ws = web.WebSocketResponse(heartbeat=60.0, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self._conns.add(ws)
        self_id = request.headers.get("X-Self-ID", "?")
        log.info("QQ 端已连接（self_id=%s，来自 %s），共 %d 个连接",
                 self_id, request.remote, len(self._conns))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._on_text(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning("WS 异常：%s", ws.exception())
        finally:
            self._conns.discard(ws)
            log.info("QQ 端断开（self_id=%s），剩余 %d 个连接", self_id, len(self._conns))
        return ws

    def _authorized(self, request: web.Request) -> bool:
        if not self.access_token:
            return True
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer ") and header[7:].strip() == self.access_token:
            return True
        return request.query.get("access_token", "") == self.access_token

    async def _on_text(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("收到非 JSON 消息：%s", raw[:200])
            return
        if not isinstance(data, dict):
            return

        # 1) 这是对我们某个 API 调用的回执
        echo = data.get("echo")
        if echo is not None and "post_type" not in data:
            future = self._pending.pop(int(echo), None)
            if future and not future.done():
                future.set_result(data)
            if data.get("status") == "failed":
                log.warning("API 调用失败：%s", data.get("wording") or data.get("retcode"))
            return

        post_type = data.get("post_type")
        # 2) 新消息：丢给后台任务处理，别堵住收包
        if post_type == "message" and data.get("message_type") in ("private", "group"):
            asyncio.create_task(self._on_message(ws, data))
        elif post_type == "meta_event":
            meta = data.get("meta_event_type")
            if meta == "lifecycle":
                log.info("QQ 端生命周期事件：%s", data.get("sub_type"))
        elif post_type == "message_sent":
            pass  # 自己发的消息，忽略

    # ------------------------------------------------------------ 消息处理

    async def _on_message(self, ws: web.WebSocketResponse, event: dict[str, Any]) -> None:
        if str(event.get("user_id")) == str(event.get("self_id")):
            return

        self_id = event.get("self_id")
        msg_type = event.get("message_type")
        user_id = event.get("user_id")
        group_id = event.get("group_id")
        nick = (event.get("sender") or {}).get("card") or (event.get("sender") or {}).get("nickname") or ""

        text, at_me = parse_message(event, self_id)

        if msg_type == "group":
            if self.group_prefix and text.lstrip().startswith(self.group_prefix):
                text = text.lstrip()[len(self.group_prefix):].lstrip()
            elif at_me:
                pass
            elif not self.group_need_at:
                pass
            else:
                return  # 群里没 @ 也没前缀，不插嘴
        elif msg_type == "private":
            if not self.private_enabled:
                return
        else:
            return

        text = text.strip()
        if not text:
            if at_me:  # 只 @ 了没说话
                await self._send_text(ws, msg_type, group_id, user_id, "在呢，想聊点什么？")
            return

        log.info("收到[%s] %s(%s): %s", msg_type, nick or user_id, user_id, text[:80])

        key = f"group:{group_id}:{user_id}" if msg_type == "group" else f"private:{user_id}"
        reply = await self.chat.handle(key, text)
        if not reply:
            return

        for chunk in split_text(reply, self.max_reply_chars):
            await self._send_text(ws, msg_type, group_id, user_id, chunk)

    async def _send_text(
        self,
        ws: web.WebSocketResponse,
        msg_type: str,
        group_id: Any,
        user_id: Any,
        text: str,
    ) -> None:
        # 用消息段数组发送，用户内容里的 [CQ:...] 不会被当成指令
        message = [{"type": "text", "data": {"text": text}}]
        if msg_type == "group":
            action = "send_group_msg"
            params = {"group_id": group_id, "message": message}
        else:
            action = "send_private_msg"
            params = {"user_id": user_id, "message": message}

        result = await self.call_action(ws, action, params, timeout=15)
        if result is None:
            log.warning("发送失败（超时）：%s", text[:40])
        else:
            log.info("已发送 %d 字", len(text))

    async def call_action(
        self,
        ws: web.WebSocketResponse,
        action: str,
        params: dict[str, Any],
        timeout: float = 15.0,
    ) -> dict[str, Any] | None:
        echo = next(self._echo)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        try:
            await ws.send_json({"action": action, "params": params, "echo": echo})
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            log.debug("动作 %s 等待回执超时（部分实现不回 echo，不影响发送）", action)
            return None
        finally:
            self._pending.pop(echo, None)


# ---------------------------------------------------------------- 消息解析

def parse_message(event: dict[str, Any], self_id: Any) -> tuple[str, bool]:
    """返回 (纯文本, 是否 @ 了机器人)。兼容数组格式和 CQ 码字符串格式。"""
    message = event.get("message")
    self_id_str = str(self_id)

    if isinstance(message, list):
        parts: list[str] = []
        at_me = False
        for seg in message:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type")
            data = seg.get("data") or {}
            if seg_type == "text":
                parts.append(str(data.get("text", "")))
            elif seg_type == "at":
                if str(data.get("qq", "")) == self_id_str:
                    at_me = True
                parts.append(" ")
            elif seg_type == "image":
                parts.append("[图片]")
            elif seg_type == "face":
                parts.append(" ")
            # reply / mface / json / xml 等一律忽略
        return "".join(parts), at_me

    text = str(message or "")
    at_me = bool(
        re.search(rf"\[CQ:at,qq={re.escape(self_id_str)}(?:,[^\]]*)?\]", text)
    )
    text = re.sub(r"\[CQ:at,qq=[^\]]*\]", " ", text)
    text = re.sub(r"\[CQ:image,[^\]]*\]", "[图片]", text)
    text = _CQ_RE.sub("", text)
    text = (
        text.replace("&#91;", "[")
        .replace("&#93;", "]")
        .replace("&#44;", ",")
        .replace("&amp;", "&")
    )
    return text, at_me
