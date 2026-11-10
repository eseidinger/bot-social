# Storage Adoption Plan

**Status:** Proposed, sequential roadmap. Each phase has a decision gate; later systems are options rather than commitments. The [project documentation](project-documentation.md) defines the product and data model.

## Guiding rules

PostgreSQL remains the source of truth for cases, subclaims, source metadata, evidence references, findings, verdict revisions, moderation actions, and jobs. Search indexes, vector collections, and graph stores are rebuildable projections. They use stable PostgreSQL IDs and never become the only copy of a published decision. Each new store gets a named owner, backup or rebuild procedure, health check, lag metric, and rollback switch before serving user traffic.

Introduce one capability at a time. For each phase, capture a baseline workload and evaluation set, implement a small read path behind a feature flag, compare it with the existing path, and promote it only if the measured benefit outweighs operational cost. Keep the previous read path until the new one has passed correctness and recovery checks.

## Phase 0: PostgreSQL MVP

**Capability.** Store transactional data, durable jobs, full-text search, and source relationships in PostgreSQL. Add indexes for the actual case-list and evidence-search queries. Use relational joins or bounded recursive queries to find common origins and affected verdicts.

**Why first.** The concept's initial workflow requires consistent revisions and evidence references. PostgreSQL already supports full-text search, while a single authoritative database keeps the first release operable.

**Exit gate.** The end-to-end workflow passes tests; a worker crash and retry cannot duplicate output; search relevance and latency have a measured baseline; backup and restore have been exercised. Record corpus size, query mix, p95 query latency, and moderator feedback for later comparisons.

## Phase 1: S3-compatible object storage, when evidence files are needed

**Trigger.** Moderators need durable copies of uploaded PDFs, screenshots, transcripts, or other files, and URLs or passage text alone cannot preserve the reviewed evidence.

**Implementation.** Store file bytes in an S3-compatible bucket and keep the object's immutable key, checksum, media type, capture time, and storage version identifier (when supported) in PostgreSQL. A passage or verdict reference points to the exact file version reviewed. Validate file type and size on upload; restrict writes and reads by role; define retention and deletion behavior. Do not treat a mutable URL as an immutable evidence snapshot.

**Acceptance and fallback.** Test retrieval of the exact reviewed version after a replacement upload, deletion attempt, and restore. Check that a missing object is surfaced as an evidence-integrity error. If the service is unavailable, block new file-backed evidence submissions while existing PostgreSQL cases remain readable.

## Phase 2: pgvector in PostgreSQL, when semantic recall is useful

**Trigger.** Keyword search misses meaningful paraphrases of earlier subclaims or evidence passages in a fixed evaluation set.

**Implementation.** Add embeddings for selected subclaims and passages with model name, model version, input checksum, creation time, and source record ID. Start with exact vector search on a bounded corpus, then evaluate an approximate index if scale requires it. Use vector search to retrieve candidates; the review agent must still compare exact wording and evidence. Recompute embeddings when the source text or embedding model changes.

**Acceptance and fallback.** Compare recall and precision on a labeled set, plus p95 latency and database resource use, against PostgreSQL keyword search. Keep keyword search available and disable semantic retrieval if it harms relevance or database performance. pgvector is an extension of the existing database, so this phase adds no independent service.

## Phase 3: OpenSearch, when full-text search outgrows PostgreSQL

**Trigger.** The corpus expands to long posts, transcripts, and many evidence passages, and measured search quality or latency cannot be improved sufficiently with PostgreSQL indexes and query tuning.

**Implementation.** Index public/searchable records from PostgreSQL with stable IDs, revision numbers, and visibility status. Start with keyword search and passage highlighting; evaluate hybrid keyword/vector search only if it improves the same labeled queries. Feed changes through a durable, replayable projection mechanism and support full reindexing. Search results resolve back to PostgreSQL before display so unpublished or changed records are not exposed from a stale index.

**Acceptance and fallback.** Demonstrate better search quality or latency at representative load; measure projection lag; test reindexing, deletion, and permission changes. Route reads back to PostgreSQL if OpenSearch is unavailable or its index is stale.

## Phase 4: Qdrant evaluation, only if pgvector has a measured limit

**Trigger.** Semantic retrieval remains valuable but pgvector cannot meet the agreed recall, latency, filtering, or operational targets at the expected corpus size after tuning.

**Implementation.** Project the same versioned embeddings and PostgreSQL IDs into a Qdrant collection. Run the same query and relevance set against pgvector and Qdrant. Include ingest lag, rebuild time, filtering behavior, capacity, and operating cost in the comparison. Retain one semantic-search implementation in production unless there is a specific, documented reason to run both.

**Acceptance and fallback.** Adopt Qdrant only if the benchmark shows a material improvement and its rebuild and outage behavior are acceptable. Otherwise end the evaluation and keep pgvector. If adopted, keep the pgvector or keyword path available during migration and rollback.

## Phase 5: HugeGraph evaluation, only for complex provenance queries

**Trigger.** Multi-hop citation tracing, shared-source detection, or correction impact analysis becomes too slow or difficult to maintain with PostgreSQL relationships on representative real cases.

**Implementation.** Project sources, evidence passages, claims, and verdicts as vertices with explicit citation and dependency edges. Keep edge provenance and PostgreSQL IDs. Compare actual impact-analysis queries against bounded PostgreSQL recursive queries. Rebuild the graph from authoritative relational records and prevent graph-only edits.

**Acceptance and fallback.** Adopt HugeGraph only if it materially improves query results or latency without losing traceability. If projection lag or graph availability fails, use the PostgreSQL relationship query and flag uncertain impact assessments for moderator review.

## Cross-store consistency and migration procedure

For any projection, write the authoritative record to PostgreSQL first. Publish a durable change event or use a transactional outbox so indexing can retry after failures. Consumers should upsert idempotently by PostgreSQL ID plus revision, reject older revisions, and record a processing checkpoint. A periodic reconciliation job compares record counts and sampled IDs, then repairs gaps. Search and graph responses are advisory until the API checks publication state and source revision in PostgreSQL.

Each introduction follows the same deployment sequence: schema/configuration change; backfill; shadow reads against real queries; correctness and performance comparison; limited feature-flag rollout; monitor lag and errors; full rollout; documented rollback and rebuild rehearsal. Do not delete the old index or adapter until the new path has passed recovery tests.

## Decision record

Before starting a phase, record: the observed problem, baseline measurements, expected improvement, chosen evaluation dataset, cost and operational owner, acceptance threshold, and rollback criteria. If the trigger is absent or the acceptance gate fails, leave that phase unimplemented and continue product work on the current storage stack.

## Technology references

- [PostgreSQL full-text search](https://www.postgresql.org/docs/current/textsearch.html)
- [pgvector capabilities and indexes](https://github.com/pgvector/pgvector)
- [Amazon S3 versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html) (version behavior of a chosen S3-compatible service must be verified separately)
- [OpenSearch search methods](https://docs.opensearch.org/latest/search-plugins/) and [hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/)
- [Qdrant collections](https://qdrant.tech/documentation/manage-data/collections/)
- [Apache HugeGraph introduction](https://hugegraph.apache.org/docs/introduction/)
