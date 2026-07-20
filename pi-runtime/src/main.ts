import * as readline from "node:readline";
import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type JsonRecord = Record<string, unknown>;

interface RunStart extends JsonRecord {
  type: "run.start";
  request_id: string;
  cwd: string;
  agent_dir: string;
  provider_kind: string;
  base_url: string;
  model_id: string;
  thinking_level?: string;
  system_prompt: string;
  prompt: string;
  task_mode?: string;
}

interface PendingTool {
  resolve: (value: JsonRecord) => void;
  reject: (reason: Error) => void;
}

const pendingTools = new Map<string, PendingTool>();
let activeRun = false;

function emit(payload: JsonRecord): void {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

function providerApi(kind: string): "anthropic-messages" | "openai-completions" {
  return kind === "anthropic" || kind === "anthropic-compatible"
    ? "anthropic-messages"
    : "openai-completions";
}

function thinkingLevel(value: unknown): "off" | "minimal" | "low" | "medium" | "high" | "xhigh" {
  const normalized = String(value || "medium").toLowerCase();
  if (["off", "minimal", "low", "medium", "high", "xhigh"].includes(normalized)) {
    return normalized as "off" | "minimal" | "low" | "medium" | "high" | "xhigh";
  }
  return "medium";
}

async function callPythonTool(name: string, args: JsonRecord): Promise<JsonRecord> {
  const callId = crypto.randomUUID();
  emit({ type: "tool.call", call_id: callId, name, arguments: args });
  return new Promise<JsonRecord>((resolve, reject) => {
    pendingTools.set(callId, { resolve, reject });
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
      const result = await callPythonTool(name, params as JsonRecord);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result) }],
        details: result,
      };
    },
  });
}

function tools() {
  return [
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
      "search_local_evidence",
      "Search local evidence",
      "Search sentence-level evidence in the active ScanSci notebook. Use before making source-grounded scientific claims.",
      Type.Object({
        query: Type.String({ description: "Focused evidence search query" }),
        result_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
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
      "Find related papers through ScanSci Paper Atlas. Results are discovery leads, not verified evidence.",
      Type.Object({ query: Type.String() }),
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
  ];
}

function systemPrompt(request: RunStart): string {
  const evidenceRule = request.task_mode === "knowledge"
    ? "This is knowledge mode. For claims about imported literature, you MUST call build_verified_answer before the final response. If evidence is missing, state the gap instead of guessing."
    : "Use ScanSci tools when they materially improve the answer. Never claim a tool action happened unless the tool returned success.";
  return `${request.system_prompt}\n\nYou are running inside ScanSci Pi. Plan and execute the smallest useful tool sequence. ${evidenceRule}\nBuilt-in shell and filesystem mutation tools are disabled.`;
}

async function run(request: RunStart): Promise<void> {
  if (activeRun) {
    emit({ type: "run.failed", request_id: request.request_id, error: "A run is already active" });
    return;
  }
  activeRun = true;
  const apiKey = process.env.SCANSCIPI_PROVIDER_KEY || "";
  if (!apiKey) {
    emit({ type: "run.failed", request_id: request.request_id, error: "Provider API key is unavailable" });
    activeRun = false;
    return;
  }

  let session: Awaited<ReturnType<typeof createAgentSession>>["session"] | undefined;
  try {
    const runtime = await ModelRuntime.create({ allowModelNetwork: false, modelsPath: null });
    runtime.registerProvider("scansci-pi", {
      name: "ScanSci Pi provider",
      baseUrl: request.base_url,
      apiKey: "$SCANSCIPI_PROVIDER_KEY",
      api: providerApi(request.provider_kind),
      models: [{
        id: request.model_id,
        name: request.model_id,
        reasoning: thinkingLevel(request.thinking_level) !== "off",
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 16384,
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
    });
    await loader.reload();
    const created = await createAgentSession({
      cwd: request.cwd,
      agentDir: request.agent_dir,
      modelRuntime: runtime,
      model,
      thinkingLevel: thinkingLevel(request.thinking_level),
      noTools: "builtin",
      customTools: tools(),
      resourceLoader: loader,
      sessionManager: SessionManager.inMemory(request.cwd),
    });
    session = created.session;
    session.subscribe((event) => {
      if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
        emit({ type: "message.delta", request_id: request.request_id, delta: event.assistantMessageEvent.delta });
      } else if (event.type === "tool_execution_start") {
        emit({ type: "status.update", request_id: request.request_id, status: "tool_started", name: event.toolName });
      } else if (event.type === "tool_execution_end") {
        emit({ type: "status.update", request_id: request.request_id, status: event.isError ? "tool_failed" : "tool_completed", name: event.toolName });
      } else if (event.type === "auto_retry_start") {
        emit({ type: "status.update", request_id: request.request_id, status: "retry", attempt: event.attempt, delay_ms: event.delayMs });
      }
    });
    emit({ type: "run.ready", request_id: request.request_id });
    await session.prompt(request.prompt);
    emit({
      type: "run.completed",
      request_id: request.request_id,
      text: session.getLastAssistantText(),
      stats: session.getSessionStats(),
    });
  } catch (error) {
    emit({ type: "run.failed", request_id: request.request_id, error: errorText(error) });
  } finally {
    session?.dispose();
    activeRun = false;
  }
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
    emit({ type: "pong", runtime: "pi", version: "0.80.10" });
    return;
  }
  if (message.type === "tool.result") {
    const callId = String(message.call_id || "");
    const pending = pendingTools.get(callId);
    if (!pending) return;
    pendingTools.delete(callId);
    if (message.ok === false) pending.reject(new Error(String(message.error || "Tool failed")));
    else pending.resolve((message.result || {}) as JsonRecord);
    return;
  }
  if (message.type === "run.start") {
    void run(message as RunStart);
    return;
  }
  emit({ type: "protocol.error", error: `Unsupported message type: ${String(message.type || "")}` });
});

process.on("SIGTERM", () => process.exit(0));
