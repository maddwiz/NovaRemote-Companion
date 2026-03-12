# Companion Server Open-Source Checklist

Updated: 2026-03-11

This checklist gates open-sourcing Codex Remote as the public companion server for NovaRemote.

## 1. Contract Stability

- [x] companion `/health` returns sidecar status
- [x] companion `/agents/capabilities` exists and is validated
- [x] allowlisted `/agents/*` proxy surface is documented
- [x] websocket/SSE behavior is documented for all public streaming routes
- [x] versioning policy is written down for companion protocol changes

## 2. Security Boundary

- [x] bearer token is required for protected HTTP APIs
- [x] websocket/browser token fallback is documented
- [x] NovaAdapt routes are allowlisted instead of open passthrough
- [x] threat review for spectator token/query-token behavior
- [x] explicit token rotation guidance in README/runbook
- [x] rate-limit/revocation posture documented for public release

## 3. Sidecar Packaging

- [x] sidecar compose file exists
- [x] sidecar env example exists
- [x] local validator checks package and live host
- [x] live validation includes capability contract
- [x] one-command bootstrap for sidecars is documented beyond local macOS flow
- [ ] rollback examples verified on clean machine

## 4. CI and Verification

- [x] Python unit tests exist for agent proxy routes
- [x] sidecar validator tests exist
- [x] CI should run Python tests on every push/PR
- [x] CI should run a sidecar smoke check in containerized mode
- [x] compatibility test against pinned NovaAdapt branch should exist

## 5. Repository Hygiene

- [x] remove or isolate any local-machine assumptions from docs/examples
- [x] separate commercial/team-cloud guidance from open companion README
- [x] add issue templates / contribution guide
- [x] add release notes template and changelog policy

## 6. Launch Criteria

Open-source when all of these are true:
- public README matches actual live contract
- sidecar validator passes on a clean machine
- auth/protocol surface is stable enough to support outside contributors
- no private infra dependency is required to run the companion locally
