# AIResearcher repository instructions

## Current stage

- The repository is in Phase 0. The current baseline contains collaboration rules and documentation only.
- Read `README.md`, `docs/architecture.md`, `docs/roadmap.md`, and the nearest nested `AGENTS.md` before changing a subsystem.
- Keep each task inside its declared boundary. Do not add unrelated scaffolding, dependencies, or speculative abstractions.

## System boundaries

- `frontend/` is the React client. It calls only the Java API under `/api/v1/**`.
- `backend/` is the Java Web backend/BFF. It validates web requests, normalizes responses, forwards SSE, and calls the Python Agent.
- `agent/` is the Python Agent API and worker. It owns paper files, AI data, ingestion, retrieval, prompts, providers, and future research workflows.
- `contracts/` is the source of truth for Java-to-Agent and browser-to-Java API and SSE contracts.
- `infrastructure/` contains development infrastructure configuration only. It must never contain database software or runtime data.

## Change workflow

- Inspect `git status` before editing and preserve user or other-task changes.
- Make contract-affecting changes in `contracts/` first. Update implementations only after the contract change is accepted.
- A task must explicitly own shared contract files before modifying them. Never let multiple chats edit the same contract concurrently.
- Use one bounded task per branch or Codex Worktree. Start new work from the latest accepted `main`.
- Do not commit, push, rewrite history, or modify remote repository settings unless the task explicitly requests it.

## Architecture rules

- Preserve the request path React -> Java BFF -> Python Agent. React must not call Python directly.
- Python is the only source of truth for paper and AI-domain data. Java must not duplicate paper persistence.
- Keep ordinary JSON APIs distinct from SSE, downloads, and health endpoints.
- Do not introduce LangGraph into Phase 0-3 ingestion or RAG request paths without a new accepted ADR.
- Prefer the simplest implementation that satisfies the current phase and its tests.

## Validation

- Run the checks documented by the nearest subsystem instructions.
- Contract changes must validate specifications, schemas, examples, and affected consumers.
- Add or update tests for behavior changes. Never hide a failing check by weakening assertions or disabling validation.
- Before handoff, run `git diff --check` and report checks that could not run.

## Data and environment safety

- Never commit API keys, passwords, tokens, `.env` files, private research data, PDFs, database files, vectors, models, caches, or logs.
- Use only synthetic, redistributable fixtures in tests.
- Do not install global tools, modify `PATH`, or change the Conda `base` environment without explicit user approval.
- Use project wrappers and isolated project environments. The planned Python environment is `airesearcher-agent`, separate from existing environments.
- Do not install Docker Desktop, Maven, project skills, or other machine-wide software as an incidental task step.

## Documentation

- Documentation is Chinese-first. Code identifiers, API fields, branch names, and commit messages are English.
- Keep `AGENTS.md` executable and concise; put architectural explanations and decisions under `docs/`.
- Update relevant documentation and ADRs whenever a boundary, contract, dependency policy, or development workflow changes.
