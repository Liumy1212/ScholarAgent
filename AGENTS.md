# AIResearcher repository instructions

## Before changing files

- Inspect `git status --short --branch` and preserve unrelated user changes.
- Read the root `README.md`, the target module `README.md`, and the nearest nested
  `AGENTS.md`.
- Read `docs/architecture.md` for boundary changes, `docs/roadmap.md` for scope or status
  changes, and `docs/deployment.md` for runtime changes.
- Keep each task inside its declared boundary. Do not add unrelated scaffolding, dependencies,
  or speculative abstractions.

## Current stage

- The implemented baseline is the single-paper local RAG and paper-library flow described as stages 1.1-1.4 in
  `docs/roadmap.md`.
- Local paper-library scan, manual ingestion, and exclusion contracts are implemented by the
  Agent and Backend, and runtime configuration uses `AIRESEARCHER_PAPER_LIBRARY_DIR` below the
  ignored repository `.private/` boundary.
- The Frontend uses the unified library list, browser scan controls, manual ingestion, and
  exclusion/restore workflow; Chat only selects `searchable=true` papers. Stage 1.4 has passed the
  documented synthetic-PDF full-stack smoke test.

## System boundaries

- `frontend/` is the React client and calls only the Java API under `/api/v1/**`.
- `backend/` is the Java BFF. It validates browser requests, normalizes responses, forwards
  SSE/PDF traffic, and calls the Python Agent.
- `agent/` owns paper files, AI-domain data, ingestion, retrieval, prompts, providers, and
  workers.
- `contracts/` is the source of truth for accepted browser-to-Java and Java-to-Agent wire
  contracts. Consumer implementations may temporarily lag an accepted contract; track that
  status in the roadmap.
- `infrastructure/` contains development infrastructure configuration only, never runtime data.

## Change workflow

- Make wire-contract changes in `contracts/` first and validate them before changing consumers.
- Consumer implementations must not silently invent, rename, or reshape contract fields.
- Add or update tests for behavior changes in the owning module.
- Use only synthetic, redistributable fixtures.
- Before handoff, run the checks documented by the nearest module instructions and
  `git diff --check`. Report checks that could not run.

## Git policy

- The user alone manages commits, branches, worktrees, merges, rebases, pushes, and history.
- Read-only commands such as `git status`, `git diff`, and `git log` are allowed.
- Do not commit, create or switch branches, operate on worktrees, merge, rebase, reset, push,
  force-update, or rewrite history.

## Architecture and safety

- Preserve the request path React -> Java BFF -> Python Agent.
- Python remains the only source of truth for paper and AI-domain data; Java must not duplicate
  that persistence.
- Keep ordinary JSON APIs distinct from SSE, downloads, and health endpoints.
- Prefer the simplest implementation that satisfies the current stage and its tests.
- Never commit secrets, `.env` files, private research data, PDFs, databases, vectors, models,
  caches, or logs.
- Do not install global tools, modify `PATH`, change the Conda `base` environment, or install
  machine-wide software as an incidental task step.

## Documentation

- Human-facing documentation is Chinese-first. Code identifiers, API fields, and commands remain
  in English.
- Keep `AGENTS.md` files concise and executable.
- Do not create ADR files or a decision-log directory. Record current architecture in
  `docs/architecture.md` and future sequencing in `docs/roadmap.md`.
- Do not duplicate the same explanation across documents. Link to its single source of truth.
- Clearly distinguish implemented behavior, accepted contracts, and future plans.
