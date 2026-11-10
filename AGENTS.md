# Coding instructions for agents

These instructions apply to the whole repository. Follow the existing project design in `README.md` and `docs/` when changing behavior.

## Code standards

- Keep changes small and readable. Put domain validation and state transitions in the backend, and keep UI pages focused on data loading and composition of typed components.
- Use Python type annotations and the generated OpenAPI types for TypeScript API data. Do not edit `web/src/schema.d.ts` or `web/openapi.json` by hand; regenerate them after an API contract change.
- Preserve evidence provenance, published verdict revisions, moderator approval, and job idempotency when changing the fact-check workflow.
- Follow the configured Ruff, ESLint, and Prettier rules. Fix reported issues instead of disabling a rule unless a short explanation in code makes an exception necessary.

## Tests

- Add or update focused unit tests for every behavior change. Test observable outcomes and relevant edge cases, including invalid inputs and failure paths. Avoid tests that merely repeat the implementation.
- Add integration tests when a change crosses API, database, worker, or UI boundaries. Documentation-only changes do not need new tests.
- Keep tests deterministic and independent of live model calls or external services. Use fixtures or test doubles for those boundaries.

## Required checks before finishing

For backend changes, run from `backend/`:

```bash
uv run --extra test ruff format bot_social tests migrations
uv run --extra test ruff format --check bot_social tests migrations
uv run --extra test ruff check bot_social tests migrations
uv run --extra test pytest
```

For UI changes, run from the repository root:

```bash
npm --prefix web run format
npm --prefix web run format:check
npm --prefix web run lint
npm --prefix web test
npm --prefix web run build
```

After changing SQLAlchemy models or API schemas, also run the relevant migration or OpenAPI generation checks. Report which checks passed and any check that could not be run. Do not describe a failing check as complete.
