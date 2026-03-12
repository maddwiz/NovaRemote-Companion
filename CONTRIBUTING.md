# Contributing to Codex Remote

## Workflow

- Work in feature branches only: `feat/*`, `fix/*`, `hotfix/*`, `release/*`.
- Keep `main` stable.
- Run all repo-local git commands with explicit targeting when operating from a parent workspace:

```bash
git -C /absolute/path/to/codex_remote status
```

## Before opening a PR

Run:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m compileall app
python -m unittest discover -s tests -p 'test_*.py'
```

If you are working on NovaAdapt sidecar compatibility, also validate the sidecar contract:

```bash
python scripts/validate_nova_sidecars.py --env-file .env.nova-sidecars --live-check
```

## Scope boundaries

Codex Remote is the companion boundary. Keep it responsible for:
- auth
- allowlisting
- terminal/file/codex APIs
- sidecar health/capability visibility

Do not widen the `/agents/*` proxy surface without:
- explicit contract documentation in `COMPANION_PROTOCOL.md`
- tests for allowlisting and denied routes
- version bumps where required

## Changelog and release notes

Document user-visible behavior and contract changes in release notes using `RELEASE_NOTES_TEMPLATE.md`.
When auth semantics, `/health`, `/agents/capabilities`, or streamed event framing changes, update:
- `COMPANION_PROTOCOL.md`
- `README.md`
- `OPEN_SOURCE_CHECKLIST.md`

## Security reporting

Do not file sensitive security issues publicly.
Until a dedicated security contact is added, report them privately to the maintainer through the existing private channel.
