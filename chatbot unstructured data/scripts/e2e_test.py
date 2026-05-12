"""Full end-to-end test: ingest sample.md → query Weaviate.

Stages tested:
  1. Parse      (UnstructuredParser)
  2. Chunk      (UnstructuredElementChunker)
  3. Enrich     (Hierarchy + Keywords + Language + Confidence)
  4. Dedup      (MinHash LSH)
  5. Embed      (AsyncOllamaBatchEmbedder → Ollama bge-m3)
  6. Store      (WeaviateSink)
  7. Search     (hybrid_search with new filters)
"""
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from pathlib import Path

# ── 1. Ingest ──────────────────────────────────────────────────────────────
print("=" * 60)
print("STAGE 1-6: Ingest sample.md")
print("=" * 60)

from src.ingestion.pipeline import ingest_path
from src.ingestion.sink import WeaviateSink

sink = WeaviateSink()
sink.ensure_schema()

# Delete any previous test run so we always get fresh results
from src.retrieval.weaviate_client import get_client
from src.config import get_settings
s = get_settings()
coll = get_client().collections.get(s.weaviate_collection)
from weaviate.classes.query import Filter
coll.data.delete_many(
    where=Filter.by_property("tenant_id").equal("e2e_test")
)
print("Cleared previous e2e_test data")

# Also clear the LSH index so same-document re-ingest isn't flagged as duplicate
lsh_path = Path(s.dedup_index_path)
if lsh_path.exists():
    lsh_path.unlink()
    print("Cleared LSH index")

result = ingest_path(
    "./data/sample.md",
    tenant_id="e2e_test",
    tags=["test", "sample"],
    sink=sink,
)

print()
print(f"  file_name      : {result.file_name}")
print(f"  doc_sha256     : {result.doc_sha256[:16]}...")
print(f"  chunks_indexed : {result.chunks_indexed}")
print(f"  skipped        : {result.skipped}  (reason: {result.reason})")

if result.skipped:
    print("\nERROR: ingest was skipped unexpectedly")
    sys.exit(1)
if result.chunks_indexed == 0:
    print("\nERROR: no chunks were indexed")
    sys.exit(1)

print("\nStages 1-6 PASSED")

# ── 2. Search ───────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STAGE 7: Search (hybrid + new filters)")
print("=" * 60)

from src.retrieval.search import hybrid_search

queries = [
    ("basic query",         "what is this document about",               {}),
    ("confidence filter",   "chatbot",                                   {"confidence_min": 0.7}),
    ("element_type filter", "document title",                            {"element_type": "Title"}),
]

all_passed = True
for label, query, filters in queries:
    hits = hybrid_search(query, tenant_id="e2e_test", k=3, filters=filters)
    status = "PASS" if hits else "FAIL (no results)"
    if not hits:
        all_passed = False
    print(f"\n  [{status}] {label}: '{query}'")
    for i, h in enumerate(hits[:2], 1):
        kw  = (h.get("keywords") or [])[:3]
        print(f"    hit {i}: element_type={h.get('element_type'):<15} "
              f"confidence={h.get('confidence_score'):.2f}  "
              f"kw={kw}")
        print(f"           text: {h.get('text','')[:80].strip()}...")

# ── 3. New-field verification ───────────────────────────────────────────────
print()
print("=" * 60)
print("STAGE 7b: Verify new v2 fields are stored in Weaviate")
print("=" * 60)

hits = hybrid_search("chatbot", tenant_id="e2e_test", k=5)
v2_fields = ["element_type", "hierarchy_path", "breadcrumb",
             "keywords", "confidence_score"]

for field in v2_fields:
    values = [h.get(field) for h in hits if h.get(field) is not None]
    status = "PASS" if values else "FAIL (all None)"
    if not values:
        all_passed = False
    print(f"  [{status}] {field}: {values[0] if values else 'N/A'!r}")

# ── Summary ──────────────────────────────────────────────────────────────────
print()
print("=" * 60)
if all_passed:
    print("ALL TESTS PASSED — v2 pipeline is fully operational")
else:
    print("SOME TESTS FAILED — check output above")
    sys.exit(1)
print("=" * 60)
