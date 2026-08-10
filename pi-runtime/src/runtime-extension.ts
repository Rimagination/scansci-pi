import {
  defineTool,
  type BeforeAgentStartEvent,
  type BeforeAgentStartEventResult,
  type BeforeProviderRequestEvent,
  type ContextEvent,
  type ContextEventResult,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { searchToolCatalog, type ToolCatalogEntry } from "./tool-catalog.js";

type JsonRecord = Record<string, unknown>;

export interface ContextViewResult {
  messages: ContextEvent["messages"];
  report?: JsonRecord;
}

export function buildNonDestructiveContextView(
  messages: ContextEvent["messages"],
  keepRecentTurns = 2,
): ContextViewResult {
  const output = structuredClone(messages);
  let currentTurn = 0;
  const locations: Array<{ index: number; turn: number }> = [];
  for (let index = 0; index < output.length; index += 1) {
    const message = output[index] as unknown as JsonRecord;
    const role = String(message.role || "").toLowerCase();
    if (role === "user") currentTurn += 1;
    if (["tool", "toolresult", "tool_result"].includes(role)) locations.push({ index, turn: currentTurn });
  }
  let pruned = 0;
  let originalChars = 0;
  let retainedChars = 0;
  for (const location of locations) {
    const message = output[location.index] as unknown as JsonRecord;
    const encoded = JSON.stringify(message.content ?? "");
    const size = encoded.length;
    originalChars += size;
    if (currentTurn - location.turn >= Math.max(1, keepRecentTurns)) {
      const notice = {
        _scansci_pruned: true,
        tool: String(message.toolName || message.tool_name || message.name || "tool").slice(0, 80),
        original_chars: size,
        notice: "Stale tool output was pruned in the provider context view; rerun a focused tool if needed.",
      };
      message.content = [{ type: "text", text: JSON.stringify(notice) }];
      message._scansci_context_pruned = true;
      pruned += 1;
    }
    retainedChars += JSON.stringify(message.content ?? "").length;
  }
  return {
    messages: output,
    report: {
      policy: "non_destructive_stale_tool_result_view",
      examined_tool_results: locations.length,
      pruned_tool_results: pruned,
      preserved_tool_results: Math.max(0, locations.length - pruned),
      original_chars: originalChars,
      retained_chars: retainedChars,
      saved_chars: Math.max(0, originalChars - retainedChars),
    },
  };
}

export interface RuntimeLifecycleOptions {
  current: () => { request_id?: unknown; session_id?: unknown };
  emit: (payload: JsonRecord) => void;
  beforeAgentStart?: (event: BeforeAgentStartEvent) => BeforeAgentStartEventResult | void;
  context?: (event: ContextEvent) => ContextViewResult | ContextEventResult | void;
  beforeProviderRequest?: (event: BeforeProviderRequestEvent) => unknown;
  onContextReport?: (report: JsonRecord) => void;
}

/**
 * Register authority-neutral lifecycle hooks with bounded audit telemetry.
 *
 * Pi intentionally treats most extension failures as fail-open.  These hooks
 * therefore never grant authority: the Node lease check and Python host
 * reauthorization remain the only execution gates.
 */
export function registerRuntimeLifecycleHooks(
  pi: ExtensionAPI,
  options: RuntimeLifecycleOptions,
): void {
  let sequence = 0;
  const audit = (
    name: string,
    startedAt: number,
    decision: "observed" | "projected" | "failed" = "observed",
    details: JsonRecord = {},
  ): void => {
    try {
      const current = options.current();
      options.emit({
        type: "status.update",
        request_id: String(current.request_id || ""),
        session_id: String(current.session_id || ""),
        status: "hook",
        name,
        duration_ms: Math.max(0, Date.now() - startedAt),
        details: {
          sequence: ++sequence,
          decision,
          ...details,
        },
      });
    } catch {
      // Telemetry must never change model behavior or broaden authority.
    }
  };

  pi.on("before_agent_start", (event) => {
    const startedAt = Date.now();
    try {
      const result = options.beforeAgentStart?.(event);
      audit("before_agent_start", startedAt, result ? "projected" : "observed", {
        image_count: Array.isArray(event.images) ? event.images.length : 0,
      });
      return result;
    } catch {
      audit("before_agent_start", startedAt, "failed");
      return undefined;
    }
  });
  pi.on("context", (event) => {
    const startedAt = Date.now();
    try {
      const result = options.context?.(event);
      const report = result && "report" in result && result.report && typeof result.report === "object"
        ? result.report as JsonRecord
        : {};
      let reportTelemetryFailed = false;
      try {
        options.onContextReport?.(report);
      } catch {
        reportTelemetryFailed = true;
      }
      audit("context", startedAt, result ? "projected" : "observed", {
        message_count: event.messages.length,
        pruned_tool_results: Number(report.pruned_tool_results || 0),
        report_telemetry_failed: reportTelemetryFailed,
      });
      return result ? { messages: result.messages } : undefined;
    } catch {
      audit("context", startedAt, "failed", { message_count: event.messages.length });
      return undefined;
    }
  });
  pi.on("before_provider_request", (event) => {
    const startedAt = Date.now();
    try {
      const result = options.beforeProviderRequest?.(event);
      audit("before_provider_request", startedAt, result === undefined ? "observed" : "projected", {
        payload_kind: Array.isArray(event.payload) ? "array" : typeof event.payload,
      });
      return result;
    } catch {
      // Pi's runner is fail-open here as well.  Make that outcome explicit;
      // hard request limits must live below this hook (Task 5).
      audit("before_provider_request", startedAt, "failed");
      return undefined;
    }
  });
  pi.on("after_provider_response", (event) => {
    const startedAt = Date.now();
    audit("after_provider_response", startedAt, "observed", { status_code: Number(event.status || 0) });
  });
  pi.on("tool_call", (event) => {
    const startedAt = Date.now();
    audit("tool_call", startedAt, "observed", { tool_name: String(event.toolName || "").slice(0, 120) });
  });
  pi.on("tool_result", (event) => {
    const startedAt = Date.now();
    audit("tool_result", startedAt, "observed", {
      tool_name: String(event.toolName || "").slice(0, 120),
      is_error: event.isError === true,
      content_blocks: Array.isArray(event.content) ? event.content.length : 0,
    });
  });
  pi.on("agent_settled", () => {
    const startedAt = Date.now();
    audit("settled", startedAt);
  });
}

interface DynamicSession {
  getActiveToolNames(): string[];
  setActiveToolsByName(names: string[]): void;
}

export interface DynamicToolRuntimeOptions {
  catalog: ToolCatalogEntry[];
  getSession: () => DynamicSession | undefined;
  isAuthorized: (name: string) => boolean;
  onActivation?: (activeNames: string[], activatedNames: string[]) => void;
  emit?: (payload: JsonRecord) => void;
  requestId?: () => string;
}

export function createSearchToolsTool(options: DynamicToolRuntimeOptions) {
  return defineTool({
    name: "search_tools",
    label: "Search authorized tools",
    description: "Search the current ScanSci capability lease by tool name, label, description, aliases, tags, group, risk, or availability. Matching authorized tools can be additively activated for the next model turn. This loader never expands the host lease.",
    executionMode: "sequential",
    parameters: Type.Object({
      query: Type.Optional(Type.String({ maxLength: 500 })),
      names: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 160 }), { maxItems: 20 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      activate: Type.Optional(Type.Boolean({ default: true })),
    }),
    execute: async (_toolCallId, params) => {
      const session = options.getSession();
      if (!session) throw new Error("Dynamic tool session is not ready");
      const before = session.getActiveToolNames();
      const result = searchToolCatalog(options.catalog, {
        query: params.query,
        names: params.names,
        limit: params.limit,
        activeNames: before,
        isAuthorized: options.isAuthorized,
      });
      const shouldActivate = params.activate !== false;
      const selected = shouldActivate
        ? result.matches.map((match) => match.name).filter((name) => options.isAuthorized(name))
        : [];
      const next = [...new Set([...before, ...selected])]
        .filter((name) => name === "search_tools" || options.isAuthorized(name) || ["ask_user", "submit_plan"].includes(name))
        .sort();
      const activated = next.filter((name) => !before.includes(name));
      if (activated.length) session.setActiveToolsByName(next);
      options.onActivation?.(next, activated);
      options.emit?.({
        type: "status.update",
        request_id: options.requestId?.() || "",
        status: "tool_catalog_searched",
        name: "search_tools",
        details: {
          query: String(params.query || "").slice(0, 200),
          match_count: result.matches.length,
          activated,
          active_tool_count: next.length,
          rejected: result.rejected,
        },
      });
      const payload = {
        schema_version: "scansci.tool-search.v1",
        query: String(params.query || ""),
        matches: result.matches.map((match) => ({ ...match, active: next.includes(match.name) })),
        activated,
        rejected: result.rejected,
        active_tools: next,
      };
      return {
        content: [{ type: "text" as const, text: JSON.stringify(payload) }],
        details: payload,
      };
    },
  });
}
