# ScanSci Pi vs Deep Agents A/B

Status: incomplete (0/144 valid runs).

| Architecture | Runs | Success | Bad citations | Mean latency | P95 latency | Total tokens |
|---|---:|---:|---:|---:|---:|---:|
| pi | 0 | 0.0% | 0.0% | 0.00s | 0.00s | 0 |
| deep | 0 | 0.0% | 0.0% | 0.00s | 0.00s | 0 |

## Reliability

Pi uses persisted Pi JSONL sessions, SDK abort, restart recovery, and native context compaction. The current Deep Agents integration has summarization middleware but no durable checkpointer or cancellation API.

The provider reports token usage but no billed USD. Monetary cost is unavailable, so tokens are the comparison proxy.
