# Literature Evidence RAG Project Plan

This document describes how to turn `ScanSci` into a high-accuracy literature
QA and writing-assistance system. The current implementation keeps
`scansci-html` as the HTML-first capture layer and compatibility entrypoint.
The central idea is not "RAG with pretty citations". The central idea is:

> Build a verified evidence table first, synthesize answers second, and render
> every factual sentence back to exact source spans in the saved HTML.

The existing project is already a good base because it captures clean,
offline-readable scholarly HTML without saving PDFs, cookies, or credentials.
The next layer should treat those HTML files as the canonical source corpus.

Naming note: `ScanSci` is the long-term brand and top-level namespace;
`scansci-html` remains the distribution package, Python import, and legacy CLI
entrypoint for compatibility. See [`naming.zh.md`](naming.zh.md) for the
Chinese naming plan.

## Goals

1. Answer research questions from a local scholarly HTML library.
2. Prefer accuracy over latency and cost.
3. Support thesis or paper writing, especially literature review sections.
4. Make every factual claim auditable down to source sentence or paragraph.
5. Refuse or mark "insufficient evidence" when the corpus does not support an
   answer.
6. Reuse mature open-source systems and ideas wherever practical.

## Non-Goals

- Do not replace human judgement for final academic claims.
- Do not generate uncited literature-review prose from model memory.
- Do not rely only on abstracts when full text is available.
- Do not use citation links as decorative confidence signals.
- Do not store institutional login state, passwords, cookies, or tokens.

## What To Reuse

### Reuse Directly Or As Baselines

- `scansci-html`: keep the current HTML-first capture, cleaning, article-structure
  checks, official XML/JATS probes, browser authorization boundary, and asset
  localization.
- [PaperQA2](https://github.com/Future-House/paper-qa): use as an accuracy
  baseline and borrow the agentic RAG design: iterative search, evidence
  gathering, LLM reranking/contextual summarization, citation traversal, and
  answer generation. PaperQA2 explicitly targets high-accuracy RAG for
  scientific papers and reports strong results on LitQA2.
- [Ai2 ScholarQA](https://github.com/allenai/ai2-scholarqa-lib): borrow the
  three-step generation design: retrieval and reranking, quote extraction,
  outline/clustering, then report generation. This is very close to the desired
  writing workflow.
- [OpenScholar](https://github.com/akariasai/openscholar): borrow the
  architecture: scientific datastore, domain retriever, cross-encoder reranker,
  iterative self-feedback, and citation verification. Do not try to reproduce
  its 45M-paper datastore locally at first.
- [LlamaIndex CitationQueryEngine](https://developers.llamaindex.ai/python/examples/workflow/citation_query_engine/):
  useful for a quick prototype of inline source-node citations, but not enough
  by itself for thesis-grade accuracy.
- [RAGTruth](https://aclanthology.org/2024.acl-long.585/): use the error model
  and evaluation mindset: RAG can still produce unsupported or contradictory
  claims.

### Reuse Libraries

- Parsing and HTML: `beautifulsoup4`, `lxml`, existing `cleaner` and
  `article_structure`.
- Sentence segmentation: `spacy`, `blingfire`, or `pysbd`. Start with `pysbd`
  for predictable sentence boundaries, then add domain-specific fixes.
- Keyword index: SQLite FTS5 or Tantivy. SQLite FTS5 is simplest for local use;
  Tantivy is already mentioned in PaperQA2 dependencies and is a strong option.
- Vector index: `faiss-cpu`, Qdrant, Chroma, or LanceDB. For local MVP, use
  FAISS or SQLite + numpy files. For a long-lived app, Qdrant is cleaner.
- Embeddings: start with `text-embedding-3-large` or a local
  `sentence-transformers` model. Make this provider-pluggable.
- Reranking: `mixedbread-ai/mxbai-rerank-large-v1`,
  `BAAI/bge-reranker-large`, or a hosted reranker. Reranking is not optional
  for accuracy.
- Structured outputs: `pydantic` models and JSON schema validation.
- UI: local HTML with a small static JS bundle. Use source HTML anchors and a
  side panel; do not build a heavy app until the data model works.

## Accuracy Definition

The system is accurate only when all of these hold:

1. The key evidence is present in the retrieved candidate set.
2. The evidence actually supports, contradicts, or limits the claim.
3. The answer does not add unsupported facts.
4. Each citation points to the supporting span, not merely to the right paper.
5. The system abstains when support is weak or absent.

Useful metrics:

- Retrieval recall at k: does the gold evidence span appear in top 20, 50, 100?
- Rerank recall at k: does reranking keep the key evidence in top 10 or 20?
- Claim support precision: of supported claims, how many are actually supported?
- Claim support recall: of answer claims that need evidence, how many have it?
- Citation F1: citation precision and citation recall, following ALCE and
  ScholarQABench style evaluation.
- Abstention accuracy: when evidence is missing, does the system say so?
- Contradiction detection: does the system surface conflicting findings?

## System Architecture

```text
HTML papers
  -> source normalization
  -> sentence/span anchoring
  -> evidence store
  -> hybrid retrieval
  -> cross-encoder reranking
  -> quote extraction
  -> evidence table
  -> answer synthesis
  -> claim verification
  -> HTML report with source highlighting
```

The important inversion is that the answer is generated from an evidence table,
not directly from raw retrieved chunks.

## Data Model

Add these durable entities. Store them in SQLite first; export JSONL for
debugging and model prompts.

### SourceDocument

```json
{
  "doc_id": "10.1038_s41586_...",
  "doi": "10.1038/s41586-...",
  "title": "...",
  "source_url": "https://...",
  "html_path": "html-papers/...",
  "publication_year": 2026,
  "journal": "Nature",
  "publisher": "Springer Nature",
  "capture_status": "success",
  "structure_hash": "sha256:..."
}
```

### EvidenceSpan

Sentence-level or sub-paragraph-level unit.

```json
{
  "evidence_id": "doc123.s0042",
  "doc_id": "doc123",
  "section": "Results",
  "section_kind": "results",
  "block_id": "doc123:p0017",
  "sentence_index": 42,
  "text": "The treatment increased X by 18% compared with control.",
  "char_start": 10231,
  "char_end": 10292,
  "html_anchor": "s-doc123-0042",
  "metadata": {
    "doi": "10....",
    "title": "...",
    "year": 2026
  }
}
```

### EvidenceChunk

Retrieval unit, usually a sentence window.

```json
{
  "chunk_id": "doc123.c0017",
  "doc_id": "doc123",
  "evidence_ids": ["doc123.s0040", "doc123.s0041", "doc123.s0042"],
  "text": "... sentence window ...",
  "section": "Results",
  "token_count": 220
}
```

### ExtractedQuote

The quote extraction stage selects exact evidence for the current question.

```json
{
  "quote_id": "q0007",
  "question": "How does method A compare with method B?",
  "evidence_ids": ["doc123.s0042"],
  "exact_quote": "The treatment increased X by 18% compared with control.",
  "role": "supports",
  "claim_hint": "Method A improved X relative to control.",
  "confidence": 0.83
}
```

### AnswerClaim

Every factual answer sentence becomes a claim object.

```json
{
  "claim_id": "c0012",
  "text": "Method A improved X relative to control in the cited trial.",
  "citation_quote_ids": ["q0007"],
  "support_status": "supported",
  "verification_score": 0.91
}
```

## HTML Anchoring

The saved article HTML should remain human-readable, but each evidence sentence
needs a stable anchor. During indexing, create a sidecar normalized HTML copy or
an overlay map:

```html
<span
  id="s-doc123-0042"
  data-evidence-id="doc123.s0042"
  data-section-kind="results">
  The treatment increased X by 18% compared with control.
</span>
```

If mutating source HTML is risky, keep the clean HTML unchanged and generate a
parallel `*.evidence.html` with spans injected. The report can link to the
parallel copy. The sidecar spans are stable machine anchors, not default visual
markup; source highlighting should be applied by the active report, answer, or
review layer. When `index-v2 --inject-evidence-html` creates this sidecar,
stored evidence hits should use `*.evidence.html#anchor` as their review target
while `source_documents` keeps both the original clean HTML path and the
sidecar path. If the same DOI or source-derived `doc_id` appears more than once
under a library root, `index-v2` indexes the first copy and reports later copies
as `duplicate_documents_skipped` so repeated capture directories do not inflate
multi-document evidence counts. Browser-saved resource folders such as
`_rejected_preview`, `raw-snapshots`, and `*_files` are skipped. The span
extractor also keeps QA evidence focused on article content by excluding
references, author affiliations, funding, data availability, rights, and
supplementary/source-data sections. Run `scansci evidence-doctor --db ...` to
verify that each stored `html_path#html_anchor` exists and that sidecar anchors
carry the matching `data-evidence-id`.

## Retrieval Pipeline

### Step 1: Query Analysis

Parse the question into:

- topic terms;
- entities, methods, datasets, species, disease names, model names;
- desired answer type: definition, comparison, mechanism, evidence table,
  contradiction, trend, limitation, or literature map;
- optional filters: year, journal, DOI, section, field.

Use an LLM only to produce structured query variants, not to answer.

### Step 2: Multi-Route Candidate Recall

Run several retrieval paths and merge candidates:

1. BM25/FTS over sentence windows.
2. Dense vector search over sentence windows.
3. Metadata search over title, DOI, authors, journal, year, references.
4. Citation traversal when available: expand to papers cited by or citing the
   currently relevant papers.
5. Optional external discovery: Semantic Scholar, Crossref, OpenAlex, PubMed,
   arXiv, then fetch full HTML with the existing `scansci-html` pipeline.

Keep a large candidate pool. PaperQA2's engineering notes suggest that the key
passage may be buried beyond the top few embedding hits; their high-accuracy
design trades compute for quality.

### Step 3: Rerank

Use a cross-encoder reranker over query and candidate chunks. Keep:

- top 50 chunks overall;
- max 3 to 5 chunks per paper to avoid one paper dominating;
- at least some diversity across years and methods for literature-review
  questions.

Reranking should be a first-class module because OpenScholar reports that
removing reranking causes large drops in correctness and citation accuracy.

### Step 4: Evidence Adequacy Check

Before answer generation, ask:

- Do retrieved quotes cover all subquestions?
- Are there conflicting findings?
- Is the answer likely single-paper or multi-paper?
- Is there enough support to answer?

If not enough support, the agent should run another query or abstain.

## Quote Extraction

Follow Ai2 ScholarQA's pattern: do not ask the final generator to discover
evidence while writing. First extract exact quotes.

Prompt contract:

- Input: question plus reranked chunks with `evidence_id`.
- Output: JSON list of quotes.
- Each quote must copy text verbatim or identify exact `evidence_id`.
- Each quote has role: `supports`, `contradicts`, `background`, `limitation`,
  `method`, `metric`, `definition`.
- The model may return `insufficient_evidence`.

Validate that every returned `evidence_id` exists and every quote is an exact
substring of the corresponding span/window. Reject invalid quote IDs.

## Evidence Table

The evidence table is the intermediate artifact the user should be able to
inspect before trusting the answer.

Example columns:

| Claim target | Stance | Exact quote | Paper | Section | Year | DOI | Confidence |
|---|---|---|---|---|---:|---|---:|

For thesis writing, this table is often more useful than the generated prose.
It can become a literature-review matrix.

## Answer Synthesis

Only synthesize from the evidence table.

Rules:

1. Every factual sentence must cite one or more quote IDs.
2. If evidence conflicts, say so explicitly.
3. Preserve uncertainty and scope.
4. Do not cite papers that are not in the evidence table.
5. Do not cite a paper merely because it is topically related.
6. Prefer short paragraphs plus evidence tables for complex questions.

Output should be structured JSON first, then rendered:

```json
{
  "answer": [
    {
      "claim_id": "c001",
      "text": "The strongest evidence suggests ...",
      "quote_ids": ["q001", "q004"]
    }
  ],
  "limitations": ["Only five papers in the local corpus address ..."],
  "followup_queries": ["..."]
}
```

## Claim Verification

After synthesis, split the answer into claims and verify each one.

Verification options:

1. LLM judge with strict entailment prompt.
2. NLI model trained for scientific text, where available.
3. Cross-check with a second model/provider for high-stakes outputs.
4. Exact quote overlap checks for numeric values, named entities, methods, and
   datasets.

Statuses:

- `supported`: cited evidence entails the claim.
- `partially_supported`: evidence supports only part of the claim.
- `contradicted`: evidence contradicts the claim.
- `unsupported`: citation does not support the claim.
- `not_enough_information`: no adequate evidence in corpus.

Any unsupported or contradicted claim should trigger one of:

- delete the sentence;
- revise to match the evidence;
- retrieve more evidence;
- mark as insufficient.

This stage is the difference between "citation-looking RAG" and reliable
literature QA.

## HTML Report UI

The report should have three linked panes:

1. Answer pane: paragraphs with claim-level citation badges.
2. Evidence pane: exact quotes, paper metadata, section, confidence, stance.
3. Source pane: embedded local HTML source with highlighted sentence anchors.

Interactions:

- Hover citation -> show exact quote.
- Click citation -> open source sentence.
- Click claim -> show verification status and all supporting/contradicting
  quotes.
- Toggle "show unsupported" -> reveal discarded or revised claims.
- Export evidence table as CSV/JSON for thesis notes.

## CLI Commands

Keep the command-line interface composable:

```powershell
scansci index-v2 `
  --library-dir .\html-papers `
  --db .\html-papers\evidence.sqlite `
  --inject-evidence-html
```

```powershell
scansci search-v2 `
  --db .\html-papers\evidence.sqlite `
  --query "What evidence supports X?" `
  --limit 10 `
  --initial-limit 200 `
  --reranker cross-encoder `
  --reranker-model BAAI/bge-reranker-large
```

```powershell
scansci ask `
  --db .\html-papers\evidence.sqlite `
  --question "What evidence supports X?" `
  --output .\reports\question-001.html `
  --json-output .\reports\question-001.json `
  --adequacy-profile auto `
  --min-quotes 1 `
  --min-documents 1
```

Optional LLM-backed quote extraction, answer synthesis, and verification:

```powershell
scansci ask `
  --db .\html-papers\evidence.sqlite `
  --question "What evidence supports X?" `
  --output .\reports\question-001.html `
  --json-output .\reports\question-001.json `
  --quote-provider llm `
  --answer-provider llm `
  --verification-provider llm `
  --chat-provider openai-compatible
```

```powershell
scansci verify `
  --report .\reports\question-001.json `
  --output .\reports\question-001.verified.json
```

```powershell
scansci verify `
  --report .\reports\question-001.json `
  --output .\reports\question-001.verified.json `
  --verification-provider llm `
  --chat-provider openai-compatible
```

```powershell
scansci review-matrix `
  --report .\reports\question-001.json `
  --output .\reports\question-001.matrix.html `
  --format html
```

`review-matrix --format html` renders a human-checkable review matrix whose
evidence IDs link back to `html_path#html_anchor`. The exported rows also keep
the query plan, retrieval filters, executed retrieval queries, and evidence
adequacy audit so the matrix can circulate independently of the original ask
report. Repeat `--report` to merge multiple questions or review subtopic
reports into one matrix; `csv` and `json` remain available for downstream
tools. Use `--support-status`, `--question-type`, `--section-kind`,
`--evidence-sufficient true|false`, and `--columns` to export focused review
subsets before moving them into thesis notes.

```powershell
scansci bench `
  --db .\html-papers\evidence.sqlite `
  --gold .\bench\gold_questions.jsonl `
  --min-retrieval-recall 0.8 `
  --min-all-gold-retrieval-recall 0.8 `
  --min-gold-evidence-recall 0.8 `
  --min-citation-f1 0.8 `
  --min-answerable-evidence-adequacy 0.8 `
  --adequacy-profile auto `
  --min-quotes 1 `
  --min-documents 1 `
  --details-output .\bench\benchmark-details.json `
  --details-html-output .\bench\benchmark-details.html
```

With `--details-output`, `bench` writes per-question diagnostics JSON: gold
evidence IDs, retrieved evidence IDs, retrieved/missing gold evidence IDs,
quoted evidence IDs, cited/missing cited gold evidence IDs, evidence adequacy
thresholds and outcomes, answer point matching, and claim support counts.
`--details-html-output` renders the same diagnostics as an HTML review report. Use these files
first when a local acceptance set fails so the failure can be traced to
retrieval, quote selection, citation coverage, adequacy thresholds, or answer
verification.

The top-level metrics include `answerable_evidence_adequacy_rate`, the share of
answerable gold questions whose final evidence set passed the adequacy gate.
Use `--min-answerable-evidence-adequacy` to make this a CI gate.

`--adequacy-profile auto` raises comparison, conflict, and synthesis questions
to at least two validated quotes from two source documents. In benchmark runs,
the gold `answer_type` also contributes to this gate: `multi_paper_synthesis`
and `conflict_evidence` rows are promoted even when the question text lacks an
obvious synthesis or conflict cue. Use `--adequacy-profile manual` when a run
should use exactly the supplied `--min-quotes` and `--min-documents` thresholds.

Current `html-papers` coverage is now much cleaner after section inheritance,
back-matter exclusion, saved-resource filtering, and decimal/subscript sentence
split fixes: 72 documents and 15,575 spans, with `abstract` 478,
`introduction` 682, `methods` 5,368, `results` 1,846, `discussion` 1,260,
`conclusion` 210, `other` 5,731, and `references` 0.
The previous 16,404 `other` / 3,131 `references` / 89 `methods` / 52 `results`
profile is resolved enough to proceed to targeted corpus sampling if a local
acceptance set is needed, though the remaining `other` rows still need spot
checks before those rows become a quality gate.

```powershell
scansci bench-validate `
  --gold .\bench\gold_questions.jsonl `
  --db .\html-papers\evidence.sqlite `
  --min-questions 50 `
  --min-per-answer-type 10 `
  --require-answer-types single_paper_fact,single_paper_method,multi_paper_synthesis,conflict_evidence,unanswerable,numeric_extraction `
  --html-output .\bench\gold-validation.html
```

With `--db`, `bench-validate` also checks that every `gold_evidence_id` exists
in the current evidence store, catching hand-written ID mistakes and corpus
version drift before benchmark runs. `--min-per-answer-type` makes answer-type
coverage a real gate, so a local acceptance set cannot silently collapse into one
easy question class. With an evidence store, the validator also checks gold
evidence adequacy by answer type: synthesis and conflict rows need at least two
gold evidence IDs from two source documents, and numeric rows need at least one
gold evidence text containing a digit. `--html-output` renders the validation
payload as a human cleanup report with schema issues, missing IDs, answer-type
coverage gaps, gold-evidence adequacy problems, and non-fatal quality warnings
for caption-like gold evidence in synthesis/conflict rows; question-specific issues
are grouped by `question_id` with in-page anchors, and each question card
includes answer type, annotation status, question text, and gold evidence IDs.
The validation payload and HTML report also include annotation progress
(`completed_rows`, `incomplete_rows`, `empty_question_rows`, and status counts)
plus reviewer-only suggestion fields for unfinished template rows. With `--db`,
they also include `gold_evidence_coverage` for auditing source-document,
section-kind, and block-type concentration in the local acceptance set.
When `--db` is supplied, each found gold evidence ID is also expanded into a
source card with title, DOI, section, escaped evidence text, and a clickable
`html_path#html_anchor` link back to the source HTML.
For benchmark-ready rows, validation also enforces answer-accuracy rubrics:
answerable rows need at least one `required_points` entry, and unanswerable rows
need at least one `forbidden_points` entry. `annotation_status: "todo"` template
rows remain a focused human-task list instead of also emitting point-gate noise.

```powershell
scansci corpus-coverage --db .\html-papers\evidence.sqlite
```

```powershell
scansci bench-template `
  --db .\html-papers\evidence.sqlite `
  --output .\bench\gold_questions.template.jsonl `
  --html-output .\bench\gold_questions.template.html `
  --questions-per-type 10
```

```powershell
scansci bench-template-report `
  --template .\bench\gold_questions.template.jsonl `
  --output .\bench\gold_questions.template.html
```

The repository also includes a tiny CI smoke benchmark in
`bench/sample_library` plus `bench/gold_questions.sample.jsonl`. It covers one
factual question, one unanswerable question, and one conflict-evidence question;
it is a quality-gate scaffold, not a substitute for public benchmark
reproduction or a larger optional local acceptance set.
`bench-validate` checks schema consistency, answer-type coverage, and unfinished
`annotation_status: "todo"` rows before a local acceptance set is used as a gate. It
also supports `--min-per-answer-type` for per-class coverage gates and reports
`gold_evidence_adequacy_issues` for weak multi-paper, conflict, or numeric gold
rows. Benchmark-ready rows must include answer-accuracy rubrics
(`required_points` for answerable rows and `forbidden_points` for unanswerable
rows), plus non-fatal `gold_evidence_quality_warnings` when verified
multi-paper/conflict gold rows include caption-like evidence. The same
validation payload can be rendered as HTML for annotation cleanup.
`bench-template` creates a human-annotation
starter JSONL from `evidence.sqlite`; it leaves `question` empty and marks rows
as `annotation_status: "todo"` so it is not confused with validated gold truth.
Single-evidence answer types are sampled in a document-balanced round-robin, so
one paper does not monopolize factual, method, or numeric starter rows; body
sections are preferred over abstracts when both are available.
Multi-paper and conflict starter pairs skip figure-caption-like rows so generic
caption vocabulary does not dominate cross-paper pairing. On the current real
library, `--questions-per-type 10` generates 60 starter rows in a few seconds
and `bench-validate --db --min-questions 50
--min-per-answer-type 10` fails only because human fields are still unfinished;
the starter rows have no missing IDs, no underrepresented answer types, and no
gold-evidence adequacy issues or quality warnings; the validation report shows
70 gold-evidence references, 41 unique evidence spans, and 23 source documents.
Each starter row also carries reviewer-only `suggested_question`,
`suggested_required_points`, and
`suggested_forbidden_points`; these do not fill the final `question` field and
do not satisfy validation without human approval and benchmark-ready
`required_points` / `forbidden_points`. The generated
`gold-validation.template.html` is therefore a focused checklist of unfinished
human fields rather than retrieval or evidence-structure failures.
`bench-template --html-output` and `bench-template-report` render the same rows
as an HTML human-review worksheet with links back to `html_path#html_anchor`.
The template JSON summary and HTML worksheet also include `template_coverage`
for pre-annotation audit: the current real template has 70 candidate evidence
references, 41 unique evidence spans, 23 source documents, section-kind counts
of `methods=10`, `results=60`, and `paragraph=70` block types.

## Suggested Module Layout

```text
src/scansci_html/
  evidence.py              # keep current block extraction; extend carefully
  evidence_spans.py        # sentence anchors and span extraction
  evidence_store.py        # SQLite schema and JSONL import/export
  evidence_doctor.py       # evidence store -> HTML anchor link validation
  coverage.py              # corpus coverage summary for gold-set planning
  review.py                # literature-review evidence matrix export
  embeddings.py            # provider-pluggable embedding interface
  retrieval.py             # keep current lexical search; add hybrid interface
  rerankers.py             # cross-encoder reranking
  qa/
    schemas.py            # Pydantic schemas for LLM JSON outputs
    query_planner.py       # query decomposition and metadata filters
    quote_extractor.py     # exact quote JSON extraction
    evidence_table.py      # inspectable table assembly
    synthesizer.py         # evidence-only answer generation
    verifier.py            # claim-level support checks
    agent.py               # iterative retrieve-check-refine orchestration
  render/
    report.py              # HTML report renderer
    gold_template.py       # gold-question annotation HTML report renderer
    source_overlay.py      # evidence span highlighting
```

## Implementation Phases

### Phase 1: Sentence Evidence Store

Deliverables:

- `EvidenceSpan` extraction from existing clean HTML.
- Stable `evidence_id` and `html_anchor`.
- SQLite store with FTS5.
- `publication_year` metadata when the saved HTML exposes article/date metadata.
- JSONL export for debugging.
- Tests for Nature, Science, Wiley examples already in `html-papers`.

Acceptance criteria:

- Each paragraph/caption block maps to ordered sentence spans.
- Clicking an evidence ID opens the local HTML at the source sentence.
- Publication year metadata survives span extraction, SQLite storage, and JSONL export.
- Existing `index` command remains compatible or gets a clear `index-v2`.

Current local corpus status: `html-papers` has been indexed with
`index-v2 --inject-evidence-html`, producing 72 unique source documents, 15,575
evidence spans, and 72 sidecar HTML files while skipping 95 duplicate `doc_id`
captures. `evidence-doctor` verified all 15,575 `html_path#html_anchor` links
and matching `data-evidence-id` values; sidecar files and SQLite references are
aligned at 72/72 with zero orphan sidecars.

### Phase 2: Hybrid Retrieval And Reranking

Deliverables:

- BM25/FTS retrieval.
- Dense embedding retrieval.
- Candidate merge and deduplication.
- Cross-encoder reranking.
- Metadata filtering, including `publication_year >= year_min` and
  `section_kind in (...)`.
- Per-paper diversity cap.

Acceptance criteria:

- Search results include exact evidence IDs, source text, section, DOI, title.
- Reranked output is stable and inspectable.
- Explicit `--year-min` filters out older and unknown-year documents.
- Explicit `--section-kind` filters out evidence from unrelated article
  sections such as Abstract, Methods, Results, or Discussion.
- Retrieval recall can be measured on a small gold set.

### Phase 3: Quote Extraction

Deliverables:

- Structured quote extraction prompt.
- Pydantic schema validation.
- Exact substring or evidence ID validation.
- Evidence table renderer.

Acceptance criteria:

- Invalid evidence IDs are rejected.
- The model cannot invent source text.
- User can inspect the evidence table before answer synthesis.

### Phase 4: Evidence-Only Answer Generation

Deliverables:

- Answer JSON schema.
- Claim IDs and quote IDs.
- HTML answer renderer.
- Retrieval audit renderer.
- Insufficient-evidence path.

Acceptance criteria:

- Every factual sentence has quote IDs.
- No source outside the evidence table appears in citations.
- The HTML report shows query plan, filters, executed retrieval queries, and
  adequacy status for human audit.
- Conflicting evidence is represented rather than hidden.

### Phase 5: Claim Verification

Deliverables:

- Claim splitter.
- Citation support verifier.
- Regenerate-or-abstain loop.
- Verification report.

Acceptance criteria:

- Unsupported claims are removed, revised, or marked.
- Verification status is visible in the HTML report.
- Citation precision/recall is measured on gold examples.

### Phase 6: Agentic Retrieval

Deliverables:

- Query planner that can issue follow-up searches.
- Evidence adequacy check.
- Citation traversal using references/DOIs when available.
- Optional Semantic Scholar/OpenAlex/PubMed discovery hook.

Current implementation:

- `answer_question` records the executed `retrieval_queries`.
- Planned `year_min` filters from questions such as "since 2020" and simple
  section-kind filters from explicit methods questions are passed to the first
  retrieval pass and follow-up searches.
- If the first retrieval pass does not produce enough validated quotes, the
  agent runs planned follow-up searches, merges evidence hits, re-extracts
  quotes, and stops when adequacy is sufficient.
- If adequacy is still insufficient after all follow-up searches, the agent
  keeps the evidence table for human review but does not run answer synthesis,
  LLM generation, or claim verification for factual claims; the final answer is
  marked `insufficient_evidence` with the adequacy-gate reason in limitations.
- External discovery and citation traversal return candidate metadata only;
  papers must still go through the HTML capture pipeline before entering the
  evidence store.

Acceptance criteria:

- The system improves recall on multi-paper questions.
- The agent stops when evidence is sufficient or clearly missing.
- All external papers are fetched through the existing safe HTML pipeline.

### Phase 7: Benchmark And Quality Gates

Deliverables:

- Local benchmark JSONL.
- Metrics: retrieval recall, all-gold retrieval recall, gold evidence recall,
  answer accuracy, citation F1, unsupported-claim rate, abstention accuracy.
- Regression tests for known questions.
- Evidence link doctor gate.

Acceptance criteria:

- A change that lowers any-gold retrieval recall, all-gold retrieval recall,
  gold evidence recall, or citation F1 fails CI.
- A change that breaks `html_path#html_anchor` or `data-evidence-id` links fails
  CI.
- The benchmark includes answerable and unanswerable questions.
- The benchmark includes contradiction or mixed-evidence questions.

## Benchmark Design

Start with 50 to 100 hand-written questions over your local corpus.

Question types:

- Single-paper fact: answer appears in one sentence.
- Single-paper method/detail: answer appears in Methods or Results, not
  abstract.
- Multi-paper synthesis: answer requires comparing several papers.
- Contradiction: two papers disagree or qualify each other.
- Unanswerable: corpus lacks enough support.
- Numeric extraction: result, sample size, effect size, p value, date.

Gold annotation:

```json
{
  "question_id": "q001",
  "question": "...",
  "answer_type": "multi_paper_synthesis",
  "gold_evidence_ids": ["doc1.s0032", "doc7.s0111"],
  "required_points": [
    "A improves X in setting Y",
    "B has lower cost but weaker evidence"
  ],
  "forbidden_points": [
    "Do not claim clinical efficacy; only animal data is present"
  ],
  "answerable": true
}
```

## Borrowing Strategy

Practical order:

1. Use PaperQA2 as a black-box baseline on the same corpus and questions.
2. Borrow Ai2 ScholarQA's quote extraction and planning prompts as design
   templates.
3. Borrow OpenScholar's self-feedback and citation verification pattern after
   the basic pipeline works.
4. Use LlamaIndex CitationQueryEngine only for a quick comparison baseline.
5. Keep `scansci-html` as the source capture and source-rendering layer.

Do not try to merge all frameworks into one runtime. Treat them as references
and baselines. The project-specific core is the HTML evidence store and the
claim-to-source renderer.

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Key evidence is not retrieved | Multi-route retrieval, larger candidate pool, reranking, query expansion |
| Model cites adjacent but wrong text | Evidence ID validation and claim-level verification |
| Answer overgeneralizes | Evidence-only synthesis and required scope/limitation fields |
| Too many citations reduce readability | Keep answer concise; put full evidence in expandable table |
| Local corpus is incomplete | Mark corpus coverage and optionally trigger external discovery |
| Tables/figures contain key facts | Add table and figure-caption extraction; later add OCR/table parsers |
| Long-context model ignores evidence | Use quote extraction and evidence table instead of dumping all chunks |
| Citation traversal retrieves low-quality papers | Use metadata filters, citation counts cautiously, venue/year/retraction checks |

## Minimum Viable Product

The MVP should answer questions over local HTML papers with source-highlighted
claims.

MVP scope:

- Sentence evidence store.
- FTS + dense retrieval.
- Reranker.
- Quote extraction.
- Evidence-only answer.
- Claim verification.
- HTML report.

Defer:

- Large external corpus.
- Complex agent UI.
- Full PDF geometry support.
- Automatic paper recommendation beyond Semantic Scholar/OpenAlex hooks.

## Reference Materials

- PaperQA2 paper: [Language agents achieve superhuman synthesis of scientific knowledge](https://arxiv.org/html/2409.13740v1).
- PaperQA2 code: [Future-House/paper-qa](https://github.com/Future-House/paper-qa).
- PaperQA2 engineering notes: [Journey to superhuman performance on scientific tasks](https://www.futurehouse.org/research/engineering-blog-journey-to-superhuman-performance-on-scientific-tasks).
- OpenScholar paper: [OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs](https://ar5iv.labs.arxiv.org/html/2411.14199v1).
- OpenScholar Nature article: [Synthesizing scientific literature with retrieval-augmented language models](https://www.nature.com/articles/s41586-025-10072-4).
- OpenScholar code: [akariasai/openscholar](https://github.com/akariasai/openscholar).
- Ai2 ScholarQA paper: [Ai2 Scholar QA: Organized Literature Synthesis with Attribution](https://arxiv.org/abs/2504.10861).
- Ai2 ScholarQA blog: [Introducing Ai2 ScholarQA](https://allenai.org/blog/ai2-scholarqa).
- Ai2 ScholarQA code: [allenai/ai2-scholarqa-lib](https://github.com/allenai/ai2-scholarqa-lib).
- ALCE citation evaluation: [Enabling Large Language Models to Generate Text with Citations](https://aclanthology.org/2023.emnlp-main.398/).
- AIS attribution framework: [Measuring Attribution in Natural Language Generation Models](https://aclanthology.org/2023.cl-4.2/).
- RAGTruth hallucination corpus: [RAGTruth](https://aclanthology.org/2024.acl-long.585/).
- Self-RAG: [Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511).
- Corrective RAG: [Corrective Retrieval Augmented Generation](https://arxiv.org/abs/2401.15884).
- LlamaIndex citations: [Build RAG with in-line citations](https://developers.llamaindex.ai/python/examples/workflow/citation_query_engine/).
- Google grounding check design: [Check grounding with RAG](https://docs.cloud.google.com/generative-ai-app-builder/docs/check-grounding).
