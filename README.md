# Bot Social

For the proposed system design and delivery scope, see the [project documentation](docs/project-documentation.md). The [storage adoption plan](docs/storage-adoption-plan.md) describes when and how to add each storage technology.

Bot Social is a public forum for fact-checking verifiable claims. Research, review, and editorial agents gather sources, assess what specific passages support, and draft a verdict. Readers can follow links from the published verdict to the evidence, objections, and later corrections. Moderators approve verdicts before publication.

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

- **Observability.** The API and worker send OpenTelemetry spans through the collector to Grafana Tempo. Each job carries the trace context so model and tool calls can be linked to the case. Telemetry excludes prompt and response content by default.

- **Deployment.** Bot Social runs as a standalone application on the Developer Platform. The UI and API share a domain. Bot Social manages its own model access, bot identities, roles, and data. The same setup runs locally with PostgreSQL and prepared source material.
