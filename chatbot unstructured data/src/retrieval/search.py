"""Search functions over the Weaviate Document collection.

Always require `tenant_id` to enforce isolation. The agent's tools are thin
wrappers over these functions.

v2 additions:
    _base_filter  — 5 new filter keys: element_type, hierarchy_path_contains,
                    hierarchy_depth_max, confidence_min, keywords
                  — always excludes near-duplicate chunks (is_duplicate=false)
    _format_hit   — 5 new returned fields: element_type, hierarchy_path,
                    breadcrumb, keywords, confidence_score
    hybrid_search — optional Rerank via Weaviate reranker module
"""
from __future__ import annotations

import logging
from typing import Any

from weaviate.classes.query import Filter, MetadataQuery

from src.config import get_settings
from src.llm import get_embeddings
from src.retrieval.weaviate_client import get_client

log = logging.getLogger(__name__)


def _base_filter(tenant_id: str, filters: dict[str, Any] | None) -> Filter:
    f = Filter.by_property("tenant_id").equal(tenant_id)
    # Always hide near-duplicates from search results
    f = f & Filter.by_property("is_duplicate").equal(False)

    if not filters:
        return f

    if v := filters.get("file_name"):
        f = f & Filter.by_property("file_name").equal(v)
    if v := filters.get("doc_sha256"):
        f = f & Filter.by_property("doc_sha256").equal(v)
    if v := filters.get("format"):
        f = f & Filter.by_property("format").equal(v)
    if v := filters.get("language"):
        f = f & Filter.by_property("language").equal(v)
    if v := filters.get("tags"):
        if isinstance(v, str):
            v = [v]
        f = f & Filter.by_property("tags").contains_any(list(v))
    if pr := filters.get("page_range"):
        if isinstance(pr, (list, tuple)) and len(pr) == 2:
            lo, hi = pr
            if lo is not None:
                f = f & Filter.by_property("page").greater_or_equal(int(lo))
            if hi is not None:
                f = f & Filter.by_property("page").less_or_equal(int(hi))
    # v2 filters
    if v := filters.get("element_type"):
        f = f & Filter.by_property("element_type").equal(v)
    if v := filters.get("hierarchy_path_contains"):
        f = f & Filter.by_property("hierarchy_path").like(f"*{v}*")
    if v := filters.get("hierarchy_depth_max"):
        f = f & Filter.by_property("hierarchy_depth").less_or_equal(int(v))
    if v := filters.get("confidence_min"):
        f = f & Filter.by_property("confidence_score").greater_or_equal(float(v))
    if v := filters.get("keywords"):
        if isinstance(v, str):
            v = [v]
        f = f & Filter.by_property("keywords").contains_any(list(v))
    return f


def _format_hit(obj) -> dict[str, Any]:
    p = obj.properties
    md = obj.metadata
    return {
        "text":             p.get("text"),
        "file_name":        p.get("file_name"),
        "page":             p.get("page"),
        "section":          p.get("section"),
        "chunk_index":      p.get("chunk_index"),
        "format":           p.get("format"),
        "tags":             p.get("tags") or [],
        "doc_sha256":       p.get("doc_sha256"),
        "source_uri":       p.get("source_uri"),
        "score":            getattr(md, "score", None),
        "distance":         getattr(md, "distance", None),
        # v2 enriched fields
        "element_type":     p.get("element_type"),
        "hierarchy_path":   p.get("hierarchy_path"),
        "breadcrumb":       p.get("breadcrumb"),
        "keywords":         p.get("keywords") or [],
        "confidence_score": p.get("confidence_score"),
    }


def hybrid_search(
    query: str,
    tenant_id: str,
    k: int | None = None,
    filters: dict[str, Any] | None = None,
    alpha: float | None = None,
    rerank: bool = False,
) -> list[dict[str, Any]]:
    s = get_settings()
    coll = get_client().collections.get(s.weaviate_collection)
    qvec = get_embeddings().embed_query(query)

    query_kwargs: dict[str, Any] = dict(
        query=query,
        vector=qvec,
        alpha=alpha if alpha is not None else s.hybrid_alpha,
        limit=k or s.retrieval_top_k,
        filters=_base_filter(tenant_id, filters),
        return_metadata=MetadataQuery(score=True, distance=True),
    )

    # Optional Weaviate reranker module (requires reranker-transformers in Docker)
    if rerank:
        try:
            from weaviate.classes.query import Rerank  # type: ignore
            query_kwargs["rerank"] = Rerank(prop="text", query=query)
        except (ImportError, Exception) as exc:
            log.debug("rerank unavailable: %s", exc)

    try:
        res = coll.query.hybrid(**query_kwargs)
    except Exception as exc:
        # Reranker module not enabled in this Weaviate instance — retry without it
        if "rerank" in str(exc).lower() and "rerank" in query_kwargs:
            log.warning("Weaviate reranker module not enabled; retrying without rerank")
            del query_kwargs["rerank"]
            res = coll.query.hybrid(**query_kwargs)
        else:
            raise

    hits = [_format_hit(o) for o in res.objects]

    # Drop hits whose relevance score is below the configured threshold.
    # This prevents the agent from answering off-topic questions using the
    # "closest" (but still unrelated) chunks in the database.
    min_score = s.retrieval_min_score
    before = len(hits)
    hits = [h for h in hits if (h.get("score") or 0.0) >= min_score]
    if before != len(hits):
        log.info(
            "score filter: dropped %d/%d hits (min_score=%.2f)",
            before - len(hits), before, min_score,
        )

    return hits


def list_documents(
    tenant_id: str,
    prefix: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    s = get_settings()
    coll = get_client().collections.get(s.weaviate_collection)
    f = Filter.by_property("tenant_id").equal(tenant_id)
    if prefix:
        f = f & Filter.by_property("file_name").like(f"{prefix}*")
    res = coll.query.fetch_objects(
        filters=f,
        limit=limit,
        return_properties=["file_name", "doc_sha256", "format", "mime_type"],
    )
    seen: dict[str, dict[str, Any]] = {}
    for o in res.objects:
        sha = o.properties.get("doc_sha256")
        if not sha or sha in seen:
            continue
        seen[sha] = {
            "file_name": o.properties.get("file_name"),
            "doc_sha256": sha,
            "format": o.properties.get("format"),
            "mime_type": o.properties.get("mime_type"),
        }
    return list(seen.values())


def get_corpus_stats(tenant_id: str, limit: int = 2000) -> dict[str, Any]:
    """Fetch chunk-level stats for the Ingestion Dashboard.

    Returns a dict with:
        total_docs, total_chunks, unique_languages, avg_confidence,
        element_type_counts, confidence_buckets, format_counts, documents
    """
    s = get_settings()
    coll = get_client().collections.get(s.weaviate_collection)

    props = [
        "doc_sha256", "file_name", "format", "mime_type",
        "element_type", "language", "confidence_score",
        "is_duplicate", "keywords", "ingested_at",
    ]
    res = coll.query.fetch_objects(
        filters=Filter.by_property("tenant_id").equal(tenant_id),
        limit=limit,
        return_properties=props,
    )

    total_chunks = len(res.objects)
    docs: dict[str, dict] = {}
    element_type_counts: dict[str, int] = {}
    confidence_sum = 0.0
    confidence_count = 0
    confidence_buckets: dict[str, int] = {
        "≥ 0.9": 0, "0.7–0.9": 0, "0.5–0.7": 0, "< 0.5": 0
    }
    format_counts: dict[str, int] = {}
    languages: set[str] = set()
    keyword_freq: dict[str, int] = {}

    for obj in res.objects:
        p = obj.properties
        sha = p.get("doc_sha256") or ""
        if sha and sha not in docs:
            docs[sha] = {
                "file_name": p.get("file_name", ""),
                "format": p.get("format", ""),
                "mime_type": p.get("mime_type", ""),
                "ingested_at": str(p.get("ingested_at", ""))[:19],
                "chunks": 0,
            }
        if sha:
            docs[sha]["chunks"] = docs[sha].get("chunks", 0) + 1

        et = p.get("element_type") or "Unknown"
        element_type_counts[et] = element_type_counts.get(et, 0) + 1

        fmt = p.get("format") or "unknown"
        format_counts[fmt] = format_counts.get(fmt, 0) + 1

        lang = p.get("language")
        if lang:
            languages.add(lang)

        sc = p.get("confidence_score")
        if sc is not None:
            confidence_sum += float(sc)
            confidence_count += 1
            if sc >= 0.9:
                confidence_buckets["≥ 0.9"] += 1
            elif sc >= 0.7:
                confidence_buckets["0.7–0.9"] += 1
            elif sc >= 0.5:
                confidence_buckets["0.5–0.7"] += 1
            else:
                confidence_buckets["< 0.5"] += 1

        for kw in (p.get("keywords") or []):
            keyword_freq[kw] = keyword_freq.get(kw, 0) + 1

    avg_confidence = round(confidence_sum / confidence_count, 3) if confidence_count else 0.0
    top_keywords = sorted(keyword_freq.items(), key=lambda x: -x[1])[:20]

    return {
        "total_docs": len(docs),
        "total_chunks": total_chunks,
        "unique_languages": sorted(languages),
        "avg_confidence": avg_confidence,
        "element_type_counts": element_type_counts,
        "confidence_buckets": confidence_buckets,
        "format_counts": format_counts,
        "top_keywords": dict(top_keywords),
        "documents": list(docs.values()),
    }


def get_chunk(
    doc_sha256: str,
    chunk_index: int,
    tenant_id: str,
) -> dict[str, Any] | None:
    s = get_settings()
    coll = get_client().collections.get(s.weaviate_collection)
    res = coll.query.fetch_objects(
        filters=Filter.by_property("doc_sha256").equal(doc_sha256)
        & Filter.by_property("chunk_index").equal(chunk_index)
        & Filter.by_property("tenant_id").equal(tenant_id),
        limit=1,
    )
    if not res.objects:
        return None
    return _format_hit(res.objects[0])
