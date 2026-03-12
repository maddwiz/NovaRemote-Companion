# Companion Protocol Surface

Updated: 2026-03-11

This document defines the app-facing contract for the Codex Remote companion server while NovaAdapt and NovaSpine run as optional sidecars.

## Trust Boundary

NovaRemote talks only to Codex Remote.

```text
NovaRemote app
  -> Codex Remote (:8787)
      -> NovaAdapt bridge (:9797)
      -> NovaSpine (:8420, optional)
```

The phone does not call NovaAdapt or NovaSpine directly.

## Authentication

All protected HTTP routes require:

```text
Authorization: Bearer <CODEXREMOTE_TOKEN>
```

Websocket/browser routes also support token query parameters for browser-only contexts.

## Versioning Policy

Codex Remote publishes two compatibility markers:

- `protocol_version`
- `agent_contract_version`

Rules:

- `protocol_version` changes whenever the mobile-facing companion envelope changes (`/health`, `/agents/capabilities`, auth semantics, or streamed event framing).
- `agent_contract_version` changes whenever the allowlisted `/agents/*` contract changes in a way the app must understand.
- Additive route exposure should still bump the relevant version if the app’s capability handling or fallback behavior must change.
- Live sidecar validation is expected to fail if the running companion reports versions older or newer than the checked-out validator expects.

This is intentional: operators should notice contract drift before they assume a runtime stack is healthy.

## Core Health Contract

### `GET /health`

Returns the top-level companion health plus sidecar summaries when configured.

Required top-level fields:
- `ok`
- `protocol_version`
- `agent_contract_version`
- `features`
- `novaadapt`
- `novaspine`

Important `features` flags:
- `terminal`
- `tmux`
- `stream`
- `spectate`
- `agents`

Expected sidecar status shape:
- `novaadapt.enabled`
- `novaadapt.configured`
- `novaadapt.ok`
- `novaspine.configured`
- `novaspine.ok`

## Agent Runtime Contract

### `GET /agents/health`

Authenticated passthrough to the NovaAdapt bridge health endpoint.

Expected fields:
- `ok`
- `service`
- `core`
- `bridge`

### `GET /agents/capabilities`

Companion-owned cached capability summary for optional NovaAdapt route families.

Expected fields:
- `ok`
- `protocol_version`
- `agent_contract_version`
- `checked_at`
- `cached`
- `capabilities`

Required capability keys:
- `memoryStatus`
- `governance`
- `workflows`
- `templates`
- `templateGallery`

This endpoint exists so NovaRemote can avoid probing unsupported optional NovaAdapt routes on every refresh.

## Streaming Routes

The companion currently exposes two streaming transports:

### WebSocket

- `WS /tmux/stream`
- `WS /spectate/stream`

Auth:

- bearer header for native/app clients
- `?token=` query support for browser viewers

Behavior:

- newline-delimited terminal deltas
- reconnect is client-driven
- no public guarantee of replay beyond the normal tail/session APIs

### Server-Sent Events (SSE)

- `GET /agents/events/stream`
- `GET /agents/plans/{id}/stream`
- `GET /agents/jobs/{id}/stream`

Behavior:

- `text/event-stream`
- event names and payloads are bridge-defined pass-throughs from NovaAdapt
- mobile clients should treat SSE as live-state enhancement, not the only source of truth
- normal JSON reads (`/agents/events`, `/agents/plans`, `/agents/jobs`) remain the recovery path after reconnects or missed events

## Allowlisted `/agents/*` Routes

The companion server proxies only an allowlisted subset of NovaAdapt routes.

### Health and events
- `GET /agents/health`
- `GET /agents/events`
- `GET /agents/events/stream`

### Plans
- `GET /agents/plans`
- `GET /agents/plans/{id}`
- `GET /agents/plans/{id}/stream`
- `POST /agents/plans`
- `POST /agents/plans/{id}/approve`
- `POST /agents/plans/{id}/approve_async`
- `POST /agents/plans/{id}/retry_failed`
- `POST /agents/plans/{id}/retry_failed_async`
- `POST /agents/plans/{id}/reject`
- `POST /agents/plans/{id}/undo`

### Jobs
- `GET /agents/jobs`
- `GET /agents/jobs/{id}`
- `GET /agents/jobs/{id}/stream`
- `POST /agents/jobs/{id}/cancel`

### Memory
- `GET /agents/memory/status`
- `POST /agents/memory/recall`
- `POST /agents/memory/ingest`

### Governance
- `GET /agents/runtime/governance`
- `POST /agents/runtime/governance`
- `POST /agents/runtime/jobs/cancel_all`

### Templates
- `GET /agents/templates`
- `GET /agents/templates/{id}`
- `GET /agents/gallery`
- `POST /agents/templates/import`
- `POST /agents/templates/{id}/launch`

### Workflows
- `GET /agents/workflows/status`
- `GET /agents/workflows/list`
- `GET /agents/workflows/item`
- `POST /agents/workflows/start`
- `POST /agents/workflows/advance`
- `POST /agents/workflows/resume`

### Terminal bridge routes
- `GET /agents/terminal/sessions`
- `GET /agents/terminal/sessions/{id}`
- `GET /agents/terminal/sessions/{id}/output`
- `POST /agents/terminal/sessions/{id}/input`
- `POST /agents/terminal/sessions/{id}/close`

## Explicitly Not Proxied

These NovaAdapt route families are intentionally blocked at the companion layer
until they have a reviewed mobile contract, tests, and rollout plan:

- `/agents/browser/*`
- `/agents/voice/*`
- `/agents/canvas/*`
- `/agents/mobile/*`
- `/agents/execute/*`
- `/agents/adapt/*`

This keeps the companion boundary narrow even when NovaAdapt grows new
capabilities on parallel branches.

## Companion Responsibilities

Codex Remote owns:
- bearer-token auth
- route allowlisting
- timeout enforcement
- route-family capability caching
- mobile-facing health envelope
- terminal/file/codex APIs outside NovaAdapt

NovaAdapt owns:
- planning
- jobs
- workflows
- runtime governance
- memory operations behind the bridge

NovaSpine owns:
- persistent memory service
- health and memory API when configured as the NovaAdapt backend

## Validation Requirements

A healthy sidecar deployment must pass:

```bash
python scripts/validate_nova_sidecars.py --live-check
```

That live validation checks:
- `GET /health`
- `GET /agents/health`
- `GET /agents/capabilities`

It also verifies:
- required capability keys exist
- any enabled read-only sidecar route family answers through the companion
- `protocol_version` matches the checked-out companion build
- `agent_contract_version` matches the checked-out companion build

The deployment is not considered healthy if `/agents/capabilities` is missing required keys.

## Open-Source Boundary

The companion server is publishable once this contract remains stable and documented.

Open-source boundary should include:
- auth model
- health contract
- allowlisted `/agents/*` contract
- sidecar runbook
- validation script

Hosted/team cloud services should remain outside this repository.
