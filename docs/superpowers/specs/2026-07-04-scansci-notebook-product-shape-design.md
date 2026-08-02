# ScanSci Notebook Product Shape Design

Date: 2026-07-04

## Decision

ScanSci V0 product shape is **ScanSci Notebook**, a NotebookLM-like evidence notebook for scientific reading, review, and citation-grounded writing.

The user-facing product is not an engineering console. The engineering console still exists underneath as `agent status`, `agent plan`, `agent run`, benchmark outputs, and run manifests, but the default UI should feel like a notebook:

```text
Sources -> Ask / Read / Evidence -> Studio Outputs
```

The durable difference from NotebookLM is the evidence contract:

```text
Sources -> clean HTML -> evidence spans -> grounded answers -> human review -> benchmarkable outputs
```

## Product Promise

ScanSci Notebook helps a researcher turn a source collection into trustworthy, inspectable research material:

- ask questions over sources;
- see citations that jump back to the original clean HTML anchors;
- turn answers and claims into reviewable evidence items;
- generate briefing documents, evidence matrices, review sets, and benchmark runs;
- keep every automated step auditable through Agent run manifests.

The product should feel like a thinking notebook first and an agent runtime second.

## Primary UI Shell

The stable V0 shell is a three-pane notebook layout:

```text
+--------------+------------------------------+---------------------+
| Sources      | Ask / Read / Evidence        | Studio              |
|              |                              |                     |
| paper A      | Chat with sources            | Briefing Doc        |
| paper B      | Source-grounded answer       | Evidence Matrix     |
| paper C      | Reader with highlighted span | Review Set          |
|              | Claim / citation review      | Benchmark Run       |
+--------------+------------------------------+---------------------+
```

### Left Pane: Sources

Purpose: manage and inspect source material.

V0 elements:

- source list grouped by status: ready, needs evidence build, warning;
- source cards with title, DOI/source URL, year, evidence span count;
- add/import source action;
- evidence health badges kept compact and non-technical.

### Center Pane: Work Surface

Purpose: do the user's actual thinking work.

V0 modes:

- `Ask`: chat with sources, showing citation cards and answer trace.
- `Read`: clean HTML reader with source anchors and highlighted evidence spans.
- `Evidence`: table or card view of evidence spans, claims, and support status.
- `Review`: human review queue for claims, gold questions, and citation audits.

The center pane is the product's emotional center. Agent status should not dominate it.

### Right Pane: Studio

Purpose: produce structured outputs from the notebook.

V0 Studio actions:

- Briefing Doc;
- Evidence Matrix;
- Claim Review Set;
- Acceptance Set;
- Benchmark Run;
- Export Report.

Each Studio action may call `agent plan` or `agent run`, but the user sees an output-oriented button, not a raw command.

## Home Screen

The first screen is a notebook list:

```text
My Notebooks

[Urban heat and health]
Sources 42 | Evidence ready | 3 claims need review | Last run 2h ago

[Blue carbon review]
Sources 18 | Needs evidence build | No benchmark yet
```

A notebook card exposes the research state in human language. It should not start with benchmark metrics or agent internals.

## Object Model

These product objects are stable for V0:

- `Notebook`: user-facing research workspace.
- `Source`: clean HTML source, metadata, and source health.
- `EvidenceSpan`: citeable source span with anchor and section metadata.
- `Question`: user or benchmark question tied to sources.
- `Answer`: generated answer with quotes and evidence IDs.
- `Claim`: atomic statement that can be supported, partially supported, or unsupported.
- `ReviewItem`: human review unit for claim, citation, or gold question.
- `StudioArtifact`: briefing doc, evidence matrix, review set, benchmark result, or export.
- `AgentRunManifest`: audit trail for background runtime work.

`AgentRunManifest` is a system object, not a primary user object. It should be available through "View run details" links.

## Agent Runtime Integration

The UI consumes runtime JSON instead of duplicating workflow logic:

- `agent status`: small badges and readiness summaries;
- `agent plan`: Studio button enable/disable states and next-action explanations;
- `agent run`: background execution, dry-run preview, and audit manifest;
- `events`: replayable activity feed for advanced inspection.

Default mode:

- `control_plane.type=codex`;
- `autonomy.level=L1` for previews;
- `autonomy.level=L2` only when the user clicks an explicit execution action;
- local model remains `worker_model.role=action_decider`.

Human gates remain visible in product language:

```text
Needs your review
3 generated questions must be checked before benchmarking.
```

The product must not expose "blocked_human" as the main copy.

## Navigation

V0 routes or top-level screens:

- `/notebooks`: notebook list;
- `/notebooks/:id`: default notebook workspace;
- `/notebooks/:id/sources`: source management;
- `/notebooks/:id/ask`: chat with sources;
- `/notebooks/:id/read/:sourceId`: clean HTML reader;
- `/notebooks/:id/evidence`: evidence browser;
- `/notebooks/:id/review`: human review queue;
- `/notebooks/:id/studio`: output studio;
- `/notebooks/:id/runs/:runId`: advanced run manifest details.

Routes can be implemented later, but the mental model should stay stable.

## Visual Tone

The UI should be calmer than a dashboard and denser than a marketing page.

Design rules:

- no oversized hero;
- no engineering-first status grid as the default view;
- sources and citations should feel tangible;
- Studio outputs should feel like documents, matrices, and review packs;
- agent internals should be one click away, not always visible.

## What V0 Is Not

V0 is not:

- a generic file search product;
- a PDF chat clone;
- a Zotero replacement;
- a benchmark leaderboard UI first;
- a local-model autonomous agent first;
- a developer control panel first.

## Success Criteria

V0 product shape is successful if a new user can understand the product in one minute:

1. Put sources into a notebook.
2. Ask and read with citations.
3. Turn useful answers into evidence-backed outputs.
4. Review uncertain claims before trusting them.
5. Export or benchmark when ready.

The advanced runtime remains present, but the user experiences it as trustworthy notebook behavior, not as agent plumbing.

## Implementation Implications

Near-term implementation should prioritize:

1. a static clickable prototype or local web UI using the three-pane shell;
2. a notebook list backed by existing workspace/evidence state;
3. Studio cards wired to `agent plan`;
4. a dry-run `agent run` drawer or modal;
5. source reader links from citations to clean HTML anchors.

Do not add more agent actions before the notebook shell exists. The shell is the product container for future iteration.
