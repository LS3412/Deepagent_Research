# Complete Ingestion Pipeline — End-to-End Walkthrough

> Trace a real document through all 6 stages of the ingestion pipeline with concrete examples at every transformation point.

---

## Overview

The DeepAgent ingestion pipeline processes raw files into searchable, enriched chunks stored in Weaviate. This guide follows one example document through all stages.

```
FILE INPUT
    ↓
[Stage 1] Parse      → Detect format, extract blocks with metadata
    ↓
[Stage 2] Chunk      → Split into semantic chunks, preserve hierarchy
    ↓
[Stage 3] Enrich     → Add keywords, language, hierarchy, confidence
    ↓
[Stage 4] Deduplicate → Find near-duplicates, skip embedding for dupes
    ↓
[Stage 5] Embed      → Generate vector embeddings (bge-m3, async)
    ↓
[Stage 6] Store      → Upsert enriched chunks + vectors to Weaviate
    ↓
SEARCHABLE KB
```

---

## Example Document

**File:** `AWS_Security_Best_Practices.pdf`  
**Size:** 200 KB (5 pages)  
**Content:** Technical guide covering security topics  
**Entry point:** Streamlit UI upload → `ingest_bytes()`

---

## STAGE 1: Parse (Unstructured)

**Purpose:** Detect file format, extract content blocks with structural metadata.

**Library:** unstructured[all-docs]  
**Time:** ~2–5 sec (depends on file size)

### Input
```
Raw file bytes (200 KB PDF)
```

### Processing

The **UnstructuredParser** (from `src/ingestion/parsers/unstructured_parser.py`) calls Unstructured's API/library:

```python
from unstructured.partition.pdf import partition_pdf

# Partition strategy: "elements" (default) or "semantic"
blocks = partition_pdf(
    file=content_bytes,
    strategy="elements",  # element-based extraction
    infer_table_structure=True,
    languages=["en"]
)
```

### Output: Blocks

Unstructured returns a list of **Block** objects. Each block has:
- `element_id` — unique ID
- `element_type` — "Title", "Header", "NarrativeText", "Table", "ListItem", "Footer", "Image", etc.
- `text` — content
- `metadata` — page, section, language, parent_id (hierarchy)

**Example blocks extracted from the PDF:**

```python
[
    Block(
        element_id="0",
        element_type="Title",
        text="AWS Security Best Practices",
        metadata={
            "page_number": 1,
            "section": "Title",
            "language": "eng"  # ISO 639-3
        }
    ),
    Block(
        element_id="1",
        element_type="Header",
        text="Identity & Access Management",
        metadata={
            "page_number": 2,
            "section": "IAM",
            "language": "eng",
            "parent_id": "0"  # hierarchical parent
        }
    ),
    Block(
        element_id="2",
        element_type="NarrativeText",
        text="Use IAM roles instead of long-term access keys. Roles are "
             "temporary credentials that expire automatically, reducing "
             "the risk of credential leakage. Implement least privilege "
             "access control policies across all AWS services.",
        metadata={
            "page_number": 2,
            "section": "Best Practices",
            "language": "eng",
            "parent_id": "1"  # child of "Identity & Access Management"
        }
    ),
    Block(
        element_id="3",
        element_type="ListItem",
        text="Rotate access keys regularly",
        metadata={
            "page_number": 2,
            "section": "Best Practices",
            "language": "eng",
            "parent_id": "1"
        }
    ),
    Block(
        element_id="4",
        element_type="Header",
        text="Encryption Best Practices",
        metadata={
            "page_number": 3,
            "section": "Encryption",
            "language": "eng",
            "parent_id": "0"
        }
    ),
    # ... 407 more blocks
]

# Total: 412 blocks extracted from 5-page PDF
```

### Stage 1 Summary

| Input | Output | Count |
|-------|--------|-------|
| 200 KB PDF file | Block[] with element_type, hierarchy, page, text | 412 blocks |
| Binary bytes | Structured + metadata | ~2–5 sec |

---

## STAGE 2: Chunk (Split into Semantic Units)

**Purpose:** Split blocks into semantically meaningful chunks while preserving hierarchy and element type.

**Library:** langchain-text-splitters (UnstructuredElementChunker) or sentence-transformers (SemanticChunker)  
**Time:** ~1–3 sec

### Input

```python
blocks: list[Block] = [412 blocks from Stage 1]
```

### Processing

The **chunker** (from `src/ingestion/chunker.py`) groups blocks intelligently:

```python
# Configuration (from config.py)
chunk_size = 800           # target tokens per chunk
chunk_overlap = 120        # overlap between chunks
strategy = "element"       # or "semantic"

# Chunking logic for UnstructuredElementChunker
# - Groups blocks by element_type and hierarchy
# - Respects semantic boundaries (don't split mid-sentence)
# - Preserves heading chain (parent_id references)
```

### Output: Chunks

Chunks are a **higher-level abstraction** than blocks:

```python
# Example chunks created from blocks:

chunks = [
    Chunk(
        chunk_index=0,
        text="AWS Security Best Practices",
        section="Title",
        page=1,
        extra={
            "element_type": "Title",
            "heading_chain_texts": ["AWS Security Best Practices"],
            "source_uri": "upload://AWS_Security_Best_Practices.pdf",
            "file_name": "AWS_Security_Best_Practices.pdf",
            "mime_type": "application/pdf"
        }
    ),
    Chunk(
        chunk_index=1,
        text="Identity & Access Management",
        section="IAM",
        page=2,
        extra={
            "element_type": "Header",
            "heading_chain_texts": ["AWS Security Best Practices", "Identity & Access Management"],
            "source_uri": "upload://AWS_Security_Best_Practices.pdf",
            "file_name": "AWS_Security_Best_Practices.pdf",
            "mime_type": "application/pdf"
        }
    ),
    Chunk(
        chunk_index=2,
        text="Use IAM roles instead of long-term access keys. Roles are "
             "temporary credentials that expire automatically, reducing "
             "the risk of credential leakage. Implement least privilege "
             "access control policies across all AWS services.",
        section="Best Practices",
        page=2,
        extra={
            "element_type": "NarrativeText",
            "heading_chain_texts": ["AWS Security Best Practices", "Identity & Access Management", "Best Practices"],
            "source_uri": "upload://AWS_Security_Best_Practices.pdf",
            "file_name": "AWS_Security_Best_Practices.pdf",
            "mime_type": "application/pdf"
        }
    ),
    Chunk(
        chunk_index=3,
        text="Rotate access keys regularly. Store keys in a secure vault or secrets manager. Never hardcode credentials in application code.",
        section="Best Practices",
        page=2,
        extra={
            "element_type": "ListItem",
            "heading_chain_texts": ["AWS Security Best Practices", "Identity & Access Management", "Best Practices"],
            "source_uri": "upload://AWS_Security_Best_Practices.pdf",
            "file_name": "AWS_Security_Best_Practices.pdf",
            "mime_type": "application/pdf"
        }
    ),
    # ... 123 more chunks
]

# Total: 127 chunks from 412 blocks
```

### Stage 2 Summary

| Input | Output | Transformation |
|-------|--------|---|
| 412 blocks | 127 chunks | Grouped by element type + hierarchy |
| Structured text | Semantic units (~500 words avg) | Preserves heading_chain_texts |
| ~1–3 sec | Ready for enrichment | ~31% reduction (dedup later removes more) |

---

## STAGE 3: Enrich (Add Metadata)

**Purpose:** Attach semantic metadata to every chunk for better search, filtering, and ranking.

**Enrichers:** HierarchyEnricher → KeywordEnricher → LanguageEnricher → ConfidenceEnricher  
**Time:** ~15–20 sec (dominated by keyword extraction)

### Input

```python
chunks: list[Chunk] = [127 chunks from Stage 2]
raw_doc: RawDocument  # metadata: source_uri, file_name, tenant_id, etc.
```

### Processing

Four enrichers run sequentially on each chunk:

#### 3a. HierarchyEnricher

**Transforms heading chain into navigable structure:**

```python
# Input for chunk_index=2
heading_chain_texts = ["AWS Security Best Practices", "Identity & Access Management", "Best Practices"]
section = "Best Practices"

# Output
chunk.extra["ancestral_headings"] = [
    {"level": 0, "text": "AWS Security Best Practices"},
    {"level": 1, "text": "Identity & Access Management"},
    {"level": 2, "text": "Best Practices"}
]
chunk.extra["hierarchy_path"] = "AWS Security Best Practices > Identity & Access Management > Best Practices"
chunk.extra["breadcrumb"] = "AWS Security B / Identity & Acces / Best Practic"
chunk.extra["hierarchy_depth"] = 2
```

#### 3b. KeywordEnricher

**Extracts semantic keyphrases using KeyBERT + bge-m3:**

```python
# Input
text = "Use IAM roles instead of long-term access keys. Roles are temporary..."

# Processing (KeyBERT with Ollama bge-m3 backend)
# - Embed chunk text with bge-m3 (local Ollama, no HF download)
# - Find top-5 keyphrases by semantic similarity
# - Filter English stop words

# Output
chunk.extra["keywords"] = [
    "IAM roles",
    "access keys",
    "temporary credentials",
    "privilege access",
    "credential leakage"
]
```

#### 3c. LanguageEnricher

**Detects language and normalizes to ISO 639-1:**

```python
# Input
text = "Use IAM roles instead of long-term access keys. Roles are temporary..."

# Processing (langdetect library)
# Fast probabilistic language detection on text > 20 chars

# Output
chunk.extra["language"] = "en"  # ISO 639-1 code
```

#### 3d. ConfidenceEnricher

**Scores chunk reliability based on element type and depth:**

```python
# Input
element_type = "NarrativeText"
hierarchy_depth = 2

# Processing (rule-based)
# Base confidence for "NarrativeText": 0.85
# Penalty for depth: 2 × 0.03 = 0.06
# Final: 0.85 - 0.06 = 0.79

# Output
chunk.extra["confidence_score"] = 0.79
```

### Output: Enriched Chunks

```python
Chunk(
    chunk_index=2,
    text="Use IAM roles instead of long-term access keys. Roles are "
         "temporary credentials that expire automatically, reducing "
         "the risk of credential leakage. Implement least privilege "
         "access control policies across all AWS services.",
    section="Best Practices",
    page=2,
    extra={
        # Original metadata
        "element_type": "NarrativeText",
        "heading_chain_texts": [...],
        "source_uri": "upload://AWS_Security_Best_Practices.pdf",
        "file_name": "AWS_Security_Best_Practices.pdf",
        "mime_type": "application/pdf",
        
        # Enriched metadata (NEW)
        "ancestral_headings": [
            {"level": 0, "text": "AWS Security Best Practices"},
            {"level": 1, "text": "Identity & Access Management"},
            {"level": 2, "text": "Best Practices"}
        ],
        "hierarchy_path": "AWS Security Best Practices > Identity & Access Management > Best Practices",
        "breadcrumb": "AWS Security B / Identity & Acces / Best Practic",
        "hierarchy_depth": 2,
        "keywords": ["IAM roles", "access keys", "temporary credentials", "privilege access", "credential leakage"],
        "language": "en",
        "confidence_score": 0.79
    }
)
```

### Stage 3 Summary

| Enricher | Time | Output Fields |
|----------|------|---|
| HierarchyEnricher | ~1 ms | ancestral_headings, hierarchy_path, breadcrumb, hierarchy_depth |
| KeywordEnricher | ~100 ms/chunk | keywords[] (5 phrases) |
| LanguageEnricher | <1 ms | language (ISO 639-1) |
| ConfidenceEnricher | <0.1 ms | confidence_score (0.0–1.0) |
| **Total** | **~12–15 sec** | **All metadata added** |

---

## STAGE 4: Deduplicate (Near-Duplicate Detection)

**Purpose:** Identify near-duplicate chunks to skip expensive embedding for dupes.

**Library:** datasketch (MinHash LSH)  
**Algorithm:** Jaccard similarity with LSH (O(1) lookup)  
**Time:** ~2–3 sec

### Input

```python
enriched_chunks: list[Chunk] = [127 enriched chunks from Stage 3]
doc_sha256: str = "abc123..."  # SHA256 of entire file
```

### Processing

The **MinHashDeduplicator** (from `src/ingestion/deduplicator.py`) compares each chunk against existing chunks in the LSH index:

```python
from datasketch import MinHash, MinHashLSH

# Configuration
threshold = 0.85        # Jaccard similarity threshold
num_perm = 128         # Hash functions (trade-off: accuracy vs speed)
index_path = "./data/lsh_index.pkl"

# For each enriched chunk
for chunk in enriched_chunks:
    # 1. Create MinHash signature from chunk text
    mh = MinHash(num_perm=128)
    for word in chunk.text.split():
        mh.update(word.encode('utf8'))
    
    # 2. Query LSH index: "Are there similar chunks already indexed?"
    candidates = lsh_index.query(mh, num_perm)
    
    # 3. Compute Jaccard similarity with candidates
    if any(jaccard_sim > 0.85 for _, jaccard_sim in candidates):
        chunk.extra["is_duplicate"] = True
        chunk.extra["matched_doc_id"] = matched_doc_id
    else:
        chunk.extra["is_duplicate"] = False
    
    # 4. Add this chunk to index for future comparisons
    lsh_index.insert(f"chunk_{chunk.chunk_index}", mh)
```

### Output: Deduplicated Chunks

Most chunks marked as unique; a few marked as duplicates:

```python
# Example: chunk_index=2 (IAM roles chunk)
chunk.extra["is_duplicate"] = False   # Unique chunk

# Example: chunk_index=47 (another chunk that's 87% similar to an existing one)
chunk.extra["is_duplicate"] = True
chunk.extra["matched_doc_id"] = "5f3c8d2a..."  # References similar chunk

# Results across all 127 chunks:
# - Unique chunks: 124
# - Near-duplicates (90%+ similar to existing): 3
```

### Stage 4 Summary

| Metric | Value |
|--------|-------|
| Input chunks | 127 |
| Unique chunks | 124 |
| Duplicates detected | 3 |
| Embedding cost saved | ~3 × (embedding time) |
| LSH lookup time | O(1) per chunk |
| Total stage time | ~2–3 sec |

---

## STAGE 5: Embed (Generate Vectors)

**Purpose:** Convert unique chunks into dense vector embeddings for semantic search.

**Library:** bge-m3 (running in Ollama)  
**Embedding dimensions:** 1024  
**Batch size:** 32 (default, tunable)  
**Time:** ~10–12 sec (async)

### Input

```python
unique_chunks: list[Chunk] = [124 chunks with is_duplicate=False]
```

### Processing

The **AsyncOllamaBatchEmbedder** (from `src/ingestion/embedder.py`) encodes chunks concurrently:

```python
# Configuration
batch_size = 32
max_concurrent_batches = 4

# Ollama API call (local, no network latency)
# POST http://localhost:11434/api/embed

request = {
    "model": "bge-m3:latest",
    "input": [chunk.text for chunk in unique_chunks]
}

# Response: 124 vectors (each 1024-dim float32)
vectors = [
    [0.023, -0.156, 0.892, ..., 0.041],  # chunk 0
    [-0.104, 0.234, -0.067, ..., 0.219], # chunk 1
    [0.187, -0.045, 0.534, ..., -0.098], # chunk 2
    # ... 121 more
]
```

### Output: Embedded Chunks

Chunks paired with their vector embeddings:

```python
# zip(unique_chunks, vectors) creates associations:

embedded_chunks = [
    (
        Chunk(chunk_index=0, text="AWS Security Best Practices", ...),
        vector([0.023, -0.156, 0.892, ..., 0.041])  # 1024-dim
    ),
    (
        Chunk(chunk_index=2, text="Use IAM roles instead...", ...),
        vector([-0.104, 0.234, -0.067, ..., 0.219])  # 1024-dim
    ),
    # ... 122 more
]

# Duplicate chunks NOT embedded (cost savings)
# chunk_index=47: is_duplicate=True → vector=[]
```

### Stage 5 Summary

| Metric | Value |
|--------|-------|
| Unique chunks to embed | 124 |
| Embedding model | bge-m3:latest (Ollama) |
| Dimensions per vector | 1024 (float32) |
| Batches | 4 batches (32 chunks each) |
| Time per batch | ~3 sec (Ollama local) |
| **Total stage time** | **~10–12 sec** |
| **Embedding cost saved** | ~3 vectors (dupes) |

---

## STAGE 6: Store (Upsert to Weaviate)

**Purpose:** Store enriched chunks + embeddings in Weaviate for retrieval.

**Database:** Weaviate (vector DB)  
**Tenant isolation:** Multi-tenant (tenant_id per document)  
**Time:** ~2–3 sec

### Input

```python
embedded_chunks: list[Chunk] = [124 unique chunks with vectors]
duplicate_chunks: list[Chunk] = [3 chunks with is_duplicate=True, no vectors]
metadata: dict = {
    "tenant_id": "default_tenant",
    "source_uri": "upload://AWS_Security_Best_Practices.pdf",
    "file_name": "AWS_Security_Best_Practices.pdf",
    "doc_sha256": "abc123...",
    "mime_type": "application/pdf",
    "tags": [],
    "created": "2026-05-12T14:23:45Z",
    "ingested": "2026-05-12T14:23:45Z"
}
```

### Processing

The **WeaviateSink** (from `src/ingestion/sink.py`) builds `IngestRecord` objects and upserts to Weaviate:

```python
# For each unique chunk with vector
ingest_record = IngestRecord(
    chunk_id=f"chunk_{doc_sha256}_{chunk_index}",
    tenant_id="default_tenant",
    doc_sha256="abc123...",
    source_uri="upload://AWS_Security_Best_Practices.pdf",
    file_name="AWS_Security_Best_Practices.pdf",
    mime_type="application/pdf",
    parser_name="UnstructuredParser",
    created="2026-05-12T14:23:45Z",
    ingested="2026-05-12T14:23:45Z",
    
    # Chunk-level content
    content=chunk.text,
    page_number=chunk.page,
    section_name=chunk.section,
    
    # Enriched metadata (from Stage 3)
    keywords=chunk.extra["keywords"],           # ["IAM roles", ...]
    language=chunk.extra["language"],           # "en"
    confidence_score=chunk.extra["confidence_score"],  # 0.79
    hierarchy_path=chunk.extra["hierarchy_path"],      # "AWS > IAM > Best Practices"
    breadcrumb=chunk.extra["breadcrumb"],              # "AWS > IAM > ..."
    element_type=chunk.extra["element_type"],         # "NarrativeText"
    
    # Vector embedding
    vector=vector  # [0.023, -0.156, 0.892, ..., 0.041]
)

# Weaviate upsert (create or update)
weaviate_client.data_object.create(
    data_object=ingest_record.to_dict(),
    class_name="Document",
    tenant=tenant_id,
    uuid=chunk_id,
    vector=vector
)
```

### Weaviate Schema Mapping

The chunk fields map to Weaviate properties:

```yaml
Document:
  properties:
    content: text             # chunk.text
    page_number: int          # chunk.page
    section_name: text        # chunk.section
    keywords: text[]          # enriched metadata
    language: text            # enriched metadata
    confidence_score: number  # enriched metadata
    hierarchy_path: text      # enriched metadata
    breadcrumb: text          # enriched metadata
    element_type: text        # chunk.extra["element_type"]
    source_uri: text          # metadata
    file_name: text           # metadata
    mime_type: text           # metadata
    doc_sha256: text          # metadata
    parser_name: text         # metadata
    created: date             # timestamp
    ingested: date            # timestamp
  
  # Special: Vector for semantic search
  vectorIndexConfig:
    distance: "cosine"        # HNSW index
    ef: 256
    efConstruction: 128
```

### Output: Stored & Searchable

```
✅ 124 unique chunks stored with vectors
✅ 3 duplicate chunks stored with empty vector (cost savings)
✅ All enriched metadata (keywords, hierarchy, language, confidence) indexed
✅ All chunks in Weaviate tenant isolation
✅ Ready for hybrid search (BM25 + semantic)
```

**Example: Query for "IAM best practices"**

```python
# Hybrid search combines:
# 1. BM25 (keyword match) — finds chunks matching "IAM" or "best practices"
# 2. HNSW (semantic search) — finds chunks semantically similar to query embedding

results = weaviate_client.query.hybrid(
    class_name="Document",
    query="IAM best practices",
    tenant="default_tenant",
    limit=5
)

# Returns:
# [
#   {
#     "uuid": "chunk_abc123_2",
#     "content": "Use IAM roles instead of long-term access keys...",
#     "keywords": ["IAM roles", "access keys", ...],
#     "confidence_score": 0.79,
#     "hierarchy_path": "AWS > IAM > Best Practices",
#     "score": 0.92,  # hybrid score (BM25 + semantic)
#   },
#   ...
# ]
```

### Stage 6 Summary

| Metric | Value |
|--------|-------|
| Unique chunks stored | 124 |
| Duplicate chunks stored | 3 (vector=[]) |
| Total IngestRecords | 127 |
| Weaviate tenant | default_tenant |
| Vector dimensions | 1024 (float32) |
| Storage format | HNSW index + metadata |
| **Total stage time** | **~2–3 sec** |
| **Total upsert time** | **~2–3 sec** |

---

## Complete Pipeline Execution Summary

### End-to-End Flow

```
Input file: AWS_Security_Best_Practices.pdf (200 KB, 5 pages)
                           ↓
         [Stage 1: Parse with Unstructured]
         Input: 200 KB binary PDF
         Output: 412 blocks with element_type, hierarchy, page
         Time: ~2–5 sec
                           ↓
         [Stage 2: Chunk with SemanticChunker]
         Input: 412 blocks
         Output: 127 semantic chunks (~500 words avg)
         Time: ~1–3 sec
                           ↓
         [Stage 3: Enrich with 4 enrichers]
         Input: 127 chunks
         Output: 127 chunks + keywords, hierarchy, language, confidence
         Time: ~12–15 sec (dominated by KeywordEnricher)
                           ↓
         [Stage 4: Deduplicate with MinHash LSH]
         Input: 127 enriched chunks
         Output: 124 unique, 3 duplicates marked
         Time: ~2–3 sec
                           ↓
         [Stage 5: Embed with bge-m3 (Ollama)]
         Input: 124 unique chunks
         Output: 124 vectors (1024-dim)
         Time: ~10–12 sec (async batches)
                           ↓
         [Stage 6: Store to Weaviate]
         Input: 127 IngestRecords (124 w/ vectors, 3 w/o)
         Output: Weaviate objects indexed + searchable
         Time: ~2–3 sec
                           ↓
         ✅ COMPLETE — Ready for retrieval
         
Total pipeline time: ~29–41 seconds
Storage: 127 chunks in Weaviate
Searchable: All fields (content, keywords, hierarchy, language, confidence)
```

---

## Configuration & Tuning

### Pipeline Toggles

```python
# .env or config.py

# Disable enrichment entirely
enrich_enabled = True

# Tune keyword extraction
enrich_keywords_top_n = 5  # Extract 5 top keywords per chunk

# Tune deduplication
dedup_enabled = True
dedup_threshold = 0.85     # Jaccard similarity threshold
dedup_num_perm = 128       # MinHash hash functions

# Tune embedding
embed_strategy = "async"   # or "sync"
embed_batch_size = 32
embed_max_concurrent_batches = 4

# Tune chunking
chunk_size = 800
chunk_overlap = 120
chunk_strategy = "element"  # or "semantic"
```

### Performance Metrics by Stage

| Stage | Time | Throughput | Bottleneck |
|-------|------|-----------|-----------|
| 1 Parse | 2–5 sec | ~40–100 KB/sec | PDF parsing (Unstructured) |
| 2 Chunk | 1–3 sec | 127 chunks | Semantic boundary detection |
| 3 Enrich | 12–15 sec | ~10 chunks/sec | KeywordEnricher (Ollama) |
| 4 Dedupe | 2–3 sec | ~42 chunks/sec | LSH lookups (fast) |
| 5 Embed | 10–12 sec | ~12 chunks/sec | Ollama bge-m3 throughput |
| 6 Store | 2–3 sec | ~42 chunks/sec | Weaviate upsert |
| **Total** | **29–41 sec** | **5–7 chunks/sec** | Enrichment + Embedding |

### Scaling: 100 MB (500-page) Document

```
Files: 100 MB
Blocks: ~20,000
Chunks: ~6,000

Estimated times:
- Stage 1: 100–250 sec (PDF parsing scales linearly)
- Stage 2: 50–150 sec (chunking)
- Stage 3: 600–900 sec (keyword extraction — parallelization needed)
- Stage 4: 100–150 sec (deduplication)
- Stage 5: 600–900 sec (embedding — async batches help)
- Stage 6: 100–150 sec (Weaviate upsert)

Total: ~1,550–2,500 sec (~26–42 minutes)
Bottlenecks: Enrichment, Embedding (both network to Ollama)

Optimization: Parallelize chunking, enrich, and embed stages
```

---

## Error Handling & Recovery

### Graceful Degradation

Each stage has fallbacks:

```
Stage 1 (Parse):
  - If unstructured fails → fallback to registry parser (binary, txt, etc.)

Stage 2 (Chunk):
  - If chunking produces 0 chunks → skip file, return error

Stage 3 (Enrich):
  - If HierarchyEnricher fails → continue with partial enrichment
  - If KeywordEnricher fails → empty keywords[], continue
  - If LanguageEnricher fails → language=None, continue
  - If ConfidenceEnricher fails → confidence_score=0.5, continue

Stage 4 (Dedupe):
  - If dedup_enabled=False → all chunks treated as unique
  - If LSH index corrupted → rebuild from scratch

Stage 5 (Embed):
  - If Ollama unavailable → fail stage (critical)
  - If batch embedding fails → retry individual chunks

Stage 6 (Store):
  - If Weaviate schema missing → auto-create schema
  - If upsert fails → retry with exponential backoff
```

### Idempotency

All stages are idempotent:

```python
# Ingesting the same file twice
ingest_bytes(content=pdf_bytes, file_name="doc.pdf")
ingest_bytes(content=pdf_bytes, file_name="doc.pdf")  # Same SHA256

# Result: Second call skips all processing
# Returns: IngestResult(skipped=True, reason="already indexed")
```

---

## Monitoring & Logging

### Logs for Complete Pipeline

```
[2026-05-12 14:23:45] INFO: Ingesting AWS_Security_Best_Practices.pdf
[2026-05-12 14:23:47] DEBUG: Stage 1: Parsed 412 blocks
[2026-05-12 14:23:50] DEBUG: Stage 2: Chunked into 127 chunks
[2026-05-12 14:24:02] DEBUG: Stage 3a: Hierarchy enriched 127 chunks
[2026-05-12 14:24:04] DEBUG: Stage 3b: Keyword extracted 127 chunks
[2026-05-12 14:24:05] DEBUG: Stage 3c: Language detected for 127 chunks
[2026-05-12 14:24:05] DEBUG: Stage 3d: Confidence scored 127 chunks
[2026-05-12 14:24:08] DEBUG: Stage 4: Deduplicator marked 3 near-duplicates
[2026-05-12 14:24:20] DEBUG: Stage 5: Embedded 124 unique chunks
[2026-05-12 14:24:23] INFO: Stage 6: Upserted 127 records to Weaviate
[2026-05-12 14:24:23] INFO: Successfully ingested: 127 chunks indexed, 3 duplicates (SHA256: abc123...)
```

---

## Summary

The **6-stage ingestion pipeline** transforms raw files into a searchable knowledge base:

1. **Parse** → Extract structured blocks with hierarchy
2. **Chunk** → Split into semantic units
3. **Enrich** → Add keywords, hierarchy, language, confidence
4. **Deduplicate** → Identify near-duplicates (O(1) LSH)
5. **Embed** → Generate vectors (bge-m3, async)
6. **Store** → Upsert to Weaviate with full metadata

**Result:** Searchable, multi-lingual, ranked chunks ready for retrieval with hybrid search (BM25 + semantic).
