from __future__ import annotations

from typing import Any


def fuse_ranked_hits(
    route_results: list[dict[str, Any]],
    *,
    rank_constant: float = 60.0,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Fuse ranked retrieval lists with weighted reciprocal rank fusion."""

    merged: dict[str, dict[str, Any]] = {}
    for route_index, route_result in enumerate(route_results, start=1):
        query = str(route_result.get("query", "")).strip()
        label = str(route_result.get("label", "")).strip() or f"query-{route_index}"
        route_weight = _positive_float(route_result.get("weight"), default=1.0)
        hits = list(route_result.get("hits", []) or [])
        for rank, raw_hit in enumerate(hits, start=1):
            hit = dict(raw_hit)
            evidence_id = str(hit.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            contribution = route_weight / (float(rank_constant) + float(rank))
            existing = merged.get(evidence_id)
            if existing is None:
                existing = dict(hit)
                existing["rrf_score"] = 0.0
                existing["best_route_score"] = float(hit.get("score", 0.0) or 0.0)
                existing["fusion_routes"] = []
                existing["retrieval_queries"] = []
                existing["route_ranks"] = {}
                merged[evidence_id] = existing
            else:
                hit_score = float(hit.get("score", 0.0) or 0.0)
                if hit_score > float(existing.get("best_route_score", 0.0) or 0.0):
                    preserved = {
                        "rrf_score": existing.get("rrf_score", 0.0),
                        "best_route_score": hit_score,
                        "fusion_routes": list(existing.get("fusion_routes", []) or []),
                        "retrieval_queries": list(existing.get("retrieval_queries", []) or []),
                        "route_ranks": dict(existing.get("route_ranks", {}) or {}),
                    }
                    existing.update(hit)
                    existing.update(preserved)

            existing["rrf_score"] = float(existing.get("rrf_score", 0.0) or 0.0) + contribution
            existing["score"] = float(existing.get("rrf_score", 0.0) or 0.0)
            existing["fts_score"] = max(float(existing.get("fts_score", 0.0) or 0.0), float(hit.get("fts_score", 0.0) or 0.0))
            existing["dense_score"] = max(
                float(existing.get("dense_score", 0.0) or 0.0),
                float(hit.get("dense_score", 0.0) or 0.0),
            )

            fusion_routes = [str(value) for value in existing.get("fusion_routes", []) or []]
            if label not in fusion_routes:
                fusion_routes.append(label)
            existing["fusion_routes"] = fusion_routes

            retrieval_queries = [str(value) for value in existing.get("retrieval_queries", []) or []]
            if query and query not in retrieval_queries:
                retrieval_queries.append(query)
            existing["retrieval_queries"] = retrieval_queries

            route_ranks = dict(existing.get("route_ranks", {}) or {})
            route_ranks[label] = min(int(route_ranks.get(label, rank) or rank), rank)
            existing["route_ranks"] = route_ranks

            routes = {str(value) for value in existing.get("routes", []) or [] if str(value)}
            routes.update(str(value) for value in hit.get("routes", []) or [] if str(value))
            routes.add(label)
            existing["routes"] = sorted(routes)

    fused = sorted(
        merged.values(),
        key=lambda hit: (
            -float(hit.get("rrf_score", 0.0) or 0.0),
            -float(hit.get("best_route_score", 0.0) or 0.0),
            str(hit.get("evidence_id", "")),
        ),
    )
    if limit > 0:
        return fused[: int(limit)]
    return fused


def _positive_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed
