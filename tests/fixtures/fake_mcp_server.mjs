import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({ name: "scansci-test-mcp", version: "1.0.0" });
server.registerTool(
  "search_library",
  {
    description: "Search a fixture library",
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  async () => ({ content: [{ type: "text", text: "fixture result" }] }),
);
server.registerTool(
  "create_note",
  {
    description: "Create a fixture note",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  },
  async () => ({ content: [{ type: "text", text: "created" }] }),
);
server.registerTool(
  "notes.put",
  {
    description: "Write a note through a dotted remote tool id",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  },
  async () => ({ content: [{ type: "text", text: "dotted write executed" }] }),
);
await server.connect(new StdioServerTransport());
