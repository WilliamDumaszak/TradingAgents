# Improvement plan: TradingAgents as the central project

This document records the consolidation of the most useful capabilities from
`agentic-rag-platform` and `llm-serving-monitoring` into TradingAgents. The
goal is to evolve the financial framework without replacing its CLI, LangGraph
workflow, or point-in-time analysis guarantees.

## Scope and principles

- The CLI remains a supported interface; the API is an additional interface.
- RAG is optional and must not prevent a normal analysis when it is disabled or
  unavailable.
- Every retrieved document must have a source and date. Historical analyses may
  only use content published on or before the reference date, preventing
  look-ahead bias.
- Changes must be incremental, tested, and compatible with Python 3.10 through
  3.13, which are already validated in CI.
- Do not copy the former projects wholesale: port only capabilities that fit
  the financial domain and the current codebase.

## Delivery order

### 1. HTTP API with FastAPI and Uvicorn

**Goal:** provide a programmatic interface for the same workflow currently run
through the CLI.

**Proposed implementation**

- Create an `api/` package with `api/main.py`, Pydantic schemas, and a service
  layer that invokes the existing workflow in `tradingagents/graph/`.
- Add `fastapi` and `uvicorn[standard]` as direct project dependencies.
- Initially create these endpoints:
  - `GET /health`: application availability and version;
  - `POST /analysis`: starts an analysis with ticker, reference date, LLM
    configuration, and execution options;
  - `GET /analysis/{run_id}`: returns the result or status of an analysis.
- Keep explicit request and response contracts, including validation errors and
  the distinction between completed, running, and failed executions.
- Run locally with `python -m uvicorn api.main:app --reload`; OpenAPI
  documentation will be available at `/docs`.

**Acceptance criteria**

- The CLI continues to work without behavior changes.
- `GET /health` and a `POST /analysis` test pass with mocked LLM and data
  dependencies.
- The API does not expose secrets, stack traces, or sensitive configuration.

### 2. Financial document RAG

**Goal:** allow agents to consult proprietary documents and financial sources
before producing a recommendation.

**Proposed implementation**

- Create `tradingagents/rag/` for document ingestion, chunking, embeddings,
  storage, and retrieval.
- Start with local ChromaDB because it is straightforward for individual use
  and development. Do not add Elasticsearch, Azure AI Search, or Airflow at
  this stage.
- Initially support text and PDF; every chunk must store at least `ticker`,
  `source`, `publication_date`, `document_id`, `ingested_at`, and a page number
  when applicable.
- Provide ingestion commands or routes separately from running an analysis.
- Filter results by ticker and the analysis reference date. Date filtering is
  mandatory to preserve the framework's historical integrity.
- Return chunks, metadata, and retrieval scores so responses can cite sources.

**Candidate dependencies**

- `chromadb`, `langchain-chroma`, and an embeddings implementation;
- a PDF reader, preferably `pymupdf`;
- `rank-bm25` only if hybrid search is needed after measuring simple vector
  search.

**Acceptance criteria**

- A test document can be ingested and retrieved for the correct ticker.
- A document published after the reference date never appears in a historical
  backtest.
- Retrieval returns a source and date for every selected chunk.

### 3. RAG integration with LangGraph agents

**Goal:** use document context where it improves analysis without forcing every
agent to query the knowledge base.

**Proposed implementation**

- Expose retrieval as a tool, for example `retrieve_financial_research`.
- Initially enable the tool for the fundamentals and news analysts and for the
  bull/bear researchers.
- Control the feature through a configuration option such as `use_rag`; the
  initial default must preserve existing behavior.
- Put only the most relevant chunks, bounded in size and including source
  references, into the workflow state to avoid wasting model context.
- Require the agent to identify the sources used in its final report.
- Treat unavailability, an empty database, and insufficient results as a safe
  fallback to the existing workflow, not as an analysis failure.

**Acceptance criteria**

- With RAG disabled, existing tests and workflow output structure do not
  change.
- With RAG enabled, an analyst receives only chunks eligible for the analysis
  ticker and reference date.
- The final report retains citations for retrieved documents.

### 4. Observability with Prometheus and Grafana

**Goal:** make API and document-retrieval usage, performance, and reliability
visible.

**Proposed implementation**

- Add `prometheus-client` and expose `GET /metrics` from the API.
- Instrument, at minimum:
  - count, duration, and failures of HTTP analyses;
  - duration of RAG retrieval steps;
  - count of documents and chunks retrieved;
  - LLM provider calls and failures;
  - tokens and cost when supplied by the provider.
- Add version-controlled Prometheus configuration and a Grafana dashboard under
  `monitoring/`.
- Do not label metrics by ticker, full query, or `run_id`, because that creates
  high cardinality and degrades Prometheus.

**Acceptance criteria**

- Prometheus collects the `/metrics` endpoint in the Docker environment.
- The dashboard shows analysis and RAG volume, error rate, and latency.
- Metrics contain neither sensitive information nor high-cardinality labels.

### 5. Docker and CI/CD

**Goal:** make the API service reproducible and validate the new capabilities
before publishing images.

**Proposed implementation**

- Preserve the existing multi-stage Dockerfile and the CLI service in
  `docker-compose.yml`.
- Add an `api` service that runs
  `uvicorn api.main:app --host 0.0.0.0 --port 8000`, exposes port 8000, and
  includes a `/health` health check.
- Add optional development services for persistent ChromaDB, Prometheus, and
  Grafana; basic CLI execution must not depend on them.
- Extend GitHub Actions to run API, RAG, and metrics tests in addition to the
  existing suite, smoke install, and lint checks.
- Once tests pass, create a build-and-publish image job for pushes to `main`.
  Publishing must depend on credentials configured in secrets and produce
  `latest` and commit-SHA tags.
- Do not include deployment to Azure, Kubernetes, or any other provider in this
  scope.

**Acceptance criteria**

- `docker compose up api` starts the API and its health check becomes healthy.
- CI fails when API, RAG, metrics, or lint tests fail.
- On `main`, an image is published only after every check passes and without
  exposing credentials in logs.

## Out of scope for this plan

The following technologies from the auxiliary projects will not be migrated
now:

- Redis and semantic caching;
- Airflow and scheduled ingestion;
- PostgreSQL and Elasticsearch;
- Kubernetes, Azure Container Apps, Bicep, and Azure services;
- RAGAS, reranking, and human-in-the-loop (HITL) review.

They can be evaluated later, but must not delay the five priority improvements
above.
