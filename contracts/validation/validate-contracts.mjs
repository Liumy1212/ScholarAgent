import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import SwaggerParser from "@apidevtools/swagger-parser";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const validationDirectory = path.dirname(fileURLToPath(import.meta.url));
const contractsDirectory = path.resolve(validationDirectory, "..");
const sseDirectory = path.join(contractsDirectory, "sse", "v1");
const terminalTypes = new Set(["run.completed", "run.failed"]);
const stableStreamFields = [
  "requestId",
  "runId",
  "conversationId",
  "assistantMessageId",
];

function relative(filePath) {
  return path.relative(contractsDirectory, filePath).replaceAll(path.sep, "/");
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function findFiles(directory, predicate) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await findFiles(entryPath, predicate)));
    } else if (predicate(entryPath)) {
      files.push(entryPath);
    }
  }

  return files;
}

function formatAjvErrors(errors) {
  return (errors ?? [])
    .map((error) => `${error.instancePath || "/"} ${error.message}`)
    .join("; ");
}

async function validateJsonSchemasAndExamples() {
  const schemaFiles = await findFiles(sseDirectory, (filePath) =>
    filePath.endsWith(".schema.json"),
  );
  assert.equal(schemaFiles.length, 2, "SSE v1 必须包含事件和建流错误两个 JSON Schema");

  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);

  for (const schemaFile of schemaFiles) {
    const schema = await readJson(schemaFile);
    assert.equal(
      ajv.validateSchema(schema),
      true,
      `${relative(schemaFile)} 不是合法 JSON Schema: ${formatAjvErrors(ajv.errors)}`,
    );
    ajv.addSchema(schema);
  }

  const eventSchemaId = "https://airesearcher.dev/contracts/sse/v1/sse-event.schema.json";
  const openErrorSchemaId =
    "https://airesearcher.dev/contracts/sse/v1/stream-open-error.schema.json";
  const validateEvent = ajv.getSchema(eventSchemaId);
  const validateOpenError = ajv.getSchema(openErrorSchemaId);
  assert.ok(validateEvent, "无法加载 SSE event Schema");
  assert.ok(validateOpenError, "无法加载 StreamOpenError Schema");

  const validEventDirectory = path.join(sseDirectory, "examples", "events");
  const validEventFiles = await findFiles(validEventDirectory, (filePath) =>
    filePath.endsWith(".json"),
  );
  const expectedTypes = new Set([
    "run.started",
    "message.delta",
    "citation.created",
    "run.completed",
    "run.failed",
  ]);
  const exampleTypes = new Set();

  for (const eventFile of validEventFiles) {
    const event = await readJson(eventFile);
    assert.equal(
      validateEvent(event),
      true,
      `${relative(eventFile)} 未通过事件 Schema: ${formatAjvErrors(validateEvent.errors)}`,
    );
    assert.equal(
      path.basename(eventFile, ".json"),
      event.type,
      `${relative(eventFile)} 的文件名必须等于事件 type`,
    );
    assert.equal(exampleTypes.has(event.type), false, `事件 ${event.type} 存在重复合法示例`);
    exampleTypes.add(event.type);
  }
  assert.deepEqual(exampleTypes, expectedTypes, "每种 SSE 事件必须恰有一个合法 JSON 示例");

  const openErrorExample = path.join(sseDirectory, "examples", "stream-open-error.json");
  const openError = await readJson(openErrorExample);
  assert.equal(
    validateOpenError(openError),
    true,
    `${relative(openErrorExample)} 未通过 StreamOpenError Schema: ${formatAjvErrors(
      validateOpenError.errors,
    )}`,
  );

  const invalidEventDirectory = path.join(sseDirectory, "fixtures", "invalid", "events");
  const invalidEventFiles = await findFiles(invalidEventDirectory, (filePath) =>
    filePath.endsWith(".json"),
  );
  assert.ok(invalidEventFiles.length > 0, "至少需要一个非法事件夹具");

  for (const eventFile of invalidEventFiles) {
    const event = await readJson(eventFile);
    assert.equal(
      validateEvent(event),
      false,
      `${relative(eventFile)} 被错误地接受为合法事件`,
    );
  }

  return validateEvent;
}

function parseSseBlock(block, sourceName) {
  const comments = [];
  const fields = new Map();

  const lines = block.split("\n");
  for (const [index, line] of lines.entries()) {
    if (line === "" && index === lines.length - 1) {
      continue;
    }
    if (line.startsWith(":")) {
      comments.push(line.slice(1).trimStart());
      continue;
    }

    const separator = line.indexOf(":");
    assert.notEqual(separator, -1, `${sourceName}: SSE 行缺少冒号: ${line}`);
    const name = line.slice(0, separator);
    const rawValue = line.slice(separator + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    assert.ok(
      ["event", "id", "data"].includes(name),
      `${sourceName}: 不允许 SSE 字段 ${name}`,
    );
    const values = fields.get(name) ?? [];
    values.push(value);
    fields.set(name, values);
  }

  if (comments.length > 0) {
    assert.equal(fields.size, 0, `${sourceName}: 心跳 comment 必须是独立 block`);
    assert.ok(
      comments.every((comment) => comment === "heartbeat" || comment.startsWith("heartbeat ")),
      `${sourceName}: v1 comment 只用于 heartbeat`,
    );
    return { kind: "heartbeat" };
  }

  assert.deepEqual(
    [...fields.keys()].sort(),
    ["data", "event", "id"],
    `${sourceName}: 数据事件必须包含且只包含 event、id、data`,
  );
  assert.equal(fields.get("event").length, 1, `${sourceName}: event 字段必须出现一次`);
  assert.equal(fields.get("id").length, 1, `${sourceName}: id 字段必须出现一次`);

  let data;
  try {
    data = JSON.parse(fields.get("data").join("\n"));
  } catch (error) {
    throw new Error(`${sourceName}: data 不是合法 JSON: ${error.message}`);
  }

  return {
    kind: "event",
    event: fields.get("event")[0],
    id: fields.get("id")[0],
    data,
  };
}

async function validateSseStream(filePath, validateEvent) {
  const sourceName = relative(filePath);
  const text = (await readFile(filePath, "utf8")).replaceAll("\r\n", "\n").replaceAll("\r", "\n");
  const blocks = text.split(/\n\n+/u).filter((block) => block.length > 0);
  const parsedBlocks = blocks.map((block) => parseSseBlock(block, sourceName));
  const frames = parsedBlocks.filter((block) => block.kind === "event");

  assert.ok(frames.length >= 2, `${sourceName}: 流至少需要 started 和 terminal 两个事件`);

  for (const frame of frames) {
    assert.equal(
      validateEvent(frame.data),
      true,
      `${sourceName}: ${frame.event} 未通过事件 Schema: ${formatAjvErrors(validateEvent.errors)}`,
    );
    assert.equal(frame.event, frame.data.type, `${sourceName}: SSE event 必须等于 JSON type`);
    assert.equal(frame.id, frame.data.eventId, `${sourceName}: SSE id 必须等于 JSON eventId`);
  }

  assert.equal(frames[0].data.type, "run.started", `${sourceName}: 首事件必须是 run.started`);
  assert.equal(
    frames.filter((frame) => frame.data.type === "run.started").length,
    1,
    `${sourceName}: run.started 必须恰好出现一次`,
  );

  const baseline = frames[0].data;
  const eventIds = new Set();
  frames.forEach((frame, index) => {
    assert.equal(frame.data.sequence, index, `${sourceName}: sequence 必须从 0 严格递增`);
    assert.equal(eventIds.has(frame.data.eventId), false, `${sourceName}: eventId 在流内必须唯一`);
    eventIds.add(frame.data.eventId);
    for (const field of stableStreamFields) {
      assert.equal(frame.data[field], baseline[field], `${sourceName}: ${field} 在流内必须保持不变`);
    }
  });

  const terminalFrames = frames.filter((frame) => terminalTypes.has(frame.data.type));
  assert.equal(terminalFrames.length, 1, `${sourceName}: 流必须且只能包含一个终止事件`);
  assert.equal(
    terminalTypes.has(frames.at(-1).data.type),
    true,
    `${sourceName}: 终止事件必须是最后一个数据事件`,
  );

  return frames.map((frame) => frame.data.type);
}

async function validateSseFixtures(validateEvent) {
  const validStreamDirectory = path.join(sseDirectory, "examples", "streams");
  const validStreamFiles = await findFiles(validStreamDirectory, (filePath) =>
    filePath.endsWith(".sse"),
  );
  assert.equal(validStreamFiles.length, 2, "必须提供正常终止和失败终止两个合法流");

  const streamTypes = new Set();
  for (const streamFile of validStreamFiles) {
    for (const type of await validateSseStream(streamFile, validateEvent)) {
      streamTypes.add(type);
    }
  }
  assert.deepEqual(
    streamTypes,
    new Set(["run.started", "message.delta", "citation.created", "run.completed", "run.failed"]),
    "合法流示例合计必须覆盖五种事件",
  );

  const invalidStreamDirectory = path.join(sseDirectory, "fixtures", "invalid", "streams");
  const invalidStreamFiles = await findFiles(invalidStreamDirectory, (filePath) =>
    filePath.endsWith(".sse"),
  );
  assert.ok(invalidStreamFiles.length > 0, "至少需要一个非法流夹具");

  for (const streamFile of invalidStreamFiles) {
    let rejected = false;
    try {
      await validateSseStream(streamFile, validateEvent);
    } catch {
      rejected = true;
    }
    assert.equal(rejected, true, `${relative(streamFile)} 被错误地接受为合法流`);
  }
}

async function assertExternalValuesExist(value, specDirectory, sourceName) {
  if (Array.isArray(value)) {
    for (const item of value) {
      await assertExternalValuesExist(item, specDirectory, sourceName);
    }
    return;
  }
  if (value === null || typeof value !== "object") {
    return;
  }

  for (const [key, child] of Object.entries(value)) {
    if (key === "externalValue" && typeof child === "string" && !child.includes("://")) {
      const externalPath = path.resolve(specDirectory, child);
      await access(externalPath);
      assert.ok(
        externalPath.startsWith(contractsDirectory + path.sep),
        `${sourceName}: externalValue 必须位于 contracts 内`,
      );
    } else {
      await assertExternalValuesExist(child, specDirectory, sourceName);
    }
  }
}

async function validateOpenApi(specPath, expectedPath, requestIdRequired) {
  const sourceName = relative(specPath);
  const parser = new SwaggerParser();
  const parsed = await parser.validate(specPath);
  const dereferenced = await SwaggerParser.dereference(specPath);

  assert.equal(parsed.openapi, "3.1.0", `${sourceName}: OpenAPI 版本必须为 3.1.0`);
  assert.deepEqual(Object.keys(parsed.paths), [expectedPath], `${sourceName}: 只能声明冻结路径`);
  assert.equal(
    JSON.stringify(parsed).toLowerCase().includes("last-event-id"),
    false,
    `${sourceName}: v1 不得声明 Last-Event-ID`,
  );

  await assertExternalValuesExist(parsed, path.dirname(specPath), sourceName);
  await access(path.resolve(path.dirname(specPath), parsed.externalDocs.url));

  const operation = dereferenced.paths[expectedPath].post;
  assert.ok(operation, `${sourceName}: 冻结路径必须定义 POST`);
  const requestIdParameter = operation.parameters.find(
    (parameter) => parameter.in === "header" && parameter.name.toLowerCase() === "x-request-id",
  );
  assert.ok(requestIdParameter, `${sourceName}: 必须声明 X-Request-Id`);
  assert.equal(
    requestIdParameter.required,
    requestIdRequired,
    `${sourceName}: X-Request-Id required 值不正确`,
  );

  const conversationIdParameter = operation.parameters.find(
    (parameter) => parameter.in === "path" && parameter.name === "conversationId",
  );
  assert.equal(conversationIdParameter?.required, true, `${sourceName}: conversationId 必须是必填路径参数`);

  const requestSchema = operation.requestBody.content["application/json"].schema;
  assert.equal(requestSchema.type, "object", `${sourceName}: 请求体必须是对象`);
  assert.equal(requestSchema.additionalProperties, false, `${sourceName}: 请求体不得有额外字段`);
  assert.deepEqual(
    [...requestSchema.required].sort(),
    ["content", "paperIds"],
    `${sourceName}: 请求体必须要求 content 和 paperIds`,
  );
  assert.equal(requestSchema.properties.content.type, "string", `${sourceName}: content 必须是 string`);
  assert.equal(requestSchema.properties.paperIds.type, "array", `${sourceName}: paperIds 必须是 array`);
  assert.equal(
    requestSchema.properties.paperIds.items.type,
    "string",
    `${sourceName}: paperIds 元素必须是 string`,
  );
  assert.match(
    requestSchema.properties.paperIds.description,
    /空数组.*默认全库/u,
    `${sourceName}: 必须冻结空 paperIds 的默认全库语义`,
  );

  const successResponse = operation.responses["200"];
  assert.ok(successResponse.content["text/event-stream"], `${sourceName}: 200 必须返回 text/event-stream`);
  assert.equal(
    Object.hasOwn(successResponse.content, "application/json"),
    false,
    `${sourceName}: SSE 成功响应不得使用 JSON Result 包装`,
  );
  assert.ok(successResponse.headers["X-Request-Id"], `${sourceName}: 200 必须返回 X-Request-Id`);
  assert.equal(
    operation["x-sse-event-schema"].title,
    "AIResearcher SSE event v1",
    `${sourceName}: 必须关联共享 SSE event Schema`,
  );

  for (const [status, response] of Object.entries(operation.responses)) {
    if (status === "200") {
      continue;
    }
    assert.ok(response.content?.["application/json"], `${sourceName}: ${status} 必须返回 JSON`);
    assert.equal(
      response.content["application/json"].schema.title,
      "AIResearcher StreamOpenError v1",
      `${sourceName}: ${status} 必须使用 StreamOpenError`,
    );
    assert.ok(response.headers?.["X-Request-Id"], `${sourceName}: ${status} 必须返回 X-Request-Id`);
  }

  return requestSchema;
}

async function validateOpenApis() {
  const agentSpec = path.join(contractsDirectory, "agent-api", "agent-openapi-v1.yaml");
  const webSpec = path.join(contractsDirectory, "web-api", "web-openapi-v1.yaml");
  const agentRequestSchema = await validateOpenApi(
    agentSpec,
    "/agent-api/v1/conversations/{conversationId}/messages/stream",
    true,
  );
  const webRequestSchema = await validateOpenApi(
    webSpec,
    "/api/v1/conversations/{conversationId}/messages/stream",
    false,
  );
  assert.deepEqual(agentRequestSchema, webRequestSchema, "Agent API 与 Web API 请求体必须完全一致");
}

async function main() {
  const validateEvent = await validateJsonSchemasAndExamples();
  await validateSseFixtures(validateEvent);
  await validateOpenApis();
  console.log("Contract validation passed:");
  console.log("- 2 OpenAPI documents");
  console.log("- 2 JSON Schemas");
  console.log("- 5 valid event examples and 1 StreamOpenError example");
  console.log("- valid completed/failed streams and all invalid fixtures");
}

main().catch((error) => {
  console.error(error.stack ?? error.message);
  process.exitCode = 1;
});
