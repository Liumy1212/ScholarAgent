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
const httpMethods = new Set(["get", "post", "put", "patch", "delete", "head", "options"]);
const routeDefinitions = [
  { suffix: "/library", methods: ["get"], kind: "json" },
  { suffix: "/library/files", methods: ["get", "post"], kind: "json" },
  { suffix: "/library/files/{libraryFileId}/file", methods: ["get"], kind: "pdf" },
  { suffix: "/library/files/{libraryFileId}/ingestion", methods: ["post"], kind: "json" },
  { suffix: "/library/scans", methods: ["post"], kind: "json", successStatus: "202" },
  { suffix: "/library/scans/{scanId}", methods: ["get"], kind: "json" },
  { suffix: "/library/scans/{scanId}/items", methods: ["get"], kind: "json" },
  { suffix: "/papers", methods: ["get", "post"], kind: "json" },
  { suffix: "/papers/{paperId}", methods: ["get"], kind: "json" },
  { suffix: "/papers/{paperId}/exclusion", methods: ["post", "delete"], kind: "json" },
  { suffix: "/papers/{paperId}/file", methods: ["get"], kind: "pdf" },
  { suffix: "/ingestion-jobs/{jobId}", methods: ["get"], kind: "json" },
  { suffix: "/ingestion-jobs/{jobId}/retry", methods: ["post"], kind: "json" },
  {
    suffix: "/conversations/{conversationId}/messages/stream",
    methods: ["post"],
    kind: "sse",
  },
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

  const eventSchema = await readJson(path.join(sseDirectory, "sse-event.schema.json"));
  assert.deepEqual(
    eventSchema.$defs.toolStatusPayload.properties.toolName.enum,
    ["knowledge_base_search", "document_lookup"],
    "tool.status 只能公开两个只读白名单工具名",
  );
  assert.deepEqual(
    eventSchema.$defs.toolStatusPayload.required,
    ["toolCallId", "toolName", "status", "message"],
    "tool.status payload 必须只要求安全状态字段",
  );
  assert.ok(
    eventSchema.$defs.citationCreatedPayload.required.includes("chunkId"),
    "citation.created 必须携带 chunkId",
  );
  assert.deepEqual(
    eventSchema.$defs.runCompletedPayload.properties.answerMode.enum,
    ["KNOWLEDGE_BASE", "DOCUMENT_LOOKUP", "MODEL_KNOWLEDGE"],
    "run.completed 必须冻结三种 answerMode",
  );

  const validEventDirectory = path.join(sseDirectory, "examples", "events");
  const validEventFiles = await findFiles(validEventDirectory, (filePath) =>
    filePath.endsWith(".json"),
  );
  const expectedTypes = new Set([
    "run.started",
    "message.delta",
    "citation.created",
    "tool.status",
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
  assert.ok(invalidEventFiles.length >= 4, "必须覆盖结构、类型和安全字段非法事件");

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
    assert.ok(["event", "id", "data"].includes(name), `${sourceName}: 不允许 SSE 字段 ${name}`);
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

  const toolCalls = new Map();
  for (const frame of frames.filter((candidate) => candidate.data.type === "tool.status")) {
    const { toolCallId, toolName, status } = frame.data.payload;
    const existing = toolCalls.get(toolCallId);
    if (status === "started") {
      assert.equal(existing, undefined, `${sourceName}: toolCallId ${toolCallId} 只能 started 一次`);
      toolCalls.set(toolCallId, { toolName, terminal: false });
      continue;
    }
    assert.ok(existing, `${sourceName}: ${toolCallId} 必须先 started 再 ${status}`);
    assert.equal(existing.toolName, toolName, `${sourceName}: ${toolCallId} 的 toolName 必须保持不变`);
    assert.equal(existing.terminal, false, `${sourceName}: ${toolCallId} 只能有一个终止状态`);
    existing.terminal = true;
  }
  for (const [toolCallId, state] of toolCalls) {
    assert.equal(state.terminal, true, `${sourceName}: ${toolCallId} 必须以 completed 或 failed 结束`);
  }

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
    new Set([
      "run.started",
      "message.delta",
      "citation.created",
      "tool.status",
      "run.completed",
      "run.failed",
    ]),
    "合法流示例合计必须覆盖六种事件",
  );

  const invalidStreamDirectory = path.join(sseDirectory, "fixtures", "invalid", "streams");
  const invalidStreamFiles = await findFiles(invalidStreamDirectory, (filePath) =>
    filePath.endsWith(".sse"),
  );
  assert.ok(invalidStreamFiles.length >= 6, "必须覆盖线格式、顺序、终止和工具生命周期非法流");

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

function operationMethods(pathItem) {
  return Object.keys(pathItem).filter((key) => httpMethods.has(key)).sort();
}

function responseSchema(response, mediaType = "application/json") {
  return response.content?.[mediaType]?.schema;
}

function assertRequestId(operation, required, sourceName) {
  const requestIdParameter = (operation.parameters ?? []).find(
    (parameter) => parameter.in === "header" && parameter.name.toLowerCase() === "x-request-id",
  );
  assert.ok(requestIdParameter, `${sourceName}: 每个 operation 必须声明 X-Request-Id`);
  assert.equal(requestIdParameter.required, required, `${sourceName}: X-Request-Id required 不正确`);
}

function assertPathParameters(operation, pathName, sourceName) {
  const names = [...pathName.matchAll(/\{([^}]+)\}/gu)].map((match) => match[1]);
  for (const name of names) {
    const parameter = (operation.parameters ?? []).find(
      (candidate) => candidate.in === "path" && candidate.name === name,
    );
    assert.equal(parameter?.required, true, `${sourceName}: ${name} 必须是必填路径参数`);
  }
}

function assertResponseRequestIds(operation, sourceName) {
  for (const [status, response] of Object.entries(operation.responses)) {
    assert.ok(response.headers?.["X-Request-Id"], `${sourceName}: ${status} 必须返回 X-Request-Id`);
  }
}

function assertJsonOperation(operation, side, sourceName, successStatus = "200") {
  const success = operation.responses[successStatus];
  assert.ok(success, `${sourceName}: 普通 JSON operation 必须有 ${successStatus} 响应`);
  const schema = responseSchema(success);
  assert.ok(schema, `${sourceName}: ${successStatus} 必须返回 application/json`);
  assert.equal(
    Object.hasOwn(success.content, "text/event-stream"),
    false,
    `${sourceName}: 普通 JSON operation 不得返回 SSE`,
  );
  const serialized = JSON.stringify(schema);
  if (side === "web") {
    assert.match(serialized, /"const":"SUCCESS"/u, `${sourceName}: Web JSON 成功响应必须使用 Result`);
    assert.match(serialized, /"data"/u, `${sourceName}: Web JSON Result 必须包含 data`);
  } else {
    assert.doesNotMatch(serialized, /"const":"SUCCESS"/u, `${sourceName}: Agent DTO 不得使用 Java Result`);
  }

  for (const [status, response] of Object.entries(operation.responses)) {
    if (status === successStatus) {
      continue;
    }
    const errorSchema = responseSchema(response);
    assert.ok(errorSchema, `${sourceName}: ${status} 必须返回 application/json 错误`);
    const errorText = JSON.stringify(errorSchema);
    if (side === "web") {
      assert.match(errorText, /"requestId"/u, `${sourceName}: Web 错误必须包含 requestId`);
      assert.doesNotMatch(errorText, /"schemaVersion"/u, `${sourceName}: 普通 Web 错误必须是 Result`);
    } else {
      assert.match(errorText, /"schemaVersion"/u, `${sourceName}: Agent 错误必须有 schemaVersion`);
      assert.match(errorText, /"retryable"/u, `${sourceName}: Agent 错误必须有 retryable`);
    }
  }
}

function assertPdfOperation(operation, sourceName) {
  for (const status of ["200", "206"]) {
    const response = operation.responses[status];
    assert.ok(response?.content?.["application/pdf"], `${sourceName}: ${status} 必须返回 application/pdf`);
    assert.equal(Object.hasOwn(response.content, "application/json"), false, `${sourceName}: PDF 不得包装 JSON`);
    for (const header of ["X-Request-Id", "Accept-Ranges", "Content-Length", "ETag"]) {
      assert.ok(response.headers?.[header], `${sourceName}: ${status} 必须声明 ${header}`);
    }
  }
  assert.ok(operation.responses["206"].headers["Content-Range"], `${sourceName}: 206 必须声明 Content-Range`);
  const rangeParameter = operation.parameters.find(
    (parameter) => parameter.in === "header" && parameter.name.toLowerCase() === "range",
  );
  assert.equal(rangeParameter?.required, false, `${sourceName}: Range 必须是可选请求头`);

  for (const [status, response] of Object.entries(operation.responses)) {
    if (["200", "206"].includes(status)) {
      continue;
    }
    const schema = responseSchema(response);
    assert.ok(schema, `${sourceName}: ${status} PDF 错误必须是 application/json`);
    assert.match(JSON.stringify(schema), /"schemaVersion"/u, `${sourceName}: PDF 错误不得使用 Result`);
  }
}

function assertSseOperation(operation, sourceName) {
  const requestSchema = operation.requestBody?.content?.["application/json"]?.schema;
  assert.ok(requestSchema, `${sourceName}: SSE 请求必须是 application/json`);
  assert.equal(requestSchema.type, "object", `${sourceName}: SSE 请求体必须是对象`);
  assert.equal(requestSchema.additionalProperties, false, `${sourceName}: SSE 请求体不得有额外字段`);
  assert.deepEqual([...requestSchema.required].sort(), ["content", "paperIds"]);
  assert.match(
    requestSchema.properties.paperIds.description,
    /空数组.*默认全库/u,
    `${sourceName}: 必须冻结空 paperIds 的默认全库语义`,
  );

  const success = operation.responses["200"];
  assert.ok(success.content?.["text/event-stream"], `${sourceName}: 200 必须返回 text/event-stream`);
  assert.equal(Object.hasOwn(success.content, "application/json"), false, `${sourceName}: SSE 不得使用 Result`);
  assert.equal(
    operation["x-sse-event-schema"].title,
    "AIResearcher SSE event v1",
    `${sourceName}: 必须关联共享 SSE event Schema`,
  );

  for (const [status, response] of Object.entries(operation.responses)) {
    if (status === "200") {
      continue;
    }
    const schema = responseSchema(response);
    assert.equal(schema?.title, "AIResearcher StreamOpenError v1", `${sourceName}: ${status} 必须使用 StreamOpenError`);
  }

  return requestSchema;
}

function validateExample(schema, example, sourceName) {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  const validate = ajv.compile(schema);
  assert.equal(
    validate(example),
    true,
    `${sourceName}: OpenAPI inline example 未通过 Schema: ${formatAjvErrors(validate.errors)}`,
  );
}

function validateInlineExamples(document, sourceName) {
  for (const [pathName, pathItem] of Object.entries(document.paths)) {
    for (const method of operationMethods(pathItem)) {
      const operation = pathItem[method];
      for (const [mediaType, media] of Object.entries(operation.requestBody?.content ?? {})) {
        if (media.example !== undefined) {
          validateExample(media.schema, media.example, `${sourceName}: ${method} ${pathName} ${mediaType}`);
        }
        for (const [name, example] of Object.entries(media.examples ?? {})) {
          if (example.value !== undefined) {
            validateExample(media.schema, example.value, `${sourceName}: ${method} ${pathName} ${name}`);
          }
        }
      }
      for (const [status, response] of Object.entries(operation.responses)) {
        for (const [mediaType, media] of Object.entries(response.content ?? {})) {
          if (media.example !== undefined) {
            validateExample(
              media.schema,
              media.example,
              `${sourceName}: ${method} ${pathName} ${status} ${mediaType}`,
            );
          }
          for (const [name, example] of Object.entries(media.examples ?? {})) {
            if (example.value !== undefined) {
              validateExample(
                media.schema,
                example.value,
                `${sourceName}: ${method} ${pathName} ${status} ${name}`,
              );
            }
          }
        }
      }
    }
  }
}

async function loadAndValidateOpenApi(specPath, prefix, side, requestIdRequired) {
  const sourceName = relative(specPath);
  const parser = new SwaggerParser();
  const parsed = await parser.validate(specPath);
  const dereferenced = await SwaggerParser.dereference(specPath);

  assert.equal(parsed.openapi, "3.1.0", `${sourceName}: OpenAPI 版本必须为 3.1.0`);
  const expectedPaths = routeDefinitions.map((route) => `${prefix}${route.suffix}`).sort();
  assert.deepEqual(Object.keys(parsed.paths).sort(), expectedPaths, `${sourceName}: Demo 路径集合不完整`);
  assert.equal(
    JSON.stringify(parsed).toLowerCase().includes("last-event-id"),
    false,
    `${sourceName}: v1 不得声明 Last-Event-ID`,
  );

  await assertExternalValuesExist(parsed, path.dirname(specPath), sourceName);
  await access(path.resolve(path.dirname(specPath), parsed.externalDocs.url));

  for (const route of routeDefinitions) {
    const pathName = `${prefix}${route.suffix}`;
    const pathItem = dereferenced.paths[pathName];
    assert.deepEqual(operationMethods(pathItem), [...route.methods].sort(), `${sourceName}: ${pathName} 方法不正确`);
    for (const method of route.methods) {
      const operation = pathItem[method];
      const operationName = `${sourceName}: ${method.toUpperCase()} ${pathName}`;
      assertRequestId(operation, requestIdRequired, operationName);
      assertPathParameters(operation, pathName, operationName);
      assertResponseRequestIds(operation, operationName);
      if (route.kind === "json") {
        assertJsonOperation(operation, side, operationName, route.successStatus ?? "200");
      } else if (route.kind === "pdf") {
        assertPdfOperation(operation, operationName);
      } else {
        assertSseOperation(operation, operationName);
      }
    }
  }

  for (const uploadPath of [`${prefix}/papers`, `${prefix}/library/files`]) {
    const upload = dereferenced.paths[uploadPath].post;
    const uploadSchema = upload.requestBody.content["multipart/form-data"].schema;
    assert.equal(uploadSchema.type, "object", `${sourceName}: ${uploadPath} 必须是 multipart object`);
    assert.equal(uploadSchema.additionalProperties, false, `${sourceName}: ${uploadPath} 不得包含额外 part`);
    assert.deepEqual(uploadSchema.required, ["file"], `${sourceName}: ${uploadPath} 必须且只能要求 file`);
    assert.deepEqual(Object.keys(uploadSchema.properties), ["file"], `${sourceName}: ${uploadPath} 只能定义 file`);
    assert.equal(uploadSchema.properties.file.format, "binary", `${sourceName}: ${uploadPath} file 必须是 binary`);
  }

  assert.equal(
    dereferenced.paths[`${prefix}/papers`].post.deprecated,
    true,
    `${sourceName}: 兼容性 POST /papers 必须标记 deprecated`,
  );

  const paperSchema = dereferenced.components.schemas.Paper;
  assert.deepEqual(
    paperSchema.properties.status.enum,
    ["PROCESSING", "READY", "FAILED", "EXCLUDED"],
    `${sourceName}: PaperStatus 必须包含 EXCLUDED`,
  );
  assert.deepEqual(
    paperSchema.properties.sourceStatus.enum,
    ["AVAILABLE", "MISSING", "REPLACED"],
    `${sourceName}: sourceStatus 枚举不正确`,
  );
  for (const field of ["libraryRelativePath", "sourceStatus", "searchable"]) {
    assert.ok(paperSchema.required.includes(field), `${sourceName}: Paper 必须要求 ${field}`);
  }

  const libraryFileSchema = dereferenced.components.schemas.LibraryFile;
  assert.deepEqual(
    libraryFileSchema.properties.knowledgeStatus.enum,
    ["NOT_INGESTED", "PROCESSING", "READY", "FAILED", "EXCLUDED"],
    `${sourceName}: LibraryFileKnowledgeStatus 枚举不正确`,
  );
  for (const field of [
    "libraryFileId",
    "relativePath",
    "sha256",
    "sourceStatus",
    "knowledgeStatus",
    "paperId",
    "searchable",
    "currentIngestion",
  ]) {
    assert.ok(libraryFileSchema.required.includes(field), `${sourceName}: LibraryFile 必须要求 ${field}`);
  }

  const listLibraryFiles = dereferenced.paths[`${prefix}/library/files`].get;
  const libraryFileQueryNames = listLibraryFiles.parameters
    .filter((parameter) => parameter.in === "query")
    .map((parameter) => parameter.name)
    .sort();
  assert.deepEqual(
    libraryFileQueryNames,
    ["limit", "offset"],
    `${sourceName}: 原件清单分页参数不完整`,
  );

  const uploadLibraryFile = dereferenced.paths[`${prefix}/library/files`].post;
  assert.match(
    uploadLibraryFile.description,
    /仅登记|不创建入库任务|另行调用 ingestion/u,
    `${sourceName}: 原件上传必须冻结只登记、不自动入库语义`,
  );

  const ingestLibraryFile = dereferenced.paths[`${prefix}/library/files/{libraryFileId}/ingestion`].post;
  assert.match(
    ingestLibraryFile.description,
    /扫描和上传本身绝不调用此操作/u,
    `${sourceName}: 手动入库边界必须明确`,
  );

  const createScan = dereferenced.paths[`${prefix}/library/scans`].post;
  assert.ok(createScan.responses["202"], `${sourceName}: 创建扫描必须返回 202`);
  assert.equal(
    createScan.responses["409"].content["application/json"].example.code,
    "LIBRARY_SCAN_ACTIVE",
    `${sourceName}: 活动扫描冲突错误码必须固定`,
  );
  assert.match(
    dereferenced.components.schemas.LibraryScan.properties.registeredCount.description,
    /登记.*不会自动创建.*入库任务/u,
    `${sourceName}: registeredCount 必须表示原件登记而非自动入库`,
  );

  const scanItems = dereferenced.paths[`${prefix}/library/scans/{scanId}/items`].get;
  const queryNames = scanItems.parameters
    .filter((parameter) => parameter.in === "query")
    .map((parameter) => parameter.name)
    .sort();
  assert.deepEqual(queryNames, ["limit", "offset", "outcome"], `${sourceName}: 扫描项分页/过滤参数不完整`);
  assert.ok(
    dereferenced.components.schemas.LibraryScanItem.required.includes("libraryFileId"),
    `${sourceName}: 扫描项必须返回可空 libraryFileId`,
  );

  validateInlineExamples(dereferenced, sourceName);
  return { parsed, dereferenced };
}

async function validateOpenApis() {
  const agentSpec = path.join(contractsDirectory, "agent-api", "agent-openapi-v1.yaml");
  const webSpec = path.join(contractsDirectory, "web-api", "web-openapi-v1.yaml");
  const agent = await loadAndValidateOpenApi(agentSpec, "/agent-api/v1", "agent", true);
  const web = await loadAndValidateOpenApi(webSpec, "/api/v1", "web", false);

  const commonSchemas = [
    "Identifier",
    "PaperStatus",
    "PaperSourceStatus",
    "LibraryFileKnowledgeStatus",
    "LibraryScanStatus",
    "LibraryScanItemOutcome",
    "IngestionJobStatus",
    "IngestionStage",
    "IngestionFailure",
    "IngestionSummary",
    "Paper",
    "IngestionJob",
    "LibraryFile",
    "LibraryFilesPage",
    "LibraryScanFailure",
    "LibraryScan",
    "LibraryInfo",
    "LibraryScanItem",
    "LibraryScanItemsPage",
    "ChatStreamRequest",
  ];
  for (const name of commonSchemas) {
    assert.deepEqual(
      agent.parsed.components.schemas[name],
      web.parsed.components.schemas[name],
      `Agent API 与 Web API 的 ${name} 必须完全一致`,
    );
  }
  assert.deepEqual(
    agent.parsed.components.schemas.PaperUploadResponse,
    web.parsed.components.schemas.PaperUploadData,
    "上传 data DTO 必须跨 BFF 保持一致",
  );
  assert.deepEqual(
    agent.parsed.components.schemas.PaperListResponse,
    web.parsed.components.schemas.PaperListData,
    "论文列表 data DTO 必须跨 BFF 保持一致",
  );
  assert.deepEqual(
    agent.parsed.components.schemas.LibraryFileUploadResponse,
    web.parsed.components.schemas.LibraryFileUploadData,
    "原件上传 data DTO 必须跨 BFF 保持一致",
  );
  assert.deepEqual(
    agent.parsed.components.schemas.LibraryFileIngestionResponse,
    web.parsed.components.schemas.LibraryFileIngestionData,
    "手动入库 data DTO 必须跨 BFF 保持一致",
  );
}

async function main() {
  const validateEvent = await validateJsonSchemasAndExamples();
  await validateSseFixtures(validateEvent);
  await validateOpenApis();
  console.log("Contract validation passed:");
  console.log("- 2 OpenAPI documents with 16 REST operations plus shared SSE");
  console.log("- 2 JSON Schemas");
  console.log("- 6 valid event examples and 1 StreamOpenError example");
  console.log("- valid completed/failed streams and all invalid fixtures");
  console.log("- library file/manual ingestion/scan/exclusion semantics, DTO parity, Result/PDF/SSE boundaries, Range headers, and inline examples");
}

main().catch((error) => {
  console.error(error.stack ?? error.message);
  process.exitCode = 1;
});
