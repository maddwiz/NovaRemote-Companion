# NovaAdapt + NovaSpine Sidecar Runbook

This runbook keeps Codex Remote as the only mobile-facing origin while NovaAdapt and NovaSpine run beside it.

Target topology:

```text
NovaRemote app
  -> Codex Remote (host process, :8787)
      -> NovaAdapt bridge sidecar (:9797)
          -> NovaAdapt core sidecar (:8788 mapped, :8787 in-container)
              -> NovaSpine sidecar (:8420)
```

## Why this shape

- Codex Remote stays the single endpoint the phone already trusts.
- NovaAdapt stays independently upgradeable.
- NovaSpine stays optional and can be disabled without taking down Codex Remote.
- Rollback is a sidecar shutdown, not a full companion-server rewrite.

## Prerequisites

- macOS host already running Codex Remote via `./install_mac.sh`
- Docker Desktop or compatible `docker compose`
- sibling checkout at `../NovaAdapt`, or set `NOVAADAPT_REPO_PATH`
- sibling checkout at `../NovaSpine`, or set `NOVASPINE_REPO_PATH`

## 1. Prepare sidecar env

From the Codex Remote repo:

```bash
cp .env.nova-sidecars.example .env.nova-sidecars
```

Edit at minimum:

- `NOVAADAPT_CORE_TOKEN`
- `NOVAADAPT_BRIDGE_TOKEN`
- `NOVASPINE_TOKEN`
- `NOVAADAPT_REPO_PATH` if your NovaAdapt checkout is not `../NovaAdapt`
- `NOVASPINE_REPO_PATH` if your NovaSpine checkout is not `../NovaSpine`
- `NOVAADAPT_OPENAI_API_KEY` / `NOVAADAPT_ANTHROPIC_API_KEY` only if you want those providers inside NovaAdapt
- `NOVAADAPT_OLLAMA_HOST` if the host Ollama daemon is not available at `http://host.docker.internal:11434`
- `NOVAADAPT_ENABLE_WORKFLOWS=1`
- `NOVAADAPT_ENABLE_WORKFLOWS_API=1`

## 2. Start sidecars

One-command bootstrap:

```bash
./scripts/bootstrap_nova_sidecars.sh
```

If `.env.nova-sidecars` does not exist yet, the bootstrap script creates it from the example and stops so you can fill in repo paths and tokens.

`bootstrap_nova_sidecars.sh` now retries live validation for up to 90 seconds after `docker compose up -d --build`. This is intentional because the first NovaSpine boot may need extra time to install its Python package before the health endpoint is ready. The pinned NovaAdapt compatibility baseline that validator enforces now lives in `compat/novaadapt_baseline.json`.

Validate the package first:

```bash
python scripts/validate_nova_sidecars.py --env-file .env.nova-sidecars
```

Validate the frozen local NovaAdapt checkout against the companion contract before you merge runtime upgrades:

```bash
python scripts/validate_nova_sidecars.py \
  --env-file .env.nova-sidecars \
  --novaadapt-contract-check
```

The repository CI now mirrors that contract check against the pinned NovaAdapt integration target and also runs a full sidecar smoke validation in containers.

If the sidecars are already running and Codex Remote is pointed at them, validate the live stack too:

```bash
python scripts/validate_nova_sidecars.py --env-file .env.nova-sidecars --live-check
```

If the stack is already running and you do not keep a checked-in `.env.nova-sidecars` file around on this machine, the validator can also fall back to compose-only package checks plus the live host/runtime probe:

```bash
python scripts/validate_nova_sidecars.py --live-check
```

Then start the sidecars:

```bash
docker compose \
  --env-file .env.nova-sidecars \
  -f docker-compose.nova-sidecars.yml \
  up -d --build
```

Equivalent helper:

```bash
./scripts/bootstrap_nova_sidecars.sh
./scripts/start_nova_sidecars.sh
```

## 3. Point Codex Remote at the sidecars

Add these to `~/.codexremote/config.env`:

```bash
export CODEXREMOTE_NOVAADAPT_ENABLED="true"
export CODEXREMOTE_NOVAADAPT_BRIDGE_URL="http://127.0.0.1:9797"
export CODEXREMOTE_NOVAADAPT_BRIDGE_TOKEN="replace-with-bridge-token"
export CODEXREMOTE_NOVAADAPT_TIMEOUT_SECONDS="15"
export CODEXREMOTE_NOVASPINE_URL="http://127.0.0.1:8420"
export CODEXREMOTE_NOVASPINE_TOKEN="replace-with-spine-token"
```

Restart Codex Remote after editing:

```bash
launchctl kickstart -k gui/$(id -u)/com.desmond.codexremote
```

## 4. Validate health

Codex Remote:

```bash
curl -s http://127.0.0.1:8787/health \
  -H "Authorization: Bearer $CODEXREMOTE_TOKEN"
```

Expected:

- `novaadapt.enabled=true`
- `novaadapt.reachable=true`
- `novaspine.reachable=true` when configured

Bridge direct:

```bash
curl -s http://127.0.0.1:9797/health
```

NovaSpine direct:

```bash
curl -s http://127.0.0.1:8420/api/v1/health \
  -H "Authorization: Bearer $NOVASPINE_TOKEN"
```

## 5. Validate app-facing routes through Codex Remote

```bash
curl -s http://127.0.0.1:8787/agents/health \
  -H "Authorization: Bearer $CODEXREMOTE_TOKEN"

curl -s http://127.0.0.1:8787/agents/capabilities \
  -H "Authorization: Bearer $CODEXREMOTE_TOKEN"

curl -s http://127.0.0.1:8787/agents/plans \
  -H "Authorization: Bearer $CODEXREMOTE_TOKEN"

curl -s http://127.0.0.1:8787/agents/workflows/list \
  -H "Authorization: Bearer $CODEXREMOTE_TOKEN"

curl -s http://127.0.0.1:8787/agents/workflows/start \
  -H "Authorization: Bearer $CODEXREMOTE_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"objective":"watch cluster","context":"api"}'
```

If those work, NovaRemote can use the server runtime without talking to NovaAdapt directly.

`/agents/capabilities` is a Codex Remote convenience endpoint. It caches optional NovaAdapt route-family support so the mobile app can avoid probing unsupported routes on every refresh, including memory, governance, workflows, templates, gallery, control artifacts, and the newer mobile/browser/voice/canvas/home-assistant/mqtt status families.
The live sidecar validator now checks that this endpoint is reachable, returns the expected capability keys plus `protocol_version` and `agent_contract_version`, enforces version parity with the current companion build, and verifies that any enabled read-only companion routes for those status/detail families are actually reachable through Codex Remote.

## Operational notes

- `novaspine` is installed from your checked-out `NovaSpine` repo. There is no public `pip install novaspine` wheel to rely on inside the sidecar.
- `novaspine` persists data in the named volume `novaspine-data`.
- `novaadapt-core` currently uses `config/models.example.json`; replace that with your own model config strategy before production.
- `NOVAADAPT_OLLAMA_HOST` defaults to `http://host.docker.internal:11434`, which is the simplest way to let NovaAdapt containers use a host Ollama daemon on macOS.
- workflow endpoints are disabled in NovaAdapt unless `NOVAADAPT_ENABLE_WORKFLOWS=1` or `NOVAADAPT_ENABLE_WORKFLOWS_API=1` is set for the core container.
- provider credentials use the `NOVAADAPT_*` prefixed env vars on purpose so the sidecars do not silently inherit unrelated host shell API keys.

## Rollback

1. Disable the bridge env in `~/.codexremote/config.env`:

```bash
export CODEXREMOTE_NOVAADAPT_ENABLED="false"
unset CODEXREMOTE_NOVAADAPT_BRIDGE_URL
unset CODEXREMOTE_NOVAADAPT_BRIDGE_TOKEN
unset CODEXREMOTE_NOVASPINE_URL
unset CODEXREMOTE_NOVASPINE_TOKEN
```

2. Restart Codex Remote:

```bash
launchctl kickstart -k gui/$(id -u)/com.desmond.codexremote
```

3. Stop sidecars:

```bash
docker compose \
  --env-file .env.nova-sidecars \
  -f docker-compose.nova-sidecars.yml \
  down
```

Equivalent helper:

```bash
./scripts/stop_nova_sidecars.sh
```

Phone behavior after rollback:

- Codex Remote still works normally
- NovaRemote falls back to the in-app NovaAdapt preview/runtime paths where supported

## Token rotation

When rotating sidecar credentials, update both the sidecar env file and the host companion config:

1. Generate replacement secrets for:
   - `NOVAADAPT_CORE_TOKEN`
   - `NOVAADAPT_BRIDGE_TOKEN`
   - `NOVASPINE_TOKEN`
   - `CODEXREMOTE_TOKEN` if you are rotating the mobile-facing companion auth too
2. Update:
   - `.env.nova-sidecars`
   - `~/.codexremote/config.env`
3. Restart both layers:

```bash
./scripts/stop_nova_sidecars.sh
./scripts/start_nova_sidecars.sh
launchctl kickstart -k gui/$(id -u)/com.desmond.codexremote
```

4. Re-run:

```bash
python scripts/validate_nova_sidecars.py --env-file .env.nova-sidecars --live-check
```

Do not rotate only one side of the bridge. A mismatched bridge/core/spine token set will make `/health` and `/agents/capabilities` fail fast, which is the intended behavior.

See also:
- [COMPANION_PROTOCOL.md](./COMPANION_PROTOCOL.md)
- [SECURITY_MODEL.md](./SECURITY_MODEL.md)
