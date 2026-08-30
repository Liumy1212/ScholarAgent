# Frontend instructions

These instructions extend the repository root `AGENTS.md` for work under `frontend/`.

## Boundary

- Build only the React browser client.
- All application traffic goes through Java under `/api/v1/**`; never call the Python Agent,
  MySQL, Qdrant, or local files directly.
- Keep browser-facing DTOs independent from Python persistence and integration DTOs.
- Keep knowledge-base and question-answering pages separate; extract shared UI only after real
  reuse appears.

## Current implementation

- The current UI implements the unified library list, original-only PDF upload, manual scan and
  ingestion, status/retry, exclusion/restore, native original preview, tool status, SSE answers,
  and page citations.
- There is no browser hard-delete action for originals. Chat selection is limited to
  `searchable=true` papers.

## API and streaming

- Treat `contracts/web-api/` as the accepted target contract. Do not silently rename fields or
  invent wire behavior.
- POST SSE uses `fetch`; do not replace it with `EventSource`, which cannot send the request body.
- Preserve event names, IDs, sequence numbers, request IDs, payloads, and terminal states.
- Distinguish completed, failed, and interrupted streams. Do not add replay or automatic reconnect
  unless the versioned SSE contract defines it.
- Render paper evidence separately from ordinary model knowledge.

## Implementation and quality

- Use React 19, Vite 7, strict TypeScript, pnpm 11, typed functional components, and the existing
  Ant Design dependency.
- Do not use `any` to bypass contract mismatches or add a state/data framework without a current
  feature need.
- Add unit tests for parsers and state transitions, and component tests for visible behavior.
- Keep loading, empty, disabled, failure, interrupted, and accessibility states testable.
- Before handoff run:

  ```powershell
  pnpm lint
  pnpm typecheck
  pnpm test
  pnpm build
  ```
