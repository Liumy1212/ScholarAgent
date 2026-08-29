# AIResearcher repository instructions

## Current stage

- The repository is in Phase 0. Contracts and application skeletons are being implemented and integrated locally.
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
- `contracts/**` is owned by the documentation Chat. Never let multiple Chats edit the same contract concurrently, and do not let implementation Chats change wire shapes.
- Keep long-lived local branches and Worktrees for `codex/frontend`, `codex/backend`, `codex/agent`, `codex/docs`, and `codex/test`. Each branch may carry only one bounded, unfinished task at a time.
- Before a new long-lived-branch task, run `git merge --ff-only main`. After Local integration, fast-forward that branch to `main` again before accepting another task.
- Ownership is fixed: frontend, backend, and agent own their directories and module tests; docs owns `contracts/**`, `docs/**`, all `README.md` and `AGENTS.md` files, and `.env.example`; test owns only repository-level `tests/**`.
- Cross-subsystem work uses temporary `codex/feature/<feature>-<slice>` branches and separate Worktrees created from the latest accepted local `main`. One Chat owns one slice; contract changes are accepted before consumer slices begin.
- A Worktree task may commit only its own validated changes. It must not push, create a pull request, rebase, reset, force-update, or rewrite shared history.
- Keep the Local checkout on `main`. The Local integration chat merges completed task branches into local `main` one at a time after reviewing their diff and validation results.
- Codex must not push `main` or any task branch, create pull requests, rewrite shared history, or modify remote repository settings. The user alone publishes local `main` to GitHub.
- Module behavior changes include tests in the owning module; the test Chat adds only cross-system tests and returns module defects to the owning Chat.
- Keep long-lived branches and Worktrees. Keep temporary feature branches until the user confirms the integrated `main` has been uploaded; delete branches or Worktrees only when explicitly requested.

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
