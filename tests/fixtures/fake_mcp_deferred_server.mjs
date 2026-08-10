import fs from "node:fs";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const marker = process.argv[2] || "";
const mode = process.argv[3] || "ok";
if (marker) fs.appendFileSync(marker, "connected\n", "utf8");

const server = new McpServer({ name: "scansci-deferred-mcp", version: "1.0.0" });
server.registerTool(
  "search_library",
  {
    description: "Search the deferred fixture library using its native schema",
    inputSchema: {},
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  async () => {
    if (marker) fs.appendFileSync(marker, "called\n", "utf8");
    if (mode === "disconnect-once") {
      const calls = fs.readFileSync(marker, "utf8").split(/\r?\n/).filter((line) => line === "called").length;
      if (calls === 1) process.exit(23);
    }
    if (mode === "timeout-once") {
      const calls = fs.readFileSync(marker, "utf8").split(/\r?\n/).filter((line) => line === "called").length;
      if (calls === 1) await new Promise((resolve) => setTimeout(resolve, 2_000));
    }
    if (mode === "is-error") {
      return { isError: true, content: [{ type: "text", text: "fixture failure" }] };
    }
    return { content: [{ type: "text", text: "native deferred result" }] };
  },
);
await server.connect(new StdioServerTransport());
