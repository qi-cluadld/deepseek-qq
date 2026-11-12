"""DeepSeek 对话接口（OpenAI 兼容 /chat/completions）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger("bot.deepseek")


class DeepSeekError(Exception):
    """带中文提示的异常，直接可以回给用户。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


_RETRY_STATUS = {429, 500, 502, 503, 504}


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        temperature: float = 1.0,
        max_tokens: int = 2048,
        timeout: float = 60,
        retries: int = 2,
    ):
        self.api_key = (api_key or "").strip()
        self.endpoint = self._build_endpoint(base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self._session: aiohttp.ClientSession | None = None

    @staticmethod
    def _build_endpoint(base_url: str) -> str:
        url = (base_url or "https://api.deepseek.com").strip().rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return url + "/chat/completions"
        return url + "/v1/chat/completions"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """发送一轮对话，返回助手回复文本。"""
        if not self.api_key:
            raise DeepSeekError("未配置 API Key")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                session = await self._get_session()
                async with session.post(self.endpoint, json=payload, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status == 200:
                        return self._extract(text)
                    if resp.status in _RETRY_STATUS and attempt < self.retries:
                        wait = 1.5 * (attempt + 1)
                        log.warning(
                            "DeepSeek 返回 %s，%.1fs 后重试（%d/%d）：%s",
                            resp.status, wait, attempt + 1, self.retries, text[:200],
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise DeepSeekError(self._http_error(resp.status, text))

            except asyncio.TimeoutError:
                last_error = DeepSeekError("响应超时")
                if attempt < self.retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
            except aiohttp.ClientConnectorError as exc:
                last_error = DeepSeekError("连不上 DeepSeek，检查网络或代理设置")
                log.warning("连接失败：%s", exc)
                if attempt < self.retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
            except aiohttp.ClientError as exc:
                last_error = DeepSeekError("网络异常")
                log.warning("请求异常：%r", exc)
                if attempt < self.retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue

        raise last_error or DeepSeekError("请求失败")

    @staticmethod
    def _extract(body: str) -> str:
        import json

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise DeepSeekError("返回内容无法解析") from None

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise DeepSeekError("返回内容为空") from None

        content = (content or "").strip()
        if not content:
            raise DeepSeekError("模型没有给出回复")
        return content

    @staticmethod
    def _http_error(status: int, body: str) -> str:
        detail = ""
        try:
            import json

            detail = str(json.loads(body).get("error", {}).get("message", ""))[:120]
        except Exception:  # noqa: BLE001
            detail = body[:120]

        mapping = {
            400: "请求参数有误",
            401: "API Key 无效",
            402: "账户余额不足",
            403: "没有访问权限",
            404: "接口地址不对，检查 base_url",
            422: "请求参数有误",
            429: "请求太频繁，被限流了",
        }
        head = mapping.get(status, f"服务返回 {status}")
        return f"{head}：{detail}" if detail else head
