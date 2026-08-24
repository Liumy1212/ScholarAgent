# Backend instructions

These instructions extend the repository root `AGENTS.md` for work under `backend/`.

## Boundary

- Java is the Web Backend/BFF. Use the flow `Controller -> Service -> AgentClient`.
- Validate browser requests, convert DTOs, normalize errors, propagate request IDs, and proxy Agent REST/SSE responses.
- Do not parse PDFs, create embeddings, implement retrieval, own prompts, call models, or duplicate Agent persistence.
- Do not create a Java database or Mapper merely to satisfy a layered architecture.

## Implementation baseline

- Use Java 21, Spring Boot 4, Spring MVC, Maven Wrapper, and domain-oriented packages when the application is scaffolded.
- Use `WebClient` only as the downstream client. Do not switch the server runtime from Spring MVC to WebFlux.
- Prefer Java records for request and response DTOs.
- Keep Agent integration DTOs internal. Convert them before returning browser-facing responses.
- Use MapStruct for non-trivial DTO mapping; do not use `BeanUtils.copyProperties`.

## Responses and streaming

- Wrap ordinary JSON business responses in `Result<T>`; use `Result<PageResult<T>>` for pagination.
- Use correct HTTP status codes and centralize failures in `GlobalExceptionHandler`. Controllers must not hand-build failure envelopes.
- Do not wrap SSE, PDF downloads, or Actuator responses in `Result<T>`.
- Accept or generate `X-Request-Id`, return it to the browser, and forward it to the Agent.
- Preserve downstream SSE event name, ID, and data. Cancel the downstream subscription when the browser disconnects.
- Map connection failures before the stream opens to the agreed non-2xx error. Express failures after streaming begins with the contracted terminal event.

## Quality

- Test controllers, services, DTO conversion, request tracking, downstream timeouts, cancellation, and stream error mapping.
- When the wrapper exists, run `./mvnw verify` or `mvnw.cmd verify` before handoff.
- Use contract examples in integration tests rather than copying ad hoc payloads.
