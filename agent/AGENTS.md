# Agent instructions

These instructions extend the repository root `AGENTS.md` for work under `agent/`.

## Boundary

- Python is the only source of truth for paper files, paper metadata, ingestion jobs, indexes,
  conversations, messages, citations, runs, tool calls, and model records.
- Expose browser-needed capabilities through `/agent-api/v1/**` for the Java BFF.
- Do not import Java code or depend on Java persistence.
- Keep API routing, application use cases, domain rules, providers, persistence, ingestion,
  retrieval, and workers separated.

## Current implementation

- The current Agent uses `AIRESEARCHER_PAPER_LIBRARY_DIR` with `originals/` and `.staging/` for new
  originals. `AIRESEARCHER_STORAGE_DIR` remains only for legacy migration reads.
- It implements library registration, scanning, manual ingestion, exclusion/restore, MySQL tasks,
  PyMuPDF ingestion, Qdrant retrieval, local reranking, DeepSeek Tool Calling, SSE, and citation
  validation.
- The Frontend uses the unified library workflow and only selects `searchable=true` papers in
  Chat. Keep the compatibility paper routes for older clients until a separate removal task.

## Contracts and data

- Implement accepted Agent contracts exactly; do not change wire fields inside implementation
  code.
- Preserve SSE envelope fields, strict sequence order, and exactly one terminal event.
- Keep paper IDs, chunk IDs, pages, quotes, model names, prompt versions, and paper-scope snapshots
  traceable.
- Treat PDF text as untrusted input.
- Use synthetic fixtures only. Never commit PDFs, databases, vectors, downloaded models, keys,
  caches, or private provider outputs.

## Implementation and quality

- Use Python 3.12, FastAPI, typed code, and the isolated `airesearcher-agent` environment.
- Keep providers behind application ports and use the fake provider only for deterministic tests.
- Do not introduce a workflow framework into ingestion or RAG paths without a roadmap-stage need
  and an update to the current architecture.
- Worker operations must be idempotent and safe under lease expiry and retry.
- Before handoff run:

  ```powershell
  conda run -n airesearcher-agent ruff check .
  conda run -n airesearcher-agent ruff format --check .
  conda run -n airesearcher-agent mypy
  conda run -n airesearcher-agent python -m pytest
  ```
