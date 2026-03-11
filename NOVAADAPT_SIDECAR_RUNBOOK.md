# NovaAdapt + NovaSpine Sidecar Runbook

Updated: 2026-03-10

## Goal

Run `codex_remote` as the single mobile-facing origin while NovaAdapt and NovaSpine run as separate local sidecars on the same machine.

This keeps:

- terminal/file/process transport in `codex_remote`
- long-running agent execution in `NovaAdapt`
- memory in `NovaSpine`

## Topology

```text
NovaRemote app
  -> codex_remote (http://127.0.0.1:8787)
      -> NovaAdapt bridge/core sidecar (http://127.0.0.1:9797)
      -> NovaSpine memory service (http://127.0.0.1:8420)
```

## Prerequisites

- local checkout of:
  - `/Users/desmondpottle/Documents/New project/codex_remote`
  - `/Users/desmondpottle/Documents/New project/NovaAdapt`
  - `/Users/desmondpottle/Documents/New project/NovaSpine`
- Python toolchain for `codex_remote` and `NovaAdapt`
- whatever runtime NovaSpine requires in its own repo

## 1. Start NovaSpine

Use the NovaSpine repo’s normal startup path first.

Target URL expected by NovaAdapt:

```text
http://127.0.0.1:8420
```

Expected API shape:

- `GET /api/v1/health`
- `POST /api/v1/memory/recall`
- `POST /api/v1/memory/ingest`
- `POST /api/v1/memory/augment`

## 2. Start NovaAdapt locally

From the NovaAdapt repo:

```bash
cd '/Users/desmondpottle/Documents/New project/NovaAdapt'
export NOVAADAPT_MEMORY_BACKEND='novaspine-http'
export NOVAADAPT_SPINE_URL='http://127.0.0.1:8420'
export NOVAADAPT_SPINE_TOKEN='replace-with-spine-token-if-required'
export NOVAADAPT_CORE_TOKEN='replace-with-core-token'
export NOVAADAPT_BRIDGE_TOKEN='replace-with-bridge-token'
./installer/run_local_operator_stack.sh
```

Expected sidecar endpoints after startup:

- core:
  - `http://127.0.0.1:8787`
- bridge:
  - `http://127.0.0.1:9797`

If you want to avoid the core using `8787` because `codex_remote` will own that port, override ports before launch:

```bash
export NOVAADAPT_CORE_PORT='8788'
export NOVAADAPT_BRIDGE_PORT='9797'
./installer/run_local_operator_stack.sh
```

When you change the bridge port, keep `codex_remote` pointed at the bridge URL, not the core URL.

## 3. Configure codex_remote bridge passthrough

Edit `~/.codexremote/config.env`:

```bash
export CODEXREMOTE_NOVAADAPT_ENABLED='true'
export CODEXREMOTE_NOVAADAPT_BRIDGE_URL='http://127.0.0.1:9797'
export CODEXREMOTE_NOVAADAPT_BRIDGE_TOKEN='replace-with-bridge-token'
export CODEXREMOTE_NOVAADAPT_TIMEOUT_SECONDS='15'
export CODEXREMOTE_NOVASPINE_URL='http://127.0.0.1:8420'
export CODEXREMOTE_NOVASPINE_TOKEN='replace-with-spine-token-if-required'
```

Then restart `codex_remote`.

## 4. Verify health

First verify `codex_remote`:

```bash
TOKEN='replace-with-codexremote-token'
BASE='http://127.0.0.1:8787'

curl -H "Authorization: Bearer $TOKEN" "$BASE/health?deep=1"
```

You should see `novaadapt` and `novaspine` blocks in the response.

Then verify the proxied agent routes:

```bash
curl -H "Authorization: Bearer $TOKEN" "$BASE/agents/health"
curl -H "Authorization: Bearer $TOKEN" "$BASE/agents/plans?limit=5"
curl -H "Authorization: Bearer $TOKEN" "$BASE/agents/jobs?limit=5"
curl -H "Authorization: Bearer $TOKEN" "$BASE/agents/workflows/list?limit=5&context=api"
curl -H "Authorization: Bearer $TOKEN" "$BASE/agents/memory/status"
```

## 5. Verify streaming

The mobile app now expects streamed plan/job updates to work through `codex_remote`.

Quick curl checks:

```bash
curl -N -H "Authorization: Bearer $TOKEN" "$BASE/agents/plans/<PLAN_ID>/stream?timeout=30&interval=0.25"
curl -N -H "Authorization: Bearer $TOKEN" "$BASE/agents/jobs/<JOB_ID>/stream?timeout=30&interval=0.25"
```

Expected content type:

```text
text/event-stream
```

## Current mobile status

With this sidecar setup, NovaRemote currently supports:

- runtime health and memory visibility
- plan/job/workflow listing
- live plan/job stream updates
- plan actions:
  - approve
  - reject
  - retry failed
  - undo
- dedicated `Agents` screen in the app

## Still pending

- fully moving agent CRUD/execution off the phone runtime
- richer server event transport if needed beyond plan/job SSE
- production packaging/deployment templates for this three-service layout
- companion-server open-source cleanup and protocol hardening
