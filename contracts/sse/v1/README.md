# SSE v1 契约

本目录冻结 Phase 0 流式问答的 SSE 线协议。`sse-event.schema.json` 是数据事件 envelope 的 JSON Schema，`stream-open-error.schema.json` 是建流前错误体 Schema。

## 建流与请求追踪

- Web API 的 `X-Request-Id` 可选。Java 接收调用方值；缺失时生成一个有效值。
- Agent API 的 `X-Request-Id` 必填。Java 必须把有效值原样转发给 Agent。
- 有效 request ID 必须出现在成功或错误 HTTP 响应的 `X-Request-Id` 响应头中，并与 SSE envelope 或 `StreamOpenError.requestId` 相同。
- HTTP 200 和 `Content-Type: text/event-stream` 表示流已建立。此后的失败不能再改写 HTTP 状态。
- 建流前错误必须使用非 2xx HTTP 状态和 `application/json` 的 `StreamOpenError`；不得包装为 `Result<T>`。
- 建流后错误必须以唯一的 `run.failed` 终止事件表达。

## SSE 线格式

每个数据事件包含且只包含 `event`、`id` 和一个或多个 `data` 字段，后跟空行：

```text
event: message.delta
id: evt-demo-002
data: {"schemaVersion":"1.0","type":"message.delta","eventId":"evt-demo-002",...}

```

- SSE `event` 必须逐字等于 JSON `type`。
- SSE `id` 必须逐字等于 JSON `eventId`。
- `data` 拼接后必须是一个符合 `sse-event.schema.json` 的 UTF-8 JSON 对象。
- Java 转发时必须保留事件名、事件 ID 和完整 JSON envelope，不得重新编号或改名。
- 不发送 SSE `retry` 字段。

心跳不是数据事件，只能使用独立 SSE comment block，例如：

```text
: heartbeat 2026-01-01T00:00:01Z

```

心跳没有 envelope，不占用 `sequence`，也不能使用 `event: heartbeat`。

## Envelope

所有五种事件都必须包含以下字段，且不接受未声明字段：

| 字段 | 规则 |
| --- | --- |
| `schemaVersion` | v1 固定为字符串 `1.0` |
| `type` | 五种事件类型之一 |
| `eventId` | 流内唯一的不透明事件标识 |
| `requestId` | 与有效 `X-Request-Id` 相同 |
| `runId` | 本流固定的 run 标识 |
| `conversationId` | 与路径参数相同 |
| `assistantMessageId` | 本流固定的助手消息标识 |
| `sequence` | 从 0 开始，对每个数据事件严格加 1 |
| `timestamp` | RFC 3339 `date-time` 字符串 |
| `payload` | 由 `type` 决定的对象 |

同一个流内的 `requestId`、`runId`、`conversationId` 和 `assistantMessageId` 必须保持不变。

## 事件与 payload

| `type` | `payload` | 语义 |
| --- | --- | --- |
| `run.started` | 空对象 | 流的第一个数据事件 |
| `message.delta` | `{ "delta": string }` | 非空的增量文本 |
| `citation.created` | `citationId`、`paperId`、`paperTitle`、`pageNumber`、`quote` | 创建一条带页码和原文快照的论文引用 |
| `run.completed` | 空对象 | 唯一的正常终止事件 |
| `run.failed` | `code`、`message`、`retryable` | 唯一的失败终止事件 |

所有示例都是合成、可再分发数据，位于 `examples/events/`。`examples/streams/` 提供一个正常终止流和一个失败终止流。

## 顺序与终止

一个合法流满足：

1. 第一个数据事件是 `run.started` 且 `sequence` 为 0。
2. 中间可以有零个或多个 `message.delta` 与 `citation.created`。
3. 每个后续数据事件的 `sequence` 恰好比前一个大 1；comment 心跳不参与计数。
4. 最后一个数据事件是且只能是一个 `run.completed` 或 `run.failed`。
5. 终止事件之后不得再发送数据事件。

## 中断、重放与重连

v1 不保存事件以支持重放，不接受 `Last-Event-ID`，也不定义自动重连。连接在终止事件之前断开时，客户端把本次流标记为中断；只有用户发起新的 POST 才能开始新的 run。新的 POST 是新请求，不是旧流恢复。

## 夹具

- `examples/events/*.json`：五种事件各一个合法示例。
- `examples/streams/*.sse`：合法完成流和合法失败流。
- `examples/stream-open-error.json`：合法建流前错误。
- `fixtures/invalid/`：必须被校验器拒绝的事件与跨事件流。

在 `contracts/` 执行 `npm run validate` 会同时验证结构和上述线协议语义。
