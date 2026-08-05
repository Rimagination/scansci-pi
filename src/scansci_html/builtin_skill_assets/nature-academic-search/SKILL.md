---
name: nature-academic-search
description: Structured academic literature discovery and citation verification across Crossref, OpenAlex, PubMed, Europe PMC, arXiv, Semantic Scholar, and configured providers. Use for finding papers, checking DOI metadata, tracing citations, or building a source-backed search set.
---

# Nature Academic Search

Run a reproducible, source-aware literature search.

1. Convert the request into topic, population or system, intervention or method, outcome, time range, venue, and evidence-type constraints.
2. Search multiple configured scholarly sources through ScanSci. Keep discovery metadata separate from locally indexed evidence.
3. Deduplicate by DOI, PMID, arXiv ID, and normalized title. Preserve the original provider and URL for every candidate.
4. Verify high-value records against Crossref or another authoritative metadata source. Flag title, author, year, journal, and DOI conflicts instead of silently choosing one.
5. Report a table with relevance rationale, source, identifier, access route, verification status, and next action. A candidate becomes evidence only after lawful acquisition and indexing into the selected ScanSci evidence store.
6. For citation questions, distinguish total citations, strict self-citations, citing papers, and citation-count provenance. Do not infer prestige from a single citation metric.

Prefer primary papers for claims, reviews for landscape framing, and official repository or publisher pages for metadata. Never fabricate a DOI or claim that a paper was read when only its abstract or metadata was available.

This is a ScanSci adaptation of the `nature-academic-search` workflow from Yuan1z0825/nature-skills. Provider credentials remain outside the repository.
