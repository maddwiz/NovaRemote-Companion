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
