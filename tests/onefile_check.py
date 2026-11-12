"""验证「单文件 exe」在普通用户令牌下能否正常启动并收发消息。

本会话启动的进程处在受限令牌里，PyInstaller onefile 解压临时目录会被拒。
这里改用 Windows 计划任务（以当前用户身份、脱离本会话的作业）启动 exe，
再从外部连它的 WebSocket 做一次真实收发，证明单文件版本身可用。

    python tests/onefile_check.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "deepseek-qq.exe"
TMP = ROOT / "tests" / "tmp"
PORT = 18091
TASK = "DSHDeepSeekQQVerify"
BAT = TMP / "run_onefile.bat"
OUT = TMP / "onefile.out.txt"

CONFIG = TMP / "onefile.yaml"


def shell(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="mbcs", errors="replace")


def prepare() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(
        f"""\
backend: onebot
deepseek:
  api_key: "sk-test"
  base_url: "http://127.0.0.1:18080"
  model: "deepseek-chat"
  timeout: 10
  retries: 0
chat:
  cooldown_seconds: 0
onebot:
  host: "127.0.0.1"
  port: {PORT}
  path: "/onebot"
  access_token: "test-token"
""",
        encoding="utf-8",
    )
    BAT.write_text(
        "@echo off\r\n"
        f'cd /d "{EXE.parent}"\r\n'
        f'"{EXE}" --config "{CONFIG}" --log-level DEBUG > "{OUT}" 2>&1\r\n',
        encoding="utf-8",
    )
    shell("schtasks", "/delete", "/tn", TASK, "/f")
    made = shell(
        "schtasks", "/create", "/tn", TASK, "/tr", str(BAT),
        "/sc", "ONCE", "/st", "23:59", "/f",
    )
    if made.returncode != 0:
        raise SystemExit(f"创建计划任务失败：{made.stdout}{made.stderr}")
    ran = shell("schtasks", "/run", "/tn", TASK)
    if ran.returncode != 0:
        raise SystemExit(f"运行计划任务失败：{ran.stdout}{ran.stderr}")


def cleanup() -> None:
    shell("taskkill", "/F", "/T", "/IM", "deepseek-qq.exe")
    shell("schtasks", "/delete", "/tn", TASK, "/f")


def port_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


async def check() -> bool:
    from aiohttp import web

    async def mock_chat(request: web.Request) -> web.Response:
        body = await request.json()
        last = next(
            (m["content"] for m in reversed(body.get("messages", [])) if m["role"] == "user"), ""
        )
        return web.json_response(
            {"choices": [{"message": {"role": "assistant", "content": f"回声:{last}"}}]}
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", mock_chat)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 18080).start()

    try:
        return await _check_with_mock()
    finally:
        await runner.cleanup()


async def _check_with_mock() -> bool:
    deadline = time.time() + 45
    while time.time() < deadline:
        if port_open(PORT):
            break
        await asyncio.sleep(0.3)
    else:
        print("[FAIL] 单文件 exe 没能启动（45 秒内端口未监听）")
        if OUT.exists():
            print("---- 程序输出 ----")
            print(OUT.read_text(encoding="utf-8", errors="replace")[-3000:])
        return False
    print("[PASS] 单文件 exe 启动成功，WS 已监听")

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(
            f"ws://127.0.0.1:{PORT}/onebot",
            headers={"Authorization": "Bearer test-token", "X-Self-ID": "10000"},
        ) as ws:
            await ws.send_json({
                "post_type": "message", "message_type": "private", "sub_type": "friend",
                "self_id": 10000, "user_id": 99901, "message_id": 1,
                "message": [{"type": "text", "data": {"text": "单文件自检"}}],
                "sender": {"user_id": 99901, "nickname": "tester"},
            })
            try:
                async with asyncio.timeout(15):
                    while True:
                        msg = await ws.receive()
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        if "action" not in data:
                            continue
                        await ws.send_json({"status": "ok", "retcode": 0, "echo": data.get("echo")})
                        params = data.get("params", {})
                        text = "".join(
                            seg.get("data", {}).get("text", "")
                            for seg in params.get("message", [])
                        )
                        print(f"[INFO] 收到动作 {data['action']} → {text!r}")
                        print("[PASS] 单文件 exe 完成了 DeepSeek 调用与回消息")
                        return text == "回声:单文件自检"
            except TimeoutError:
                print("[FAIL] 15 秒内没收到回复动作")
                return False


def main() -> int:
    if not EXE.exists():
        print(f"找不到 exe：{EXE}")
        return 2
    try:
        prepare()
        ok = asyncio.run(check())
    finally:
        cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
