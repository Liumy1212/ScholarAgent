# Contract instructions

These instructions extend the repository root `AGENTS.md` for work under `contracts/`.

## Ownership

- Contracts are shared public interfaces. A task must explicitly own a contract path before editing it.
- Only one chat may modify shared contract files at a time. Land contract changes before starting dependent implementation tasks.
- Python is the Agent API implementer, Java is its consumer, and React consumes the Web API exposed by Java.

## Contract-first rules

- Update OpenAPI, JSON Schema, prose rules, and valid examples together.
- Keep Agent API contracts under `agent-api/` and browser-facing Java contracts under `web-api/`.
- Use `/agent-api/v1/**` for Python and `/api/v1/**` for Java.
- Do not overwrite a released contract with a breaking change. Add a new API or schema version and document migration.
- Keep request and response types explicit. Do not expose Java entities or Agent persistence models as wire formats.

## SSE rules

- Define event name, event ID, JSON envelope, ordering, terminal behavior, heartbeat comments, and open-versus-streaming failures.
- Every example must validate against its schema and represent a real event supported by all affected implementations.
- Do not add replay, `Last-Event-ID`, or automatic reconnect semantics unless the versioned contract defines storage and recovery behavior.

## Validation

- Contract tasks must add machine-readable validation and valid/invalid fixtures when the first specifications are introduced.
- Validate both OpenAPI documents, every JSON Schema, examples, and affected consumer tests before handoff.
- Report compatibility impact explicitly in the change summary.
