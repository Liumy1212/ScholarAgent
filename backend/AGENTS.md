# Backend instructions

These instructions extend the repository root `AGENTS.md` for work under `backend/`.

## Boundary

- Java is the browser-facing Backend/BFF. Keep the flow `Controller -> Service -> AgentClient`.
- Validate browser requests, convert DTOs, normalize errors, propagate request IDs, and proxy
  Agent REST/SSE/PDF responses.
- Do not parse PDFs, create embeddings, implement retrieval, own prompts, call models, or duplicate
  Agent persistence.
- Do not create a Java database or Mapper without data that clearly belongs to the Web layer.

## Current implementation

- The current BFF proxies library files, manual ingestion, scans, exclusion/restore, PDF Range, and
  streaming answers, while retaining compatibility paper routes.
- The Frontend uses the unified library workflow. Keep compatibility routes for older clients
  until a separate removal task explicitly changes the accepted contracts.

## Responses and streaming

- Use Java 21, Spring Boot 4, Spring MVC, the Maven Wrapper, and the existing domain packages.
- Use `WebClient` only as the downstream Agent client; do not switch the server to WebFlux.
- Prefer records for DTOs and keep Agent integration DTOs internal.
- Wrap ordinary browser JSON responses in `Result<T>` and pagination in `Result<PageResult<T>>`.
- Do not wrap SSE, PDF downloads, or Actuator responses in `Result<T>`.
- Accept or generate `X-Request-Id`, return it to the browser, and forward it to the Agent.
- Preserve downstream SSE event names, IDs, and data; cancel downstream work when the browser
  disconnects.

## Quality

- Test controllers, services, DTO conversion, request tracking, timeouts, cancellation, PDF Range,
  and stream error mapping.
- Use contract fixtures rather than copied ad hoc payloads.
- Before handoff run:

  ```powershell
  .\mvnw.cmd verify
  ```
