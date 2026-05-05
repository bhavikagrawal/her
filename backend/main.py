# Starts HER's Python sidecar: WebSocket control plus Phase 1 full-duplex voice conversation.
# Each browser socket spins up a `VoiceSession` thread that chains mic → Whisper → Qwen → TTS.
# Tauri still launches this file through `scripts/run-backend.sh` before the desktop window opens.
# `generate_context!()` stays outside Python — Rust owns menus/icons while Python owns time-domain audio.

"""WebSocket entry point for the HER desktop app (Phase 1 — voice + streaming chat)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import sys
import threading
from typing import Any, cast

import websockets
from websockets import server
from websockets.legacy.server import WebSocketServerProtocol
from websockets.typing import Data

from backend.voice.session import VoiceSession

# CONCEPT: The type we use is the object the `websockets` library hands your handler (a "connection").
Connection = WebSocketServerProtocol

HOST: str = "127.0.0.1"
PORT: int = 8765

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_json_payload(message: Data) -> dict[str, Any] | None:
    """Turn a WebSocket text frame into JSON if possible; ignore malformed chatter."""
    if not isinstance(message, str):
        return None
    try:
        parsed: dict[str, Any] = cast(dict[str, Any], json.loads(message))
        return parsed
    except json.JSONDecodeError:
        return None


async def handle_client(
    connection: Connection,
    server_halt: asyncio.Event,
    user_name: str = "User",
) -> None:
    """Bridge the WebSocket to the blocking `VoiceSession` worker thread."""
    loop = asyncio.get_running_loop()
    halt = threading.Event()

    # CONCEPT: The desktop app can open multiple windows (main chat + settings).
    # Each window creates its own WebSocket connection. Only the main chat window
    # should start the microphone/STT/TTS loop, otherwise windows can contend for
    # the mic device and make listening appear "broken".
    client_role: str = "voice"
    first_payload: dict[str, Any] | None = None
    try:
        first_msg = await asyncio.wait_for(connection.recv(), timeout=0.35)
        first_payload = _parse_json_payload(first_msg)
        if isinstance(first_payload, dict) and first_payload.get("type") == "client_role":
            role = first_payload.get("role")
            if role in ("voice", "settings"):
                client_role = str(role)
                first_payload = None
    except asyncio.TimeoutError:
        pass

    session = VoiceSession(loop, connection, halt, user_label=user_name)
    target = session.run if client_role == "voice" else session.run_settings_only
    voice_thread = threading.Thread(target=target, name=f"her-{client_role}", daemon=True)
    voice_thread.start()
    peer = getattr(connection, "remote_address", "unknown")
    logger.info("WebSocket client connected from %s role=%s", peer, client_role)
    hello = json.dumps({"type": "status", "connected": True})
    await connection.send(hello)
    try:
        # If we pulled one non-role message during handshake, process it first.
        if first_payload is not None and isinstance(first_payload, dict):
            if first_payload.get("type") == "ping":
                await connection.send(json.dumps({"type": "pong"}))
            elif first_payload.get("type") in ("set_audio_devices", "set_settings"):
                session.enqueue_control(first_payload)

        async for message in connection:
            if server_halt.is_set():
                break
            payload = _parse_json_payload(message)
            if payload is None:
                continue
            if payload.get("type") == "ping":
                await connection.send(json.dumps({"type": "pong"}))
                continue
            if payload.get("type") == "set_audio_devices":
                session.enqueue_control(payload)
                continue
            if payload.get("type") == "set_settings":
                session.enqueue_control(payload)
                continue
            if payload.get("type") == "user_text":
                session.enqueue_control(payload)
    except websockets.exceptions.ConnectionClosedOK:
        logger.info("Client disconnected normally")
    except websockets.exceptions.ConnectionClosedError as exc:
        logger.info("Client disconnected with error: %s", exc)
    finally:
        halt.set()


async def run_server(stop_event: asyncio.Event) -> None:
    """Bind the socket and run until `stop_event` or process exit."""

    async def _handler(connection: Connection) -> None:
        await handle_client(connection, stop_event)

    async with server.serve(
        _handler,
        HOST,
        PORT,
    ):
        print("Python WebSocket server started on ws://localhost:8765", flush=True)
        await stop_event.wait()


def _install_shutdown_handlers(
    loop: asyncio.AbstractEventLoop,
    stop_event: asyncio.Event,
) -> None:
    """Register SIGINT/SIGTERM so Ctrl+C tears down the server cleanly."""

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)


async def async_main() -> None:
    """Bridge between asyncio's event loop and our graceful shutdown flag."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_shutdown_handlers(loop, stop_event)
    await run_server(stop_event)


def main() -> None:
    """Python entrypoint used by `scripts/run-backend.sh` and future packaging."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
