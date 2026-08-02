# ScanSci Architecture

The Agent-specific evolution plan is maintained in
[`docs/research-agent-architecture.zh.md`](research-agent-architecture.zh.md).
It records the current Pi/MCP boundary, the capability-catalog direction, and
the staged plan for deferred MCP tools, research subagents, advisor checks, and
stable research-resource URIs.

`ScanSci` is the long-term brand and top-level namespace. The current
`scansci-html` package remains the HTML-first capture layer, and its central
contract is intentionally narrow:

- save clean, readable `.html` when the user already has lawful access;
- never save PDF or Markdown;
- never store passwords, cookies, tokens, or institution credentials;
- keep publisher access decisions evidence-based rather than guessing from one
  marker.

The layered project-governance map lives in
[`docs/project-governance.zh.md`](project-governance.zh.md). It defines the
boundary between capture/preprocessing, evidence store, RAG core,
evidence-based annotation/review, and benchmark governance.

The precise clean-HTML output contract lives in
[`docs/clean-html-contract.zh.md`](clean-html-contract.zh.md). Publisher,
official-source, browser, and `paper-fetch-provider` routes may use different
recipes, but they should converge on that single `article.paper` evidence
format before a paper enters `index-v2`.

## Quality Ledger

Project failures, benchmark misses, methodology risks, and hard-won lessons are
tracked in [`docs/mistake-ledger.zh.md`](mistake-ledger.zh.md). Machine-readable
cases live in `bench/mistake_cases.jsonl`, with a starter row in
`bench/mistake_cases.template.jsonl`.

Every significant retrieval miss, citation mismatch, capture false positive,
benchmark bias, data-leakage risk, or performance bottleneck should become a
ledger entry with a root cause, fix, regression guard, and next action. The
ledger is part of the evidence-first contract: ScanSci should not only improve
scores, it should remember why previous failures happened.

## Evidence Agent

`evidence_agent` and `evidence_agent_runtime` form the local small-model
orchestration layer, not a chat layer. They inspect local facts that already
exist on disk: the SQLite evidence store, the local acceptance workbench
manifest, the Notebook/Source/Note/Layer workspace, and optional annotation
layers.

The first CLI surface is intentionally small:

- `scansci agent status`: report current workbench state as JSON.
- `scansci agent next`: return the next executable action as JSON.
- `scansci agent plan`: return staged evidence/workbench/benchmark readiness as JSON.
- `scansci agent run`: run the bounded observe/decide/act loop and record a
  manifest.

This keeps ScanSci independent from any single model host or workbench UI.
Codex plugins, Zotero integrations, standalone desktop views, and automation
scripts can all consume the same status/next protocol. LLMs may help with query
rewriting, claim splitting, or synthesis later, but the agent's core job is to
coordinate evidence-backed artifacts and quality gates.

The runtime may call an OpenAI-compatible local model, but only as an action
selector over the already assembled `allowed_actions`. It cannot invent shell
commands. Actions marked `requires_human=true`, such as local gold review, stop
the run even when `--execute` is enabled. The full Chinese usage guide lives in
[`docs/evidence-agent.zh.md`](evidence-agent.zh.md).

The preferred control pattern is `Codex-supervised Runtime`: Codex or the
current strongest model acts as the control plane, ScanSci stores typed actions
and run events, and any local small model is only a worker-level action decider.
Run manifests record `control_plane`, `autonomy`, `worker_model`, and append-only
`events` so later reviews can replay what was observed, selected, and executed.

## Research Task Router

The desktop Deep Agents harness is a separate, bounded research-task router.
It adapts configured OpenAI- and Anthropic-compatible models through LangChain,
then lets the model select from a small set of high-level ScanSci tools. It is
not a shell, filesystem, or browser-automation agent.

In its default `task_mode=auto`, it can inspect the workspace and available
capabilities, search Paper Atlas, look up journals, verify DOI metadata, audit
references, and create a source-linked presentation outline. Those tools return
typed outputs and can be delivered as a clearly labelled non-evidence research
artefact (for example, a discovery report or a research plan). Downloading
papers and creating projects remain explicit workflow actions rather than
model-initiated side effects.

The evidence gate applies at delivery time, not as a restriction on all task
planning: a scientific conclusion about imported literature must be finalised by
`build_verified_answer`, which uses the local evidence store and citation
verifier. The optional `task_mode=evidence` removes non-evidence delivery tools
and restores the strict evidence-only contract. If a run produces neither a
valid research delivery nor a verified answer, ScanSci rejects free-form model
text and, when possible, falls back to deterministic evidence verification.

## Retrieval Decisions

The retrieval layer is moving from a fixed `search(query)` pipeline toward an
observable retrieval-decision system. The roadmap and source-code reuse notes
live in [`docs/retrieval-decision-roadmap.zh.md`](retrieval-decision-roadmap.zh.md).

Benchmark runs are compared through the evidence retrieval leaderboard in
[`docs/evidence-retrieval-leaderboard.zh.md`](evidence-retrieval-leaderboard.zh.md).
`bench-leaderboard` reads existing details JSON files and ranks runs only inside
comparable groups such as `qasper/gold-docs/k20/q1005`, so smoke samples cannot
accidentally outrank full benchmark runs.

The benchmark protocol itself lives in
[`docs/benchmark-suite.zh.md`](benchmark-suite.zh.md). It defines the task
layers, method families, accuracy metrics, citation/faithfulness metrics,
efficiency metrics, and comparability rules used before scores are promoted to
figures or claims.

The default user path does not require a gold set. `local-ask` indexes a local
HTML library when needed, reuses the SQLite evidence store on later questions,
and writes an evidence-only HTML report with source anchors. Gold questions are
quality gates and regression checks, not a prerequisite for asking questions of
the user's own papers.

`workflow` writes `paper-evaluation.plan.md` on every run. That plan treats
public QASPER / SciFact / BEIR-style benchmarks, paper-defined benchmarks,
synthetic questions, LLM-as-judge, human or expert spot checks, and ablations as
the paper-style validation route. Local HTML gold rows are optional acceptance
evidence for a specific library and must be reported separately from public
benchmark leaderboards.

Every benchmarked retrieval run should expose enough trace data to explain which
route contributed candidates or hits: exact/FTS, dense, query variants, reranker,
parent context, and future graph expansion. This trace is the prerequisite for
measuring over-search, under-search, wrong scope, and bad query variants without
turning blind benchmark answers into a leakage channel.

The default RAG path is now a staged evidence pipeline rather than one flat
vector search. For large scholarly libraries, `paper_recall_limit` can select a
bounded set of likely source documents from document profiles before sentence
retrieval. `query_variants` runs structured rewrite routes and multi-query
recall before the evidence adequacy gate; candidates are fused with weighted RRF
so sparse/dense/query scores do not need to share a scale. The reranker remains
pluggable, with MiniLM, BGE-M3 / BGE reranker, and Qwen3 profiles treated as
comparable retrieval components, and strong rerankers run once on the fused
candidate pool instead of once per rewrite route.
Agentic retrieval is deliberately bounded by `max_followup_queries` so complex
questions can search again without turning every query into an unbounded loop.
Citation verification is structural and evidence-first: generated claims must
cite known quote IDs, cited evidence rows must contain exact quotes, and source
anchors must be present for human review.

Benchmark output makes this separation explicit. Local `bench` runs now declare
`benchmark_target=local_gold_evidence_answer` and `benchmark_mode=core` or
`enhanced`. Core mode is the comparable module benchmark: one query, no
paper-level recall, no follow-up retrieval. Enhanced mode measures the staged
workflow with query variants, paper recall, bounded follow-up, and citation
verification. External `bench-external` runs declare
`benchmark_target=external_evidence_retrieval`; they remain retrieval-only and
must not be reported as answer/citation quality scores.

## Benchmark Splits

Benchmark rows can declare `benchmark_split` as `dev`, `calibration`, or
`blind`. Rows without a split are treated as `dev`. Public QASPER / SciFact /
BEIR imports are development/reference benchmarks by default, not final blind
evidence. BEIR-format datasets such as Climate-FEVER evaluate document-level
retrieval from `qrels`, not local HTML sentence-level citation truth.

The split protocol lives in [`bench/splits/README.zh.md`](../bench/splits/README.zh.md).
Blind benchmark runs suppress per-question gold diagnostics by default:
`bench-external --benchmark-split blind --details-output ...` writes aggregate
metrics only, and `bench-mistakes` refuses blind details so the quality ledger
cannot become an answer leak.

## Runtime Layers

The project is organized as a pipeline:

1. `resolver`: normalize DOI, DOI URL, and article URL inputs.
2. `official_sources`: try publisher or repository XML/JATS sources that are
   officially exposed and enabled by entitlement/API keys. Elsevier uses a
   direct-first `view=FULL` API route and may verify MAIN PDF object EIDs as
   HTTP/API evidence, but browser-required verdicts still need browser evidence.
3. `fetchers`: perform normal HTTP preflight fetches.
4. `browser`: use a visible persistent browser only when rendered access state
   matters.
5. `publisher_recipes`: classify publisher-specific pages and define safe
   access-entry actions.
6. `cleaner`: convert full-text HTML into standalone clean HTML.
7. `article_structure`: summarize sections, body/endmatter presence, figures,
   images, references, collapsed-reference controls, and access markers.
8. `assets`: localize already visible image assets beside the saved HTML.
9. `service`: orchestrate fetch, auth fallback, cleaning, snapshots, and writes.
10. `cli`: translate command-line options into project config and JSON output.

## Browser Identity

The browser layer is CloakBrowser-first. `BrowserSessionBroker` owns one live
persistent browser context for a batch, and `CloakBrowserRuntime` launches that
context with a stable profile.

Browser identity configuration is centralized in `browser_config`:

- `BrowserIdentityConfig`: browser-only proxy, extension directories, and
  optional probe profile path.
- `BrowserFetcherConfig`: all options needed to construct `BrowserFetcher` from
  a CLI invocation.

`browser_identity` writes `.scansci-browser-identity.json` inside the profile.
The manifest records enough metadata to audit which browser identity was used,
but it does not persist secrets or local extension paths.

## Batch Retry

Batch recovery must happen inside the same live browser context whenever a
browser authorization path is active. Reusing only the disk profile is not
enough for SSO flows because publishers and institution IdPs may keep temporary
state in session cookies, sessionStorage, redirects, or in-memory browser
process state.

`batch_save_clean_html(..., retry_incomplete_rounds=N)` retries
`auth_required` and `fetch_error` results after the first pass without
recreating the fetcher. The CLI defaults to one retry round when `--browser` is
used or when the automatic auth browser fallback is enabled. It defaults to zero
for `--no-auth-browser`.

Publisher-specific retry routing belongs in service-level retry helpers or
publisher recipes. Science DOI retries use direct article URLs such as
`https://www.science.org/doi/10.1126/science.aed5051` instead of returning to
`doi.org`, because the first pass has already established that the publisher
route is Science and DOI redirects can fail independently of authorization.

## OpenCLI Bridge

OpenCLI is optional. It is not a second browser runtime and must not own the
profile, cookies, or lifecycle. When configured, it is loaded as an unpacked
Chrome extension inside the CloakBrowser context.

`opencli_bridge` provides diagnostics:

- inspect configured extension manifests;
- check the local OpenCLI daemon;
- optionally launch a CloakBrowser runtime probe.

This keeps the BrowserAct/OpenCLI lesson scoped correctly: stable profile,
human handoff, better observation, no proxy rotation for academic entitlement.

The intended OpenCLI role is an observer/inspector layer: produce richer DOM
evidence and stable element handles for the existing state machine. It should
not replace provider routing, entitlement checks, official XML/API fetchers, or
the clean-HTML output contract.

## Article Structure Gate

`article_structure` is the lightweight structure layer that prevents "HTML was
downloaded" from being confused with "the paper body was captured". It extracts
and reports:

- title, DOI, source URL, text length;
- ordered section headings and section kinds;
- body and endmatter presence;
- figure, image, table, and reference counts;
- access markers such as `check-access` and institutional-login text;
- collapsed reference controls such as `SHOW ALL REFERENCES`.

`SaveResult.structure` and CLI/broker JSON payloads expose this summary. The
service also treats selected structure warnings as blocking evidence. For
example, a page with access-gate text but no body sections is not saved as full
text, and a Science page that still contains `SHOW ALL REFERENCES` is rejected
until the browser recipe expands references and retries the DOM capture.

This is the main lesson from high-throughput fetchers such as
`paper-fetch-skill`: success must be judged by article structure and evidence,
not by HTTP 200, title presence, or a long abstract/backmatter page.

## Publisher Recipes

Publisher logic belongs in `publisher_recipes`, not in the browser runtime.

Examples of stable rules:

- Wiley: start from the article page; click `Read the full text`, `PDF`, or the
  visible access control before filling an institution picker. Never type the
  institution into Wiley global search.
- Science: do not use AAAS individual-login pages for institution access; return
  to the article and use the institutional path.
- Springer Nature: advance through WAYF/institution picker pages when the
  institution query is configured.

Recipes should produce access-state evidence such as `access_entry`,
`institution_picker`, `human_login`, `fulltext`, `subscription_preview`, or
`security_challenge`. Saving is allowed only after full-text evidence is present.

Recipes also own safe browser action hints:

- `access_entry_selectors()` returns the ordered selectors that may be clicked
  to reach institutional access.
- `institution_input_rules()` returns institution input candidates.
- `should_try_institution_input()` applies publisher guards before the browser
  fills anything.
- `prepare_fulltext_capture()` performs publisher-owned DOM preparation after
  full-text evidence is present and before `page.content()` is captured. Science
  uses this hook to expand collapsed `SHOW ALL REFERENCES` / `SEE ALL
  REFERENCES` controls, and the returned warning records that action in the
  fetch evidence.

`BrowserFetcher` consumes these recipe APIs. It should not add new
publisher-specific selector lists or institution-picker exceptions inline.

## Extension Path For Future Work

New publisher support should follow this order:

1. Add or refine a `PublisherRecipe`.
2. Add tests for access-state classification and safe clicks.
3. Add browser evidence checkpoints if the route depends on visual state.
4. Reuse `BrowserFetcherConfig` and `BrowserIdentityConfig`; do not introduce a
   parallel config object.
5. Keep API/XML fetchers in `official_sources` and keep browser login state out
   of HTTP clients.

This separation keeps the project cohesive: official sources, browser access,
publisher recipes, clean HTML, and evidence retrieval each have one home.
