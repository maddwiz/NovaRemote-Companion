# Codex Remote (Full Terminal Authority)

Personal remote terminal + Codex control service for macOS over Tailscale.

This build intentionally provides full shell authority equal to your local Mac user account:
- no safe mode
- no time lock
- no workspace restrictions
- no command filtering

Security model:
- bind server to `127.0.0.1:8787`
- private access over Tailscale
- bearer token on control APIs and tmux websocket
- optional short-lived spectator tokens for read-only shared links
- append-only audit log

## Features
- tmux session lifecycle and control
- arbitrary command execution in tmux sessions
- Codex run/stop orchestration in tmux
- live terminal stream over websocket
- file list/read/tail
- read-only live spectator links with browser viewer
- dashboard web app
- optional NovaAdapt bridge passthrough for agents, plans, jobs, and memory
- optional NovaSpine health visibility for server-side memory deployments
- macOS install script + launchd auto-start

## API
- `GET /health`
- `GET /tmux/sessions`
- `POST /tmux/session`
- `POST /tmux/send`
- `POST /tmux/ctrl`
- `GET /tmux/tail`
- `WS /tmux/stream`
- `POST /session/spectate` (aliases: `/tmux/spectate`, `/terminal/spectate`, `/spectate/token`)
- `GET /spectate`
- `WS /spectate/stream`
- `POST /codex/run`
- `POST /codex/stop`
- `POST /mac/attach`
- `POST /shell/run`
- `GET /files/list`
- `GET /files/read`
- `GET /files/tail`
- `GET /agents/capabilities`
- `GET|POST /agents/*` (authenticated NovaAdapt sidecar passthrough; allowlisted routes only)

## Optional NovaAdapt + NovaSpine Sidecars

You can keep Codex Remote as the single origin your phone talks to while running NovaAdapt and NovaSpine as separate services on the same machine.

For a concrete operator setup, use [NOVAADAPT_SIDECAR_RUNBOOK.md](./NOVAADAPT_SIDECAR_RUNBOOK.md) together with:

Also see:
- [COMPANION_PROTOCOL.md](./COMPANION_PROTOCOL.md) for the app-facing contract
- [OPEN_SOURCE_CHECKLIST.md](./OPEN_SOURCE_CHECKLIST.md) for the publication checklist

- [docker-compose.nova-sidecars.yml](./docker-compose.nova-sidecars.yml)
- [.env.nova-sidecars.example](./.env.nova-sidecars.example)
- [scripts/validate_nova_sidecars.py](./scripts/validate_nova_sidecars.py)
- [scripts/start_nova_sidecars.sh](./scripts/start_nova_sidecars.sh)
- [scripts/stop_nova_sidecars.sh](./scripts/stop_nova_sidecars.sh)

Set these environment variables in `~/.codexremote/config.env`:

```bash
export CODEXREMOTE_NOVAADAPT_ENABLED="true"
export CODEXREMOTE_NOVAADAPT_BRIDGE_URL="http://127.0.0.1:9797"
export CODEXREMOTE_NOVAADAPT_BRIDGE_TOKEN="replace-with-bridge-token"
export CODEXREMOTE_NOVAADAPT_TIMEOUT_SECONDS="15"
export CODEXREMOTE_NOVASPINE_URL="http://127.0.0.1:8420"
export CODEXREMOTE_NOVASPINE_TOKEN="replace-with-spine-token"
```

With that configured:
- `GET /health` includes `novaadapt` and `novaspine` status blocks
- `GET /agents/capabilities` returns cached support flags for optional NovaAdapt route families (`memory`, `governance`, `workflows`, `templates`, `gallery`, `control-artifacts`, `mobile`, `browser`, `voice`, `canvas`, `home-assistant`, `mqtt`)
- both `/health` and `/agents/capabilities` now include `protocol_version` and `agent_contract_version` for compatibility checks
- `GET|POST /agents/*` proxies a safe allowlist of NovaAdapt bridge routes:
  - `/agents/health`
  - `/agents/jobs`
  - `/agents/jobs/{id}`
  - `/agents/jobs/{id}/cancel`
  - `/agents/plans`
  - `/agents/plans/{id}`
  - `/agents/plans/{id}/approve`
  - `/agents/plans/{id}/approve_async`
  - `/agents/plans/{id}/retry_failed`
  - `/agents/plans/{id}/retry_failed_async`
  - `/agents/plans/{id}/reject`
  - `/agents/plans/{id}/undo`
  - `/agents/memory/status`
  - `/agents/memory/recall`
  - `/agents/memory/ingest`
  - `/agents/runtime/governance`
  - `/agents/runtime/jobs/cancel_all`
  - `/agents/terminal/sessions`
  - `/agents/terminal/sessions/{id}`
  - `/agents/terminal/sessions/{id}/output`
  - `/agents/terminal/sessions/{id}/input`
  - `/agents/terminal/sessions/{id}/close`

Validate the sidecar package before running Docker:

```bash
python scripts/validate_nova_sidecars.py --env-file .env.nova-sidecars
```

Validate the checked-out NovaAdapt branch against the companion contract before merging runtime upgrades:

```bash
python scripts/validate_nova_sidecars.py \
  --env-file .env.nova-sidecars \
  --novaadapt-contract-check
```

Validate the running host + sidecars end-to-end:

```bash
python scripts/validate_nova_sidecars.py --env-file .env.nova-sidecars --live-check
```

That live validation now checks the companion `/agents/capabilities` contract as well as `/health` and `/agents/health`.

If the sidecars are already running and you never created `.env.nova-sidecars`, you can still run:

```bash
python scripts/validate_nova_sidecars.py --live-check
```

Start or stop the sidecars with the packaged helpers:

```bash
./scripts/start_nova_sidecars.sh
./scripts/stop_nova_sidecars.sh
```

This keeps the agent runtime and memory service decoupled from Codex Remote while giving the mobile app one server origin.

## Install (macOS)
Run from project root:

```bash
cd /Users/desmondpottle/Documents/New\ project/codex_remote
./install_mac.sh
```

Installer actions:
1. Creates `.venv`
2. Installs dependencies
3. Generates strong bearer token (or keeps existing token)
4. Writes `~/.codexremote/config.env`
5. Installs helper commands in `~/.codexremote/bin`:
   - `codex-live` (start/attach Codex in tmux)
   - `codex-attach` (attach to an existing Codex tmux session)
6. Adds a `~/.zshrc` snippet so running `codex` in a normal Mac terminal starts in tmux
7. Installs `~/Library/LaunchAgents/com.desmond.codexremote.plist`
8. Starts service via `launchctl`

## Access
Local dashboard:

```text
http://127.0.0.1:8787/?token=<TOKEN>
```

Simple phone flow:
1. Open the URL.
2. Tap `Save Token`.
3. Tap `Start New Codex` (optionally keep `Open this session on Mac Terminal` enabled).
4. Pick a session and send messages in `Message Codex...`.

The home page is mobile-first and only shows Codex terminals/sessions.

## Shared terminal mirror behavior
- Mac -> Phone:
  - Open a normal Mac terminal and run `codex`.
  - Because of the installed shell snippet, this launches Codex in tmux and attaches you.
  - The same session appears in the phone app with full history/context.
- Phone -> Mac:
  - Start a session from phone.
  - Use `Open on Mac` for that session (or keep `Open this session on Mac Terminal` enabled at start).
  - A Terminal window opens on Mac attached to the exact same tmux session.
- Manual attach from Mac:
  - `codex-attach` (interactive picker), or
  - `tmux attach -t <session_name>`

Tailscale dashboard:

```text
http://<YOUR_TAILSCALE_IP>:8787/?token=<TOKEN>
```

API auth header:

```text
Authorization: Bearer <TOKEN>
```

## Example API calls

```bash
TOKEN="..."
BASE="http://127.0.0.1:8787"

curl -H "Authorization: Bearer $TOKEN" "$BASE/health"

curl -X POST "$BASE/tmux/session" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"ops","cwd":"/Users/desmondpottle"}'

curl -X POST "$BASE/shell/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session":"ops","command":"git status"}'

curl -X POST "$BASE/codex/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cwd":"/Users/desmondpottle/Documents/New project/NovaSpine","prompt":"Fix failing tests and run them"}'
```

## Notes
- Websocket auth supports bearer token via query string for browser clients:
  - `ws://host:8787/tmux/stream?session=<name>&token=<TOKEN>`
- Spectator links are read-only and time-limited:
  - create token: `POST /session/spectate` with bearer token
  - open browser viewer: `http://host:8787/spectate?session=<name>&token=<SPECTATOR_TOKEN>`
  - stream endpoint for viewer: `ws://host:8787/spectate/stream?session=<name>&token=<SPECTATOR_TOKEN>`
- Audit log path defaults to `~/.codexremote/audit.log`
