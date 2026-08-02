# ScanSci Pi vs Deep Agents A/B

Status: complete (2/2 valid runs).

| Architecture | Runs | Success | Bad citations | Mean latency | P95 latency | Total tokens |
|---|---:|---:|---:|---:|---:|---:|
| pi | 1 | 0.0% | 0.0% | 40.79s | 40.79s | 2288 |
| deep | 1 | 0.0% | 0.0% | 34.43s | 34.43s | 2729 |

## Reliability

Pi uses persisted Pi JSONL sessions, SDK abort, restart recovery, and native context compaction. The current Deep Agents integration has summarization middleware but no durable checkpointer or cancellation API.

The provider reports token usage but no billed USD. Monetary cost is unavailable, so tokens are the comparison proxy.
