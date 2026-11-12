"""端到端自测：用本地假服务器驱动打包好的 exe，验证两条后端链路。

    python tests/e2e.py [exe路径]

覆盖：
  A. OneBot 后端：鉴权、私聊、群聊@、群聊无@不回复、多轮上下文、长文分条、错误兜底
  B. 官方机器人后端：换 token、Identify、心跳、群@消息 → 被动回复

不需要真实 QQ、不需要联网、不需要 DeepSeek Key。
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "deepseek-qq.exe"

DS_PORT = 18080
QQ_API_PORT = 18082
QQ_WS_PORT = 18083
ONEBOT_PORT = 18081

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


# ---------------------------------------------------------------- 假 DeepSeek

class MockDeepSeek:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.requests.append(body)
        messages = body.get("messages", [])
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "长文" in last:
            content = "这是一个很长的回答。" * 40
        elif "故障" in last:
            return web.json_response({"error": {"message": "server exploded"}}, status=500)
        else:
            content = f"回声:{last}|上下文{len(messages)}条"
        return web.json_response(
            {"id": "mock", "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}
        )


# ---------------------------------------------------------------- 假 QQ 官方服务

class MockQQ:
    def __init__(self) -> None:
        self.identify: dict | None = None
        self.heartbeats = 0
        self.posts: list[tuple[str, dict]] = []
        self.message_sent = asyncio.Event()
        self.heartbeat_seen = asyncio.Event()

    async def token(self, request: web.Request) -> web.Response:
        body = await request.json()
        if body.get("appId") != "102000000" or body.get("clientSecret") != "secret":
            return web.json_response({"code": 100016, "message": "bad appid"}, status=400)
        return web.json_response({"access_token": "tok123", "expires_in": 7200})

    async def group_message(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.posts.append((request.path, body))
        self.message_sent.set()
        return web.json_response({"id": "sent-1", "timestamp": "2026-01-01T00:00:00Z"})

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=None)
        await ws.prepare(request)
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": 2000}})

        async def pump() -> None:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                op = data.get("op")
                if op == 2:  # Identify
                    self.identify = data.get("d", {})
                    await ws.send_json(
                        {"op": 0, "s": 1, "t": "READY",
                         "d": {"session_id": "sess-1", "user": {"username": "TestBot"}}}
                    )
                    await asyncio.sleep(0.3)
                    await ws.send_json({
                        "op": 0, "s": 2, "t": "GROUP_AT_MESSAGE_CREATE",
                        "d": {
                            "id": "msg-1",
                            "content": " 你好呀",
                            "group_openid": "group-1",
                            "author": {"member_openid": "user-1"},
                        },
                    })
                elif op == 1:  # Heartbeat
                    self.heartbeats += 1
                    self.heartbeat_seen.set()
                    await ws.send_json({"op": 11})

        try:
            await pump()
        finally:
            await ws.close()
        return ws


# ---------------------------------------------------------------- 工具

def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


async def wait_port(port: int, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        await asyncio.sleep(0.2)
    return False


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def kill_stale() -> None:
    """onefile 的引导进程被杀后，子进程会残留 —— 连进程树一起清掉。"""
    import subprocess

    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", EXE.name],
        capture_output=True, check=False,
    )


async def ensure_port_free(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_open(port):
            return
        await asyncio.sleep(0.2)


class ExeProcess:
    def __init__(self, config: Path, tag: str, log_dir: Path):
        self.config = config
        self.tag = tag
        self.log_dir = log_dir
        self.proc: asyncio.subprocess.Process | None = None
        self._out = None

    async def __aenter__(self) -> "ExeProcess":
        kill_stale()
        out_path = self.log_dir / f"{self.tag}.out.log"
        self._out = open(out_path, "wb")
        self.proc = await asyncio.create_subprocess_exec(
            str(EXE), "--config", str(self.config), "--log-level", "DEBUG",
            stdout=self._out, stderr=asyncio.subprocess.STDOUT,
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        kill_stale()
        if self._out:
            self._out.close()


async def collect_actions(ws, timeout: float) -> list[dict]:
    """收 N 秒内的 OneBot 动作，顺手把 echo 回执补上。"""
    actions: list[dict] = []
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return actions
        try:
            msg = await ws.receive(timeout=remaining)
        except asyncio.TimeoutError:
            return actions
        if msg.type != aiohttp.WSMsgType.TEXT:
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                return actions
            continue
        data = json.loads(msg.data)
        if "action" in data:
            actions.append(data)
            await ws.send_json({"status": "ok", "retcode": 0, "data": {"message_id": 1},
                                "echo": data.get("echo")})


def action_texts(actions: list[dict]) -> list[str]:
    out = []
    for item in actions:
        params = item.get("params") or {}
        message = params.get("message") or []
        if isinstance(message, list):
            out.append("".join(
                seg.get("data", {}).get("text", "")
                for seg in message
                if isinstance(seg, dict) and seg.get("type") == "text"
            ))
    return out


def private_event(text: str, user: int) -> dict:
    return {
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "self_id": 10000, "user_id": user, "message_id": 1, "raw_message": text,
        "message": [{"type": "text", "data": {"text": text}}],
        "sender": {"user_id": user, "nickname": "tester"},
    }


def group_event(segments: list[dict], user: int, group: int = 20002) -> dict:
    return {
        "post_type": "message", "message_type": "group", "sub_type": "normal",
        "self_id": 10000, "user_id": user, "group_id": group, "message_id": 2,
        "message": segments, "sender": {"user_id": user, "card": "群友"},
    }


# ---------------------------------------------------------------- 测试 A：OneBot

ONEBOT_CONFIG = """\
backend: onebot
deepseek:
  api_key: "sk-test"
  base_url: "http://127.0.0.1:{ds}"
  model: "deepseek-chat"
  timeout: 10
  retries: 0
chat:
  cooldown_seconds: 0
  max_reply_chars: 100
  history_turns: 5
onebot:
  host: "127.0.0.1"
  port: {port}
  path: "/onebot"
  access_token: "test-token"
  group_need_at: true
  group_prefix: "#"
""".format(ds=DS_PORT, port=ONEBOT_PORT)


async def test_onebot(work: Path) -> None:
    print("\n[A] OneBot 后端")
    cfg = write_config(work / "onebot.yaml", ONEBOT_CONFIG)
    await ensure_port_free(ONEBOT_PORT)
    try:
        async with ExeProcess(cfg, "onebot", work):
            if not await wait_port(ONEBOT_PORT):
                check("exe 启动并监听 WS 端口", False, f"端口 {ONEBOT_PORT} 未打开")
                return
            check("exe 启动并监听 WS 端口", True)

            # 1) 令牌校验
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect(f"ws://127.0.0.1:{ONEBOT_PORT}/onebot",
                                                  headers={"Authorization": "Bearer wrong"}):
                        check("错误 token 被拒绝", False, "竟然连上了")
                except aiohttp.WSServerHandshakeError as exc:
                    check("错误 token 被拒绝", exc.status == 401, f"HTTP {exc.status}")

                async with session.ws_connect(
                    f"ws://127.0.0.1:{ONEBOT_PORT}/onebot",
                    headers={"Authorization": "Bearer test-token", "X-Self-ID": "10000"},
                ) as ws:
                    # 2) 私聊
                    await ws.send_json(private_event("你好", 10001))
                    actions = await collect_actions(ws, 8)
                    texts = action_texts(actions)
                    check("私聊有回复", bool(texts), f"收到 {actions}")
                    if texts:
                        check("私聊回复内容正确", texts[0] == "回声:你好|上下文2条", texts[0])
                        check("用的是 send_private_msg", actions[0].get("action") == "send_private_msg",
                              actions[0].get("action"))

                    # 3) 多轮上下文
                    await ws.send_json(private_event("第二句", 10001))
                    actions = await collect_actions(ws, 8)
                    texts = action_texts(actions)
                    if texts:
                        check("多轮上下文已带上历史", texts[0] == "回声:第二句|上下文4条", texts[0])
                    else:
                        check("多轮上下文已带上历史", False, "没有回复")

                    # 4) 群聊没 @ 不插嘴
                    await ws.send_json(group_event(
                        [{"type": "text", "data": {"text": "大家好"}}], 10002))
                    actions = await collect_actions(ws, 3)
                    check("群聊未@不回复", not actions, f"却收到了 {actions}")

                    # 5) 群聊 @ 机器人
                    await ws.send_json(group_event([
                        {"type": "at", "data": {"qq": "10000"}},
                        {"type": "text", "data": {"text": " 在吗"}},
                    ], 10003))
                    actions = await collect_actions(ws, 8)
                    texts = action_texts(actions)
                    check("群聊@有回复", bool(texts), f"收到 {actions}")
                    if actions:
                        check("用的是 send_group_msg", actions[0].get("action") == "send_group_msg",
                              actions[0].get("action"))
                        check("群里 @ 已被剥离", texts and "回声:在吗" in texts[0], texts[0] if texts else "")

                    # 6) 群聊用 # 前缀触发
                    await ws.send_json(group_event(
                        [{"type": "text", "data": {"text": "# 前缀触发"}}], 10004))
                    actions = await collect_actions(ws, 8)
                    texts = action_texts(actions)
                    check("# 前缀可触发", bool(texts) and "回声:前缀触发" in texts[0],
                          texts[0] if texts else "无回复")

                    # 7) 长文自动分条
                    await ws.send_json(private_event("讲个长文", 10005))
                    actions = await collect_actions(ws, 10)
                    texts = [t for t in action_texts(actions) if t]
                    check("长回复自动拆成多条", len(texts) >= 2, f"只发了 {len(texts)} 条")
                    check("分条后每条不超长", all(len(t) <= 100 for t in texts),
                          f"最长 {max((len(t) for t in texts), default=0)}")

                    # 8) /reset 清空上下文
                    await ws.send_json(private_event("/reset", 10006))
                    actions = await collect_actions(ws, 6)
                    texts = action_texts(actions)
                    check("/reset 有提示", bool(texts) and "清空" in texts[0], texts[0] if texts else "")

                    # 9) 上游报错兜底
                    await ws.send_json(private_event("制造故障", 10007))
                    actions = await collect_actions(ws, 10)
                    texts = action_texts(actions)
                    check("上游 500 时给出友好提示",
                          bool(texts) and "故障" in texts[0] and "server exploded" in texts[0],
                          texts[0] if texts else "无回复")
    finally:
        pass


# ---------------------------------------------------------------- 测试 B：官方机器人

QQ_CONFIG = """\
backend: qqofficial
deepseek:
  api_key: "sk-test"
  base_url: "http://127.0.0.1:{ds}"
  model: "deepseek-chat"
  timeout: 10
  retries: 0
chat:
  cooldown_seconds: 0
qqofficial:
  app_id: "102000000"
  client_secret: "secret"
  ws_url: "ws://127.0.0.1:{ws}/websocket"
  api_base: "http://127.0.0.1:{api}"
  token_url: "http://127.0.0.1:{api}/app/getAppAccessToken"
""".format(ds=DS_PORT, ws=QQ_WS_PORT, api=QQ_API_PORT)


async def test_qqofficial(work: Path, mock_qq: MockQQ) -> None:
    print("\n[B] QQ 官方机器人后端")
    cfg = write_config(work / "qq.yaml", QQ_CONFIG)
    async with ExeProcess(cfg, "qqofficial", work):
        try:
            await asyncio.wait_for(mock_qq.message_sent.wait(), timeout=45)
        except asyncio.TimeoutError:
            check("官方机器人收到群消息并回复", False, "45 秒内没等到回复，见 qqofficial.out.log")
            return

        check("官方机器人收到群消息并回复", True)
        check("Identify 带上了 QQBot token",
              (mock_qq.identify or {}).get("token") == "QQBot tok123",
              str(mock_qq.identify))
        check("Identify 带上了 intents",
              (mock_qq.identify or {}).get("intents") == 1107296256,
              str(mock_qq.identify))
        try:
            await asyncio.wait_for(mock_qq.heartbeat_seen.wait(), timeout=6)
        except asyncio.TimeoutError:
            pass
        check("网关心跳已发送", mock_qq.heartbeats >= 1, f"心跳 {mock_qq.heartbeats} 次")

        path, body = mock_qq.posts[0] if mock_qq.posts else ("", {})
        check("回复打到 /v2/groups/{openid}/messages",
              path == "/v2/groups/group-1/messages", path)
        check("回复内容正确", body.get("content") == "回声:你好呀|上下文2条", str(body))
        check("被动回复带上了 msg_id", body.get("msg_id") == "msg-1", str(body))
        check("msg_type 为 0（文本）", body.get("msg_type") == 0, str(body))


# ---------------------------------------------------------------- 主流程

async def main() -> int:
    if not EXE.exists():
        print(f"找不到 exe：{EXE}\n先运行 build.ps1 打包。")
        return 2

    print(f"被测程序：{EXE}（{EXE.stat().st_size / 1024 / 1024:.1f} MB）")
    work = ROOT / "tests" / "tmp"
    work.mkdir(parents=True, exist_ok=True)

    mock_ds = MockDeepSeek()
    mock_qq = MockQQ()

    ds_app = web.Application()
    ds_app.router.add_post("/v1/chat/completions", mock_ds.handle)

    qq_app = web.Application()
    qq_app.router.add_post("/app/getAppAccessToken", mock_qq.token)
    qq_app.router.add_post("/v2/groups/{openid}/messages", mock_qq.group_message)
    qq_app.router.add_post("/v2/users/{openid}/messages", mock_qq.group_message)
    qq_app.router.add_get("/websocket", mock_qq.ws)

    runners = []
    for app, port in ((ds_app, DS_PORT), (qq_app, QQ_API_PORT)):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        runners.append(runner)
    ws_runner = web.AppRunner(qq_app, access_log=None)
    await ws_runner.setup()
    await web.TCPSite(ws_runner, "127.0.0.1", QQ_WS_PORT).start()
    runners.append(ws_runner)

    try:
        await test_onebot(work)
        await test_qqofficial(work, mock_qq)
    finally:
        for runner in runners:
            await runner.cleanup()

    print(f"\n{'=' * 56}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for item in FAIL:
            print(f"  - {item}")
        print("日志：tests/tmp/*.out.log 和 dist/logs/bot.log")
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
