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

## Core Health Contract

### `GET /health`

Returns the top-level companion health plus sidecar summaries when configured.

Required top-level fields:
- `ok`
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
