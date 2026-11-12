"""会话管理 + 对话编排（多轮上下文、限流、并发保护、命令）。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .deepseek import DeepSeekClient, DeepSeekError

log = logging.getLogger("bot.chat")

HELP_TEXT = (
    "我是接入了 DeepSeek 的 QQ 助手，直接发消息就能聊。\n"
    "可用命令：\n"
    "/reset 或 /clear —— 清空当前对话上下文，重新开始\n"
    "/help —— 看这条帮助"
)


@dataclass
class Session:
    messages: list[dict[str, str]] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_active = time.time()


class ChatService:
    def __init__(self, cfg, client: DeepSeekClient):
        self.cfg = cfg
        self.client = client
        self.system_prompt = cfg.get("deepseek.system_prompt", "")
        self.history_turns = int(cfg.get("chat.history_turns", 10))
        self.ttl = float(cfg.get("chat.session_ttl_minutes", 30)) * 60
        self.max_sessions = int(cfg.get("chat.max_sessions", 500))
        self.cooldown = float(cfg.get("chat.cooldown_seconds", 1.5))
        self.max_concurrent = int(cfg.get("chat.max_concurrent", 4))
        self.busy_reply = cfg.get("chat.busy_reply", "稍等，我这边有点忙~")
        self.cooldown_reply = cfg.get("chat.cooldown_reply", "慢一点~")
        self.error_reply = cfg.get("chat.error_reply", "出错了（{reason}）")

        self._sessions: dict[str, Session] = {}
        self._last_request: dict[str, float] = {}
        self._sem = asyncio.Semaphore(self.max_concurrent)

    # ------------------------------------------------------------ 对外入口

    async def handle(self, key: str, text: str) -> str | None:
        """返回要发回 QQ 的文本；返回 None 表示不回复。"""
        text = (text or "").strip()
        if not text:
            return None

        command = text.split()[0].lower() if text else ""
        if command in ("/help", "/?", "help"):
            return HELP_TEXT
        if command in ("/reset", "/clear", "/new"):
            self._sessions.pop(key, None)
            return "上下文已清空，我们重新开始聊吧。"

        now = time.time()
        last = self._last_request.get(key, 0.0)
        if now - last < self.cooldown:
            return self.cooldown_reply
        self._last_request[key] = now

        # 限制并发：拿不到信号量就直接回“忙”，不排队堆积
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=0.05)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return self.busy_reply

        try:
            session = self._get_session(key)
            session.messages.append({"role": "user", "content": text})
            payload = self._build_payload(session)

            log.info("→ DeepSeek [%s] %s", key, _preview(text))
            started = time.perf_counter()
            try:
                reply = await self.client.chat(payload)
            except DeepSeekError as exc:
                session.messages.pop()  # 失败的这轮别留在上下文里
                log.warning("DeepSeek 失败 [%s]：%s", key, exc.message)
                return self.error_reply.format(reason=exc.message)

            elapsed = time.perf_counter() - started
            session.messages.append({"role": "assistant", "content": reply})
            self._trim(session)
            session.touch()
            self._evict_if_needed()
            log.info("← DeepSeek [%s] %.1fs %s", key, elapsed, _preview(reply))
            return reply
        finally:
            self._sem.release()

    # ------------------------------------------------------------ 内部

    def _get_session(self, key: str) -> Session:
        session = self._sessions.get(key)
        if session is None or time.time() - session.last_active > self.ttl:
            if session is not None:
                log.info("会话 [%s] 闲置超时，上下文已重置", key)
            session = Session()
            self._sessions[key] = session
        return session

    def _build_payload(self, session: Session) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        if self.system_prompt:
            payload.append({"role": "system", "content": self.system_prompt})
        payload.extend(session.messages)
        return payload

    def _trim(self, session: Session) -> None:
        keep = max(1, self.history_turns) * 2
        if len(session.messages) > keep:
            session.messages = session.messages[-keep:]

    def _evict_if_needed(self) -> None:
        overflow = len(self._sessions) - self.max_sessions
        if overflow <= 0:
            return
        # 按最后活跃时间淘汰最老的
        ordered = sorted(self._sessions.items(), key=lambda kv: kv[1].last_active)
        for key, _ in ordered[:overflow]:
            self._sessions.pop(key, None)
            self._last_request.pop(key, None)
        log.info("会话数超过上限，清理了 %d 个最旧会话", overflow)


def _preview(text: str, limit: int = 60) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def split_text(text: str, limit: int) -> list[str]:
    """把长回复切成若干条不超过 limit 的短消息，尽量在换行/句号处断开。"""
    if limit <= 0 or len(text) <= limit:
        return [text]

    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(
            window.rfind("\n"),
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("；"),
            window.rfind(" "),
        )
        if cut < limit // 2:  # 断点太靠前就硬切
            cut = limit
        else:
            cut += 1
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest.strip():
        chunks.append(rest.strip())
    return [c for c in chunks if c]
