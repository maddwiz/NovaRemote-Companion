# Security Model

Updated: 2026-03-11

## Threat review: spectator and query-token behavior

### Protected APIs
Protected HTTP APIs require `Authorization: Bearer <CODEXREMOTE_TOKEN>`.
This includes the companion `/health` details used by the app and all `/agents/*` proxy routes.

### Browser-only token fallback
Browser-oriented websocket and spectator flows may use query tokens.
That behavior exists only to support:
- shared terminal viewers
- browser websocket clients that cannot set native headers as easily

Risk:
- query tokens are easier to leak via browser history, copy/paste, screenshots, and proxy logs.

Mitigations in current design:
- query-token use is limited to browser/spectator contexts, not the primary app auth path
- spectator links are read-only by design
- companion `/agents/*` routes do not use spectator query tokens
- the main mobile app path continues to use bearer headers

Required operator guidance:
- do not reuse the primary bearer token as a spectator token
- treat spectator URLs as secrets
- rotate share tokens after demos or incident response

## Rate-limit and revocation posture

Current posture:
- bearer tokens are static operator secrets
- spectator links are intended to be short-lived and narrower in scope
- sidecar bridge tokens are isolated from the primary mobile-facing token
- protected HTTP APIs reject query-string bearer tokens; query-token fallback is reserved for websocket/browser spectator flows

Recommended operational controls:
- rotate `CODEXREMOTE_TOKEN` on team changes, device loss, or suspected disclosure
- rotate sidecar bridge tokens independently
- avoid exposing the companion server directly to the public internet; prefer Tailscale or another private network
- keep the `/agents/*` allowlist narrow and versioned

Current limitations:
- there is no first-class token revocation list or rate-limiter built into Codex Remote yet
- revocation is operational: rotate token, restart service, invalidate old share links

## Release gate

Before public open-source launch, confirm:
- spectator/query-token handling is documented in `README.md` and `COMPANION_PROTOCOL.md`
- token rotation instructions are present in `README.md` and `NOVAADAPT_SIDECAR_RUNBOOK.md`
- no protected route silently falls back to unauthenticated access
