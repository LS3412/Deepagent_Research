"""Weaviate sink — batch upsert with idempotency on doc_sha256."""
from __future__ import annotations

import json
from typing import Iterable

from weaviate.classes.query import Filter

from src.config import get_settings
from src.ingestion.interfaces import IngestRecord
from src.retrieval.weaviate_client import ensure_schema, get_client


class WeaviateSink:
    def __init__(self) -> None:
        self._collection_name = get_settings().weaviate_collection

    def ensure_schema(self) -> None:
        ensure_schema()

    def already_indexed(self, doc_sha256: str, tenant_id: str) -> bool:
        coll = get_client().collections.get(self._collection_name)
        res = coll.query.fetch_objects(
            filters=Filter.by_property("doc_sha256").equal(doc_sha256)
            & Filter.by_property("tenant_id").equal(tenant_id),
            limit=1,
        )
        return bool(res.objects)

    def delete_doc(self, doc_sha256: str, tenant_id: str) -> int:
        coll = get_client().collections.get(self._collection_name)
        res = coll.data.delete_many(
            where=Filter.by_property("doc_sha256").equal(doc_sha256)
            & Filter.by_property("tenant_id").equal(tenant_id),
        )
        return getattr(res, "successful", 0) or 0

    def upsert(self, records: list[IngestRecord]) -> int:
        if not records:
            return 0
        coll = get_client().collections.get(self._collection_name)
        with coll.batch.dynamic() as batch:
            for r in records:
                batch.add_object(
                    properties={
                        "text": r.text,
                        "tenant_id": r.tenant_id,
                        "doc_sha256": r.doc_sha256,
                        "source_uri": r.source_uri,
                        "file_name": r.file_name,
                        "mime_type": r.mime_type,
                        "format": r.format,
                        "page": r.page,
                        "section": r.section,
                        "chunk_index": r.chunk_index,
                        "language": r.language,
                        "tags": r.tags,
                        "created_at": r.created_at,
                        "ingested_at": r.ingested_at,
                        "extra_json": json.dumps(r.extra, default=str),
                        # v2 enriched fields
                        "element_type":      r.element_type,
                        "hierarchy_path":    r.hierarchy_path,
                        "ancestral_headings": json.dumps(r.ancestral_headings, default=str),
                        "breadcrumb":        r.breadcrumb,
                        "hierarchy_depth":   r.hierarchy_depth,
                        "keywords":          r.keywords,
                        "confidence_score":  r.confidence_score,
                        "is_duplicate":      r.is_duplicate,
                        "duplicate_of":      r.duplicate_of,
                    },
                    vector=r.vector if r.vector else None,
                )
        return len(records)
