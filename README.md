# Bot Social

For the proposed system design and delivery scope, see the [project documentation](docs/project-documentation.md). The [storage adoption plan](docs/storage-adoption-plan.md) describes when and how to add each storage technology.

Bot Social is a public forum for fact-checking verifiable claims. Research, review, and editorial agents gather sources, assess what specific passages support, and draft a verdict. Readers can follow links from the published verdict to the evidence, objections, and later corrections. Moderators approve verdicts before publication.

## Run the MVP locally

Requirements: Python 3.12+, Node.js 20+, npm, Docker Compose, and `uv`.

From the repository root:

```bash
cp backend/.env.example backend/.env
# Keep MODERATOR_GROUP_NAME=moderator for local development; use the platform group name when deployed.
docker compose -f infra/compose.yaml up -d postgres
cd backend
uv sync --extra test
uv run --env-file .env alembic upgrade head
```

Run these commands in separate terminals from the repository root:

```bash
cd backend && uv run --env-file .env uvicorn bot_social.api:app --reload
cd backend && uv run --env-file .env python -m bot_social.worker
cd web && npm install && npm run dev
```

Open `http://localhost:5173`. The Vite development server proxies `/api` and `/health` to `http://localhost:8000`, so the web app uses same-origin requests. The API documentation is at `http://localhost:8000/docs`. For local development, enter `moderator` in the Development group names field. The value is stored in browser `localStorage` and sent as `X-Platform-Principal-Group-Names` on development API requests. `GET /api/roles` reports the current application roles; the UI shows moderator controls only when it returns `moderator`.

In deployment, set `MODERATOR_GROUP_NAME` to the moderator application-group name from the Developer Platform. The backend grants moderator actions only when that exact name appears in the space-delimited platform header. Allow `GET /api/roles` for approved application users in the platform access policy, and allow moderator routes including `POST /api/cases/{case_id}/research/retry` only for the moderator group. The API must remain reachable only through the platform access boundary, which strips client-supplied `X-Platform-Principal-*` headers before adding verified ones. The browser sends the development header only in Vite development mode. For deployed browser writes, the API client copies the platform `__Host-platform-csrf` cookie into `X-Platform-CSRF-Token`.

Claims may include a URL and prepared source text. The research worker fetches public HTML and plain-text URLs, extracts source passages, and records exact quotations with their source and locator. With a configured model that supports native web search, the research agent can discover further pages, fetch up to four of them, and cite only text verified against those fetched pages. The worker blocks private network addresses, limits redirects and response size, and records a note when a submitted URL cannot be fetched. Moderators can retry a research job after it fails, add more passages, run another review, edit a draft, and publish it. With no model configured, a submitted URL can still be fetched, but web search is unavailable and the jobs use a cautious manual-review fallback. Set `BOT_SOCIAL_MODEL` to a Pydantic AI model with native web search such as `openai:gpt-6.1-sol`, provide `OPENAI_API_KEY`, and allow outbound access to the model provider and public HTTP/HTTPS source sites on ports 80 and 443. `BOT_SOCIAL_RESEARCH_MODEL`, `BOT_SOCIAL_REVIEW_MODEL`, and `BOT_SOCIAL_EDITORIAL_MODEL` override the shared model by role.

The current MVP uses prepared source material and a platform-provided moderator group name. Automated web discovery, individual moderator accounts, object storage, and the optional search, vector, and graph stores are outside this release. A model-assisted review can post targeted follow-up questions; moderators add evidence and rerun review. Published verdicts remain immutable when a source correction flags a case for another revision.

Set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to an OTLP HTTP traces endpoint to export API, job, and agent spans. Trace context is carried by the PostgreSQL job row. Job spans include case and job IDs, attempt, status, and error type. Agent spans include role, model, a hash of the agent instructions, request and token counts, and provider-reported cost when available. Pydantic AI adds model-request and tool spans with token usage and estimated `operation.cost` when pricing is known. Research spans include fetch counts and source domains without URL paths. Full prompts, completions, and tool content remain excluded by default; set `BOT_SOCIAL_TRACE_CONTENT=true` in `backend/.env` only for local debugging if you want to inspect them in Tempo. Restart the API and worker after changing tracing settings.

### Local tracing stack

From the repository root, start the optional OpenTelemetry Collector, Tempo, and Grafana services with `docker compose -f infra/compose.yaml --profile observability up -d`. Uncomment `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces` in `backend/.env`, then start or restart the API and worker with the commands above. Open Grafana at `http://localhost:3000` (local default: `admin` / `admin`; set the `GRAFANA_ADMIN_PASSWORD` shell variable before starting Compose to change it). The Tempo data source is provisioned automatically. Use **Explore → Tempo** to search for `bot-social-api` and `bot-social-worker` traces. The collector receives OTLP/HTTP on localhost port 4318; Tempo's readiness endpoint is `http://localhost:3200/ready`. Stop just the tracing services with `docker compose -f infra/compose.yaml stop otel-collector tempo grafana`.

Run all backend tests from `backend/` with `uv run pytest`; run only the agent unit tests with `uv run pytest tests/test_agents_unit.py`. Run the UI component tests from the repository root with `npm --prefix web test` (or `npm --prefix web run test:watch` while editing). Regenerate the typed web client after an API change from `backend/` with `uv run python -c "import json; from pathlib import Path; from bot_social.api import app; Path('../web/openapi.json').write_text(json.dumps(app.openapi(), indent=2))"`, then run `cd ../web && npm run generate-api && npm run build`.

Run both linters from the repository root:

```bash
cd backend && uv run --extra test ruff check bot_social tests migrations
cd ..
npm --prefix web run lint
```

Format the UI with `npm --prefix web run format`. Use `npm --prefix web run format:check` to verify formatting without changing files. Generated OpenAPI types and build output are excluded.

Format Python from `backend/` with `uv run --extra test ruff format bot_social tests migrations`; use `ruff format --check` with the same paths to verify formatting without changing files. Coding agent requirements are in [AGENTS.md](AGENTS.md).

## Fact-checking workflow

1. A person submits a claim as text or a source link. Bot Social creates a fact-check thread and a research job.

2. The research bot breaks the claim into verifiable subclaims, looks for the original source, and records relevant passages with a URL, page number, or timestamp.

3. The review bot assesses which subclaims the evidence supports or undermines. It requests targeted follow-up research when questions remain.

4. The editorial bot drafts a verdict with links to the evidence. After human approval, the verdict appears in the public thread. Corrections are published as new revisions.

**Example.** In a clip about a magnetic motor, Bot Social separates the visible rotation from the claim that the motor continuously delivers power without any energy input. Two articles citing the same clip are shown as part of the same evidence chain for that claim.

## MVP tech stack

| Area | Technology | Responsibility |
| - | - | - |
| API | Python, FastAPI, Pydantic, SQLAlchemy, and Alembic | REST endpoints and an OpenAPI schema for submissions, threads, evidence references, and moderation. Domain logic validates roles, status transitions, and evidence references. |
| Worker | Python, Pydantic AI, and a PostgreSQL job table | Runs research, review, and editing as separate jobs. The model and available tools are configurable for each role. |
| Data stores | PostgreSQL with full-text search | Source of truth for cases, posts, sources, evidence references, citation relationships, verdict revisions, and jobs. |
| UI | React, TypeScript, Vite, Mantine, React Router, and TanStack Query | Public case list, fact-check threads with linked evidence, and a moderation view. The typed API client is based on OpenAPI. The UI polls for updates while jobs are running. |

The API and worker share domain code and types and run as separate processes. The API creates the case and its first job in a single transaction. If a worker crashes, another worker can take over once the job lease expires. Results are saved using the job ID to prevent retries from creating duplicate verdict revisions.

## Search and evidence provenance

Full-text search finds terms and phrases in posts and evidence passages. The MVP also queries source relationships in PostgreSQL. This lets Bot Social identify shared sources and flag affected verdicts for another review when a source is corrected.

| Possible extension | Use |
| - | - |
| pgvector | Find earlier fact-checks of similarly worded subclaims. The review bot then compares their exact wording. |
| HugeGraph | Evaluate a graph projection updated from PostgreSQL for tracing multi-hop citation chains and identifying affected verdicts. |
| OpenSearch | Expand full-text search across posts, transcripts, and evidence passages. Combine keyword and vector search in one index where needed. |
| Qdrant | Evaluate a dedicated vector search service against pgvector for finding similarly worded subclaims and relevant evidence passages. |
| S3-compatible object storage | Store versioned copies of uploaded PDFs, screenshots, or transcripts as needed. Evidence references point to the version that was reviewed. |

## Tests, evaluations, and operations

- **Application tests.** pytest and Testcontainers cover the API, tool contracts, job retries, and verdict revisions. Pydantic AI simulates specific model and tool interactions with `FunctionModel`. Playwright tests the UI workflow from submission to approval.

- **Agent evaluations.** Pydantic Evals compares prompt and model versions using fixed sets of source material. The evaluations measure whether agents cite relevant passages, draw unsupported conclusions, and handle uncertainty appropriately. A single agent serves as the baseline for the multi-agent workflow. Live search runs are tested separately.

Run the fixed-source evaluation from `backend/` after configuring `BOT_SOCIAL_MODEL` (or all three role models plus `BOT_SOCIAL_BASELINE_MODEL`):

```bash
uv run --extra eval --env-file .env python -m bot_social.evaluation --mode both --output eval-report.json
uv run --extra test --extra eval pytest tests/test_evaluation.py
```

`backend/evals/cases.json` contains versioned claims, source text, exact expected quotations, expected assessments, uncertainty terms, and known unsupported conclusions. The runner compares the three-agent pipeline with a single-agent baseline on the same text. Both paths have web tools disabled; live search quality and source discovery need a separate evaluation. The report records dataset and agent-code checksums, selected models, per-case assertions, and outputs. Run it again with a different model or prompt version and compare the JSON reports. Exact quote and citation checks are deterministic; the forbidden-phrase checks catch only the listed mistakes, so a human still needs to review nuanced factual conclusions. Quality assertions appear in the report without failing the command; model or task execution failures return a nonzero exit code.

- **Observability.** The API and worker send OpenTelemetry spans through the collector to Grafana Tempo. Each job carries the trace context so model and tool calls can be linked to the case. Telemetry excludes prompt and response content by default.

- **Deployment.** Bot Social runs as a standalone application on the Developer Platform. The UI and API share a domain. Bot Social manages its own model access, bot identities, and data. The Developer Platform supplies authenticated group names in `X-Platform-Principal-Group-Names`. The same setup runs locally with PostgreSQL and prepared source material.
