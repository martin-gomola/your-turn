"""Loopback-only Your Turn server: an inbox of agent chats (Codex, Claude Code, Cursor) and a per-turn summary of each."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yourturn import __version__
from yourturn.config import DEFAULT_HISTORY_DAYS
from yourturn.engine import SessionHub
from yourturn.model import UUID, Harness, SessionKey
from yourturn.state import InboxState

LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
PAGE_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
ASSET_TYPES = {".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png"}


def _static(name: str) -> str:
    return files("yourturn").joinpath("static", name).read_text(encoding="utf-8")


def create_app(
    codex_home: Path, poll_seconds: float = POLL_SECONDS, should_stop: Callable[[], bool] = lambda: False,
    history_days: int = DEFAULT_HISTORY_DAYS, claude_home: Path | None = None,
    cursor_home: Path | None = None, cursor_user_dir: Path | None = None, state_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Your Turn", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS)
    hub = SessionHub.for_codex_home(codex_home, claude_home=claude_home, cursor_home=cursor_home, cursor_user_dir=cursor_user_dir)
    state = InboxState(state_path) if state_path else InboxState()

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = PAGE_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    served = {Harness(adapter.name) for adapter in hub.adapters}

    def checked(thread: str) -> SessionKey:
        """Resolve `<harness>:<uuid>` or a bare `<uuid>` (Codex, same rule as `SessionHub.detail`) to a session key.

        Malformed ids -> 400; a well-formed key for a harness with no session source -> 404.
        """
        try:
            key = SessionKey.parse(thread)
        except ValueError:
            raise HTTPException(status_code=400, detail="thread must be a session key or Codex thread id") from None
        if key.harness not in served:
            raise HTTPException(status_code=404, detail="no session source for this harness")
        # Codex thread ids, Claude Code session ids and Cursor composer ids are all UUIDs.
        if not UUID.match(key.native_id):
            raise HTTPException(status_code=400, detail="thread must be a session key or Codex thread id")
        return key

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _static("index.html").replace("{{APP_VERSION}}", __version__).replace("{{HISTORY_DAYS}}", str(history_days))

    @app.get("/assets/{name}")
    def asset(name: str) -> Response:
        media_type = ASSET_TYPES.get(Path(name).suffix)
        if media_type is None or name not in {entry.name for entry in files("yourturn").joinpath("static").iterdir()}:
            raise HTTPException(status_code=404)
        return Response(files("yourturn").joinpath("static", name).read_bytes(), media_type=media_type)

    @app.get("/api/inbox")
    def inbox() -> list[dict[str, Any]]:
        return hub.inbox_dicts(history_days)

    @app.get("/api/threads/{thread}")
    def thread_state(thread: str) -> dict[str, Any]:
        data = hub.detail_dict(checked(thread))
        if data is None:
            raise HTTPException(status_code=404, detail="no session file for this thread")
        return data

    @app.post("/api/state", status_code=204)
    async def write_state(request: Request) -> None:
        """Mark results seen or reminders dismissed for every browser; streams push the change to the others."""
        # JSON from this page only: a cross-site form cannot send JSON, and a cross-site fetch carries its Origin.
        origin = request.headers.get("origin")
        if not request.headers.get("content-type", "").startswith("application/json") or (
                origin and urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1"}):
            raise HTTPException(status_code=403)
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(status_code=400) from None

        def entries(name: str, nullable: bool) -> dict[str, Any]:
            values = body.get(name) or {} if isinstance(body, dict) else None
            if not isinstance(values, dict) or not all(isinstance(v, str) or (nullable and v is None) for v in values.values()):
                raise HTTPException(status_code=400, detail=f"{name} must map chat keys to strings")
            return {str(checked(key)): value for key, value in values.items()}

        seen, dismissed = entries("seen", False), entries("dismissed", True)
        keep = {row["key"] for row in await asyncio.to_thread(hub.inbox_dicts, history_days)}
        await asyncio.to_thread(state.update, seen, dismissed, keep)

    @app.get("/api/stream")
    async def stream(request: Request, thread: str | None = None) -> StreamingResponse:
        key: SessionKey | None = checked(thread) if thread else None

        def current(last: str | None) -> tuple[str, Any]:
            """Blocking file reads; called off the event loop so one large chat cannot stall every stream."""
            if key is not None:
                data = hub.detail_dict(key)
                return (f"{data['version']}:{data['quiet']}" if data else "missing"), data
            if last is None:
                # Warm the entry cache so the first marker already knows which chats are quiet.
                hub.inbox_dicts(history_days)
            marker = hub.inbox_fingerprint(history_days)
            return marker, hub.inbox_dicts(history_days) if marker != last else None

        async def events() -> AsyncIterator[str]:
            last, idle, shared = None, 0.0, -1
            while not should_stop() and not await request.is_disconnected():
                if state.version != shared:
                    shared = state.version
                    yield f"event: state\ndata: {json.dumps(state.snapshot())}\n\n"
                marker, data = await asyncio.to_thread(current, last)
                if marker != last:
                    last, idle = marker, 0.0
                    yield f"event: {'thread' if thread else 'inbox'}\ndata: {json.dumps(data)}\n\n"
                elif idle >= HEARTBEAT_SECONDS:
                    idle = 0.0
                    yield ": heartbeat\n\n"
                await asyncio.sleep(poll_seconds)
                idle += poll_seconds

        return StreamingResponse(events(), media_type="text/event-stream")

    return app
