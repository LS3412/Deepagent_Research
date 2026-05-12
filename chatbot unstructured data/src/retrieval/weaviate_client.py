"""Weaviate v4 client + schema bootstrap.

We provide our own vectors (vectorizer=none), so the collection is just a typed
metadata store with HNSW + BM25.
"""
from __future__ import annotations

from functools import lru_cache

import weaviate
from weaviate.auth import AuthApiKey
from weaviate.classes.config import Configure, DataType, Property, Tokenization

from src.config import get_settings


@lru_cache(maxsize=1)
def get_client() -> weaviate.WeaviateClient:
    s = get_settings()
    auth = AuthApiKey(s.weaviate_api_key) if s.weaviate_api_key else None
    client = weaviate.connect_to_local(
        host=s.weaviate_host,
        port=s.weaviate_http_port,
        grpc_port=s.weaviate_grpc_port,
        auth_credentials=auth,
    )
    return client


def close_client() -> None:
    try:
        c = get_client()
        c.close()
    except Exception:
        pass
    try:
        get_client.cache_clear()
    except Exception:
        pass


def ensure_schema() -> None:
    s = get_settings()
    client = get_client()
    name = s.weaviate_collection
    if client.collections.exists(name):
        # Attempt to add any missing v2 properties to an existing collection
        migrate_schema(name)
        return
    client.collections.create(
        name=name,
        vector_config=Configure.Vectors.self_provided(
            vector_index_config=Configure.VectorIndex.hnsw(),
        ),
        inverted_index_config=Configure.inverted_index(
            index_property_length=True,
        ),
        properties=[
            Property(name="text", data_type=DataType.TEXT,
                     tokenization=Tokenization.WORD),
            Property(name="tenant_id", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="doc_sha256", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="source_uri", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="file_name", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="mime_type", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="format", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="page", data_type=DataType.INT),
            Property(name="section", data_type=DataType.TEXT),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="language", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="tags", data_type=DataType.TEXT_ARRAY,
                     tokenization=Tokenization.FIELD),
            Property(name="created_at", data_type=DataType.DATE),
            Property(name="ingested_at", data_type=DataType.DATE),
            # JSON-encoded blob; we never filter on it, only return it.
            Property(name="extra_json", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            # v2 enriched metadata
            Property(name="element_type", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="hierarchy_path", data_type=DataType.TEXT,
                     tokenization=Tokenization.WHITESPACE),
            Property(name="ancestral_headings", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="breadcrumb", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
            Property(name="hierarchy_depth", data_type=DataType.INT),
            Property(name="keywords", data_type=DataType.TEXT_ARRAY,
                     tokenization=Tokenization.WHITESPACE),
            Property(name="confidence_score", data_type=DataType.NUMBER),
            Property(name="is_duplicate", data_type=DataType.BOOL),
            Property(name="duplicate_of", data_type=DataType.TEXT,
                     tokenization=Tokenization.FIELD),
        ],
    )


# v2 properties that may be absent in collections created before v2
_V2_PROPERTIES: list[Property] = [
    Property(name="element_type",      data_type=DataType.TEXT,        tokenization=Tokenization.FIELD),
    Property(name="hierarchy_path",    data_type=DataType.TEXT,        tokenization=Tokenization.WHITESPACE),
    Property(name="ancestral_headings",data_type=DataType.TEXT,        tokenization=Tokenization.FIELD),
    Property(name="breadcrumb",        data_type=DataType.TEXT,        tokenization=Tokenization.FIELD),
    Property(name="hierarchy_depth",   data_type=DataType.INT),
    Property(name="keywords",          data_type=DataType.TEXT_ARRAY,  tokenization=Tokenization.WHITESPACE),
    Property(name="confidence_score",  data_type=DataType.NUMBER),
    Property(name="is_duplicate",      data_type=DataType.BOOL),
    Property(name="duplicate_of",      data_type=DataType.TEXT,        tokenization=Tokenization.FIELD),
]


def migrate_schema(collection_name: str | None = None) -> None:
    """Add any v2 properties that are absent from an existing collection.

    Safe to call repeatedly; silently skips properties that already exist.
    """
    import logging as _logging
    log = _logging.getLogger(__name__)

    s = get_settings()
    name = collection_name or s.weaviate_collection
    client = get_client()
    if not client.collections.exists(name):
        return

    coll = client.collections.get(name)
    existing = {p.name for p in coll.config.get().properties}

    for prop in _V2_PROPERTIES:
        if prop.name not in existing:
            try:
                coll.config.add_property(prop)
                log.info("migrate_schema: added property '%s' to %s", prop.name, name)
            except Exception as exc:
                log.warning(
                    "migrate_schema: could not add property '%s' to %s: %s",
                    prop.name, name, exc,
                )
