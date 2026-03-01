from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings


class TmuxError(RuntimeError):
    """Raised when tmux interaction fails."""


@dataclass
class TmuxSession:
    name: str
    created_at: str
    attached: bool
    windows: int


def _run_tmux(settings: Settings, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if not shutil.which(settings.tmux_bin):
        raise TmuxError(f"tmux binary not found: {settings.tmux_bin}")

    proc = subprocess.run(
        [settings.tmux_bin, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "unknown tmux failure").strip()
        raise TmuxError(stderr)
    return proc


def tmux_version(settings: Settings) -> str | None:
    if not shutil.which(settings.tmux_bin):
        return None
    proc = _run_tmux(settings, "-V", check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or proc.stderr.strip() or "tmux"


def has_session(settings: Settings, session: str) -> bool:
    proc = _run_tmux(settings, "has-session", "-t", session, check=False)
    return proc.returncode == 0


def list_sessions(settings: Settings) -> list[TmuxSession]:
    proc = _run_tmux(
        settings,
        "list-sessions",
        "-F",
        "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}",
        check=False,
    )
    if proc.returncode != 0:
        # No sessions is a valid state in tmux.
        text = (proc.stderr or "").lower()
        if "no server running" in text or "no sessions" in text:
            return []
        raise TmuxError((proc.stderr or proc.stdout).strip())

    out = proc.stdout.strip()
    if not out:
        return []

    sessions: list[TmuxSession] = []
    for line in out.splitlines():
        raw_name, raw_created, raw_attached, raw_windows = line.split("\t")
        created = datetime.fromtimestamp(int(raw_created), tz=timezone.utc).isoformat()
        sessions.append(
            TmuxSession(
                name=raw_name,
                created_at=created,
                attached=raw_attached == "1",
                windows=int(raw_windows),
            )
        )
    return sessions


def create_session(settings: Settings, session: str, cwd: Path) -> None:
    if has_session(settings, session):
        return
    _run_tmux(settings, "new-session", "-d", "-s", session, "-c", str(cwd))


def kill_session(settings: Settings, session: str) -> None:
    _run_tmux(settings, "kill-session", "-t", session)


def send_text(settings: Settings, session: str, text: str, enter: bool = True) -> None:
    _run_tmux(settings, "send-keys", "-t", session, "-l", "--", text)
    if enter:
        _run_tmux(settings, "send-keys", "-t", session, "Enter")


def send_ctrl(settings: Settings, session: str, key: str) -> None:
    _run_tmux(settings, "send-keys", "-t", session, key)


def capture_tail(settings: Settings, session: str, lines: int = 200) -> str:
    lines = max(1, min(lines, 5000))
    proc = _run_tmux(
        settings,
        "capture-pane",
        "-p",
        "-t",
        session,
        "-S",
        f"-{lines}",
    )
    return proc.stdout


def pane_current_command(settings: Settings, session: str) -> str:
    proc = _run_tmux(settings, "display-message", "-p", "-t", session, "#{pane_current_command}")
    return proc.stdout.strip()


def session_or_error(settings: Settings, session: str) -> None:
    if not has_session(settings, session):
        raise TmuxError(f"tmux session not found: {session}")


def to_dict(s: TmuxSession) -> dict[str, Any]:
    return {
        "name": s.name,
        "created_at": s.created_at,
        "attached": s.attached,
        "windows": s.windows,
    }
