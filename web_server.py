#!/usr/bin/env python3
"""web_server.py - ucf_desktop Web モード用 WebSocket ブリッジサーバー。

Electron の main.js と同じ役割を Python + aiohttp で実現する:
  1. agent.py --gui をサブプロセスとして起動
  2. subprocess の stdout (JSON Lines) → WebSocket クライアントへブロードキャスト
  3. WebSocket クライアントからの JSON → subprocess の stdin へ書き込み
  4. desktop/renderer/ の静的ファイルを HTTP 配信
"""

import asyncio
import json
import os
import platform
import shutil
import sys
from pathlib import Path

from aiohttp import web

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "desktop" / "renderer"
AGENT_SCRIPT = BASE_DIR / "agent.py"

HOST = os.environ.get("UCF_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("UCF_WEB_PORT", "8765"))


# ── Python 実行コマンド解決 (main.js resolveCommand のミラー) ──


def _resolve_python_command() -> list[str]:
    """agent.py --gui を実行するコマンドを返す。"""
    is_win = platform.system() == "Windows"

    # Strategy 1: uv (preferred)
    if shutil.which("uv"):
        uv = "uv.exe" if is_win else "uv"
        return [uv, "run", "python", str(AGENT_SCRIPT), "--gui"]

    # Strategy 2: .venv の python
    if is_win:
        venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = BASE_DIR / ".venv" / "bin" / "python3"

    if venv_python.exists():
        return [str(venv_python), str(AGENT_SCRIPT), "--gui"]

    # Strategy 3: システム python
    candidates = ["python", "python3"] if is_win else ["python3", "python"]
    for c in candidates:
        if shutil.which(c):
            return [c, str(AGENT_SCRIPT), "--gui"]

    raise RuntimeError(
        "Python が見つかりません。Python 3.13+ または uv をインストールしてください。"
    )


# ── AgentBridge: サブプロセス管理 + WebSocket ブリッジ ──────────


class AgentBridge:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.clients: set[web.WebSocketResponse] = set()
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        # system_info はサブプロセス起動直後に一度だけ送信されるため、
        # クライアント接続前に届く可能性がある。バッファして新規接続にリプレイする。
        self._init_messages: list[dict] = []

    async def start(self) -> None:
        cmd = _resolve_python_command()
        print(f"Spawning: {' '.join(cmd)}", file=sys.stderr)
        print(f"CWD: {BASE_DIR}", file=sys.stderr)

        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(BASE_DIR),
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
                # 初期化メッセージをバッファ (新規クライアント接続時にリプレイ)
                if msg.get("type") in ("system_info", "skills_list"):
                    self._init_messages = [
                        m for m in self._init_messages
                        if m.get("type") != msg.get("type")
                    ]
                    self._init_messages.append(msg)
                await self.broadcast(msg)
            except json.JSONDecodeError:
                print(f"[agent stdout non-JSON] {text}", file=sys.stderr)

        await self.broadcast(
            {"type": "error", "message": "Agent プロセスが終了しました"}
        )

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8").strip()
            if text:
                print(f"[agent stderr] {text}", file=sys.stderr)

    async def broadcast(self, msg: dict) -> None:
        data = json.dumps(msg, ensure_ascii=False)
        dead: set[web.WebSocketResponse] = set()
        for ws in self.clients:
            try:
                await ws.send_str(data)
            except Exception:
                dead.add(ws)
        self.clients -= dead

    async def send_to_agent(self, msg: dict) -> None:
        if self.process and self.process.stdin and not self.process.stdin.is_closing():
            data = json.dumps(msg, ensure_ascii=False) + "\n"
            self.process.stdin.write(data.encode("utf-8"))
            await self.process.stdin.drain()

    async def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()


# ── HTTP / WebSocket ハンドラ ─────────────────────────────────


bridge = AgentBridge()


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    bridge.clients.add(ws)
    # バッファされた初期化メッセージをリプレイ
    for init_msg in bridge._init_messages:
        try:
            await ws.send_str(json.dumps(init_msg, ensure_ascii=False))
        except Exception:
            pass
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await bridge.send_to_agent(data)
                except json.JSONDecodeError:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                print(
                    f"[ws error] {ws.exception()}",
                    file=sys.stderr,
                )
    finally:
        bridge.clients.discard(ws)
    return ws


async def index_handler(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def on_startup(app: web.Application) -> None:
    await bridge.start()


async def on_shutdown(app: web.Application) -> None:
    await bridge.stop()


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", STATIC_DIR)

    return app


if __name__ == "__main__":
    print(f"ucf_desktop web mode: http://{HOST}:{PORT}", file=sys.stderr)
    web.run_app(create_app(), host=HOST, port=PORT, print=None)
