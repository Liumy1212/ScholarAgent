# Frontend instructions

These instructions extend the repository root `AGENTS.md` for work under `frontend/`.

## Boundary

- Build the React browser client only. Never call the Python Agent or infrastructure services directly.
- All application traffic goes through Java under `/api/v1/**`.
- Keep knowledge-base and chat pages separate, with shared UI code extracted only after real reuse appears.

## Implementation baseline

- Use React 19, Vite 7, TypeScript strict mode, pnpm 11, and Ant Design when the application is scaffolded.
- Prefer typed functional components and explicit request/response types. Do not use `any` to bypass contract mismatches.
- Add dependencies only when the current feature uses them. Do not add TanStack Query or a state framework before a concrete need exists.
- Keep browser-facing DTOs independent from Python Agent DTOs.

## API and SSE

- Treat `contracts/web-api/` as the source of truth. Do not invent or silently rename API fields in the client.
- The chat stream is a POST SSE response parsed from `fetch`; do not replace it with `EventSource`, which cannot send the required POST body.
- Preserve event names, event IDs, sequence numbers, request IDs, payloads, and terminal states defined by the SSE contract.
- Distinguish completed, failed, and interrupted streams. Do not implement replay or automatic reconnect until the contract defines it.
- Render paper evidence separately from model knowledge and retain paper title/page citation details.

## Quality

- Add unit tests for stream parsing and state transitions, and component tests for user-visible behavior.
- When scripts exist, run `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` before handoff.
- Keep accessibility, loading, empty, failure, and interrupted states visible and testable.
