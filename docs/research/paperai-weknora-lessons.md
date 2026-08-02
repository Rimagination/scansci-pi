# paperai / WeKnora Source-Level Lessons For ScanSci

Date: 2026-07-05

Scope:
- neuml/paperai, commit `310a1948d1952945e106ba51cfd4f51d62c1c0ed`
- Tencent/WeKnora, commit `18d7a6b3d30c70fef8e901d2f63622dc23cd1fcc`

This note focuses on source-level product and architecture lessons for ScanSci.

## Bottom Line

These two projects point to different but complementary directions.

paperai is valuable because it treats research work as a repeatable report-generation job: a task file defines a research query, columns, extraction prompts, context size, and render target. This is close to ScanSci's evidence-first direction. The main lesson is: do not make the product only a chat box. Give users a structured evidence table that can be regenerated, audited, and exported.

WeKnora is valuable because it shows how to package knowledge work as a modular agent platform: configurable agents, allowed tools, MCP service selection, skills, event streaming, tool approval, datasource connectors, chunking preview, and observable runs. The main lesson is: do not make ScanSci a monolithic RAG app. Make it a thin research workbench plus a Codex/plugin control plane.

## What To Borrow From paperai

### 1. Task File As Product Primitive

paperai's report schema lets a user define:
- a top-level report name
- global RAG/LLM options
- a research query
- standard metadata columns
- generated columns with `query` and `question`
- output format

This is exactly the pattern ScanSci should use for evidence matrices:

```yaml
name: LiteratureReview
options:
  model: gpt-5.5
  context: 5
  evidence_policy: accepted_or_partial_support

Methods:
  query: transformer-based paper retrieval
  columns:
    - name: Study
    - name: Year
    - name: Dataset
      query: dataset used
      question: What dataset is used?
    - name: Method
      query: method architecture
      question: What method is proposed?
    - name: Metric
      query: evaluation metric
      question: What metric is reported?
    - name: Evidence
      query: supporting sentence
      question: Which sentence supports the extracted value?
```

ScanSci should store this as a first-class `matrix_template`, not just as a prompt.

### 2. Dynamic Columns

paperai's strongest product idea is "generated columns". A column is not just display; it is a retrieval + extraction instruction. ScanSci should adopt this directly:
- `metadata_column`: title, year, venue, DOI, source
- `extraction_column`: query + question + expected type
- `evidence_column`: quote/span/citation selector
- `review_column`: accepted / partial_support / unsupported / contradiction

This is better than a free-form summary because every output cell can carry provenance.

### 3. Multi-Format Outputs

paperai renders Markdown, CSV, and PDF annotation. ScanSci's Studio should use the same product grammar, but only for our real outputs:
- evidence matrix
- review set
- report draft
- run manifest
- benchmark table

Do not add NotebookLM-style audio/slides/mind-map until we actually implement them.

### 4. Query And Report Separation

paperai separates one-shot query, shell query, and batch report generation. ScanSci should mirror this in UI:
- Chat: ask and inspect
- Evidence: search/retrieve/cite
- Studio: regenerate artifacts from templates
- Review: human acceptance and issue tracking

## What Not To Copy From paperai

paperai is too library/CLI oriented for our final product. It lacks a polished workspace, human review flow, and visible run orchestration. We should not copy its UX shape. We should borrow its task schema and evidence-table logic.

## What To Borrow From WeKnora

### 1. Agent Config As A Contract

WeKnora's `AgentConfig` includes allowed tools, MCP selection, skills, context limits, tool output limits, parallel tool calls, and retrieval-history policy. ScanSci should have an equivalent but smaller contract:

```json
{
  "control_plane": "codex",
  "worker_model": "local_action_decider",
  "allowed_actions": [
    "read_source",
    "retrieve_spans",
    "build_matrix",
    "draft_report",
    "run_benchmark"
  ],
  "human_gate": "review_acceptance_gold",
  "max_tool_output_chars": 16000,
  "max_context_tokens": 200000,
  "record_manifest": true
}
```

This fits our current decision: Codex/GPT-5.5 remains the main intelligence, while local small models only choose or execute bounded actions.

### 2. Progressive Skills

WeKnora's skills follow progressive disclosure: metadata always visible, detailed instructions loaded only when needed, extra resources/scripts loaded later. ScanSci should adopt this for Codex plugins:
- `scansci-import`: DOI/PDF/HTML ingestion
- `scansci-evidence`: quote/span extraction and citation audit
- `scansci-matrix`: template-driven evidence matrix
- `scansci-review`: reviewer decisions and issue log
- `scansci-benchmark`: evaluation runs

This makes the plugin route meaningfully different from OneFind and NotebookLM. The product is not "another RAG UI"; it is a research-operating skill set inside Codex.

### 3. Event Stream For Runs

WeKnora emits events such as thought, tool_call, tool_result, references, final_answer, tool approval, and OAuth required. ScanSci should define a smaller event vocabulary:
- `run.started`
- `source.parsed`
- `retrieval.completed`
- `span.extracted`
- `matrix.cell.generated`
- `review.required`
- `artifact.exported`
- `run.completed`

This should power the "运行记录" Studio artifact and make every output auditable.

### 4. Datasource Connector Interface

WeKnora's datasource abstraction separates `Validate`, `ListResources`, `FetchAll`, and `FetchIncremental`. ScanSci should copy the interface pattern but specialize it for research sources:
- `Validate`
- `ListResources`
- `FetchMetadata`
- `FetchFullText`
- `FetchIncremental`
- `NormalizeToSourceDoc`

Candidate connectors:
- Zotero library
- local PDF folder
- arXiv / DOI / Crossref
- PubMed / Semantic Scholar
- browser/current page capture

### 5. Chunking Preview

WeKnora's chunking guide has an important product idea: let users preview chunk strategy before indexing. ScanSci should do the same, but with academic structure:
- abstract / methods / results / discussion detection
- figure/table caption preservation
- citation/reference section exclusion
- parent-child chunks
- evidence-span anchors

This belongs in the Source panel or Review panel, not in a global settings page.

### 6. MCP Server As A Distribution Surface

WeKnora exposes its API through an MCP server with tools for knowledge base, hybrid search, chat, agent chat, chunks, and wiki pages. ScanSci should strongly consider MCP/Codex plugin as the first serious distribution form:
- lower UI burden
- immediate access to GPT-5.5/Codex orchestration
- a natural "workbench inside Codex" identity
- easier differentiation from NotebookLM, Zotero plugins, and OneFind

## What Not To Copy From WeKnora

WeKnora is enterprise knowledge-management heavy. ScanSci should not copy:
- multi-tenant RBAC at the prototype stage
- generic IM/channel/widget ecosystem
- broad vector database matrix
- generic wiki generation as the core product
- large settings/editor surface before the core evidence workflow works

Those would dilute the research product.

## ScanSci Product Shape After This Research

The best path is:

1. Keep the NotebookLM-like three-panel workbench.
2. Make Studio only output real research artifacts.
3. Add paperai-style `matrix_template` as the central artifact generator.
4. Add WeKnora-style `run_manifest` and event stream for auditability.
5. Package the agent as a Codex plugin/MCP first, not a standalone full platform first.
6. Treat Zotero as a source connector, not as the primary workbench.
7. Treat the local small model as an action decider or cheap extractor, not as the main reasoning brain.

## Immediate Prototype Implications

The current ScanSci Notebook prototype should evolve like this:

Source panel:
- show source trust state, parse state, evidence count, citation-anchor quality
- include Zotero/local/PDF/URL import as source types

Chat panel:
- keep conversation, but every answer should be backed by visible evidence chips
- modes should stay: chat, reading, evidence, review

Studio panel:
- keep only real outputs
- rename or clarify "数据表格" as "证据矩阵"
- add "模板" entry for matrix templates
- add "运行记录" as the audit trail, not a decorative card

Backend/protocol:
- define `source_doc`, `evidence_span`, `matrix_template`, `matrix_cell`, `review_decision`, `run_manifest`
- every Studio artifact should be reproducible from these objects

## Recommended Next Build Step

Implement a static but realistic "证据矩阵模板" flow in the prototype:

1. User selects sources.
2. Studio opens "证据矩阵".
3. The right drawer shows template columns.
4. A run starts and emits steps.
5. Output table shows each cell with evidence chips and review status.

This single workflow combines the strongest lessons from both projects and makes ScanSci visibly different from NotebookLM/OneFind.
