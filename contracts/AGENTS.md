# Contract instructions

These instructions extend the repository root `AGENTS.md` for work under `contracts/`.

## Contract-first rules

- Contracts are shared public interfaces. A task must explicitly include the affected contract
  paths before editing them.
- Complete and validate contract changes before starting dependent consumer implementation.
- Python implements the Agent API, Java consumes it and implements the Web API, and React consumes
  the Web API.
- Keep Agent API contracts under `agent-api/` and browser-facing contracts under `web-api/`.
- Use `/agent-api/v1/**` for Python and `/api/v1/**` for Java.
- Do not overwrite a released breaking wire shape. Add a new version and document migration.
- Do not expose persistence models or Java internal types as wire formats.

## Consistency

- Update OpenAPI, JSON Schema, prose rules, valid examples, invalid fixtures, and semantic
  validation together.
- Accepted contracts can temporarily lead implementations. Record consumer status in
  `docs/roadmap.md` and do not describe contract-only behavior as shipped.
- Consumer defects do not authorize implementation modules to edit accepted wire shapes.

## SSE rules

- Define event name, event ID, JSON envelope, ordering, terminal behavior, heartbeat comments, and
  open-versus-streaming failures.
- Every example must validate against its schema and represent an event consumers are expected to
  support.
- Do not add replay, `Last-Event-ID`, or automatic reconnect without versioned storage and recovery
  semantics.

## Validation

- Add valid and invalid fixtures for new semantics.
- Validate both OpenAPI documents, every JSON Schema, examples, full streams, and affected consumer
  tests.
- From `contracts/` run:

  ```powershell
  npm ci
  npm run validate
  ```

- Report compatibility impact and current consumer implementation status.
