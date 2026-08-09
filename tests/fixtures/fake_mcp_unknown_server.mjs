import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({ name: "scansci-test-mcp-unknown", version: "1.0.0" });
server.registerTool(
  "lookup",
  { description: "A tool whose effect metadata is intentionally absent" },
  async () => ({ content: [{ type: "text", text: "unknown" }] }),
);
await server.connect(new StdioServerTransport());
