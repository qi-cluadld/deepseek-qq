"""QQ 官方机器人适配器（QQ 开放平台 / v2 接口）。

流程：appid+secret 换 access_token → 连 WebSocket → Identify → 心跳 →
收到 @ 消息事件 → 调 DeepSeek → 用被动回复接口回消息。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
import time
from typing import Any

import aiohttp

from .chat import ChatService, split_text

log = logging.getLogger("bot.qqofficial")

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

_MENTION_RE = re.compile(r"<@!?\d+>|<#\d+>")


class QQOfficialBot:
    def __init__(self, cfg, chat: ChatService):
        self.cfg = cfg
        self.chat = chat
        self.app_id = str(cfg.get("qqofficial.app_id", "") or "")
        self.client_secret = str(cfg.get("qqofficial.client_secret", "") or "")
        self.sandbox = bool(cfg.get("qqofficial.sandbox", False))
        self.intents = int(cfg.get("qqofficial.intents", 33570816))
        self.api_base = str(cfg.get("qqofficial.api_base", "https://api.sgroup.qq.com")).rstrip("/")
        self.token_url = str(
            cfg.get("qqofficial.token_url", "https://bots.qq.com/app/getAppAccessToken")
        )
        self.ws_url = str(cfg.get("qqofficial.ws_url", "") or "") or (
            "wss://sandbox.api.sgroup.qq.com/websocket"
            if self.sandbox
            else "wss://api.sgroup.qq.com/websocket"
        )
        self.max_reply_chars = int(cfg.get("qqofficial.max_reply_chars", 1800))

        self._session: aiohttp.ClientSession | None = None
        self._token = ""
        self._token_expire_at = 0.0
        self._session_id: str | None = None
        self._last_seq: int | None = None
        self._msg_seq = itertools.count(1)

    # ------------------------------------------------------------ 主循环

    async def run(self) -> None:
        if not self.app_id or not self.client_secret:
            raise SystemExit(
                "[官方机器人] 缺少 app_id / client_secret。\n"
                "           去 https://q.qq.com 创建机器人 → 开发设置 里拿，填进 config.yaml。"
            )
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        log.info("QQ 官方机器人启动中：app_id=%s，环境=%s",
                 self.app_id, "沙箱" if self.sandbox else "正式")
        backoff = 1.0
        try:
            while True:
                try:
                    await self._connect_once()
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 断线重连是常态
                    log.warning("连接中断（%s），%.0fs 后重连", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
        finally:
            if self._session and not self._session.closed:
                await self._session.close()

    async def _connect_once(self) -> None:
        token = await self._get_token()
        async with self._session.ws_connect(self.ws_url, heartbeat=None) as ws:
            log.info("已连接游戏网关：%s", self.ws_url)
            await self._ws_loop(ws, token)

    # ------------------------------------------------------------ 网关协议

    async def _ws_loop(self, ws: aiohttp.ClientWebSocketResponse, token: str) -> None:
        heartbeat_task: asyncio.Task | None = None
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    op = payload.get("op")
                    seq = payload.get("s")
                    if isinstance(seq, int):
                        self._last_seq = seq

                    if op == OP_HELLO:
                        interval = float(payload.get("d", {}).get("heartbeat_interval", 41250)) / 1000
                        if heartbeat_task:
                            heartbeat_task.cancel()
                        heartbeat_task = asyncio.create_task(self._heartbeat(ws, interval))
                        if self._session_id and self._last_seq is not None:
                            await self._send(ws, {
                                "op": OP_RESUME,
                                "d": {
                                    "token": f"QQBot {token}",
                                    "session_id": self._session_id,
                                    "seq": self._last_seq,
                                },
                            })
                            log.info("尝试恢复会话 %s", self._session_id)
                        else:
                            await self._send(ws, {
                                "op": OP_IDENTIFY,
                                "d": {
                                    "token": f"QQBot {token}",
                                    "intents": self.intents,
                                    "shard": [0, 1],
                                    "properties": {},
                                },
                            })

                    elif op == OP_DISPATCH:
                        await self._on_dispatch(payload.get("t", ""), payload.get("d") or {})

                    elif op == OP_HEARTBEAT_ACK:
                        log.debug("心跳正常，seq=%s", self._last_seq)

                    elif op == OP_RECONNECT:
                        log.warning("服务器要求重连")
                        return

                    elif op == OP_INVALID_SESSION:
                        log.warning("会话失效，重新鉴权")
                        self._session_id = None
                        self._last_seq = None
                        return

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.warning("WS 错误：%s", ws.exception())
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE):
                    log.info("网关连接关闭（code=%s）", ws.close_code)
                    self._explain_close(ws.close_code)
                    return
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self._send(ws, {"op": OP_HEARTBEAT, "d": self._last_seq})
            except Exception:  # noqa: BLE001
                return

    async def _on_dispatch(self, event: str, data: dict[str, Any]) -> None:
        if event == "READY":
            self._session_id = data.get("session_id")
            user = (data.get("user") or {}).get("username")
            log.info("鉴权成功，机器人：%s（session=%s）", user, self._session_id)
            return
        if event == "RESUMED":
            log.info("会话已恢复")
            return
        handler = {
            "GROUP_AT_MESSAGE_CREATE": self._on_group_at,
            "CQ_C2C_MESSAGE_CREATE": self._on_c2c,
            "C2C_MESSAGE_CREATE": self._on_c2c,
            "AT_MESSAGE_CREATE": self._on_guild_at,
            "DIRECT_MESSAGE_CREATE": self._on_direct,
        }.get(event)
        if handler:
            asyncio.create_task(handler(data))

    # ------------------------------------------------------------ 各场景消息

    async def _on_group_at(self, data: dict[str, Any]) -> None:
        group_openid = str(data.get("group_openid", ""))
        author = data.get("author") or {}
        user_openid = str(author.get("member_openid", ""))
        msg_id = str(data.get("id", ""))
        text = self._clean(data.get("content", ""))
        if not text:
            return
        log.info("群[%s] %s: %s", group_openid, user_openid, text[:60])
        reply = await self.chat.handle(f"qgroup:{group_openid}:{user_openid}", text)
        if reply:
            await self._send_group_text(group_openid, msg_id, reply)

    async def _on_c2c(self, data: dict[str, Any]) -> None:
        author = data.get("author") or {}
        user_openid = str(author.get("user_openid", "") or author.get("id", ""))
        msg_id = str(data.get("id", ""))
        text = self._clean(data.get("content", ""))
        if not text:
            return
        log.info("私聊[%s]: %s", user_openid, text[:60])
        reply = await self.chat.handle(f"qc2c:{user_openid}", text)
        if reply:
            await self._send_c2c_text(user_openid, msg_id, reply)

    async def _on_guild_at(self, data: dict[str, Any]) -> None:
        channel_id = str(data.get("channel_id", ""))
        author = data.get("author") or {}
        user_id = str(author.get("id", ""))
        msg_id = str(data.get("id", ""))
        text = self._clean(data.get("content", ""))
        if not text:
            return
        log.info("频道[%s] %s: %s", channel_id, user_id, text[:60])
        reply = await self.chat.handle(f"guild:{channel_id}:{user_id}", text)
        if not reply:
            return
        for chunk in split_text(reply, self.max_reply_chars):
            ok = await self._api_post(
                f"/channels/{channel_id}/messages",
                {"content": chunk, "msg_id": msg_id},
            )
            if not ok:
                break

    async def _on_direct(self, data: dict[str, Any]) -> None:
        guild_id = str(data.get("guild_id", ""))
        author = data.get("author") or {}
        user_id = str(author.get("id", ""))
        msg_id = str(data.get("id", ""))
        text = self._clean(data.get("content", ""))
        if not text:
            return
        reply = await self.chat.handle(f"qdm:{guild_id}:{user_id}", text)
        if not reply:
            return
        for chunk in split_text(reply, self.max_reply_chars):
            ok = await self._api_post(
                f"/dms/{guild_id}/messages", {"content": chunk, "msg_id": msg_id}
            )
            if not ok:
                break

    # ------------------------------------------------------------ 发送

    async def _send_group_text(self, group_openid: str, msg_id: str, text: str) -> None:
        for chunk in split_text(text, self.max_reply_chars):
            ok = await self._api_post(
                f"/v2/groups/{group_openid}/messages",
                {
                    "content": chunk,
                    "msg_type": 0,
                    "msg_id": msg_id,
                    "msg_seq": next(self._msg_seq) % 1_000_000,
                },
            )
            if not ok:
                log.warning("群消息发送失败：%s", chunk[:40])
                break
            log.info("群消息已发送 %d 字", len(chunk))

    async def _send_c2c_text(self, user_openid: str, msg_id: str, text: str) -> None:
        for chunk in split_text(text, self.max_reply_chars):
            ok = await self._api_post(
                f"/v2/users/{user_openid}/messages",
                {
                    "content": chunk,
                    "msg_type": 0,
                    "msg_id": msg_id,
                    "msg_seq": next(self._msg_seq) % 1_000_000,
                },
            )
            if not ok:
                log.warning("私聊消息发送失败：%s", chunk[:40])
                break
            log.info("私聊消息已发送 %d 字", len(chunk))

    # ------------------------------------------------------------ HTTP / 鉴权

    async def _api_post(self, path: str, body: dict[str, Any]) -> bool:
        token = await self._get_token()
        headers = {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}
        try:
            async with self._session.post(self.api_base + path, json=body, headers=headers) as resp:
                text = await resp.text()
                if resp.status in (200, 201, 204):
                    return True
                # token 失效时强制刷新一次再试
                if resp.status == 401:
                    self._token_expire_at = 0.0
                    token = await self._get_token()
                    headers["Authorization"] = f"QQBot {token}"
                    async with self._session.post(
                        self.api_base + path, json=body, headers=headers
                    ) as retry:
                        if retry.status in (200, 201, 204):
                            return True
                        log.warning("发送失败 %s：%s", retry.status, (await retry.text())[:200])
                        return False
                log.warning("发送失败 %s：%s", resp.status, text[:200])
                return False
        except aiohttp.ClientError as exc:
            log.warning("发送请求异常：%r", exc)
            return False

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expire_at:
            return self._token

        payload = {"appId": self.app_id, "clientSecret": self.client_secret}
        try:
            async with self._session.post(self.token_url, json=payload) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"获取 token 失败（HTTP {resp.status}）：{text[:200]}")
                data = json.loads(text)
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"连不上开放平台：{exc!r}") from exc

        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"获取 token 失败：{text[:200]}")
        expires_in = int(data.get("expires_in", 7200) or 7200)
        self._token = token
        self._token_expire_at = time.time() + max(60, expires_in - 120)
        log.info("access_token 已更新（%d 秒后过期）", expires_in)
        return token

    @staticmethod
    async def _send(ws: aiohttp.ClientWebSocketResponse, payload: dict[str, Any]) -> None:
        await ws.send_json(payload)

    @staticmethod
    def _clean(content: Any) -> str:
        text = str(content or "")
        text = _MENTION_RE.sub(" ", text)
        return " ".join(text.split())

    @staticmethod
    def _explain_close(code: int | None) -> None:
        hints = {
            4004: "鉴权失败：token 无效",
            4013: "intents 参数不合法",
            4014: "intents 没有权限（去开放平台勾选对应事件）",
            4914: "机器人已下架，只能连接沙箱",
            4915: "机器人已被封禁",
        }
        if code in hints:
            log.error("连接关闭原因：%s", hints[code])
