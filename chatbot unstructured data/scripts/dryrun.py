"""Dry-run test: stages 1-4 of the v2 pipeline (no Ollama/Weaviate needed)."""
from pathlib import Path
from src.config import get_settings
from src.ingestion.interfaces import RawDocument
from src.ingestion.parsers.unstructured_parser import UnstructuredParser
from src.ingestion.chunker import get_chunker
from src.ingestion.enricher import build_enricher_chain
from src.ingestion.deduplicator import MinHashDeduplicator

s = get_settings()
sample = Path("./data/sample.md")
content = sample.read_bytes()

raw = RawDocument(
    source_uri=sample.resolve().as_uri(),
    file_name=sample.name,
    mime_type="text/markdown",
    content=content,
    tenant_id="test",
)

# Stage 1: Parse
parser = UnstructuredParser()
blocks = list(parser.parse(raw))
print(f"Parsed {len(blocks)} blocks")

# Stage 2: Chunk
chunker = get_chunker(s)
chunks = list(chunker.chunk(blocks))
print(f"Chunked into {len(chunks)} chunks  [{type(chunker).__name__}]")

# Stage 3: Enrich
chain = build_enricher_chain()
chunks = chain.enrich_all(chunks, raw)
# Find first chunk with actual keywords (skip Title/Header which are too short)
for i, c in enumerate(chunks):
    ex = c.extra
    kw = ex.get("keywords", [])
    print(
        f"Enrich chunk[{i}]: element_type={ex.get('element_type')}, "
        f"lang={ex.get('language')}, kw={kw[:3]}, "
        f"confidence={ex.get('confidence_score')}"
    )
    if kw:
        break

# Stage 4: Dedup
dedup = MinHashDeduplicator(threshold=0.85)
chunks = dedup.process(chunks, "test-sha256")
dupes = sum(1 for c in chunks if c.extra.get("is_duplicate"))
print(f"Dedup: {len(chunks)} chunks, {dupes} near-duplicates flagged")
print()
print("Dry-run PASSED — pipeline stages 1-4 work correctly")
