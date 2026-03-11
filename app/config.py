from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    token: str
    bind_host: str
    bind_port: int
    tmux_bin: str
    codex_bin: str
    codex_args: str
    default_cwd: Path
    audit_log: Path
    max_read_bytes: int
    novaadapt_enabled: bool
    novaadapt_bridge_url: str | None
    novaadapt_bridge_token: str | None
    novaadapt_timeout_seconds: float
    novaspine_url: str | None
    novaspine_token: str | None


def _expand_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().rstrip("/")
    return cleaned or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    token = os.getenv("CODEXREMOTE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("CODEXREMOTE_TOKEN is required")

    default_cwd = _expand_path(os.getenv("CODEXREMOTE_DEFAULT_CWD", str(Path.home())))
    audit_log = _expand_path(
        os.getenv("CODEXREMOTE_AUDIT_LOG", str(Path.home() / ".codexremote" / "audit.log"))
    )

    return Settings(
        token=token,
        bind_host=os.getenv("CODEXREMOTE_BIND_HOST", "127.0.0.1"),
        bind_port=int(os.getenv("CODEXREMOTE_BIND_PORT", "8787")),
        tmux_bin=os.getenv("CODEXREMOTE_TMUX_BIN", "tmux"),
        codex_bin=os.getenv("CODEXREMOTE_CODEX_BIN", "codex"),
        codex_args=os.getenv(
            "CODEXREMOTE_CODEX_ARGS",
            "exec --dangerously-bypass-approvals-and-sandbox",
        ).strip(),
        default_cwd=default_cwd,
        audit_log=audit_log,
        max_read_bytes=int(os.getenv("CODEXREMOTE_MAX_READ_BYTES", "1048576")),
        novaadapt_enabled=_parse_bool(os.getenv("CODEXREMOTE_NOVAADAPT_ENABLED"), default=False),
        novaadapt_bridge_url=_normalize_url(os.getenv("CODEXREMOTE_NOVAADAPT_BRIDGE_URL")),
        novaadapt_bridge_token=os.getenv("CODEXREMOTE_NOVAADAPT_BRIDGE_TOKEN", "").strip() or None,
        novaadapt_timeout_seconds=float(os.getenv("CODEXREMOTE_NOVAADAPT_TIMEOUT_SECONDS", "15")),
        novaspine_url=_normalize_url(os.getenv("CODEXREMOTE_NOVASPINE_URL")),
        novaspine_token=os.getenv("CODEXREMOTE_NOVASPINE_TOKEN", "").strip() or None,
    )
