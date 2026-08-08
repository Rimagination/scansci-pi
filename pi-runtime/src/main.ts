import * as fs from "node:fs";
import * as readline from "node:readline";
import { createHash } from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";
import { Client as McpClient } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type JsonRecord = Record<string, unknown>;
type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh";
type AgentSession = Awaited<ReturnType<typeof createAgentSession>>["session"];

interface RunStart extends JsonRecord {
  type: "run.start";
  request_id: string;
  session_id: string;
  session_file?: string;
  cwd: string;
  agent_dir: string;
  provider_kind: string;
  base_url: string;
  model_id: string;
  api_surface?: string;
  responses_enabled?: boolean;
  thinking_level?: string;
  system_prompt: string;
  prompt: string;
  task_mode?: string;
  task_contract?: JsonRecord;
  prefix_shape?: JsonRecord;
  context_policy?: JsonRecord;
  mcp_servers?: JsonRecord[];
  disabled_tools?: string[];
  background?: boolean;
}

type ToolRisk = "read_only" | "reversible" | "high";

interface NormalizedTaskContract {
  contractId: string;
  goal: string;
  outputFormat: string;
  pausePolicy: string;
  requiredEvidence: string[];
  autonomy: string;
  riskLevel: string;
  requiresPlan: boolean;
  allowedTools: Set<string>;
  allowedMcpServers: Set<string>;
  hasMcpLease: boolean;
  requiredToolGroups: Set<string>[];
  successCriteria: string[];
  initialToolBudget: number;
  maxToolBudget: number;
  recoveryBudget: number;
  modelTokenBudget: number;
  allowExternalWrite: boolean;
  taskProfile: JsonRecord;
}

interface SessionState {
  session: AgentSession;
  request: RunStart;
  signature: string;
  unsubscribe: () => void;
  currentRequestId?: string;
  mcpClients: McpClient[];
  activeToolNames: string[];
  prefixShape: JsonRecord;
}

interface ActiveRun {
  requestId: string;
  sessionId: string;
  cancelled: boolean;
  startedAt: number;
  background: boolean;
  toolCalls: number;
  toolCallBudget: number;
  maxToolCallBudget: number;
  successfulToolCalls: number;
  lastExtensionSuccesses: number;
  toolFingerprints: Map<string, number>;
  idempotentResults: Map<string, JsonRecord>;
  taskContract: NormalizedTaskContract;
  planApproved: boolean;
  askUserCount: number;
  modelTokens: number;
  modelTokenBudget: number;
  modelTokenBudgetExceeded: boolean;
}

interface PendingTool {
  requestId: string;
  resolve: (value: JsonRecord) => void;
  reject: (reason: Error) => void;
}

interface PendingInteraction {
  requestId: string;
  sessionId: string;
  kind: "ask_user" | "plan";
  resolve: (value: JsonRecord) => void;
  reject: (reason: Error) => void;
}

const pendingTools = new Map<string, PendingTool>();
const pendingInteractions = new Map<string, PendingInteraction>();
const sessions = new Map<string, SessionState>();
const activeRuns = new Map<string, ActiveRun>();
const activeSessionRequests = new Map<string, string>();
const activeRunStorage = new AsyncLocalStorage<ActiveRun>();

function emit(payload: JsonRecord): void {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function redactSensitiveText(value: unknown): string {
  let text = value instanceof Error ? value.message : String(value ?? "");
  const providerKey = String(process.env.SCANSCIPI_PROVIDER_KEY || "").trim();
  if (providerKey) text = text.split(providerKey).join("[REDACTED]");
  return text
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/\b(sk-[A-Za-z0-9_-]{12,})\b/g, "[REDACTED]")
    .replace(/([?&](?:api[_-]?key|access[_-]?token|token|password|secret)=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/((?:api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*)[^\s,;]+/gi, "$1[REDACTED]");
}

function classifyError(error: unknown): JsonRecord {
  const raw = redactSensitiveText(error);
  const normalized = raw.toLowerCase();
  if (normalized.includes("insufficient balance") || normalized.includes("insufficient credit") || normalized.includes("402")) {
    return {
      code: "provider_balance_exhausted",
      message: "当前模型服务余额不足。ScanSci 已停止继续请求，请充值该服务商账户或切换模型。",
      retryable: false,
      recovery_actions: [
        { id: "change_model", label: "切换模型", kind: "branch" },
        { id: "open_settings", label: "检查模型服务", kind: "settings" },
      ],
    };
  }
  if (normalized.includes("rate_limited") || normalized.includes("rate limit") || normalized.includes("429")) {
    return {
      code: "provider_rate_limited",
      message: "模型服务暂时限流。已完成的工具结果和会话记录不会丢失。",
      retryable: true,
      recovery_actions: [
        { id: "retry", label: "自动重试", kind: "retry" },
        { id: "follow_up", label: "稍后继续", kind: "follow_up" },
      ],
    };
  }
  if (
    normalized.includes("context_length_exceeded")
    || normalized.includes("input limit")
    || normalized.includes("request body is empty or exceeds")
    || normalized.includes("provider input budget")
  ) {
    return {
      code: "context_limit",
      message: "会话或工具结果超过模型服务的输入上限。ScanSci 已保留完整结果。",
      retryable: true,
      recovery_actions: [
        { id: "compact_retry", label: "压缩并重试", kind: "compact_retry" },
        { id: "branch", label: "从此处分支", kind: "branch" },
      ],
    };
  }
  if (normalized.includes("empty response") || normalized.includes("stopped at an execution plan")) {
    return {
      code: "incomplete_model_response",
      message: "模型没有形成可交付答案。ScanSci 可以保留已完成步骤并换一种路径继续。",
      retryable: true,
      recovery_actions: [
        { id: "retry_without_thinking", label: "关闭深度思考后重试", kind: "retry_without_thinking" },
        { id: "follow_up", label: "继续执行", kind: "follow_up" },
      ],
      detail: raw,
    };
  }
  if (normalized.includes("no progress") || normalized.includes("repeatedly with equivalent arguments")) {
    return {
      code: "agent_no_progress",
      message: "当前路线连续没有产生新结果。ScanSci 已保留已有成果，不会继续重复消耗 token。",
      retryable: true,
      recovery_actions: [
        { id: "change_strategy", label: "更换路线继续", kind: "change_strategy" },
        { id: "branch", label: "保留现场并分支", kind: "branch" },
      ],
      detail: raw,
    };
  }
  if (normalized.includes("capability lease denied") || normalized.includes("requires an approved plan")) {
    return {
      code: "capability_lease_denied",
      message: "该操作超出当前任务的临时权限。ScanSci 已阻止执行，并保留现有结果。",
      retryable: true,
      recovery_actions: [
        { id: "change_strategy", label: "改用低风险路线", kind: "change_strategy" },
        { id: "plan", label: "提交计划后继续", kind: "plan" },
      ],
      detail: raw,
    };
  }
  if (normalized.includes("tool-call budget") || normalized.includes("tool call budget")) {
    return {
      code: "agent_budget_exhausted",
      message: "本轮已达到工具调用预算。ScanSci 已保留成功结果，不会继续无边界检索。",
      retryable: true,
      recovery_actions: [
        { id: "follow_up", label: "基于已有结果回答", kind: "follow_up" },
        { id: "branch", label: "缩小范围后分支", kind: "branch" },
      ],
    };
  }
  if (normalized.includes("model-token budget") || normalized.includes("model token budget")) {
    return {
      code: "agent_token_budget_exhausted",
      message: "本轮已达到模型 token 安全预算。ScanSci 已停止继续请求，并保留成功的工具结果。",
      retryable: true,
      recovery_actions: [
        { id: "follow_up", label: "基于已有结果回答", kind: "follow_up" },
        { id: "branch", label: "缩小任务范围", kind: "branch" },
      ],
    };
  }
  if (normalized.includes("timed out") || normalized.includes("timeout")) {
    return {
      code: "timeout",
      message: "当前步骤超时，但已完成的阶段与文件仍然保留。",
      retryable: true,
      recovery_actions: [
        { id: "retry", label: "重试当前步骤", kind: "retry" },
        { id: "change_strategy", label: "更换获取策略", kind: "change_strategy" },
      ],
      detail: raw,
    };
  }
  return {
    code: "agent_runtime_error",
    message: error instanceof Error ? `${error.name}: ${raw}` : raw,
    retryable: false,
    recovery_actions: [{ id: "branch", label: "保留现场并分支", kind: "branch" }],
  };
}

function errorText(error: unknown): string {
  return String(classifyError(error).message || error);
}

function providerApi(
  kind: string,
  apiSurface = "chat_completions",
): "anthropic-messages" | "openai-completions" | "openai-responses" {
  if (kind === "anthropic" || kind === "anthropic-compatible") return "anthropic-messages";
  return String(apiSurface || "chat_completions").toLowerCase() === "responses"
    ? "openai-responses"
    : "openai-completions";
}

function estimateTokenText(value: unknown): number {
  const text = String(value || "");
  return text ? Math.ceil(text.length / 4) : 0;
}

const MAX_TOOL_RESULT_BYTES = 16_000;
const MAX_MCP_SERVERS = 12;
const MAX_MCP_TOOLS = 64;
const MAX_MCP_TOOLS_PER_SERVER = 32;
const MAX_MCP_SCHEMA_BYTES = 12_000;
const MAX_MCP_DESCRIPTION_CHARS = 800;
const MCP_CONNECT_TIMEOUT_MS = 15_000;
const MCP_CALL_TIMEOUT_MS = 120_000;

function estimateProviderInputTokens(value: unknown): number {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  let ascii = 0;
  let nonAscii = 0;
  for (const char of text) {
    if (char.charCodeAt(0) <= 0x7f) ascii += 1;
    else nonAscii += 1;
  }
  // Conservative for Chinese and JSON/tool syntax. This is a safety fuse,
  // not UI billing data.
  return Math.ceil(ascii / 4) + nonAscii;
}

function jsonBytes(value: unknown): number {
  try {
    return Buffer.byteLength(JSON.stringify(value), "utf8");
  } catch {
    return Number.MAX_SAFE_INTEGER;
  }
}

function compactToolValue(
  value: unknown,
  depth = 0,
  limits = { maxDepth: 5, maxItems: 10, maxKeys: 32, maxString: 900 },
): unknown {
  if (depth >= limits.maxDepth) {
    if (Array.isArray(value)) return { _omitted_items: value.length };
    if (value && typeof value === "object") return { _omitted_keys: Object.keys(value).length };
    return String(value ?? "").slice(0, limits.maxString);
  }
  if (typeof value === "string") {
    return value.length <= limits.maxString
      ? value
      : `${value.slice(0, limits.maxString)}… [omitted ${value.length - limits.maxString} chars]`;
  }
  if (Array.isArray(value)) {
    const compacted = value
      .slice(0, limits.maxItems)
      .map((item) => compactToolValue(item, depth + 1, limits));
    if (value.length > limits.maxItems) compacted.push({ _omitted_items: value.length - limits.maxItems });
    return compacted;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as JsonRecord);
    const compacted: JsonRecord = {};
    for (const [key, item] of entries.slice(0, limits.maxKeys)) {
      compacted[key] = compactToolValue(item, depth + 1, limits);
    }
    if (entries.length > limits.maxKeys) compacted._omitted_keys = entries.length - limits.maxKeys;
    return compacted;
  }
  return value;
}

function redactToolValue(value: unknown, key = "", depth = 0): unknown {
  if (/(?:^|[_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization)(?:$|[_-])/i.test(key)) {
    return "[REDACTED]";
  }
  if (depth > 12) return "[TRUNCATED]";
  if (typeof value === "string") return redactSensitiveText(value);
  if (Array.isArray(value)) return value.map((item) => redactToolValue(item, "", depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as JsonRecord).map(([nestedKey, item]) => [
        nestedKey,
        redactToolValue(item, nestedKey, depth + 1),
      ]),
    );
  }
  return value;
}

function boundedToolPayload(name: string, value: unknown): JsonRecord {
  const safeValue = redactToolValue(value);
  const originalBytes = jsonBytes(safeValue);
  if (originalBytes <= MAX_TOOL_RESULT_BYTES && safeValue && typeof safeValue === "object" && !Array.isArray(safeValue)) {
    return safeValue as JsonRecord;
  }
  let compacted = compactToolValue(safeValue);
  if (!compacted || typeof compacted !== "object" || Array.isArray(compacted)) {
    compacted = { result: compacted };
  }
  const result = compacted as JsonRecord;
  result._scansci_truncated = true;
  result._original_bytes = originalBytes;
  result._notice = "Tool output exceeded the model-context budget; use a focused follow-up tool.";
  if (jsonBytes(result) > MAX_TOOL_RESULT_BYTES) {
    const preview = JSON.stringify(result).slice(0, MAX_TOOL_RESULT_BYTES - 1_200);
    return {
      _scansci_truncated: true,
      _original_bytes: originalBytes,
      _notice: "Tool output exceeded the model-context budget; use a focused follow-up tool.",
      summary: `${name}: bounded tool result`,
      preview,
    };
  }
  return result;
}

function estimateMessageTokens(message: JsonRecord): number {
  const content = message.content;
  if (typeof content === "string") return estimateTokenText(content);
  if (!Array.isArray(content)) return estimateTokenText(JSON.stringify(content || ""));
  return content.reduce((total, block) => {
    if (!block || typeof block !== "object") return total;
    const item = block as JsonRecord;
    if (item.type === "text") return total + estimateTokenText(item.text);
    if (item.type === "thinking") return total + estimateTokenText(item.thinking);
    if (item.type === "toolCall") return total + estimateTokenText(`${String(item.name || "")} ${JSON.stringify(item.arguments || {})}`);
    if (item.type === "image") return total + 1200;
    return total + estimateTokenText(JSON.stringify(item));
  }, 0);
}

function toolNameFromMessage(message: JsonRecord): string {
  if (typeof message.toolName === "string") return message.toolName;
  if (typeof message.name === "string") return message.name;
  return "";
}

function freshUsageTokens(usage: unknown): number {
  if (!usage || typeof usage !== "object") return 0;
  const value = usage as JsonRecord;
  const input = Math.max(0, Number(value.input ?? value.inputTokens ?? value.prompt_tokens ?? 0) || 0);
  const output = Math.max(0, Number(value.output ?? value.outputTokens ?? value.completion_tokens ?? 0) || 0);
  if (input || output) return input + output;
  const total = Math.max(0, Number(value.totalTokens ?? value.total_tokens ?? value.total ?? 0) || 0);
  const cacheRead = Math.max(0, Number(value.cacheRead ?? value.cache_read_tokens ?? 0) || 0);
  const cacheWrite = Math.max(0, Number(value.cacheWrite ?? value.cache_write_tokens ?? 0) || 0);
  return Math.max(0, total - cacheRead - cacheWrite);
}

function stableHash(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(value, (_key, nested) => {
      if (!nested || typeof nested !== "object" || Array.isArray(nested)) return nested;
      return Object.fromEntries(Object.entries(nested as JsonRecord).sort(([left], [right]) => left.localeCompare(right)));
    }))
    .digest("hex");
}

function buildPrefixShape(request: RunStart, activeToolNames: string[]): JsonRecord {
  const selectedSkillIds = [...String(request.system_prompt || "").matchAll(/<selected_skill\s+id="([^"]+)"/gi)]
    .map((match) => String(match[1] || ""))
    .filter(Boolean)
    .sort();
  const components = {
    provider: String(request.provider_kind || ""),
    model: String(request.model_id || ""),
    api_surface: String(request.api_surface || "chat_completions"),
    system_prompt_hash: stableHash(String(request.system_prompt || "")),
    tool_names_hash: stableHash([...activeToolNames].sort()),
    selected_skill_ids: selectedSkillIds,
    mcp_server_ids: (Array.isArray(request.mcp_servers) ? request.mcp_servers : [])
      .map((server) => String(server.id || server.name || ""))
      .filter(Boolean)
      .sort(),
    contract_shape: taskContractSessionSignature(request),
  };
  return {
    schema_version: "scansci.prefix-shape.v1",
    hash: stableHash(components),
    components,
  };
}

function pruneStaleToolResults(state: SessionState, keepRecentTurns = 2): JsonRecord {
  const messages = Array.isArray(state.session.messages) ? state.session.messages as JsonRecord[] : [];
  let currentTurn = 0;
  const locations: Array<{ message: JsonRecord; turn: number }> = [];
  for (const message of messages) {
    const role = String(message.role || "").toLowerCase();
    if (role === "user") currentTurn += 1;
    if (["tool", "toolresult", "tool_result"].includes(role)) locations.push({ message, turn: currentTurn });
  }
  let pruned = 0;
  let originalChars = 0;
  let retainedChars = 0;
  for (const location of locations) {
    const message = location.message;
    const content = message.content;
    const encoded = JSON.stringify(content ?? "");
    const size = encoded.length;
    originalChars += size;
    if (currentTurn - location.turn >= Math.max(1, keepRecentTurns)) {
      const notice = {
        _scansci_pruned: true,
        tool: String(message.toolName || message.tool_name || message.name || "tool").slice(0, 80),
        original_chars: size,
        notice: "Stale tool output was pruned before context compaction; rerun a focused tool if needed.",
      };
      message.content = [{ type: "text", text: JSON.stringify(notice) }];
      message._scansci_context_pruned = true;
      pruned += 1;
    }
    retainedChars += JSON.stringify(message.content ?? "").length;
  }
  return {
    policy: "stale_tool_result_pruning",
    examined_tool_results: locations.length,
    pruned_tool_results: pruned,
    preserved_tool_results: Math.max(0, locations.length - pruned),
    original_chars: originalChars,
    retained_chars: retainedChars,
    saved_chars: Math.max(0, originalChars - retainedChars),
  };
}

function sessionStats(state: SessionState): JsonRecord {
  const base = state.session.getSessionStats() as JsonRecord;
  const messages = Array.isArray(state.session.messages) ? state.session.messages as JsonRecord[] : [];
  let messageTokens = 0;
  let systemToolTokens = 0;
  let mcpToolTokens = 0;
  for (const message of messages) {
    const role = String(message.role || "");
    if (role === "assistant" && Array.isArray(message.content)) {
      for (const block of message.content as JsonRecord[]) {
        if (!block || typeof block !== "object") continue;
        const tokens = estimateMessageTokens({ content: [block] });
        if (block.type === "toolCall") {
          if (String(block.name || "").startsWith("mcp__")) mcpToolTokens += tokens;
          else systemToolTokens += tokens;
        } else {
          messageTokens += tokens;
        }
      }
    } else if (role === "toolResult") {
      const tokens = estimateMessageTokens(message);
      if (toolNameFromMessage(message).startsWith("mcp__")) mcpToolTokens += tokens;
      else systemToolTokens += tokens;
    } else {
      messageTokens += estimateMessageTokens(message);
    }
  }
  const systemPrompt = estimateTokenText(state.session.systemPrompt);
  const selectedSkillBlocks = String(state.request.system_prompt || "").match(/<selected_skill\b[\s\S]*?<\/selected_skill>/gi) || [];
  const skillTokens = selectedSkillBlocks.reduce((total, block) => total + estimateTokenText(block), 0);
  const systemPromptTokens = Math.max(0, systemPrompt - skillTokens);
  const context = base.contextUsage && typeof base.contextUsage === "object" ? base.contextUsage as JsonRecord : {};
  const contextTokens = Number(context.tokens || 0);
  const classified = messageTokens + systemToolTokens + mcpToolTokens + skillTokens + systemPromptTokens;
  const otherTokens = Math.max(0, contextTokens - classified);
  const activeTools = [...state.activeToolNames];
  const mcpTools = activeTools.filter((name) => name.startsWith("mcp__"));
  const rawTokens = base.tokens && typeof base.tokens === "object" ? base.tokens as JsonRecord : {};
  const inputTokens = Math.max(0, Number(rawTokens.input ?? rawTokens.inputTokens ?? rawTokens.prompt_tokens ?? 0) || 0);
  const outputTokens = Math.max(0, Number(rawTokens.output ?? rawTokens.outputTokens ?? rawTokens.completion_tokens ?? 0) || 0);
  const cacheRead = Math.max(0, Number(rawTokens.cacheRead ?? rawTokens.cache_read_tokens ?? 0) || 0);
  const cacheWrite = Math.max(0, Number(rawTokens.cacheWrite ?? rawTokens.cache_write_tokens ?? 0) || 0);
  const normalizedTokens = {
    ...rawTokens,
    input: inputTokens,
    output: outputTokens,
    // Reader-facing "total" means paid/generated traffic for this session.
    // Cache reads remain visible separately for the cache-hit metric, but must
    // not inflate the total or the safety budget.
    total: inputTokens + outputTokens,
  };
  return {
    ...base,
    tokens: normalizedTokens,
    contextBreakdown: {
      message: messageTokens,
      systemTools: systemToolTokens,
      mcpTools: mcpToolTokens,
      skills: skillTokens,
      systemPrompt: systemPromptTokens,
      other: otherTokens,
      total: contextTokens,
    },
    toolInventory: {
      active: activeTools.length,
      system: activeTools.length - mcpTools.length,
      mcp: mcpTools.length,
      mcpServers: Array.isArray(state.request.mcp_servers) ? state.request.mcp_servers.length : 0,
      names: activeTools,
    },
    skillInventory: {
      selected: selectedSkillBlocks.length,
      ids: selectedSkillBlocks.map((block) => block.match(/<selected_skill\s+id="([^"]+)"/i)?.[1] || "").filter(Boolean),
    },
    prefixShape: state.prefixShape,
    cacheDiagnostics: {
      cacheReadTokens: cacheRead,
      cacheWriteTokens: cacheWrite,
      cacheMissTokens: cacheWrite,
      cacheHitRate: cacheRead + cacheWrite > 0 ? Number((cacheRead / (cacheRead + cacheWrite)).toFixed(6)) : null,
    },
    contextPolicy: state.request.context_policy || {},
  };
}

function thinkingLevel(value: unknown): ThinkingLevel {
  const normalized = String(value || "medium").toLowerCase();
  if (["off", "minimal", "low", "medium", "high", "xhigh"].includes(normalized)) {
    return normalized as ThinkingLevel;
  }
  return "medium";
}

function modelCompat(request: RunStart): JsonRecord | undefined {
  if (providerApi(request.provider_kind, request.api_surface) !== "openai-completions") return undefined;
  const model = request.model_id.toLowerCase();
  const baseUrl = request.base_url.toLowerCase();
  if (baseUrl.includes("models.github.ai") || model.startsWith("openai/")) {
    return {
      supportsStore: false,
      supportsDeveloperRole: true,
      supportsUsageInStreaming: true,
      maxTokensField: "max_tokens",
      supportsStrictMode: true,
    };
  }
  if (model.includes("glm") || baseUrl.includes("bigmodel") || baseUrl.includes("api.z.ai")) {
    return {
      supportsStore: false,
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsUsageInStreaming: true,
      maxTokensField: "max_tokens",
      thinkingFormat: "zai",
      supportsStrictMode: false,
    };
  }
  if (model.includes("qwen")) {
    return {
      supportsStore: false,
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsUsageInStreaming: true,
      maxTokensField: "max_tokens",
      thinkingFormat: "qwen",
      supportsStrictMode: false,
    };
  }
  return undefined;
}

function boundedInteger(value: unknown, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.trunc(parsed)));
}

function normalizeTaskContract(request: RunStart): NormalizedTaskContract {
  const raw = request.task_contract && typeof request.task_contract === "object"
    ? request.task_contract
    : {};
  const fallbackBudget = toolCallBudget(String(request.task_mode || "general"));
  const initialToolBudget = boundedInteger(raw.initial_tool_budget, fallbackBudget, 1, 24);
  const maxToolBudget = boundedInteger(
    raw.max_tool_budget,
    Math.max(initialToolBudget, fallbackBudget),
    initialToolBudget,
    32,
  );
  const modeParts = new Set(String(request.task_mode || "general").split("+").filter(Boolean));
  const fallbackRisk = [...modeParts].some((part) => ["research", "slides"].includes(part))
    ? "reversible"
    : "read_only";
  const requiredGroups = Array.isArray(raw.required_tool_groups)
    ? raw.required_tool_groups
      .filter((group) => Array.isArray(group))
      .map((group) => new Set((group as unknown[]).map(String).filter(Boolean)))
      .filter((group) => group.size > 0)
    : requiredToolGroups(
      String(request.task_mode || "general"),
      finalUserRequestText(request.prompt || ""),
    );
  return {
    contractId: String(raw.contract_id || `legacy-${request.request_id}`),
    goal: String(raw.goal || finalUserRequestText(request.prompt || "")).slice(0, 1200),
    outputFormat: String(raw.output_format || "text").slice(0, 120),
    pausePolicy: String(raw.pause_policy || "pause only when a missing user choice changes the result").slice(0, 300),
    requiredEvidence: Array.isArray(raw.required_evidence)
      ? raw.required_evidence.map(String).filter(Boolean).slice(0, 12)
      : [],
    autonomy: String(raw.autonomy || fallbackRisk),
    riskLevel: String(raw.risk_level || fallbackRisk),
    requiresPlan: raw.requires_plan === true,
    allowedTools: new Set(
      Array.isArray(raw.allowed_tools)
        ? raw.allowed_tools.map(String).filter(Boolean)
        : [],
    ),
    allowedMcpServers: new Set(
      Array.isArray(raw.allowed_mcp_servers)
        ? raw.allowed_mcp_servers.map(String).filter(Boolean)
        : [],
    ),
    hasMcpLease: Array.isArray(raw.allowed_mcp_servers),
    requiredToolGroups: requiredGroups,
    successCriteria: Array.isArray(raw.success_criteria)
      ? raw.success_criteria.map(String).filter(Boolean).slice(0, 12)
      : [],
    initialToolBudget,
    maxToolBudget,
    recoveryBudget: boundedInteger(raw.recovery_budget, 2, 1, 4),
    modelTokenBudget: boundedInteger(
      raw.model_token_budget,
      modelTokenBudget(String(request.task_mode || "general")),
      4_000,
      64_000,
    ),
    allowExternalWrite: raw.allow_external_write === true,
    taskProfile: raw.task_profile && typeof raw.task_profile === "object"
      ? raw.task_profile as JsonRecord
      : {},
  };
}

function toolRisk(name: string): ToolRisk {
  const normalized = String(name || "");
  if (normalized.startsWith("mcp__") && isWriteLikeMcpTool(normalized)) return "high";
  if (new Set([
    "download_and_index",
    "create_document",
    "create_pdf",
    "create_spreadsheet",
    "create_presentation",
    "compile_latex",
    "edit_section",
    "edit_slide",
  ]).has(normalized)) return "reversible";
  return "read_only";
}

function riskRank(value: string): number {
  if (value === "high" || value === "approval_required") return 3;
  if (value === "reversible") return 2;
  if (value === "read_only") return 1;
  return 0;
}

function stableToolValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableToolValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as JsonRecord)
      .filter(([key]) => key !== "_scansci_idempotency_key")
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, stableToolValue(item)]),
  );
}

function toolFingerprint(name: string, args: JsonRecord): string {
  return `${String(name)}:${JSON.stringify(stableToolValue(args))}`;
}

function assertCapabilityLease(activeRun: ActiveRun, name: string): void {
  const risk = toolRisk(name);
  const contract = activeRun.taskContract;
  if (
    contract.allowedTools.size > 0
    && !String(name).startsWith("mcp__")
    && !contract.allowedTools.has(name)
  ) {
    throw new Error(`Capability lease denied tool ${name}; it is outside the current task contract.`);
  }
  if (String(name).startsWith("mcp__") && contract.hasMcpLease) {
    const serverId = String(name).split("__")[1] || "";
    if (!contract.allowedMcpServers.has(serverId)) {
      throw new Error(`Capability lease denied MCP server ${serverId || "unknown"}.`);
    }
  }
  if (riskRank(risk) > riskRank(contract.riskLevel)) {
    throw new Error(
      `Capability lease denied ${risk} tool ${name}; current risk ceiling is ${contract.riskLevel}.`,
    );
  }
  if (risk === "high" && !contract.allowExternalWrite) {
    throw new Error(`External write tool ${name} is not authorized by the current task contract.`);
  }
  if ((risk === "high" || (contract.requiresPlan && risk !== "read_only")) && !activeRun.planApproved) {
    throw new Error(`Tool ${name} requires an approved plan before execution.`);
  }
}

function claimToolCall(name: string, args: JsonRecord): ActiveRun {
  const activeRun = activeRunStorage.getStore();
  if (!activeRun) throw new Error("No active Pi run owns this tool call");
  assertCapabilityLease(activeRun, name);
  const fingerprint = toolFingerprint(name, args);
  const repeats = activeRun.toolFingerprints.get(fingerprint) || 0;
  if (repeats >= 2) {
    throw new Error(
      `No progress: ${name} was called repeatedly with equivalent arguments. Change strategy or parameters.`,
    );
  }
  if (activeRun.toolCalls >= activeRun.toolCallBudget) {
    if (
      activeRun.successfulToolCalls > activeRun.lastExtensionSuccesses
      && activeRun.toolCallBudget < activeRun.maxToolCallBudget
    ) {
      const previous = activeRun.toolCallBudget;
      activeRun.toolCallBudget = Math.min(activeRun.maxToolCallBudget, previous + 2);
      activeRun.lastExtensionSuccesses = activeRun.successfulToolCalls;
      emit({
        type: "status.update",
        request_id: activeRun.requestId,
        status: "budget_extended",
        name: "progress_based_tool_lease",
        previous_budget: previous,
        tool_call_budget: activeRun.toolCallBudget,
        max_tool_call_budget: activeRun.maxToolCallBudget,
      });
    } else {
      throw new Error(
        `Tool-call budget exhausted after ${activeRun.toolCalls} calls. ` +
        "Use the successful results already returned and deliver a concise final answer now.",
      );
    }
  }
  activeRun.toolFingerprints.set(fingerprint, repeats + 1);
  activeRun.toolCalls += 1;
  return activeRun;
}

async function callPythonTool(name: string, args: JsonRecord): Promise<JsonRecord> {
  const activeRun = activeRunStorage.getStore();
  if (!activeRun) throw new Error("No active Pi run owns this tool call");
  const fingerprint = toolFingerprint(name, args);
  if (toolRisk(name) !== "read_only" && activeRun.idempotentResults.has(fingerprint)) {
    emit({
      type: "status.update",
      request_id: activeRun.requestId,
      status: "tool_reused",
      name,
    });
    return activeRun.idempotentResults.get(fingerprint) as JsonRecord;
  }
  claimToolCall(name, args);
  const callId = crypto.randomUUID();
  const requestId = activeRun.requestId;
  const effectful = toolRisk(name) !== "read_only";
  const forwardedArgs = effectful
    ? { ...args, _scansci_idempotency_key: `${activeRun.sessionId}:${fingerprint}` }
    : args;
  emit({ type: "tool.call", request_id: requestId, call_id: callId, name, arguments: forwardedArgs });
  const result = await new Promise<JsonRecord>((resolve, reject) => {
    pendingTools.set(callId, { requestId, resolve, reject });
  });
  if (effectful) activeRun.idempotentResults.set(fingerprint, result);
  return result;
}

async function requestInteraction(
  kind: "ask_user" | "plan",
  payload: JsonRecord,
): Promise<JsonRecord> {
  const activeRun = activeRunStorage.getStore();
  if (!activeRun) throw new Error("No active Pi run owns this interaction");
  const interactionId = crypto.randomUUID();
  emit({
    type: "interaction.requested",
    request_id: activeRun.requestId,
    session_id: activeRun.sessionId,
    interaction_id: interactionId,
    interaction_kind: kind,
    payload,
  });
  return new Promise<JsonRecord>((resolve, reject) => {
    pendingInteractions.set(interactionId, {
      requestId: activeRun.requestId,
      sessionId: activeRun.sessionId,
      kind,
      resolve,
      reject,
    });
  });
}

function bridgeTool(
  name: string,
  label: string,
  description: string,
  parameters: ReturnType<typeof Type.Object>,
) {
  return defineTool({
    name,
    label,
    description,
    parameters,
    execute: async (_toolCallId, params) => {
      const result = boundedToolPayload(name, await callPythonTool(name, params as JsonRecord));
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result) }],
        details: result,
      };
    },
  });
}

function safeToolSegment(value: unknown): string {
  return String(value || "mcp")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48) || "mcp";
}

function splitCommandArgs(value: unknown): string[] {
  const source = String(value || "").trim();
  if (!source) return [];
  const args: string[] = [];
  const matcher = /"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^\s]+)/g;
  for (const match of source.matchAll(matcher)) {
    args.push(String(match[1] ?? match[2] ?? match[3] ?? "").replace(/\\([\\"'])/g, "$1"));
  }
  return args;
}

function isWriteLikeMcpTool(name: string): boolean {
  return /(?:^|[_-])(add|append|create|delete|edit|import|insert|move|remove|rename|save|set|update|upload|write)(?:$|[_-])/i.test(name);
}

type McpTransport = StdioClientTransport | StreamableHTTPClientTransport | SSEClientTransport;

function createMcpTransport(raw: JsonRecord, request: RunStart): McpTransport | undefined {
  const transportKind = String(raw.transport || "stdio").toLowerCase();
  if (transportKind === "streamable-http" || transportKind === "sse") {
    const endpoint = String(raw.endpoint || "").trim();
    if (!/^https?:\/\//i.test(endpoint)) return undefined;
    return transportKind === "sse"
      ? new SSEClientTransport(new URL(endpoint))
      : new StreamableHTTPClientTransport(new URL(endpoint));
  }
  const command = String(raw.command || "").trim();
  if (!command) return undefined;
  return new StdioClientTransport({
    command,
    args: Array.isArray(raw.args_list) ? raw.args_list.map(String) : splitCommandArgs(raw.args),
    cwd: request.cwd,
    stderr: "pipe",
  });
}

function deferredMcpTools(
  raw: JsonRecord,
  request: RunStart,
  serverId: string,
  clients: McpClient[],
): ReturnType<typeof defineTool>[] {
  const serverLabel = String(raw.name || raw.id || serverId);
  const searchName = `mcp__${serverId}__search`;
  const callName = `mcp__${serverId}__call`;
  let client: McpClient | undefined;
  let remoteTools: JsonRecord[] = [];
  let connection: Promise<JsonRecord[]> | undefined;

  const ensureConnected = async (): Promise<JsonRecord[]> => {
    if (connection) return connection;
    connection = (async () => {
      const startedAt = Date.now();
      emit({
        type: "status.update",
        request_id: request.request_id,
        status: "mcp_connecting",
        name: serverLabel,
        details: { activation_mode: "deferred" },
      });
      const transport = createMcpTransport(raw, request);
      if (!transport) throw new Error(`MCP server ${serverLabel} has no usable transport configuration`);
      const next = new McpClient({ name: "scansci-pi", version: "0.2.0" }, { capabilities: {} });
      try {
        await next.connect(transport, { timeout: MCP_CONNECT_TIMEOUT_MS });
        const listed = await next.listTools({}, { timeout: MCP_CONNECT_TIMEOUT_MS });
        client = next;
        clients.push(next);
        remoteTools = (Array.isArray(listed.tools) ? listed.tools : [])
          .filter((tool): tool is JsonRecord => Boolean(tool && typeof tool === "object"))
          .slice(0, MAX_MCP_TOOLS_PER_SERVER);
        emit({
          type: "status.update",
          request_id: request.request_id,
          status: "mcp_ready",
          name: serverLabel,
          duration_ms: Date.now() - startedAt,
          details: { activation_mode: "deferred", tool_count: remoteTools.length },
        });
        return remoteTools;
      } catch (error) {
        await next.close().catch(() => undefined);
        client = undefined;
        connection = undefined;
        emit({
          type: "status.update",
          request_id: request.request_id,
          status: "mcp_unavailable",
          name: serverLabel,
          error: errorText(error),
        });
        throw error;
      }
    })();
    return connection;
  };

  const visibleTools = async (query: string, limit: number): Promise<JsonRecord[]> => {
    const normalized = query.trim().toLowerCase();
    const tools = await ensureConnected();
    return tools
      .filter((tool) => {
        const name = String(tool.name || "");
        if (!name || (isWriteLikeMcpTool(name) && raw.allow_write !== true)) return false;
        return !normalized || `${name}\n${String(tool.description || "")}`.toLowerCase().includes(normalized);
      })
      .slice(0, limit);
  };

  return [
    defineTool({
      name: searchName,
      label: `${serverLabel} · search`,
      description: `Search ${serverLabel} MCP tools on demand. This connects the server only when used.`,
      parameters: Type.Object({
        query: Type.Optional(Type.String({ maxLength: 240 })),
        limit: Type.Optional(Type.Number({ minimum: 1, maximum: 20 })),
      }),
      execute: async (_toolCallId, params) => {
        const result = await visibleTools(String(params.query || ""), Math.max(1, Math.min(20, Number(params.limit || 8))));
        const compact = result.map((tool) => {
          const schema = tool.inputSchema && typeof tool.inputSchema === "object" ? tool.inputSchema as JsonRecord : undefined;
          return {
            name: String(tool.name || ""),
            description: String(tool.description || "").slice(0, MAX_MCP_DESCRIPTION_CHARS),
            input_schema: schema && jsonBytes(schema) <= MAX_MCP_SCHEMA_BYTES ? schema : undefined,
            write_authorized: !isWriteLikeMcpTool(String(tool.name || "")) || raw.allow_write === true,
          };
        });
        const payload = boundedToolPayload(searchName, {
          server: serverLabel,
          activation_mode: "deferred",
          count: compact.length,
          tools: compact,
        });
        emit({
          type: "status.update",
          request_id: request.request_id,
          status: "mcp_discovered",
          name: serverLabel,
          details: { activation_mode: "deferred", tool_count: compact.length },
        });
        return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], details: payload };
      },
    }),
    defineTool({
      name: callName,
      label: `${serverLabel} · call`,
      description: `Call one ${serverLabel} MCP tool found through ${searchName}.`,
      parameters: Type.Object({
        tool: Type.String({ minLength: 1, maxLength: 200 }),
        arguments: Type.Optional(Type.Unsafe<JsonRecord>({ type: "object", additionalProperties: true })),
      }),
      execute: async (_toolCallId, params, signal) => {
        const remoteName = String(params.tool || "").trim();
        const available = await visibleTools(remoteName, MAX_MCP_TOOLS_PER_SERVER);
        const selected = available.find((tool) => String(tool.name || "") === remoteName);
        if (!selected) throw new Error(`MCP tool is unavailable or not authorized: ${remoteName}`);
        if (!client) throw new Error(`MCP server did not connect: ${serverLabel}`);
        const argumentsRecord = (params.arguments && typeof params.arguments === "object" ? params.arguments : {}) as JsonRecord;
        const fingerprint = toolFingerprint(`${callName}:${remoteName}`, argumentsRecord);
        const effectful = isWriteLikeMcpTool(remoteName);
        const activeRun = activeRunStorage.getStore();
        if (!activeRun) throw new Error("No active Pi run owns this MCP tool call");
        let result = effectful ? activeRun.idempotentResults.get(fingerprint) : undefined;
        if (!result) {
          emit({
            type: "status.update",
            request_id: request.request_id,
            status: "mcp_calling",
            name: serverLabel,
            details: { activation_mode: "deferred", tool: remoteName },
          });
          claimToolCall(`${callName}:${remoteName}`, argumentsRecord);
          result = boundedToolPayload(
            `${callName}:${remoteName}`,
            await client.callTool(
              { name: remoteName, arguments: argumentsRecord },
              undefined,
              { signal, timeout: MCP_CALL_TIMEOUT_MS, maxTotalTimeout: MCP_CALL_TIMEOUT_MS },
            ),
          );
          if (effectful) activeRun.idempotentResults.set(fingerprint, result);
          emit({
            type: "status.update",
            request_id: request.request_id,
            status: "mcp_called",
            name: serverLabel,
            details: { activation_mode: "deferred", tool: remoteName },
          });
        }
        return { content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result };
      },
    }),
  ];
}

async function externalMcpTools(request: RunStart): Promise<{ tools: ReturnType<typeof defineTool>[]; clients: McpClient[] }> {
  const exposed: ReturnType<typeof defineTool>[] = [];
  const clients: McpClient[] = [];
  const usedNames = new Set<string>();
  const contract = request.task_contract ? normalizeTaskContract(request) : undefined;
  const enabledServers = (Array.isArray(request.mcp_servers) ? request.mcp_servers : [])
    .filter((raw) => raw && raw.enabled !== false && raw.uninstalled !== true)
    .filter((raw) => !contract || !contract.hasMcpLease || contract.allowedMcpServers.has(String(raw.id || raw.name || "")));
  if (enabledServers.length > MAX_MCP_SERVERS) {
    emit({
      type: "status.update",
      request_id: request.request_id,
      status: "mcp_limited",
      name: "server_inventory",
      error: `Only the first ${MAX_MCP_SERVERS} enabled MCP servers are loaded.`,
    });
  }
  for (const raw of enabledServers.slice(0, MAX_MCP_SERVERS)) {
    if (exposed.length >= MAX_MCP_TOOLS) break;
    let serverId = safeToolSegment(raw.id || raw.name);
    if (raw.deferred === true) {
      if (exposed.length + 2 > MAX_MCP_TOOLS) {
        emit({
          type: "status.update",
          request_id: request.request_id,
          status: "mcp_limited",
          name: String(raw.name || raw.id || serverId),
          error: `MCP tool limit (${MAX_MCP_TOOLS}) would be exceeded by deferred proxy tools.`,
        });
        break;
      }
      let suffix = 2;
      while (usedNames.has(`mcp__${serverId}__search`) || usedNames.has(`mcp__${serverId}__call`)) {
        serverId = `${safeToolSegment(raw.id || raw.name)}_${suffix++}`;
      }
      usedNames.add(`mcp__${serverId}__search`);
      usedNames.add(`mcp__${serverId}__call`);
      const deferred = deferredMcpTools(raw, request, serverId, clients);
      exposed.push(...deferred);
      continue;
    }
    const transport = createMcpTransport(raw, request);
    if (!transport) continue;
    const client = new McpClient({ name: "scansci-pi", version: "0.2.0" }, { capabilities: {} });
    try {
      await client.connect(transport, { timeout: MCP_CONNECT_TIMEOUT_MS });
      const listed = await client.listTools({}, { timeout: MCP_CONNECT_TIMEOUT_MS });
      clients.push(client);
      const remoteTools = Array.isArray(listed.tools) ? listed.tools : [];
      if (remoteTools.length > MAX_MCP_TOOLS_PER_SERVER) {
        emit({
          type: "status.update",
          request_id: request.request_id,
          status: "mcp_limited",
          name: String(raw.name || raw.id || serverId),
          error: `Only the first ${MAX_MCP_TOOLS_PER_SERVER} tools from this server are loaded.`,
        });
      }
      for (const remoteTool of remoteTools.slice(0, MAX_MCP_TOOLS_PER_SERVER)) {
        if (exposed.length >= MAX_MCP_TOOLS) break;
        const remoteName = String(remoteTool.name || "").trim();
        if (!remoteName || (isWriteLikeMcpTool(remoteName) && raw.allow_write !== true)) continue;
        let localName = `mcp__${serverId}__${safeToolSegment(remoteName)}`;
        let suffix = 2;
        while (usedNames.has(localName)) localName = `mcp__${serverId}__${safeToolSegment(remoteName)}_${suffix++}`;
        usedNames.add(localName);
        const inputSchema = remoteTool.inputSchema && typeof remoteTool.inputSchema === "object"
          ? remoteTool.inputSchema as JsonRecord
          : { type: "object", properties: {} };
        if (jsonBytes(inputSchema) > MAX_MCP_SCHEMA_BYTES) {
          emit({
            type: "status.update",
            request_id: request.request_id,
            status: "mcp_tool_skipped",
            name: remoteName,
            error: `MCP input schema exceeded ${MAX_MCP_SCHEMA_BYTES} bytes.`,
          });
          continue;
        }
        exposed.push(defineTool({
          name: localName,
          label: `${String(raw.name || raw.id || "MCP")} · ${remoteName}`,
          description: `${String(remoteTool.description || "MCP tool").slice(0, MAX_MCP_DESCRIPTION_CHARS)} (MCP: ${String(raw.name || raw.id || serverId)})`,
          parameters: Type.Unsafe(inputSchema),
          execute: async (_toolCallId, params, signal) => {
            const activeRun = activeRunStorage.getStore();
            if (!activeRun) throw new Error("No active Pi run owns this MCP tool call");
            const argumentsRecord = params as JsonRecord;
            const fingerprint = toolFingerprint(localName, argumentsRecord);
            const effectful = toolRisk(localName) !== "read_only";
            let result = effectful ? activeRun.idempotentResults.get(fingerprint) : undefined;
            if (!result) {
              claimToolCall(localName, argumentsRecord);
              result = boundedToolPayload(
                localName,
                await client.callTool(
                  { name: remoteName, arguments: argumentsRecord },
                  undefined,
                  { signal, timeout: MCP_CALL_TIMEOUT_MS, maxTotalTimeout: MCP_CALL_TIMEOUT_MS },
                ),
              );
              if (effectful) activeRun.idempotentResults.set(fingerprint, result);
            }
            return {
              content: [{ type: "text" as const, text: JSON.stringify(result) }],
              details: result,
            };
          },
        }));
      }
    } catch (error) {
      await client.close().catch(() => undefined);
      emit({
        type: "status.update",
        request_id: request.request_id,
        status: "mcp_unavailable",
        name: String(raw.name || raw.id || serverId),
        error: errorText(error),
      });
    }
  }
  return { tools: exposed, clients };
}

function tools(
  taskMode: string,
  mcpTools: ReturnType<typeof defineTool>[] = [],
  disabledTools: string[] = [],
  taskContract?: NormalizedTaskContract,
) {
  const controlTools = [
    defineTool({
      name: "ask_user",
      label: "Ask user",
      description: "Pause only when a missing user choice materially changes the task. Ask one concise question with concrete options; do not use this merely to report progress.",
      parameters: Type.Object({
        question: Type.String({ minLength: 1, maxLength: 1200 }),
        reason: Type.Optional(Type.String({ maxLength: 1200 })),
        options: Type.Optional(Type.Array(Type.Object({
          id: Type.String({ minLength: 1, maxLength: 80 }),
          label: Type.String({ minLength: 1, maxLength: 160 }),
          description: Type.Optional(Type.String({ maxLength: 500 })),
        }), { minItems: 1, maxItems: 6 })),
        allow_freeform: Type.Optional(Type.Boolean()),
        allow_multiple: Type.Optional(Type.Boolean()),
      }),
      execute: async (_toolCallId, params) => {
        const activeRun = activeRunStorage.getStore();
        if (activeRun) {
          if (activeRun.askUserCount >= 1) {
            throw new Error("Capability lease denied repeated AskUser in one turn.");
          }
          if (
            activeRun.taskContract.riskLevel !== "high"
            && activeRun.taskContract.allowedTools.size > 0
            && activeRun.successfulToolCalls === 0
          ) {
            throw new Error(
              "Capability lease denied AskUser before read-only discovery. Inspect available context first.",
            );
          }
          activeRun.askUserCount += 1;
        }
        const result = boundedToolPayload(
          "ask_user",
          await requestInteraction("ask_user", params as JsonRecord),
        );
        return {
          content: [{ type: "text" as const, text: JSON.stringify(result) }],
          details: result,
        };
      },
    }),
    defineTool({
      name: "submit_plan",
      label: "Submit plan for approval",
      description: "Pause before an expensive, destructive, ambiguous, or long multi-stage task and submit a concise executable plan. Continue directly for ordinary reversible work.",
      parameters: Type.Object({
        summary: Type.String({ minLength: 1, maxLength: 1600 }),
        steps: Type.Array(Type.Object({
          id: Type.String({ minLength: 1, maxLength: 80 }),
          title: Type.String({ minLength: 1, maxLength: 240 }),
          description: Type.Optional(Type.String({ maxLength: 800 })),
          tools: Type.Optional(Type.Array(Type.String({ maxLength: 120 }), { maxItems: 12 })),
        }), { minItems: 1, maxItems: 16 }),
        risks: Type.Optional(Type.Array(Type.String({ maxLength: 500 }), { maxItems: 8 })),
        expected_outputs: Type.Optional(Type.Array(Type.String({ maxLength: 500 }), { maxItems: 12 })),
      }),
      execute: async (_toolCallId, params) => {
        const response = await requestInteraction("plan", params as JsonRecord);
        const decision = String(response.decision || response.action || response.value || "approve").toLowerCase();
        const activeRun = activeRunStorage.getStore();
        if (activeRun && !["cancel", "reject", "denied", "deny"].includes(decision)) {
          activeRun.planApproved = true;
        }
        const result = boundedToolPayload(
          "submit_plan",
          response,
        );
        return {
          content: [{ type: "text" as const, text: JSON.stringify(result) }],
          details: result,
        };
      },
    }),
  ];
  const available = [
    bridgeTool(
      "inspect_workspace",
      "Inspect workspace",
      "Inspect the active ScanSci workspace and notebook counts without modifying anything.",
      Type.Object({ notebook_id: Type.Optional(Type.String()) }),
    ),
    bridgeTool(
      "inspect_available_tools",
      "Inspect ScanSci tools",
      "List the currently available ScanSci research capabilities.",
      Type.Object({}),
    ),
    bridgeTool(
      "read_task_documents",
      "Read task documents",
      "Read bounded excerpts from documents already registered by the active or most recent ScanSci task. This tool cannot read an arbitrary model-supplied filesystem path.",
      Type.Object({
        run_id: Type.Optional(Type.String({ description: "Existing ScanSci task id; omit to use the active or most recent task with documents" })),
        max_files: Type.Optional(Type.Integer({ minimum: 1, maximum: 24 })),
        per_file_chars: Type.Optional(Type.Integer({ minimum: 1000, maximum: 6000 })),
      }),
    ),
    bridgeTool(
      "download_and_index",
      "Download and index papers",
      "Download DOI or arXiv full text into the current ScanSci task and immediately index readable files in the selected knowledge library. Use only when the user asks to acquire papers.",
      Type.Object({
        identifiers: Type.Array(Type.String(), { minItems: 1, maxItems: 20 }),
        notebook_id: Type.Optional(Type.String()),
        strategy: Type.Optional(Type.Union([
          Type.Literal("legal_only"),
          Type.Literal("oa_first"),
          Type.Literal("gray_oa"),
        ])),
        timeout_seconds: Type.Optional(Type.Number({ minimum: 30, maximum: 600 })),
      }),
    ),
    bridgeTool(
      "summarize_documents",
      "Map task documents for synthesis",
      "Read complete documents already registered by a ScanSci task and return bounded per-document maps of research questions, methods, findings, and limitations. Prefer this over raw excerpts for multi-paper summaries or comparisons.",
      Type.Object({
        run_id: Type.Optional(Type.String({ description: "Existing ScanSci task id; omit to use the active or most recent task with documents" })),
        focus: Type.Optional(Type.String({ description: "Optional question or comparison focus" })),
        max_files: Type.Optional(Type.Integer({ minimum: 1, maximum: 24 })),
      }),
    ),
    bridgeTool(
      "check_task_completion",
      "Check task completion",
      "Verify persisted ScanSci stages, output artifacts, downloaded documents, and full-text indexing before claiming a task is complete.",
      Type.Object({
        run_id: Type.Optional(Type.String({ description: "Existing ScanSci task id; omit to use the active or most recent task" })),
      }),
    ),
    bridgeTool(
      "search_local_evidence",
      "Search local evidence",
      "Search sentence-level evidence in the active ScanSci notebook. Use before making source-grounded scientific claims.",
      Type.Object({
        query: Type.String({ description: "Focused evidence search query" }),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      }),
    ),
    bridgeTool(
      "kb_search",
      "Search linked knowledge bases",
      "Search the currently linked ScanSci knowledge bases. This includes Zotero metadata and Zotero-indexed attachment text when a Zotero library is selected.",
      Type.Object({
        query: Type.String({ description: "Question or focused library search query" }),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
        collection_key: Type.Optional(Type.String()),
        include_fulltext: Type.Optional(Type.Boolean()),
      }),
    ),
    bridgeTool(
      "zotero_search",
      "Search Zotero",
      "Search the user's linked local Zotero library, including collection metadata and locally indexed attachment excerpts.",
      Type.Object({
        query: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
        collection_key: Type.Optional(Type.String()),
        include_fulltext: Type.Optional(Type.Boolean()),
      }),
    ),
    bridgeTool(
      "zotero_status",
      "Inspect Zotero status",
      "Inspect local Zotero database, local API, and connector readiness without modifying Zotero.",
      Type.Object({}),
    ),
    bridgeTool(
      "zotero_fulltext",
      "Read Zotero full text",
      "Read Zotero-indexed full text for one attachment key through the local API or local full-text cache.",
      Type.Object({
        attachment_key: Type.String(),
        max_chars: Type.Optional(Type.Integer({ minimum: 1000, maximum: 80000 })),
      }),
    ),
    bridgeTool(
      "zotero_attachment",
      "Locate Zotero attachment",
      "Resolve one Zotero attachment key to its local file or Zotero local-API URL without modifying the library.",
      Type.Object({ attachment_key: Type.String() }),
    ),
    bridgeTool(
      "zotero_export_bibtex",
      "Export Zotero BibTeX",
      "Export canonical BibTeX from a running local Zotero instance. Optionally restrict export to one Zotero item key.",
      Type.Object({
        item_key: Type.Optional(Type.String()),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      }),
    ),
    bridgeTool(
      "zotero_citations",
      "Render Zotero citations",
      "Render formatted citations through a running local Zotero instance.",
      Type.Object({
        style: Type.Optional(Type.String()),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      }),
    ),
    bridgeTool(
      "obsidian_status",
      "Inspect Obsidian connection",
      "Inspect the user-linked Obsidian vaults selected for this conversation. This is read-only.",
      Type.Object({}),
    ),
    bridgeTool(
      "obsidian_search",
      "Search Obsidian notes",
      "Search note paths and Markdown bodies in the user-linked Obsidian vaults selected for this conversation.",
      Type.Object({
        query: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      }),
    ),
    bridgeTool(
      "obsidian_read",
      "Read Obsidian note",
      "Read one note by its vault-relative Markdown path. Absolute paths and traversal outside the linked vault are rejected.",
      Type.Object({
        note_path: Type.String(),
        max_chars: Type.Optional(Type.Integer({ minimum: 1000, maximum: 100000 })),
      }),
    ),
    bridgeTool(
      "obsidian_backlinks",
      "Find Obsidian backlinks",
      "Find notes in the linked vault that contain a wikilink to the requested note.",
      Type.Object({
        note_path: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      }),
    ),
    bridgeTool(
      "build_verified_answer",
      "Build verified answer",
      "Create a citation-verified answer from the active notebook. This is mandatory for evidence-grounded final answers.",
      Type.Object({
        question: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      }),
    ),
    bridgeTool(
      "verify_doi",
      "Verify DOI",
      "Verify DOI metadata against Crossref.",
      Type.Object({ doi: Type.String(), expected_title: Type.Optional(Type.String()) }),
    ),
    bridgeTool(
      "discover_papers",
      "Discover papers",
      "Search scholarly APIs, deduplicate and rerank results. The response is context-bounded and includes download_identifiers; pass them to download_and_index before summarizing.",
      Type.Object({
        query: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, description: "Alias for result_limit" })),
        per_source: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
        year_from: Type.Optional(Type.Integer({ minimum: 1800, maximum: 3000 })),
        providers: Type.Optional(Type.Array(Type.String())),
      }),
    ),
    bridgeTool(
      "search_web",
      "Search the web",
      "Search current public web pages and return source-linked titles and snippets. Use for news, current events, organisations, products, markets, and other non-scholarly web questions.",
      Type.Object({
        query: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 12 })),
      }),
    ),
    bridgeTool(
      "agent_reach",
      "Agent Reach internet router",
      "Read or search public internet channels through ScanSci's built-in zero-install Agent Reach adaptation. Use for public URLs, RSS, GitHub, Bilibili, V2EX, and public-web discovery. If the page needs login state, browser rendering, or interaction, use browser_access instead.",
      Type.Object({
        operation: Type.Union([Type.Literal("status"), Type.Literal("read"), Type.Literal("search")]),
        target: Type.Optional(Type.String({ maxLength: 2_000 })),
        query: Type.Optional(Type.String({ maxLength: 1_000 })),
        channel: Type.Optional(Type.Union([
          Type.Literal("auto"), Type.Literal("web"), Type.Literal("rss"), Type.Literal("github"),
          Type.Literal("youtube"), Type.Literal("bilibili"), Type.Literal("v2ex"), Type.Literal("xueqiu"),
          Type.Literal("twitter"), Type.Literal("reddit"), Type.Literal("xiaohongshu"), Type.Literal("facebook"),
          Type.Literal("instagram"), Type.Literal("linkedin"),
        ])),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 12 })),
        timeout_seconds: Type.Optional(Type.Number({ minimum: 3, maximum: 60 })),
      }),
    ),
    bridgeTool(
      "browser_access",
      "Rendered browser access",
      "Read one public URL through the bundled web-access CDP bridge and the user's Chrome session. Use only for login-aware, dynamically rendered, anti-bot, or interaction-dependent pages. Read-only: no arbitrary JavaScript, clicks, form submission, uploads, or writes.",
      Type.Object({
        operation: Type.Union([Type.Literal("status"), Type.Literal("read")]),
        target: Type.Optional(Type.String({ maxLength: 2_000 })),
        timeout_seconds: Type.Optional(Type.Number({ minimum: 5, maximum: 60 })),
      }),
    ),
    bridgeTool(
      "search_journal",
      "Search journals",
      "Look up journal metadata, indicators, and warning flags.",
      Type.Object({
        query: Type.String(),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      }),
    ),
    bridgeTool(
      "audit_references",
      "Audit references",
      "Audit supplied references or manuscript text through ScanSci Citation Lab.",
      Type.Object({
        text: Type.String(),
        mode: Type.Optional(Type.Union([Type.Literal("references"), Type.Literal("full")])),
      }),
    ),
    bridgeTool(
      "build_presentation_outline",
      "Build presentation outline",
      "Create a source-linked presentation outline without writing a project to disk.",
      Type.Object({
        topic: Type.Optional(Type.String()),
        notebook_id: Type.Optional(Type.String()),
        template_id: Type.Optional(Type.String()),
      }),
    ),
    bridgeTool(
      "create_document",
      "Create Word document",
      "Create a verified local DOCX artifact from a title and Markdown-like text. The file is written only inside ScanSci's artifact directory.",
      Type.Object({
        title: Type.String(),
        content: Type.String(),
        output_name: Type.Optional(Type.String()),
      }),
    ),
    bridgeTool(
      "create_pdf",
      "Create PDF",
      "Create and structurally verify a local PDF artifact from supplied text.",
      Type.Object({
        title: Type.String(),
        content: Type.String(),
        output_name: Type.Optional(Type.String()),
      }),
    ),
    bridgeTool(
      "create_spreadsheet",
      "Create spreadsheet",
      "Create a verified local XLSX workbook from column names and structured rows. Formula strings beginning with '=' remain editable formulas.",
      Type.Object({
        title: Type.String(),
        columns: Type.Array(Type.String(), { minItems: 1 }),
        rows: Type.Array(Type.Any()),
        output_name: Type.Optional(Type.String()),
      }),
    ),
    bridgeTool(
      "create_presentation",
      "Create presentation",
      "Create a verified editable PPTX from a title and a compact slide list.",
      Type.Object({
        title: Type.String(),
        subtitle: Type.Optional(Type.String()),
        slides: Type.Array(Type.Object({
          title: Type.String(),
          bullets: Type.Optional(Type.Array(Type.String())),
          content: Type.Optional(Type.String()),
        }), { minItems: 1, maxItems: 60 }),
        output_name: Type.Optional(Type.String()),
      }),
    ),
    bridgeTool(
      "compile_latex",
      "Compile LaTeX",
      "Compile supplied TeX source to a local PDF with bundled Tectonic when available, falling back to an existing TeX Live installation. Shell escape is never enabled.",
      Type.Object({
        title: Type.Optional(Type.String()),
        source: Type.String(),
        output_name: Type.Optional(Type.String()),
      }),
    ),
    bridgeTool(
      "self_assess",
      "Assess progress",
      "Return a structured summary of tools called so far, their results, and a suggestion for whether to continue, adjust, or deliver.",
      Type.Object({
        _meta: Type.Optional(Type.Boolean()),
      }),
    ),
    bridgeTool(
      "edit_section",
      "Edit document section",
      "Replace a specific string in a document with new text (exact match, first occurrence only). Use for precise edits without regenerating the entire document.",
      Type.Object({
        file_path: Type.String(),
        old_string: Type.String(),
        new_string: Type.String(),
      }),
    ),
    bridgeTool(
      "edit_slide",
      "Edit slide text",
      "Replace text on a specific slide (1-based index) in an existing PPTX file. Only the first matching occurrence is replaced. Use for targeted slide edits without regenerating the entire deck.",
      Type.Object({
        pptx_path: Type.String(),
        slide_index: Type.Integer(),
        old_string: Type.String(),
        new_string: Type.String(),
      }),
    ),
  ];
  const blocked = new Set(disabledTools.map(String));
  const enabledAvailable = available.filter((tool) => !blocked.has(tool.name));
  const namesByMode: Record<string, Set<string>> = {
    knowledge: new Set(["inspect_workspace", "inspect_available_tools", "search_local_evidence", "kb_search", "zotero_search", "zotero_status", "zotero_fulltext", "zotero_attachment", "zotero_export_bibtex", "zotero_citations", "obsidian_status", "obsidian_search", "obsidian_read", "obsidian_backlinks", "build_verified_answer", "self_assess"]),
    research: new Set(["inspect_workspace", "inspect_available_tools", "search_web", "agent_reach", "browser_access", "discover_papers", "download_and_index", "summarize_documents", "check_task_completion", "verify_doi", "search_local_evidence", "kb_search", "zotero_search", "zotero_status", "zotero_fulltext", "zotero_attachment", "zotero_export_bibtex", "zotero_citations", "obsidian_status", "obsidian_search", "obsidian_read", "obsidian_backlinks", "build_verified_answer", "self_assess"]),
    "workspace-status": new Set(["inspect_workspace"]),
    "zotero-status": new Set(["zotero_status"]),
    "zotero-search": new Set(["zotero_search"]),
    "task-documents": new Set(["read_task_documents", "summarize_documents", "check_task_completion", "self_assess"]),
    "web-auto": new Set(["search_web", "agent_reach", "browser_access", "discover_papers", "verify_doi", "self_assess"]),
    web: new Set(["search_web", "agent_reach", "browser_access", "self_assess"]),
    // The verified-answer endpoint has one mandatory terminal action. Keeping
    // only this composite tool prevents small/text-only models from spending
    // their bounded generation window on an intermediate search and stopping.
    "verified-answer": new Set(["build_verified_answer"]),
    slides: new Set(["inspect_workspace", "build_presentation_outline", "create_document", "create_pdf", "create_spreadsheet", "create_presentation", "compile_latex", "edit_section", "edit_slide", "self_assess"]),
    benchmark: new Set(enabledAvailable.map((tool) => tool.name)),
  };
  const modeParts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  const exactMode = namesByMode[taskMode];
  const enabled = exactMode || (
    modeParts.size > 1
      ? new Set([...modeParts].flatMap((part) => [...(namesByMode[part] || new Set<string>())]))
      : undefined
  );
  const modeBuiltins = enabled ? enabledAvailable.filter((tool) => enabled.has(tool.name)) : enabledAvailable;
  const builtins = taskContract && taskContract.allowedTools.size > 0
    ? modeBuiltins.filter((tool) => taskContract.allowedTools.has(tool.name))
    : modeBuiltins;
  const allowExternal = [...modeParts].some((part) => ["general", "knowledge", "research", "benchmark"].includes(part));
  const leasedMcpTools = taskContract
    ? mcpTools.filter((tool) => {
      const risk = toolRisk(tool.name);
      return riskRank(risk) <= riskRank(taskContract.riskLevel)
        && (risk !== "high" || taskContract.allowExternalWrite);
    })
    : mcpTools;
  return allowExternal ? [...controlTools, ...builtins, ...leasedMcpTools] : [...controlTools, ...builtins];
}

function evidencePolicy(taskMode: string): "off" | "assist" | "strict" {
  const parts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  if ([...parts].some((part) => ["knowledge", "research", "verified-answer", "benchmark"].includes(part))) return "strict";
  if ([...parts].some((part) => ["workspace-status", "task-documents", "zotero-search", "web", "web-auto", "slides"].includes(part))) return "assist";
  return "off";
}

function toolCallBudget(taskMode: string): number {
  const parts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  if (parts.has("research") || parts.has("slides")) return 6;
  if (parts.has("knowledge") || parts.has("task-documents")) return 4;
  if (parts.has("web") || parts.has("web-auto")) return 3;
  if (parts.has("workspace-status") || parts.has("zotero-status") || parts.has("zotero-search")) return 2;
  return 2;
}

function modelOutputBudget(taskMode: string): number {
  const parts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  if (parts.has("research") || parts.has("slides")) return 4096;
  if (parts.has("knowledge") || parts.has("task-documents")) return 3072;
  if (parts.has("web") || parts.has("web-auto")) return 2048;
  return 1536;
}

function modelTokenBudget(taskMode: string): number {
  const parts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  if (parts.has("research") || parts.has("slides")) return 48_000;
  if (parts.has("knowledge") || parts.has("task-documents")) return 32_000;
  if (parts.has("web") || parts.has("web-auto")) return 24_000;
  if (parts.has("workspace-status") || parts.has("zotero-status") || parts.has("zotero-search")) return 12_000;
  return 12_000;
}

function providerInputBudget(taskMode: string): number {
  const parts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  if (parts.has("research") || parts.has("slides")) return 48_000;
  if (parts.has("knowledge") || parts.has("task-documents")) return 32_000;
  if (parts.has("web") || parts.has("web-auto")) return 24_000;
  return 12_000;
}

function guardProviderRequest(payload: unknown, taskMode: string): unknown {
  const estimatedTokens = estimateProviderInputTokens(payload);
  const budget = providerInputBudget(taskMode);
  if (estimatedTokens > budget) {
    throw new Error(
      `Provider input budget exceeded before network request: estimated ${estimatedTokens} tokens ` +
      `(limit ${budget}). Compact the session or narrow the tool result before retrying.`,
    );
  }
  return payload;
}

function systemPrompt(request: RunStart): string {
  const taskMode = String(request.task_mode || "general");
  const contract = normalizeTaskContract(request);
  const currentHostDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const modeParts = new Set(taskMode.split("+").filter(Boolean));
  const hasMode = (mode: string): boolean => modeParts.has(mode);
  const userRequest = finalUserRequestText(request.prompt || "");
  const exactIdentifier = /(?:\b10\.\d{4,9}\/[A-Za-z0-9._;()/:+\-[\]]+|\b(?:arxiv:)?(?:\d{4}\.\d{4,5}|[a-z-]+\/\d{7})(?:v\d+)?)/i.test(userRequest);
  const hostEvidencePolicy = String(contract.taskProfile.evidence_policy || "");
  const policy = ["off", "assist", "strict"].includes(hostEvidencePolicy)
    ? hostEvidencePolicy as "off" | "assist" | "strict"
    : evidencePolicy(taskMode);
  const callBudget = contract.initialToolBudget;
  const profileRoute = String(contract.taskProfile.route || "tool_agent");
  const profileRule = [
    `Host route=${profileRoute}; cognitive complexity=${String(contract.taskProfile.cognitive_complexity || "medium")}; execution complexity=${String(contract.taskProfile.execution_complexity || "tool")}.`,
    contract.requiredToolGroups.length
      ? `Required tool groups (host authoritative): ${contract.requiredToolGroups.map((group) => [...group].join(" OR ")).join(" AND ")}.`
      : "No tool is mandatory unless the final request itself cannot be answered truthfully without one.",
    profileRoute === "resumable_workflow"
      ? "Preserve completed stage results across recovery attempts; never restart successful work merely because a later stage failed."
      : "",
  ].filter(Boolean).join("\n");
  const contractRule = [
    `Task contract ${contract.contractId}: goal=${contract.goal || "answer the final request"}.`,
    `Output format=${contract.outputFormat}; pause policy=${contract.pausePolicy}.`,
    contract.requiredEvidence.length ? `Required evidence: ${contract.requiredEvidence.join("; ")}.` : "",
    `Autonomy=${contract.autonomy}; risk ceiling=${contract.riskLevel}.`,
    contract.requiresPlan
      ? "A user-approved plan is REQUIRED before any reversible or high-risk action."
      : contract.riskLevel === "reversible"
        ? "Ordinary local reversible actions are pre-authorized: execute them, verify their persisted result, and do not ask for routine confirmation."
        : "This lease is read-only: inspect and retrieve autonomously, but do not write or mutate state.",
    contract.successCriteria.length
      ? `Success criteria: ${contract.successCriteria.join("; ")}.`
      : "",
  ].filter(Boolean).join("\n");
  const policyRule = policy === "strict"
    ? "Evidence policy is STRICT: retrieve source material, distinguish metadata from full text, and verify source-grounded claims before delivery."
    : policy === "assist"
      ? "Evidence policy is ASSIST: use available sources when they improve the result, but do not force a citation chain for editing, ideation, or other non-factual parts of the request."
      : "Evidence policy is OFF: answer ordinary conversation, drafting, and brainstorming directly unless the user explicitly asks for research or verification.";
  const evidenceRule = hasMode("zotero-status")
    ? "You MUST call zotero_status before answering. Report the actual local database, local API, connector, and ScanSci plugin status returned by the tool. Do not claim Zotero is inaccessible before inspecting it."
    : hasMode("workspace-status")
      ? "You MUST call inspect_workspace before answering. Report only the actual bounded notebook/source counts returned by the tool. Never infer that the workspace is empty without this result."
    : hasMode("zotero-search")
      ? "You MUST call zotero_search before answering. Use the user's final request as the search query, ground the answer in returned Zotero metadata or indexed attachment excerpts, and distinguish metadata-only results from full-text evidence."
      : hasMode("task-documents") && hasMode("research")
        ? "This is a conditional local-document plus acquisition task. First call read_task_documents. If the current task has no usable registered full text, call download_and_index with the exact DOI/arXiv identifier supplied by the user, then call summarize_documents and check_task_completion. Do not ask the user to enable another mode or re-upload a file while these tools are available."
      : hasMode("task-documents")
        ? "For a summary or comparison, call summarize_documents; for a focused quotation or simple read, call read_task_documents. Synthesize across every returned document map, state failed or truncated files briefly, and do not ask the user to upload files that ScanSci already registered."
        : hasMode("web")
    ? "Web access is explicitly ON. You MUST call one permitted web tool before answering. Route ordinary public search to search_web; route public direct URLs, RSS, GitHub, Bilibili, V2EX, or channel status to agent_reach; route pages requiring login state, browser rendering, anti-bot handling, or interaction to browser_access. Do not call both public readers for the same URL unless the first result is insufficient. Cite returned URLs for externally sourced claims. If browser_access returns a risk_notice, include it when relevant."
    : hasMode("web-auto")
      ? "Web search is AUTO. Call one permitted web tool when the answer depends on current or general public-web information. Use search_web for discovery, agent_reach for public direct URLs and structured channels, and browser_access only when login state, rendering, anti-bot handling, or interaction is required. Call discover_papers for not-yet-imported scholarly literature. Do not duplicate the same URL across public readers. Cite returned URLs/DOIs and distinguish discovery snippets or abstracts from verified full text."
      : hasMode("knowledge") && !hasMode("research")
        ? "Use only the selected knowledge library. For a ScanSci-indexed library, call search_local_evidence or build_verified_answer and synthesize the returned full-text excerpts. For a linked Zotero or Obsidian library, use only the matching permitted connector tools. Do not call research-run document tools, switch to an unselected library, or treat title-only metadata as full-text evidence."
      : hasMode("verified-answer") || hasMode("research") || hasMode("benchmark")
        ? `For a linked Zotero library, call kb_search or zotero_search and ground the answer in returned Zotero metadata or indexed-fulltext excerpts. For ScanSci-indexed evidence sources, call build_verified_answer before delivering scientific claims. ${exactIdentifier ? "The user supplied an exact DOI/arXiv identifier: call download_and_index directly and do not spend a turn rediscovering the same paper." : "When the user asks to find, acquire, and analyze papers, use discover_papers before download_and_index."} Then call summarize_documents and check_task_completion before claiming completion. Never invent a source or treat title-only metadata as full-text evidence.`
        : "Use ScanSci tools when they materially improve the answer. Never claim a tool action happened unless the tool returned success.";
  const artifactRule = hasMode("slides")
    ? "This request also requires a real artifact. Call the matching create_* or compile_latex tool, use retrieved/document evidence as its content, and report only the verified file_path returned by the tool. An outline or filename invented in prose is not delivery."
    : "";
  return `${request.system_prompt}\n\nYou are running inside ScanSci with the Pi agent runtime.\nCurrent ScanSci host date (Asia/Shanghai): ${currentHostDate}. For requests containing today, latest, current, or recent, include this exact date or an explicit bounded recency term in the search query. Never infer the current date from model memory. Do not label older results as today's news; if current results cannot be verified, say so and identify the actual source dates.\n\n— HOST-OWNED TASK CONTRACT —\n${contractRule}\n${profileRule}\nThe host, not the model, owns permissions, required actions, and budgets. A denied tool call means you must choose a permitted strategy; never tell the user to change modes merely because one route was denied.\n\n— REASONING FRAMEWORK —\n1. **Plan**: Decompose the request into the smallest useful tool sequence. Submit a blocking plan only when the task contract requires it. Do not pause ordinary read-only or pre-authorized reversible work.\n2. **Execute**: Call ONE tool at a time. If a search returns zero results, broaden the query or switch sources — do not give up.\n3. **Verify**: Check the persisted result of consequential actions. Under strict evidence policy, source-ground scientific claims; otherwise do not manufacture a citation workflow the user did not ask for.\n4. **Adjust**: Call \`self_assess\` when uncertain whether to continue, adjust parameters, or deliver. Call \`ask_user\` only when a missing choice materially changes the result and bounded read-only discovery cannot resolve it; never use it as a progress update.\n5. **Deliver**: Continue until you can return the requested result or a concrete, truthful blocking error.\n\n${policyRule}\n${evidenceRule}\n${artifactRule}\n\nInitial budget: ${callBudget} tool calls; the host may extend it up to ${contract.maxToolBudget} only after verified progress. The hard cumulative model-token ceiling is ${contract.modelTokenBudget}. Avoid repeating equivalent searches and deliver the best truthful partial result before the lease is exhausted.\n\nA plan written only in prose, preflight note, or promise to work later is never a final answer. Built-in shell and unrestricted filesystem mutation tools are disabled.`;
}

function looksLikeDeferredAnswer(text: string): boolean {
  const tail = String(text || "").trim().slice(-700);
  if (!tail) return true;
  return /(?:请稍候|稍后(?:为你)?(?:返回|提供)|(?:现在|接下来|下一步)(?:我|将|会|准备|开始).{0,24}(?:执行|检索|搜索|调研|下载|总结|综述|创建|生成|继续)|让我(?:重新)?(?:开始|继续)(?:执行|检索|搜索|调研|下载|总结|综述|创建|生成|这个过程)?|(?:我|本助手)(?:将|会)(?:立即|马上|现在)?(?:开始|继续)(?:执行|检索|搜索|调研|下载|总结|综述|创建|生成)|(?:i(?:'ll| will)|let me) (?:now )?(?:re)?(?:start|begin|continue|search|research|download|summari[sz]e|review|create|generate)|please wait|working on it|<SCANSCI_TOOL_CALL>|\{\s*["']name["']\s*:\s*["'][A-Za-z0-9_-]+["'])/i.test(tail);
}

function requiredToolGroups(taskMode: string, requestText = ""): Set<string>[] {
  const parts = new Set(String(taskMode || "general").split("+").filter(Boolean));
  const normalizedText = String(requestText || "");
  const groups: Set<string>[] = [];
  if (parts.has("zotero-status")) groups.push(new Set(["zotero_status"]));
  if (parts.has("workspace-status")) groups.push(new Set(["inspect_workspace"]));
  if (parts.has("zotero-search")) groups.push(new Set(["zotero_search"]));
  if (parts.has("web")) groups.push(new Set(["search_web", "agent_reach", "browser_access", "discover_papers"]));
  if (parts.has("task-documents")) groups.push(new Set(["read_task_documents", "summarize_documents"]));
  const explicitKnowledge = /(?:knowledge\s*base|zotero|obsidian|知识库|本地库|文献库|资料库|向量库)|(?:这些|这批|已连接|已链接|当前).{0,12}(?:文献|论文|资料|知识库)|(?:linked|local|selected|current).{0,18}(?:library|documents?|papers?)/i.test(normalizedText);
  if (parts.has("knowledge") && explicitKnowledge) {
    groups.push(new Set(["search_local_evidence", "kb_search", "zotero_search", "zotero_fulltext", "obsidian_search", "obsidian_read", "build_verified_answer"]));
  }
  if (parts.has("research")) {
    const wantsDownload = /(?:download|acquire|fetch|full\s*text|下载|获取(?:论文|文献)|全文|索引)/i.test(normalizedText);
    groups.push(wantsDownload
      ? new Set(["download_and_index"])
      : new Set(["discover_papers", "search_web"]));
    if (wantsDownload && /(?:summari[sz]e|synthesi[sz]e|review|compare|analy[sz]e|总结|综述|比较|对比|分析|归纳)/i.test(normalizedText)) {
      groups.push(new Set(["summarize_documents"]));
    }
    if (wantsDownload) groups.push(new Set(["check_task_completion"]));
  }
  if (parts.has("verified-answer")) groups.push(new Set(["build_verified_answer"]));
  const explicitArtifact = /(?:create|generate|make|build|export|save|produce|downloadable|创建|生成|制作|导出|保存|产出|可下载|实际文件)/i.test(normalizedText);
  if (parts.has("slides") && explicitArtifact) {
    groups.push(new Set(["build_presentation_outline", "create_document", "create_pdf", "create_spreadsheet", "create_presentation", "compile_latex"]));
  }
  return groups;
}

function finalUserRequestText(prompt: string): string {
  const source = String(prompt || "");
  const matches = [...source.matchAll(/\[USER\]\s*\n([\s\S]*?)(?=\n\n\[(?:USER|ASSISTANT)\]\s*\n|$)/gi)];
  return matches.length ? String(matches[matches.length - 1][1] || "").trim() : source;
}

function taskContractSessionSignature(request: RunStart): JsonRecord {
  if (!request.task_contract) return {};
  const contract = normalizeTaskContract(request);
  return {
    autonomy: contract.autonomy,
    riskLevel: contract.riskLevel,
    requiresPlan: contract.requiresPlan,
    allowedTools: [...contract.allowedTools].sort(),
    requiredToolGroups: contract.requiredToolGroups
      .map((group) => [...group].sort())
      .sort((left, right) => left.join("|").localeCompare(right.join("|"))),
    initialToolBudget: contract.initialToolBudget,
    maxToolBudget: contract.maxToolBudget,
    recoveryBudget: contract.recoveryBudget,
    modelTokenBudget: contract.modelTokenBudget,
    allowExternalWrite: contract.allowExternalWrite,
  };
}

function sessionSignature(request: RunStart): string {
  return JSON.stringify([
    request.cwd,
    request.agent_dir,
    request.provider_kind,
    request.api_surface || "chat_completions",
    request.responses_enabled === true,
    request.base_url,
    request.model_id,
    request.thinking_level || "medium",
    request.system_prompt,
    request.task_mode || "general",
    // Exclude per-turn identity and goal text.  A new contract id is minted
    // for every user message; only a real permission/budget change should
    // force a new Pi session and discard accumulated context.
    taskContractSessionSignature(request),
    request.mcp_servers || [],
    request.disabled_tools || [],
  ]);
}

function normalizeTextOnlyOpenAIRequest(payload: unknown): unknown {
  if (!payload || typeof payload !== "object") return payload;
  const requestPayload = payload as JsonRecord;
  const messages = Array.isArray(requestPayload.messages) ? requestPayload.messages : [];
  const normalizedMessages = messages.map((message) => {
    if (!message || typeof message !== "object") return message;
    const record = message as JsonRecord;
    if (!Array.isArray(record.content)) return record;
    const parts = record.content as JsonRecord[];
    if (!parts.every((part) => part?.type === "text" && typeof part.text === "string")) return record;
    return { ...record, content: parts.map((part) => String(part.text)).join("") };
  });
  return { ...requestPayload, messages: normalizedMessages };
}

async function createSession(
  request: RunStart,
  sessionManagerOverride?: SessionManager,
): Promise<SessionState> {
  const apiKey = process.env.SCANSCIPI_PROVIDER_KEY || "";
  if (!apiKey) throw new Error("Provider API key is unavailable");
  const runtime = await ModelRuntime.create({ allowModelNetwork: false, modelsPath: null });
  runtime.registerProvider("scansci-pi", {
    name: "ScanSci Pi provider",
    baseUrl: request.base_url,
    apiKey: "$SCANSCIPI_PROVIDER_KEY",
    api: providerApi(request.provider_kind, request.api_surface),
    models: [{
      id: request.model_id,
      name: request.model_id,
      reasoning: thinkingLevel(request.thinking_level) !== "off",
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 128000,
      maxTokens: modelOutputBudget(String(request.task_mode || "general")),
      compat: modelCompat(request),
    }],
  });
  await runtime.setRuntimeApiKey("scansci-pi", apiKey);
  const model = runtime.getModel("scansci-pi", request.model_id);
  if (!model) throw new Error(`Pi could not register model ${request.model_id}`);

  const loader = new DefaultResourceLoader({
    cwd: request.cwd,
    agentDir: request.agent_dir,
    systemPromptOverride: () => systemPrompt(request),
    appendSystemPromptOverride: () => [],
    extensionFactories: [{
      name: "scansci-provider-request-guard",
      factory: (pi) => {
        pi.on("before_provider_request", (event) => {
          const payload = providerApi(request.provider_kind, request.api_surface) === "openai-completions"
            ? normalizeTextOnlyOpenAIRequest(event.payload)
            : event.payload;
          return guardProviderRequest(payload, String(request.task_mode || "general"));
        });
      },
    }],
  });
  await loader.reload();
  const external = await externalMcpTools(request);
  const taskContract = normalizeTaskContract(request);
  const customTools = tools(
    String(request.task_mode || "general"),
    external.tools,
    request.disabled_tools || [],
    request.task_contract ? taskContract : undefined,
  );
  const prefixShape = buildPrefixShape(request, customTools.map((tool) => String(tool.name)));
  const sessionDir = `${request.agent_dir}/sessions`;
  fs.mkdirSync(sessionDir, { recursive: true });
  const resumeFile = String(request.session_file || "");
  const sessionManager = sessionManagerOverride || (
    resumeFile && fs.existsSync(resumeFile)
      ? SessionManager.open(resumeFile, sessionDir, request.cwd)
      : SessionManager.create(request.cwd, sessionDir, { id: request.session_id })
  );
  const created = await createAgentSession({
    cwd: request.cwd,
    agentDir: request.agent_dir,
    modelRuntime: runtime,
    model,
    thinkingLevel: thinkingLevel(request.thinking_level),
    noTools: customTools.length ? "builtin" : "all",
    customTools,
    resourceLoader: loader,
    sessionManager,
    settingsManager: SettingsManager.inMemory({
      httpIdleTimeoutMs: 120000,
      compaction: { enabled: true, reserveTokens: 16384, keepRecentTokens: 20000 },
      retry: {
        // ScanSci owns cross-strategy recovery. Disabling nested SDK/provider
        // retries prevents one logical turn from multiplying paid requests.
        enabled: false,
        maxRetries: 0,
        baseDelayMs: 1000,
        provider: { timeoutMs: 120000, maxRetries: 0, maxRetryDelayMs: 5000 },
      },
    }),
  });
  const state: SessionState = {
    session: created.session,
    request,
    signature: sessionSignature(request),
    unsubscribe: () => undefined,
    mcpClients: external.clients,
    activeToolNames: customTools.map((tool) => String(tool.name)),
    prefixShape,
  };
  state.unsubscribe = state.session.subscribe((event) => {
    const requestId = state.currentRequestId || "";
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      emit({ type: "message.delta", request_id: requestId, delta: event.assistantMessageEvent.delta });
    } else if (event.type === "tool_execution_start") {
      emit({ type: "status.update", request_id: requestId, status: "tool_started", name: event.toolName });
    } else if (event.type === "tool_execution_end") {
      emit({ type: "status.update", request_id: requestId, status: event.isError ? "tool_failed" : "tool_completed", name: event.toolName });
    } else if (event.type === "auto_retry_start") {
      emit({
        type: "status.update",
        request_id: requestId,
        status: "retry",
        attempt: event.attempt,
        delay_ms: event.delayMs,
        error: redactSensitiveText(event.errorMessage),
      });
    } else if (event.type === "compaction_start") {
      emit({ type: "session.compaction_started", request_id: requestId, session_id: request.session_id, reason: event.reason });
    } else if (event.type === "compaction_end") {
      emit({
        type: "session.compaction_completed",
        request_id: requestId,
        session_id: request.session_id,
        reason: event.reason,
        aborted: event.aborted,
        error: redactSensitiveText(event.errorMessage || ""),
        result: event.result || {},
      });
    }
  });
  return state;
}

async function getSession(request: RunStart): Promise<{ state: SessionState; resumed: boolean }> {
  const existing = sessions.get(request.session_id);
  if (existing && existing.signature === sessionSignature(request)) {
    existing.request = request;
    return { state: existing, resumed: true };
  }
  if (existing) {
    existing.unsubscribe();
    existing.session.dispose();
    await Promise.all(existing.mcpClients.map((client) => client.close().catch(() => undefined)));
    sessions.delete(request.session_id);
  }
  const state = await createSession(request);
  sessions.set(request.session_id, state);
  return { state, resumed: Boolean(request.session_file) };
}

async function run(request: RunStart): Promise<void> {
  const existingRequestId = activeSessionRequests.get(request.session_id);
  if (existingRequestId) {
    const failure = {
      code: "session_busy",
      message: "This session already has an active run. Queue this message as a follow-up instead.",
      retryable: true,
      recovery_actions: [{ id: "follow_up", label: "加入后续队列", kind: "follow_up" }],
    };
    emit({
      type: "run.failed",
      request_id: request.request_id,
      session_id: request.session_id,
      error: failure.message,
      failure,
      active_request_id: existingRequestId,
    });
    return;
  }
  const taskContract = normalizeTaskContract(request);
  const runState: ActiveRun = {
    requestId: request.request_id,
    sessionId: request.session_id,
    cancelled: false,
    startedAt: Date.now(),
    background: request.background === true,
    toolCalls: 0,
    toolCallBudget: taskContract.initialToolBudget,
    maxToolCallBudget: taskContract.maxToolBudget,
    successfulToolCalls: 0,
    lastExtensionSuccesses: 0,
    toolFingerprints: new Map<string, number>(),
    idempotentResults: new Map<string, JsonRecord>(),
    taskContract,
    planApproved: false,
    askUserCount: 0,
    modelTokens: 0,
    modelTokenBudget: taskContract.modelTokenBudget,
    modelTokenBudgetExceeded: false,
  };
  activeRuns.set(runState.requestId, runState);
  activeSessionRequests.set(runState.sessionId, runState.requestId);
  try {
    await activeRunStorage.run(runState, async () => executeRun(request, runState));
  } finally {
    activeRuns.delete(runState.requestId);
    if (activeSessionRequests.get(runState.sessionId) === runState.requestId) {
      activeSessionRequests.delete(runState.sessionId);
    }
  }
}

async function executeRun(request: RunStart, runState: ActiveRun): Promise<void> {
  let state: SessionState | undefined;
  let lastRetryError = "";
  const completedToolNames = new Set<string>();
  let originalThinkingLevel: ThinkingLevel | undefined;
  let thinkingReduced = false;
  try {
    const resolved = await getSession(request);
    state = resolved.state;
    originalThinkingLevel = state.session.thinkingLevel;
    state.currentRequestId = request.request_id;
    const unsubscribeRetry = state.session.subscribe((event) => {
      if (event.type === "auto_retry_start") lastRetryError = event.errorMessage;
      if (event.type === "message_end" && event.message.role === "assistant") {
        runState.modelTokens += freshUsageTokens(event.message.usage);
        if (runState.modelTokens > runState.modelTokenBudget && !runState.modelTokenBudgetExceeded) {
          runState.modelTokenBudgetExceeded = true;
          void state?.session.abort();
        }
      }
      if (event.type === "tool_execution_end" && !event.isError) {
        completedToolNames.add(event.toolName);
        runState.successfulToolCalls += 1;
      }
    });
    emit({
      type: "session.ready",
      request_id: request.request_id,
      session_id: request.session_id,
      session_file: state.session.sessionFile || "",
      resumed: resolved.resumed,
    });
    emit({
      type: "run.ready",
      request_id: request.request_id,
      session_id: request.session_id,
      task_contract: {
        contract_id: runState.taskContract.contractId,
        autonomy: runState.taskContract.autonomy,
        risk_level: runState.taskContract.riskLevel,
        task_profile: runState.taskContract.taskProfile,
        required_tool_groups: runState.taskContract.requiredToolGroups.map((group) => [...group]),
        initial_tool_budget: runState.taskContract.initialToolBudget,
        max_tool_budget: runState.taskContract.maxToolBudget,
        model_token_budget: runState.taskContract.modelTokenBudget,
      },
      prefix_shape: state.prefixShape,
      context_policy: request.context_policy || {},
    });
    try {
      const cleanup = pruneStaleToolResults(state);
      if (Number(cleanup.pruned_tool_results || 0) > 0) {
        emit({ type: "status.update", request_id: request.request_id, status: "context_pruned", name: "stale_tool_results", details: cleanup });
      }
      try {
        await state.session.prompt(request.prompt);
      } catch (error) {
        if (runState.modelTokenBudgetExceeded) {
          throw new Error(
            `Model-token budget exhausted after ${runState.modelTokens} tokens ` +
            `(limit ${runState.modelTokenBudget}).`,
          );
        }
        throw error;
      }
      if (runState.modelTokenBudgetExceeded) {
        throw new Error(
          `Model-token budget exhausted after ${runState.modelTokens} tokens ` +
          `(limit ${runState.modelTokenBudget}).`,
        );
      }
      let previousProgressSignature: string | undefined;
      let stalledRecoveries = 0;
      for (
        let continuation = 0;
        continuation < runState.taskContract.recoveryBudget;
        continuation += 1
      ) {
        const currentText = String(state.session.getLastAssistantText() || "");
        const currentError = String(state.session.agent.state.errorMessage || "").trim();
        if (currentError) throw new Error(currentError);
        const missingToolGroups = runState.taskContract.requiredToolGroups
          .filter((group) => [...group].every((name) => !completedToolNames.has(name)));
        const requiredToolMissing = missingToolGroups.length > 0;
        if (!looksLikeDeferredAnswer(currentText) && !requiredToolMissing) break;
        const progressSignature = [
          [...completedToolNames].sort().join("|"),
          String(runState.successfulToolCalls),
        ].join(":");
        if (previousProgressSignature !== undefined && progressSignature === previousProgressSignature) {
          stalledRecoveries += 1;
        } else {
          stalledRecoveries = 0;
        }
        previousProgressSignature = progressSignature;
        if (stalledRecoveries >= 2) {
          throw new Error(
            "No progress after a strategy switch. Preserve completed results and request one material user choice or branch the task.",
          );
        }
        if (!currentText.trim() && !thinkingReduced && state.session.supportsThinking()) {
          state.session.setThinkingLevel("off");
          thinkingReduced = true;
          emit({
            type: "status.update",
            request_id: request.request_id,
            status: "thinking_reduced",
            name: "empty_reasoning_recovery",
            attempt: continuation + 1,
          });
        }
        emit({
          type: "status.update",
          request_id: request.request_id,
          status: "continuing",
          name: stalledRecoveries > 0
            ? "strategy_switch"
            : requiredToolMissing ? "required_tool" : "incomplete_answer",
          attempt: continuation + 1,
        });
        const cleanup = pruneStaleToolResults(state);
        if (Number(cleanup.pruned_tool_results || 0) > 0) {
          emit({ type: "status.update", request_id: request.request_id, status: "context_pruned", name: "stale_tool_results", details: cleanup });
        }
        const strategyInstruction = stalledRecoveries > 0
          ? "The previous route made no progress. Do NOT repeat a tool with equivalent arguments. Switch source, narrow the query, change parameters, or use another permitted tool while preserving completed results. "
          : "";
        await state.session.prompt(
          requiredToolMissing
            ? `${strategyInstruction}Your previous response did not execute every required action. Call tools that satisfy these missing groups now: ${missingToolGroups.map((group) => [...group].join(" OR ")).join(" AND ")}. Inspect their real results and then provide the user's final answer. Do not repeat a plan, print pseudo tool JSON, or ask the user to wait.`
            : `${strategyInstruction}Your previous response was only an execution plan or waiting notice. Continue the task now using the available tools and return the completed final result. Do not repeat setup instructions or ask the user to wait.`,
        );
        if (runState.modelTokenBudgetExceeded) {
          throw new Error(
            `Model-token budget exhausted after ${runState.modelTokens} tokens ` +
            `(limit ${runState.modelTokenBudget}).`,
          );
        }
      }
    } finally {
      unsubscribeRetry();
    }
    if (runState.cancelled) {
      emit({ type: "run.cancelled", request_id: request.request_id, session_id: request.session_id });
      return;
    }
    const finalText = String(state.session.getLastAssistantText() || "");
    const finalError = String(state.session.agent.state.errorMessage || lastRetryError || "").trim();
    if (!finalText.trim()) throw new Error(finalError || "Pi model returned an empty response");
    if (looksLikeDeferredAnswer(finalText)) throw new Error("Pi stopped at an execution plan instead of returning a final result");
    const missingFinalGroups = runState.taskContract.requiredToolGroups
      .filter((group) => [...group].every((name) => !completedToolNames.has(name)));
    if (missingFinalGroups.length > 0) {
      throw new Error(
        `Pi did not execute required tools: ${missingFinalGroups.map((group) => [...group].join(" OR ")).join(" AND ")}`,
      );
    }
    emit({
      type: "run.completed",
      request_id: request.request_id,
      session_id: request.session_id,
      text: finalText,
      stats: sessionStats(state),
      control: {
        contract_id: runState.taskContract.contractId,
        task_profile: runState.taskContract.taskProfile,
        tool_calls: runState.toolCalls,
        tool_call_budget: runState.toolCallBudget,
        max_tool_call_budget: runState.maxToolCallBudget,
        successful_tool_calls: runState.successfulToolCalls,
      },
    });
  } catch (error) {
    if (runState.cancelled) {
      emit({ type: "run.cancelled", request_id: request.request_id, session_id: request.session_id });
    } else {
      const effectiveError = runState.modelTokenBudgetExceeded
        ? new Error(
            `Model-token budget exhausted after ${runState.modelTokens} tokens ` +
            `(limit ${runState.modelTokenBudget}).`,
          )
        : error;
      const failure = classifyError(effectiveError);
      emit({
        type: "run.failed",
        request_id: request.request_id,
        session_id: request.session_id,
        error: String(failure.message || errorText(effectiveError)),
        failure,
      });
    }
  } finally {
    if (state) {
      if (thinkingReduced && originalThinkingLevel) state.session.setThinkingLevel(originalThinkingLevel);
      state.currentRequestId = undefined;
    }
  }
}

async function cancelRun(message: JsonRecord): Promise<void> {
  const requestId = String(message.request_id || "");
  const activeRun = activeRuns.get(requestId);
  if (!activeRun) {
    emit({ type: "run.cancel_rejected", request_id: requestId, error: "Run is not active" });
    return;
  }
  activeRun.cancelled = true;
  for (const [callId, pending] of pendingTools) {
    if (pending.requestId === requestId) {
      pendingTools.delete(callId);
      pending.reject(new Error("Run cancelled"));
    }
  }
  for (const [interactionId, pending] of pendingInteractions) {
    if (pending.requestId === requestId) {
      pendingInteractions.delete(interactionId);
      pending.reject(new Error("Run cancelled"));
    }
  }
  const state = sessions.get(activeRun.sessionId);
  await state?.session.abort();
  emit({ type: "run.cancel_ack", request_id: requestId, session_id: activeRun.sessionId });
}

async function steerRun(message: JsonRecord): Promise<void> {
  const requestId = String(message.request_id || "");
  const activeRun = activeRuns.get(requestId);
  if (!activeRun) {
    emit({ type: "run.steer_rejected", request_id: requestId, error: "Run is not active" });
    return;
  }
  const state = sessions.get(activeRun.sessionId);
  if (!state) throw new Error("Active session is unavailable");
  await state.session.steer(String(message.text || ""));
  emit({ type: "run.steer_ack", request_id: requestId, session_id: activeRun.sessionId });
}

async function followUpRun(message: JsonRecord): Promise<void> {
  const requestId = String(message.request_id || "");
  const activeRun = activeRuns.get(requestId);
  if (!activeRun) {
    emit({ type: "run.follow_up_rejected", request_id: requestId, error: "Run is not active" });
    return;
  }
  const state = sessions.get(activeRun.sessionId);
  if (!state) throw new Error("Active session is unavailable");
  const text = String(message.text || "").trim();
  if (!text) throw new Error("Follow-up text is required");
  await state.session.followUp(text);
  emit({
    type: "run.follow_up_ack",
    request_id: requestId,
    session_id: activeRun.sessionId,
    queued: state.session.pendingMessageCount,
  });
}

function resolveInteraction(message: JsonRecord): void {
  const interactionId = String(message.interaction_id || "");
  const pending = pendingInteractions.get(interactionId);
  if (!pending) {
    emit({
      type: "interaction.response_rejected",
      interaction_id: interactionId,
      request_id: String(message.request_id || ""),
      error: "Interaction is no longer pending",
    });
    return;
  }
  const requestId = String(message.request_id || pending.requestId);
  if (requestId !== pending.requestId) {
    emit({
      type: "interaction.response_rejected",
      interaction_id: interactionId,
      request_id: requestId,
      error: "Interaction belongs to another run",
    });
    return;
  }
  pendingInteractions.delete(interactionId);
  const response = message.response && typeof message.response === "object"
    ? message.response as JsonRecord
    : { value: message.response };
  pending.resolve(response);
  emit({
    type: "interaction.resolved",
    interaction_id: interactionId,
    request_id: pending.requestId,
    session_id: pending.sessionId,
    interaction_kind: pending.kind,
  });
}

function listActiveRuns(message: JsonRecord): void {
  emit({
    type: "runtime.active_runs",
    command_id: String(message.command_id || ""),
    runs: [...activeRuns.values()].map((item) => ({
      request_id: item.requestId,
      session_id: item.sessionId,
      background: item.background,
      cancelled: item.cancelled,
      started_at: new Date(item.startedAt).toISOString(),
      pending_interactions: [...pendingInteractions.values()]
        .filter((pending) => pending.requestId === item.requestId).length,
    })),
  });
}

async function compactSession(message: JsonRecord): Promise<void> {
  const sessionId = String(message.session_id || "");
  const commandId = String(message.command_id || "");
  const state = sessions.get(sessionId);
  if (!state) {
    emit({ type: "session.compact_failed", command_id: commandId, session_id: sessionId, error: "Session is not loaded" });
    return;
  }
  try {
    const cleanup = pruneStaleToolResults(state);
    const result = await state.session.compact(String(message.instructions || "") || undefined);
    emit({ type: "session.compact_completed", command_id: commandId, session_id: sessionId, result, stats: { ...sessionStats(state), contextCleanup: cleanup } });
  } catch (error) {
    emit({ type: "session.compact_failed", command_id: commandId, session_id: sessionId, error: errorText(error) });
  }
}

async function loadSession(message: JsonRecord): Promise<void> {
  const sessionId = String(message.session_id || "");
  const commandId = String(message.command_id || "");
  const sessionFile = String(message.session_file || "");
  if (!sessionId || !sessionFile) {
    emit({ type: "session.load_failed", command_id: commandId, session_id: sessionId, error: "Session file is unavailable" });
    return;
  }
  try {
    const request = {
      type: "run.start",
      request_id: `load-${commandId}`,
      session_id: sessionId,
      session_file: sessionFile,
      cwd: String(message.cwd || process.cwd()),
      agent_dir: String(message.agent_dir || process.cwd()),
      provider_kind: String(message.provider_kind || "openai-compatible"),
      base_url: String(message.base_url || ""),
      model_id: String(message.model_id || ""),
      api_surface: String(message.api_surface || "chat_completions"),
      responses_enabled: message.responses_enabled === true,
      thinking_level: String(message.thinking_level || "medium"),
      system_prompt: "",
      prompt: "",
      task_mode: "general",
      mcp_servers: Array.isArray(message.mcp_servers) ? message.mcp_servers as JsonRecord[] : [],
      disabled_tools: Array.isArray(message.disabled_tools) ? message.disabled_tools.map(String) : [],
    } satisfies RunStart;
    const resolved = await getSession(request);
    emit({ type: "session.loaded", command_id: commandId, session_id: sessionId, session_file: resolved.state.session.sessionFile || "", resumed: resolved.resumed, stats: sessionStats(resolved.state) });
  } catch (error) {
    emit({ type: "session.load_failed", command_id: commandId, session_id: sessionId, error: errorText(error) });
  }
}

async function closeSession(message: JsonRecord): Promise<void> {
  const sessionId = String(message.session_id || "");
  if (activeSessionRequests.has(sessionId)) {
    emit({
      type: "session.close_rejected",
      session_id: sessionId,
      request_id: activeSessionRequests.get(sessionId) || "",
      error: "Session has an active run",
    });
    return;
  }
  const state = sessions.get(sessionId);
  if (state) {
    state.unsubscribe();
    state.session.dispose();
    await Promise.all(state.mcpClients.map((client) => client.close().catch(() => undefined)));
    sessions.delete(sessionId);
  }
  emit({ type: "session.closed", session_id: sessionId });
}

async function forkSession(message: JsonRecord): Promise<void> {
  const sourceSessionId = String(message.source_session_id || "");
  const targetSessionId = String(message.target_session_id || crypto.randomUUID());
  const commandId = String(message.command_id || "");
  const source = sessions.get(sourceSessionId);
  if (!source || !source.session.sessionFile) {
    emit({
      type: "session.fork_failed",
      command_id: commandId,
      source_session_id: sourceSessionId,
      target_session_id: targetSessionId,
      error: "Source session is not loaded or has no durable file",
    });
    return;
  }
  if (sessions.has(targetSessionId) || activeSessionRequests.has(targetSessionId)) {
    emit({
      type: "session.fork_failed",
      command_id: commandId,
      source_session_id: sourceSessionId,
      target_session_id: targetSessionId,
      error: "Target session already exists",
    });
    return;
  }
  try {
    const request: RunStart = {
      ...source.request,
      request_id: `fork-${commandId || crypto.randomUUID()}`,
      session_id: targetSessionId,
      session_file: "",
      prompt: "",
      background: false,
    };
    const sessionDir = `${request.agent_dir}/sessions`;
    fs.mkdirSync(sessionDir, { recursive: true });
    const manager = SessionManager.forkFrom(
      source.session.sessionFile,
      request.cwd,
      sessionDir,
      { id: targetSessionId },
    );
    const state = await createSession(request, manager);
    sessions.set(targetSessionId, state);
    emit({
      type: "session.forked",
      command_id: commandId,
      source_session_id: sourceSessionId,
      target_session_id: targetSessionId,
      session_file: state.session.sessionFile || "",
      stats: sessionStats(state),
    });
  } catch (error) {
    const failure = classifyError(error);
    emit({
      type: "session.fork_failed",
      command_id: commandId,
      source_session_id: sourceSessionId,
      target_session_id: targetSessionId,
      error: String(failure.message || errorText(error)),
      failure,
    });
  }
}

async function probeMcp(message: JsonRecord): Promise<void> {
  const requestId = String(message.request_id || crypto.randomUUID());
  const request = {
    type: "run.start",
    request_id: requestId,
    session_id: `mcp-probe-${requestId}`,
    cwd: String(message.cwd || process.cwd()),
    agent_dir: String(message.agent_dir || process.cwd()),
    provider_kind: "openai",
    base_url: "http://127.0.0.1",
    model_id: "mcp-probe",
    system_prompt: "",
    prompt: "",
    // A normal connection test must exercise the real server even when a
    // production session is configured for deferred activation.  Diagnostics
    // can explicitly inspect the deferred proxy surface without connecting.
    mcp_servers: Array.isArray(message.mcp_servers)
      ? (message.mcp_servers as JsonRecord[]).map((server) => ({
        ...server,
        deferred: message.activation_mode === "deferred" ? server.deferred === true : false,
      }))
      : [],
  } satisfies RunStart;
  const connected = await externalMcpTools(request);
  try {
    emit({
      type: "mcp.probe.completed",
      request_id: requestId,
      server_count: connected.clients.length,
      tool_count: connected.tools.length,
      tools: connected.tools.map((tool) => ({ name: tool.name, label: tool.label })),
    });
  } finally {
    await Promise.all(connected.clients.map((client) => client.close().catch(() => undefined)));
  }
}

async function shutdown(): Promise<void> {
  for (const runState of activeRuns.values()) {
    runState.cancelled = true;
    await sessions.get(runState.sessionId)?.session.abort().catch(() => undefined);
  }
  for (const pending of pendingInteractions.values()) pending.reject(new Error("Runtime shutting down"));
  pendingInteractions.clear();
  for (const state of sessions.values()) {
    state.unsubscribe();
    state.session.dispose();
    await Promise.all(state.mcpClients.map((client) => client.close().catch(() => undefined)));
  }
  sessions.clear();
  emit({ type: "runtime.shutdown_ack" });
  process.exit(0);
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", (line) => {
  let message: JsonRecord;
  try {
    message = JSON.parse(line) as JsonRecord;
  } catch {
    emit({ type: "protocol.error", error: "Invalid JSON input" });
    return;
  }
  if (message.type === "ping") {
    emit({
      type: "pong",
      runtime: "pi",
      version: "0.80.10",
      protocol: 3,
      capabilities: [
        "multi_session",
        "task_contracts",
        "bounded_autonomy",
        "ask_user",
        "plan_approval",
        "follow_up",
        "structured_recovery",
        "session_fork",
      ],
    });
  } else if (message.type === "tool.result") {
    const callId = String(message.call_id || "");
    const pending = pendingTools.get(callId);
    if (!pending) return;
    pendingTools.delete(callId);
    if (message.ok === false) pending.reject(new Error(String(message.error || "Tool failed")));
    else pending.resolve((message.result || {}) as JsonRecord);
  } else if (message.type === "interaction.response") {
    resolveInteraction(message);
  } else if (message.type === "run.start") {
    void run(message as RunStart);
  } else if (message.type === "mcp.probe") {
    void probeMcp(message).catch((error) => emit({
      type: "mcp.probe.failed",
      request_id: String(message.request_id || ""),
      error: errorText(error),
    }));
  } else if (message.type === "run.cancel") {
    void cancelRun(message).catch((error) => emit({ type: "protocol.error", error: errorText(error) }));
  } else if (message.type === "run.steer") {
    void steerRun(message).catch((error) => emit({ type: "protocol.error", error: errorText(error) }));
  } else if (message.type === "run.follow_up") {
    void followUpRun(message).catch((error) => emit({ type: "protocol.error", error: errorText(error) }));
  } else if (message.type === "runtime.list_active_runs") {
    listActiveRuns(message);
  } else if (message.type === "session.compact") {
    void compactSession(message);
  } else if (message.type === "session.load") {
    void loadSession(message);
  } else if (message.type === "session.close") {
    void closeSession(message).catch((error) => emit({ type: "protocol.error", error: errorText(error) }));
  } else if (message.type === "session.fork") {
    void forkSession(message).catch((error) => emit({ type: "protocol.error", error: errorText(error) }));
  } else if (message.type === "runtime.shutdown") {
    void shutdown().catch((error) => emit({ type: "protocol.error", error: errorText(error) }));
  } else {
    emit({ type: "protocol.error", error: `Unsupported message type: ${String(message.type || "")}` });
  }
});

process.on("SIGTERM", shutdown);
