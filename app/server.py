from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import quote_plus
import uuid

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .audit import AuditLog
from .config import Settings, get_settings
from .files import list_directory, read_text_file, resolve_path, tail_text_file
from .tmux import (
    TmuxError,
    capture_tail,
    create_session,
    has_session,
    kill_session,
    list_sessions,
    pane_current_command,
    send_ctrl,
    send_text,
    session_or_error,
    tmux_version,
    to_dict,
)

STARTED_AT = datetime.now(timezone.utc)
SETTINGS: Settings = get_settings()
AUDIT = AuditLog(SETTINGS.audit_log)
WEB_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"
WEB_SPECTATE = Path(__file__).resolve().parent.parent / "web" / "spectate.html"
SPECTATE_TOKENS: dict[str, dict[str, Any]] = {}
SPECTATE_TTL_MIN_SECONDS = 60
SPECTATE_TTL_MAX_SECONDS = 86400
SPECTATE_DEFAULT_TTL_SECONDS = 900

app = FastAPI(
    title="Codex Remote",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class TmuxSessionRequest(BaseModel):
    session: str = Field(..., min_length=1)
    cwd: str | None = None


class TmuxSendRequest(BaseModel):
    session: str = Field(..., min_length=1)
    text: str
    enter: bool = True


class TmuxCtrlRequest(BaseModel):
    session: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)


class CodexRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    cwd: str | None = None
    session: str | None = None


class CodexStartRequest(BaseModel):
    cwd: str | None = None
    session: str | None = None
    initial_prompt: str | None = None
    open_on_mac: bool = False


class CodexMessageRequest(BaseModel):
    session: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class CodexStopRequest(BaseModel):
    session: str = Field(..., min_length=1)
    kill_session: bool = False


class MacAttachRequest(BaseModel):
    session: str = Field(..., min_length=1)


class ShellRunRequest(BaseModel):
    session: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    wait_ms: int = 1200
    tail_lines: int = 200


class SpectateTokenRequest(BaseModel):
    session: str = Field(..., min_length=1)
    read_only: bool = True
    ttl_seconds: int = SPECTATE_DEFAULT_TTL_SECONDS


def _extract_bearer(raw_auth: str | None) -> str | None:
    if not raw_auth:
        return None
    parts = raw_auth.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token if token else None


def _extract_http_token(request: Request) -> str | None:
    token = _extract_bearer(request.headers.get("authorization"))
    if token:
        return token
    # Browser-friendly fallback for loading the dashboard and websocket streams.
    query_token = request.query_params.get("token", "").strip()
    return query_token or None


def _extract_ws_token(websocket: WebSocket) -> str | None:
    token = _extract_bearer(websocket.headers.get("authorization"))
    if token:
        return token
    query_token = websocket.query_params.get("token", "").strip()
    return query_token or None


def _clamp_spectate_ttl(ttl_seconds: int) -> int:
    return max(SPECTATE_TTL_MIN_SECONDS, min(ttl_seconds, SPECTATE_TTL_MAX_SECONDS))


def _prune_spectate_tokens(now_ts: float | None = None) -> None:
    now = now_ts if now_ts is not None else time.time()
    expired = [token for token, state in SPECTATE_TOKENS.items() if float(state.get("expires_at_ts", 0)) <= now]
    for token in expired:
        SPECTATE_TOKENS.pop(token, None)


def _issue_spectate_token(session: str, ttl_seconds: int) -> tuple[str, datetime]:
    _prune_spectate_tokens()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    token = secrets.token_urlsafe(24)
    SPECTATE_TOKENS[token] = {
        "session": session,
        "expires_at_ts": expires_at.timestamp(),
        "expires_at_iso": expires_at.isoformat(),
    }
    return token, expires_at


def _spectate_token_session(token: str, session: str) -> bool:
    if not token:
        return False
    _prune_spectate_tokens()
    state = SPECTATE_TOKENS.get(token)
    if not state:
        return False
    expected = str(state.get("session") or "")
    if expected != session:
        return False
    return True


def _ensure_token_or_401(token: str | None) -> None:
    if token != SETTINGS.token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _tmux_error(exc: TmuxError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _normalize_dir(raw: str | None) -> Path:
    path = resolve_path(raw, SETTINGS.default_cwd)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
    return path


def _codex_session_name() -> tuple[str, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:6]
    display = f"codex:{stamp}:{suffix}"
    # tmux target syntax uses ':', so use '-' for the actual target name.
    actual = display.replace(":", "-")
    return display, actual


def _codex_chat_session_name() -> tuple[str, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:6]
    display = f"codexchat:{stamp}:{suffix}"
    actual = display.replace(":", "-")
    return display, actual


def _build_codex_command(prompt: str, output_last_message: Path | None = None) -> str:
    parts = [shlex.quote(SETTINGS.codex_bin)]
    if SETTINGS.codex_args:
        parts.extend(shlex.quote(arg) for arg in shlex.split(SETTINGS.codex_args))
    if output_last_message is not None:
        parts.append("-o")
        parts.append(shlex.quote(str(output_last_message)))
    parts.append(shlex.quote(prompt))
    return " ".join(parts)


def _build_codex_interactive_command() -> str:
    parts = [shlex.quote(SETTINGS.codex_bin)]
    if SETTINGS.codex_args:
        args = shlex.split(SETTINGS.codex_args)
        if args and args[0] == "exec":
            args = args[1:]
        parts.extend(shlex.quote(arg) for arg in args)
    return " ".join(parts)


async def _send_codex_message(settings: Settings, session: str, message: str) -> None:
    # Use a single submit to avoid accidental duplicate sends.
    send_text(settings, session, message, enter=True)


def _looks_like_codex_session(name: str) -> bool:
    lower = name.lower()
    return lower.startswith("codex")


def _is_codex_running_session(session: str) -> bool:
    try:
        cmd = pane_current_command(SETTINGS, session).strip().lower()
    except TmuxError:
        return False
    if not cmd:
        return False
    codex_name = Path(SETTINGS.codex_bin).name.lower()
    return cmd == codex_name or "codex" in cmd


def _open_mac_terminal_for_session(session: str) -> tuple[bool, str | None]:
    if shutil.which("osascript") is None:
        return False, "osascript not found on host"

    target = shlex.quote(session)
    attach_cmd = f"tmux attach -t {target} || tmux new -As {target}"
    escaped = attach_cmd.replace("\\", "\\\\").replace('"', '\\"')
    proc = subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "{escaped}"',
            "-e",
            'tell application "Terminal" to activate',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Failed to open Terminal").strip()
        return False, detail
    return True, None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "GET" and request.url.path in {"/", "/spectate"}:
        return await call_next(request)
    try:
        _ensure_token_or_401(_extract_http_token(request))
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    html = WEB_INDEX.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/spectate", response_class=HTMLResponse)
async def spectate_page() -> HTMLResponse:
    html = WEB_SPECTATE.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "started_at": STARTED_AT.isoformat(),
        "tmux": {
            "binary": SETTINGS.tmux_bin,
            "available": shutil.which(SETTINGS.tmux_bin) is not None,
            "version": tmux_version(SETTINGS),
        },
        "codex": {
            "binary": SETTINGS.codex_bin,
            "available": shutil.which(SETTINGS.codex_bin) is not None,
        },
        "features": {
            "terminal": True,
            "tmux": True,
            "stream": True,
            "spectate": True,
        },
        "audit_log": str(SETTINGS.audit_log),
    }


@app.get("/tmux/sessions")
async def tmux_sessions() -> dict[str, Any]:
    try:
        sessions = [to_dict(s) for s in list_sessions(SETTINGS)]
    except TmuxError as exc:
        raise _tmux_error(exc)
    return {"sessions": sessions}


@app.post("/tmux/session")
async def tmux_create(req: TmuxSessionRequest) -> dict[str, Any]:
    cwd = _normalize_dir(req.cwd)
    try:
        create_session(SETTINGS, req.session, cwd)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write("tmux_session_create", session=req.session, cwd=str(cwd))
    return {"ok": True, "session": req.session, "cwd": str(cwd)}


@app.post("/tmux/send")
async def tmux_send(req: TmuxSendRequest) -> dict[str, Any]:
    try:
        session_or_error(SETTINGS, req.session)
        send_text(SETTINGS, req.session, req.text, enter=req.enter)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write(
        "tmux_send",
        session=req.session,
        enter=req.enter,
        text=req.text[:1000],
    )
    return {"ok": True, "session": req.session}


@app.post("/tmux/ctrl")
async def tmux_ctrl(req: TmuxCtrlRequest) -> dict[str, Any]:
    try:
        session_or_error(SETTINGS, req.session)
        send_ctrl(SETTINGS, req.session, req.key)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write("tmux_ctrl", session=req.session, key=req.key)
    return {"ok": True, "session": req.session, "key": req.key}


@app.get("/tmux/tail")
async def tmux_tail(session: str = Query(...), lines: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    try:
        session_or_error(SETTINGS, session)
        output = capture_tail(SETTINGS, session, lines=lines)
    except TmuxError as exc:
        raise _tmux_error(exc)
    return {"session": session, "output": output}


@app.websocket("/tmux/stream")
async def tmux_stream(websocket: WebSocket) -> None:
    token = _extract_ws_token(websocket)
    if token != SETTINGS.token:
        await websocket.close(code=4401)
        return

    session = websocket.query_params.get("session", "").strip()
    if not session:
        await websocket.close(code=4400)
        return

    await websocket.accept()
    last = ""

    try:
        while True:
            try:
                if not has_session(SETTINGS, session):
                    await websocket.send_json({
                        "type": "session_closed",
                        "session": session,
                        "data": "",
                    })
                    await websocket.close(code=1000)
                    return

                current = capture_tail(SETTINGS, session, lines=1000)
                if current != last:
                    if current.startswith(last):
                        delta = current[len(last) :]
                        await websocket.send_json(
                            {
                                "type": "delta",
                                "session": session,
                                "data": delta,
                            }
                        )
                    else:
                        await websocket.send_json(
                            {
                                "type": "snapshot",
                                "session": session,
                                "data": current,
                            }
                        )
                    last = current

                await asyncio.sleep(0.5)
            except TmuxError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "session": session,
                        "data": str(exc),
                    }
                )
                await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@app.post("/session/spectate")
@app.post("/tmux/spectate")
@app.post("/terminal/spectate")
@app.post("/spectate/token")
async def create_spectate_token(req: SpectateTokenRequest, request: Request) -> dict[str, Any]:
    if not req.read_only:
        raise HTTPException(status_code=400, detail="Only read_only spectator tokens are supported.")
    try:
        session_or_error(SETTINGS, req.session)
    except TmuxError as exc:
        raise _tmux_error(exc)

    ttl_seconds = _clamp_spectate_ttl(req.ttl_seconds)
    token, expires_at = _issue_spectate_token(req.session, ttl_seconds)
    base = str(request.base_url).rstrip("/")
    viewer_url = f"{base}/spectate?session={quote_plus(req.session)}&token={quote_plus(token)}"

    AUDIT.write(
        "spectate_token_create",
        session=req.session,
        read_only=True,
        ttl_seconds=ttl_seconds,
        expires_at=expires_at.isoformat(),
    )
    return {
        "ok": True,
        "session": req.session,
        "read_only": True,
        "ttl_seconds": ttl_seconds,
        "token": token,
        "path": "/spectate",
        "viewer_url": viewer_url,
        "expires_at": expires_at.isoformat(),
    }


@app.websocket("/spectate/stream")
async def spectate_stream(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "").strip()
    session = websocket.query_params.get("session", "").strip()
    if not token or not session:
        await websocket.close(code=4400)
        return
    if not _spectate_token_session(token, session):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last = ""

    try:
        while True:
            try:
                if not _spectate_token_session(token, session):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "session": session,
                            "data": "Spectator token expired.",
                        }
                    )
                    await websocket.close(code=1008)
                    return

                if not has_session(SETTINGS, session):
                    await websocket.send_json(
                        {
                            "type": "session_closed",
                            "session": session,
                            "data": "",
                        }
                    )
                    await websocket.close(code=1000)
                    return

                current = capture_tail(SETTINGS, session, lines=1000)
                if current != last:
                    if current.startswith(last):
                        delta = current[len(last) :]
                        await websocket.send_json(
                            {
                                "type": "delta",
                                "session": session,
                                "data": delta,
                            }
                        )
                    else:
                        await websocket.send_json(
                            {
                                "type": "snapshot",
                                "session": session,
                                "data": current,
                            }
                        )
                    last = current

                await asyncio.sleep(0.5)
            except TmuxError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "session": session,
                        "data": str(exc),
                    }
                )
                await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@app.post("/codex/run")
async def codex_run(req: CodexRunRequest) -> dict[str, Any]:
    cwd = _normalize_dir(req.cwd)
    display_session, generated_session = _codex_session_name()
    session = req.session or generated_session
    command = _build_codex_command(req.prompt)

    try:
        create_session(SETTINGS, session, cwd)
        send_text(SETTINGS, session, f"cd {shlex.quote(str(cwd))}")
        send_text(SETTINGS, session, "echo '[codex_remote] cwd:' $(pwd)")
        send_text(
            SETTINGS,
            session,
            "echo '[codex_remote] git branch:' $(git branch --show-current 2>/dev/null || true)",
        )
        send_text(SETTINGS, session, "git status --short --branch 2>/dev/null || true")
        send_text(SETTINGS, session, command)
        await asyncio.sleep(0.5)
        output = capture_tail(SETTINGS, session, lines=120)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write(
        "codex_run",
        session=session,
        display_session=display_session,
        cwd=str(cwd),
        prompt=req.prompt[:2000],
        command=command,
    )

    return {
        "ok": True,
        "session": session,
        "display_session": display_session,
        "cwd": str(cwd),
        "command": command,
        "tail": output,
    }


@app.get("/codex/sessions")
async def codex_sessions() -> dict[str, Any]:
    try:
        sessions = []
        for s in list_sessions(SETTINGS):
            if _looks_like_codex_session(s.name) or _is_codex_running_session(s.name):
                sessions.append(to_dict(s))
    except TmuxError as exc:
        raise _tmux_error(exc)
    return {"sessions": sessions}


@app.post("/codex/start")
async def codex_start(req: CodexStartRequest) -> dict[str, Any]:
    cwd = _normalize_dir(req.cwd)
    display_session, generated_session = _codex_chat_session_name()
    session = req.session or generated_session
    command = _build_codex_interactive_command()

    try:
        create_session(SETTINGS, session, cwd)
        send_text(SETTINGS, session, f"cd {shlex.quote(str(cwd))}")
        send_text(SETTINGS, session, "echo '[codex_remote] cwd:' $(pwd)")
        if not _is_codex_running_session(session):
            send_text(SETTINGS, session, command)
            await asyncio.sleep(1.0)
        if req.initial_prompt:
            await _send_codex_message(SETTINGS, session, req.initial_prompt)
            await asyncio.sleep(0.5)
        output = capture_tail(SETTINGS, session, lines=220)
    except TmuxError as exc:
        raise _tmux_error(exc)

    open_on_mac_result: dict[str, Any] | None = None
    if req.open_on_mac:
        opened, error = _open_mac_terminal_for_session(session)
        open_on_mac_result = {"requested": True, "opened": opened, "error": error}

    AUDIT.write(
        "codex_start",
        session=session,
        display_session=display_session,
        cwd=str(cwd),
        command=command,
        initial_prompt=(req.initial_prompt or "")[:2000],
        open_on_mac=req.open_on_mac,
        open_on_mac_opened=(open_on_mac_result or {}).get("opened"),
        open_on_mac_error=(open_on_mac_result or {}).get("error"),
    )
    return {
        "ok": True,
        "session": session,
        "display_session": display_session,
        "cwd": str(cwd),
        "command": command,
        "tail": output,
        "open_on_mac": open_on_mac_result,
    }


@app.post("/codex/message")
async def codex_message(req: CodexMessageRequest) -> dict[str, Any]:
    try:
        session_or_error(SETTINGS, req.session)
        if not _is_codex_running_session(req.session):
            send_text(SETTINGS, req.session, _build_codex_interactive_command())
            await asyncio.sleep(1.0)
        await _send_codex_message(SETTINGS, req.session, req.message)
        await asyncio.sleep(0.4)
        output = capture_tail(SETTINGS, req.session, lines=220)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write(
        "codex_message",
        session=req.session,
        message=req.message[:2000],
    )
    return {"ok": True, "session": req.session, "tail": output}


@app.post("/codex/stop")
async def codex_stop(req: CodexStopRequest) -> dict[str, Any]:
    try:
        session_or_error(SETTINGS, req.session)
        send_ctrl(SETTINGS, req.session, "C-c")
        if req.kill_session:
            kill_session(SETTINGS, req.session)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write(
        "codex_stop",
        session=req.session,
        kill_session=req.kill_session,
    )
    return {"ok": True, "session": req.session, "kill_session": req.kill_session}


@app.post("/mac/attach")
async def mac_attach(req: MacAttachRequest) -> dict[str, Any]:
    try:
        session_or_error(SETTINGS, req.session)
    except TmuxError as exc:
        raise _tmux_error(exc)

    opened, error = _open_mac_terminal_for_session(req.session)
    AUDIT.write(
        "mac_attach",
        session=req.session,
        opened=opened,
        error=error,
    )
    if not opened:
        raise HTTPException(status_code=500, detail=error or "Failed to open Terminal")
    return {"ok": True, "session": req.session}


@app.post("/shell/run")
async def shell_run(req: ShellRunRequest) -> dict[str, Any]:
    wait_seconds = max(0.0, min(req.wait_ms / 1000.0, 30.0))

    try:
        session_or_error(SETTINGS, req.session)
        send_text(SETTINGS, req.session, req.command)
        if wait_seconds:
            await asyncio.sleep(wait_seconds)
        output = capture_tail(SETTINGS, req.session, lines=req.tail_lines)
    except TmuxError as exc:
        raise _tmux_error(exc)

    AUDIT.write(
        "shell_run",
        session=req.session,
        command=req.command[:4000],
        wait_ms=req.wait_ms,
        tail_lines=req.tail_lines,
    )
    return {"ok": True, "session": req.session, "command": req.command, "output": output}


@app.get("/files/list")
async def files_list(
    path: str | None = Query(None),
    hidden: bool = Query(False),
) -> dict[str, Any]:
    resolved = resolve_path(path, SETTINGS.default_cwd)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {resolved}")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {resolved}")

    entries = list_directory(resolved, include_hidden=hidden)
    AUDIT.write("files_list", path=str(resolved), hidden=hidden, count=len(entries))
    return {"path": str(resolved), "entries": entries}


@app.get("/files/read")
async def files_read(path: str = Query(...)) -> dict[str, Any]:
    resolved = resolve_path(path, SETTINGS.default_cwd)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {resolved}")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {resolved}")

    content = read_text_file(resolved, SETTINGS.max_read_bytes)
    AUDIT.write("files_read", path=str(resolved), bytes=len(content.encode("utf-8")))
    return {"path": str(resolved), "content": content}


@app.get("/files/tail")
async def files_tail(path: str = Query(...), lines: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    resolved = resolve_path(path, SETTINGS.default_cwd)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {resolved}")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {resolved}")

    content = tail_text_file(resolved, lines, SETTINGS.max_read_bytes)
    AUDIT.write("files_tail", path=str(resolved), lines=lines)
    return {"path": str(resolved), "lines": lines, "content": content}
