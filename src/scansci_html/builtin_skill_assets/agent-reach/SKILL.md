---
name: agent-reach
description: Use ScanSci's built-in, read-only internet channel router for public pages, feeds, GitHub, Bilibili, V2EX, and permitted fallback readers.
---

# Agent Reach in ScanSci

Use the built-in `agent_reach` tool when the user asks to read or search a
public internet source outside the local evidence library.

## Routing contract

- Use `operation=status` to inspect channel readiness when the user asks what
  is available or a route has failed.
- Use `operation=read` with the complete public URL for a page, feed, GitHub
  repository/issue, or video page.
- Use `operation=search` with a focused query. Set `channel` to `github`,
  `bilibili`, `v2ex`, `youtube`, or another named channel when the user names
  a platform; otherwise use `auto` or `web`.
- Treat search results as discovery leads. Treat page/JSON/RSS content as the
  retrieved source, and preserve the returned URL and backend in the answer.
- Keep the boundary with `web-access` explicit: use `browser_access` when a
  public reader returns an anti-bot page, a login wall, incomplete dynamic
  content, or when the user asks for browser-context access.
- Do not claim that a login, browser interaction, cookie, subtitle download,
  or external CLI was used unless the tool result explicitly reports it.
- Do not ask the user to install Agent-Reach. ScanSci already ships this
  capability; optional tools are only enhancements reported by `status`.

## Safety

The built-in route is read-only, accepts public HTTP(S) URLs only, does not
inject cookies, and does not run arbitrary shell commands. If a platform
requires authentication or returns an anti-bot page, use the separate
read-only `browser_access` bridge when it is available; otherwise report that
boundary and offer the returned public fallback or ask the user to provide an
authorized source.
