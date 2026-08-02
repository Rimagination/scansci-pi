import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({ name: "scansci-test-mcp", version: "1.0.0" });
server.tool("search_library", "Search a fixture library", async () => ({
  content: [{ type: "text", text: "fixture result" }],
}));
server.tool("create_note", "Create a fixture note", async () => ({
  content: [{ type: "text", text: "created" }],
}));
await server.connect(new StdioServerTransport());
