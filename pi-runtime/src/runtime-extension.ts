import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { searchToolCatalog, type ToolCatalogEntry } from "./tool-catalog.js";

type JsonRecord = Record<string, unknown>;

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
