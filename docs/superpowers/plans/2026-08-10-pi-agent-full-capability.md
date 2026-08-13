# Pi Agent Full Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to execute this plan task-by-task, test-driven-development for every behavior change, and verification-before-completion before claiming completion.

**Goal:** Make every model-mediated ScanSci conversation run through Pi Agent SDK 0.80.10 with a fail-closed host contract, model-owned planning and tool/Skill/subagent selection, safe parallel execution, model-aware long context, multimodal input, deferred MCP, durable recovery, and release-gated evidence for every declared capability.

**Architecture:** Pi owns cognition and orchestration: planning, selecting and activating tools, loading Skills, decomposing work, spawning scientific subagents, replanning, and synthesis. The Python host owns authority and truth: capability inventory, risk classification, permissions, approval tokens, budgets, tool execution, evidence policy, persistence, cancellation, and audit. The Node sidecar is a versioned protocol adapter to Pi; empty or missing leases never broaden authority. All declared capabilities must be proved by deterministic tests and a capability-matrix report bound to the source and Pi bundle hashes.

**Tech Stack:** Python 3.12, pytest, TypeScript, Node.js, esbuild, `@earendil-works/pi-coding-agent` 0.80.10, MCP SDK, SQLite-backed ScanSci stores.

---

## Definition of 100%

The release is complete only when every declared axis below is both implemented end-to-end and reported as passing. “Unlimited resources,” “call every tool on every turn,” and provider features that the selected model does not support are not part of the definition. Unsupported provider capabilities must fail closed or emit an explicit degradation event; they cannot be counted as a Pi success.

1. Pi receives every model-mediated text and supported multimodal turn.
2. The model sees a compact catalog and autonomously discovers/activates authorized tools.
3. Independent read-only tool calls truly overlap end-to-end; effectful calls remain sequential.
4. Context and compaction budgets derive from the selected model, not fixed character slices.
5. Skills use progressive disclosure through catalog/search/load tools and never grant permission.
6. Pi lifecycle hooks enforce current-turn policy and emit auditable outcomes.
7. Sessions support resume, steer, follow-up, queue inspection/control, compaction, cancellation, and fork semantics without cross-request event loss.
8. The model can delegate up to three safe scientific subagents and collect/cancel them.
9. Model metadata controls reasoning, context, image input, and native deferred-tool compatibility.
10. MCP is deferred, structured, risk-aware, lease-bound, and fully audited.
11. Retries, idempotency, read coalescing, result references, and cancellation are deterministic.
12. Scientific evidence, approval, path, secret, and artifact gates stay fail-closed.
13. Every capability has trace events, golden tests, a threshold, and a release artifact.

## Non-negotiable compatibility boundaries

- Preserve the `core` / `local-transformers` / model-weight packaging split.
- Keep Pi built-in shell and unrestricted filesystem tools disabled.
- Keep full-ZIP updater fallback and existing release-stage ordering.
- Keep strict evidence distinctions between metadata, discovery snippets, and verified full text.
- Keep old contract/session/report readers for one compatibility window; write only the new schema.
- Do not persist raw secrets or unbounded base64 data in manifests and logs.

## Baseline

- Branch: `codex/pi-agent-full-capabilities`
- Worktree: `C:\\Users\\Liang\\.config\\superpowers\\worktrees\\scansci-pi\\pi-agent-full-capabilities`
- Baseline Pi bundle build: passing.
- Hermetic baseline: `1398 passed, 5 skipped` with `SCANSCI_MODEL_ROOT=F:\\Scratch\\scansci-pi-test-empty-models`.
- Use the same empty model root for full verification so workstation-installed models cannot leak into tests.

## Task 1: Unify the v4 protocol and fail-closed authority boundary

**Files:**

- Modify: `src/scansci_html/agent_contract.py`
- Modify: `src/scansci_html/task_contract.py`
- Modify: `src/scansci_html/agent_capabilities.py`
- Add: `src/scansci_html/tool_authorization.py`
- Modify: `src/scansci_html/pi_agent.py`
- Add: `pi-runtime/src/protocol.ts`
- Modify: `pi-runtime/src/main.ts`
- Add: `tests/fixtures/pi_task_contract_v2.json`
- Modify: `tests/test_agent_contract.py`
- Add/modify: `tests/test_task_contract.py`
- Modify: `tests/test_pi_agent.py`
- Modify: `tests/test_mcp_bridge.py`

**Behavior:**

- Write `scansci.task-contract.v2`; accept legacy v1 and integer-version payloads on read.
- Separate `allowed_tools` (hard permission envelope) from `initial_tools` (initial active subset).
- Preserve the distinction between an omitted lease and an explicit empty lease; both fail closed for executable tools unless a trusted compiler created an explicit read-only envelope.
- Add `pi_protocol_version=4` and required feature negotiation.
- Python must re-authorize every bridge tool call before dispatch using contract, descriptor risk, plan token, call counters, and current request ID.
- Approval is deny-by-default; only explicit `approve` creates a request-scoped token.
- Fix reused-session current-request references so hooks, system prompt, contract, date, and MCP events never capture the first turn.
- Replace MCP name heuristics with structured raw server ID, local alias, remote tool, effect, idempotency, and annotations; unknown effect is denied.

**TDD:**

1. Add red tests for explicit empty leases, spoofed `tool.call`, stale second-turn contracts, default-deny approvals, dotted/slashed MCP IDs, and deferred write attempts.
2. Run: `python -m pytest tests/test_agent_contract.py tests/test_task_contract.py tests/test_pi_agent.py tests/test_mcp_bridge.py -q` and confirm the new tests fail for the intended reasons.
3. Implement the smallest protocol/compiler/authorization changes.
4. Run the same command until green.
5. Run `npm.cmd run build:pi-runtime`.

**Commit:** `feat(pi): enforce protocol v4 capability leases`

## Task 2: Give Pi model-first routing and dynamic tool discovery

**Files:**

- Add: `pi-runtime/src/tool-catalog.ts`
- Add: `pi-runtime/src/runtime-extension.ts`
- Modify: `pi-runtime/src/main.ts`
- Modify: `src/scansci_html/agent_contract.py`
- Modify: `src/scansci_html/research_agent.py`
- Modify: `src/scansci_html/agent_capabilities.py`
- Add: `tests/test_pi_runtime_protocol.py`
- Add: `tests/test_pi_capability_matrix.py`
- Modify: `tests/test_agent_contract.py`
- Modify: `tests/test_pi_agent.py`
- Modify: `tests/test_webapp.py`

**Behavior:**

- Make Pi the route for every model-mediated turn, including ordinary conversation; deterministic host facts may remain local and must be labeled as such.
- Demote `_direct_pi_task_mode` and regex routing to risk, evidence, budget, and initial-tool hints. They may not decide the model’s research strategy.
- Register only contract-authorized definitions and initially activate bootstrap tools plus required groups.
- Provide an always-active `search_tools` loader that searches name, label, description, aliases, tags, group, risk, and availability, then additively activates selected tools through `setActiveToolsByName`.
- Search, activation, and final call all recheck the current contract. Revoked tools disappear on the next turn; an empty lease exposes no executable domain tool.
- Mark `search_tools`, `ask_user`, `submit_plan`, Skill loaders, and effectful tools sequential. Mark only explicitly thread-safe read-only tools parallel.
- Advertise registered versus active tools in prefix shape and manifests.

**TDD:**

1. Add a 40+ case Chinese/English routing matrix and dynamic-tool session tests.
2. Prove bootstrap-only initial schemas, additive activation, revocation, empty-inventory behavior, session continuity, and no silent direct fallback.
3. Run the new tests and confirm red.
4. Implement catalog/loader/routing changes.
5. Run: `python -m pytest tests/test_pi_capability_matrix.py tests/test_pi_runtime_protocol.py tests/test_agent_contract.py tests/test_pi_agent.py tests/test_webapp.py -q`.
6. Run `npm.cmd run build:pi-runtime`.

**Commit:** `feat(pi): let the model discover authorized tools`

## Task 3: Make Skills progressively loadable by the model

**Files:**

- Modify: `src/scansci_html/skill_runtime.py`
- Modify: `src/scansci_html/agent_context.py`
- Add: `src/scansci_html/agent_skill_tools.py`
- Modify: `src/scansci_html/pi_agent.py`
- Modify: `pi-runtime/src/tool-catalog.ts`
- Modify: `pi-runtime/src/main.ts`
- Modify: `tests/test_skill_runtime.py`
- Modify: `tests/test_pi_agent.py`
- Modify: `tests/test_webapp.py`

**Behavior:**

- Always provide a bounded compact catalog of enabled, installed, security-cleared Skills.
- Preload full instructions only for explicit `$skill`/payload selections; inferred candidates remain hints.
- Add `search_skills(query, limit)` and `load_skill(skill_id, resource?)` bridge tools.
- Restrict resource reads to the Skill package root, reject traversal/symlink escape, bound individual and cumulative bytes, and preserve source/hash/provenance.
- Preserve explicit/inferred/suppressed provenance through UI/runtime events.
- A loaded Skill changes instructions only; it never alters the capability lease, risk, evidence source, or authority.
- Keep selected Skill hashes stable across resume and compaction.

**TDD:**

1. Add red tests for explicit preload, inferred progressive load, catalog search, path traversal, disabled/uninstalled Skills, byte limits, provenance, lease non-expansion, and resume hashes.
2. Run `python -m pytest tests/test_skill_runtime.py tests/test_pi_agent.py tests/test_webapp.py -q` and confirm red.
3. Implement search/load and context changes.
4. Re-run until green and build the sidecar.

**Commit:** `feat(pi): add progressive skill discovery`

## Task 4: Enable real parallel tool execution, hooks, dispatch isolation, and cancellation

**Files:**

- Modify: `pi-runtime/src/runtime-extension.ts`
- Modify: `pi-runtime/src/tool-catalog.ts`
- Modify: `pi-runtime/src/main.ts`
- Modify: `src/scansci_html/pi_agent.py`
- Modify: `src/scansci_html/context_policy.py`
- Modify: `tests/test_pi_agent.py`
- Add: `tests/test_pi_parallel.py`
- Add: `tests/test_pi_observability.py`

**Behavior:**

- Remove “Call ONE tool at a time.” Tell the model to batch independent read-only calls when useful.
- Use Pi `executionMode`; any effectful sibling makes its batch sequential.
- Add a bounded Python executor and completion queue so stdout continues being consumed while parallel-safe tools run.
- Add a request/command dispatcher instead of dropping non-current queue messages.
- Isolate late results after cancel/timeout and protect tool history with locks.
- Use `before_agent_start`, `context`, `tool_call`, `tool_result`, `before_provider_request`, `after_provider_response`, and settled events for current-turn policy and audit.
- Replace destructive in-memory history edits with a non-destructive `context` hook.
- Coalesce identical in-flight read-only calls; keep effectful idempotency semantics.

**TDD:**

1. Add red timing tests: three 2-second read tools complete in <=3.5 seconds with observed concurrency >=3.
2. Add sequential-effect, cancel <=2 seconds, late-result isolation, command routing, current-turn hook, and in-flight coalescing tests.
3. Run `python -m pytest tests/test_pi_parallel.py tests/test_pi_observability.py tests/test_pi_agent.py -q` and confirm red.
4. Implement and re-run until green; repeat timing tests at least three times.
5. Build the sidecar.

**Commit:** `feat(pi): execute safe tools in parallel`

## Task 5: Replace fixed clipping with model-aware context and multimodal Pi turns

**Files:**

- Add: `src/scansci_html/model_metadata.py`
- Modify: `src/scansci_html/context_policy.py`
- Modify: `src/scansci_html/research_agent.py`
- Modify: `src/scansci_html/pi_agent.py`
- Modify: `pi-runtime/src/protocol.ts`
- Modify: `pi-runtime/src/runtime-extension.ts`
- Modify: `pi-runtime/src/main.ts`
- Add: `tests/test_context_policy.py`
- Add: `tests/test_pi_multimodal.py`
- Modify: `tests/test_image_attachments.py`
- Modify: `tests/test_vision_routing.py`
- Modify: `tests/test_webapp.py`

**Behavior:**

- Parse configured context windows (`32K`, `200K`, numeric) and model capabilities into a runtime descriptor.
- Replace last-12/24K character clipping with a unified token-estimated envelope prioritizing host contract, final user task, explicit Skills, recent dialogue, attachments, recaps, and referenced tool results.
- Derive Pi model context, guard, reserve, keep-recent, and output budget from the selected descriptor.
- Send validated Pi `ImageContent` blocks for supported models via `session.prompt`, steer, and follow-up.
- Enforce MIME/base64/count/byte limits on both Python and Node; never accept paths or URLs over the wire.
- Route image+tool tasks and ordinary image understanding through Pi when the model supports images. Unsupported models emit an explicit capability-degradation event and use OCR/text fallback or a declared alternate model; no silent bypass.
- Never write raw image base64 into status events or manifests.

**TDD:**

1. Add red tests for context parsing, total-envelope limits, sentinel retention, actual-token fixtures, image+tool routing, wire validation, supported/unsupported model events, and no raw binary in traces.
2. Run `python -m pytest tests/test_context_policy.py tests/test_pi_multimodal.py tests/test_image_attachments.py tests/test_vision_routing.py tests/test_webapp.py tests/test_pi_agent.py -q` and confirm red.
3. Implement and re-run until green.
4. Add a >=100K-token synthetic, 20-turn compaction test with 20/20 sentinel recovery and build the sidecar.

**Commit:** `feat(pi): add model-aware multimodal context`

## Task 6: Expose safe scientific subagents and complete session controls

**Files:**

- Modify: `src/scansci_html/research_agent.py`
- Modify: `src/scansci_html/research_subagents.py`
- Modify: `src/scansci_html/subagent_profiles.py`
- Modify: `src/scansci_html/pi_agent.py`
- Modify: `pi-runtime/src/tool-catalog.ts`
- Modify: `pi-runtime/src/main.ts`
- Modify: `tests/test_research_runs.py`
- Modify: `tests/test_pi_agent.py`
- Add: `tests/test_pi_subagents.py`

**Behavior:**

- Add Pi-callable `delegate_scientific_agents`, `list_scientific_agents`, `collect_scientific_agents`, and `cancel_scientific_agents` tools.
- Atomically reserve capacity; at most three children start within one parent.
- Child leases are strict read-only subsets of the parent with no MCP/external write, independent budgets/traces, structured handoffs, and approved `scansci://` evidence URIs.
- One child failure cannot cancel siblings; parent may wait, collect partial valid results, or cancel.
- Add acked queue inspection/clear, abort-compaction, close, load, full-history clone, and entry-level fork commands; document abort-and-resume rather than pretending suspend semantics.
- Support Pi thinking level `max`.

**TDD:**

1. Add red tests for spawn/list/wait/collect/cancel, <=3 under concurrent delegation, lease subset, failure isolation, invalid handoff rejection, and no inherited write.
2. Add session command ack/cross-request/fork/queue tests.
3. Run `python -m pytest tests/test_pi_subagents.py tests/test_research_runs.py tests/test_pi_agent.py -q` and confirm red.
4. Implement and re-run until green; build sidecar.

**Commit:** `feat(pi): delegate safe scientific subagents`

## Task 7: Finish deferred MCP, reliability, and effect audit

**Files:**

- Add: `pi-runtime/src/mcp-registry.ts`
- Modify: `pi-runtime/src/tool-catalog.ts`
- Modify: `pi-runtime/src/runtime-extension.ts`
- Modify: `pi-runtime/src/main.ts`
- Modify: `src/scansci_html/agent_capabilities.py`
- Modify: `src/scansci_html/pi_agent.py`
- Modify: `src/scansci_html/research_agent.py`
- Modify: `tests/test_mcp_bridge.py`
- Modify: `tests/test_pi_observability.py`
- Add: `tests/test_pi_security.py`

**Behavior:**

- Keep deferred servers disconnected at session start.
- Search their bounded catalogs, then register and activate actual remote schemas where supported; retain a functional provider-neutral fallback without widening permissions.
- Use explicit tool annotations/effect metadata and per-tool overrides; unknown effects deny by default.
- Recheck lease/risk/approval at search, activation, and call.
- Record standard MCP/effect start/end events with raw server ID, alias, remote name, effect, duration, decision, digest, and bounded result reference.
- Ensure selected-library-only turns clear unrelated MCP capability leases.
- Preserve timeout/disconnect isolation, safe endpoint policy, retries only when idempotent, and per-run read caching with freshness classes.

**TDD:**

1. Add red stdio and streamable-HTTP fixtures for zero initial connections, search->connect->activate->call, native/fallback paths, timeout recovery, current request IDs, and audited effects.
2. Add 100+ generated unauthorized-write/injection/malicious-name/path/secret cases with zero unauthorized effects.
3. Run `python -m pytest tests/test_mcp_bridge.py tests/test_pi_observability.py tests/test_pi_security.py -q` and confirm red.
4. Implement and re-run until green; build sidecar.

**Commit:** `feat(pi): harden deferred mcp execution`

## Task 8: Add the capability harness, release evidence, and packaging gates

**Files:**

- Add: `bench/pi_capability_tasks.json`
- Add: `scripts/verify_pi_capabilities.py`
- Modify: `scripts/release_gate.py`
- Modify: `config/release-gate.json`
- Add: `config/release-report.schema.json`
- Modify: `tests/test_harness_runtime.py`
- Modify: `tests/test_harness_p0_p2.py`
- Modify: `tests/test_release_gate.py`
- Modify: `tests/test_runtime_components.py`
- Modify: `tests/test_desktop.py`

**Behavior:**

- Produce report schema v2 containing protocol version, SDK version, source hash, bundle hash, fallback count, run-manifest references, and per-axis cases/threshold/pass.
- `_source_fingerprint()` includes all `pi-runtime/**` source/config/lock files and architecture docs.
- Gate code parses report contents; existence alone never passes.
- Targeted gate builds Pi, runs all Pi suites, validates matrix input, and runs deterministic sidecar protocol E2E.
- Real gate requires configured provider runs for provider-dependent dynamic serialization/multimodal cases; absent credentials are an explicit not-run release blocker, not a fake pass.
- Packaged diagnostics execute a bounded Pi tool loop, not just ping.
- Preserve existing targeted->full->real->package ordering and core/Node component boundaries.

**TDD:**

1. Add red tests for missing/failed axes, fallback>0, hash mismatch, omitted `pi-runtime` source, old report schema, and package without bundle/tool loop.
2. Run `python -m pytest tests/test_harness_runtime.py tests/test_harness_p0_p2.py tests/test_release_gate.py tests/test_runtime_components.py tests/test_desktop.py -q` and confirm red.
3. Implement verifier/schema/gates and make tests green.
4. Run the verifier in deterministic mode and inspect the JSON.

**Commit:** `test(pi): gate the full capability matrix`

## Task 9: Make v0.4.0 architecture and P0 explicit

**Files:**

- Modify: `AGENTS.md`
- Modify: `docs/agent-startup.zh.md`
- Modify: `docs/project-governance.zh.md`
- Modify: `docs/research-agent-architecture.zh.md`
- Modify: `docs/agent-harness-p0-p2.zh.md`
- Modify: `docs/desktop-packaging.zh.md`
- Modify: `docs/release-workflow.zh.md`
- Modify: `docs/implementation-plan.md`
- Modify: `config/release-scope.json`

**Behavior:**

- Freeze the previous v0.3.1 scope in release history and set v0.4.0 as the new single P0.
- Add acceptance IDs: `pi-routing`, `pi-dynamic-tools`, `pi-parallelism`, `pi-long-context`, `pi-skills`, `pi-subagents`, `pi-mcp`, `pi-multimodal`, `pi-safety`, `pi-observability`.
- Document Host/Pi/MCP/Skill/subagent/multimodal responsibility boundaries and the fail-closed protocol.
- State that direct fallback never counts as Pi success.
- Update handoff rules to include protocol, matrix, degradation count, validation artifacts, and unfinished axes.
- Reaffirm packaging and updater contracts.

**TDD:**

1. Add/extend schema and documentation contract tests before editing docs/config.
2. Run relevant release/config tests and confirm red.
3. Update docs/scope and run tests until green.

**Commit:** `docs(pi): adopt full capability p0`

## Task 10: Final regression, independent review, and handoff

1. Run `npm.cmd run build:pi-runtime`.
2. Run the complete Pi targeted suite listed by `config/release-gate.json`.
3. Run deterministic capability verification and validate report schema/hash binding.
4. Run full hermetic tests:

   ```powershell
   $env:SCANSCI_MODEL_ROOT='F:\\Scratch\\scansci-pi-test-empty-models'
   python -m pytest -q
   ```

5. Run targeted/source release gates that do not require unavailable signing credentials or paid providers.
6. Inspect `git diff --check`, worktree status, bundle diff, generated reports, and secret scan.
7. Request an independent final spec review against all 13 axes and an independent code-quality/security review.
8. Fix every validated issue through red tests, then rerun affected and full suites.
9. Record exact passing counts, skipped provider-dependent cases, hashes, and any external release blockers. Do not claim provider-real or packaged release completion without their evidence.
10. Follow the finishing-development-branch workflow and present the four integration options; do not merge or push without the user’s choice.

**Commit:** `chore(pi): verify full capability release`

## Release thresholds

| Axis | Required threshold |
|---|---|
| Routing | >=40 bilingual cases; 100% Pi reachability for model-mediated turns; zero silent fallback |
| Dynamic tools | 10 session mutations; inventory equals authorized catalog; 100% revoked-call rejection |
| Parallelism | Three 2s reads <=3.5s, concurrency >=3; zero overlapping effectful calls; cancel <=2s |
| Long context | >=100K tokens and >=20 turns; 20/20 sentinel recovery; no model-window overflow |
| Skills | >=20 selection/load cases; all limits/path checks pass; zero lease expansion |
| Subagents | Three children start; lease subset 100%; failure isolation and cancellation pass |
| MCP | stdio + streamable HTTP; deferred startup connections=0; 10/10 search/activate/call; all unauthorized writes rejected |
| Multimodal | All declared image cases and >=10 image+tool tasks pass; unsupported models emit explicit degradation |
| Safety | >=100 adversarial cases; unauthorized writes/path traversal/secret leaks all zero |
| Observability | Every run/effect/subagent/compaction has IDs, timing, decision and bounded result reference; schema/hash checks 100% |

## Completion rule

No checklist item may be marked complete from source inspection alone. It requires a red test observed before implementation, a green targeted test, inclusion in the deterministic matrix, and final regression evidence. Provider-dependent features may be implemented and deterministically simulated locally, but the release remains externally blocked until the configured real-provider gate is run successfully.
