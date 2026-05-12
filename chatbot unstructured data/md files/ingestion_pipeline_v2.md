# DeepAgent — Best-of-Best Data Ingestion Pipeline (v2)

> Complete end-to-end specification for the optimised ingestion pipeline.  
> Covers every stage: parsing, chunking, enrichment, deduplication, embedding, storage, and search.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Library Stack](#library-stack)
4. [Stage 1 — Parse (Unstructured)](#stage-1--parse)
5. [Stage 2 — Chunk (Element-Aware / Semantic)](#stage-2--chunk)
6. [Stage 3 — Enrich (Metadata Extraction)](#stage-3--enrich)
7. [Stage 4 — Deduplicate (MinHash LSH)](#stage-4--deduplicate)
8. [Stage 5 — Embed (Async Batch)](#stage-5--embed)
9. [Stage 6 — Store (Weaviate Extended Schema)](#stage-6--store)
10. [Search Improvements](#search-improvements)
11. [Files to Create / Modify / Delete](#files-to-create--modify--delete)
12. [Installation](#installation)
13. [Configuration](#configuration)
14. [Implementation Roadmap](#implementation-roadmap)
15. [Expected Results](#expected-results)

---

## Overview

The current pipeline uses a custom character-based `RecursiveChunker`, SHA256-only deduplication, a language detection stub (no-op), and no metadata enrichment beyond page/section. This v2 replaces each weak point with a specialist, battle-tested tool while keeping the existing `interfaces.py` protocol contracts intact.

**What stays unchanged:** `deepagents` orchestration, LangGraph, Ollama, Weaviate instance, Streamlit UI, SQLite chat history, Langfuse tracing, skills/, memory/.

**What changes:** Every stage of the ingestion pipeline.

---

## Architecture Diagram

```
FILE SOURCES (3 entry points — unchanged)
  ├─ CLI:     python -m src.ingestion.cli
  ├─ Watcher: python -m src.ingestion.watcher (watchdog)
  └─ UI:      Streamlit sidebar upload
                │
                ▼
┌───────────────────────────────────────────────────────────────┐
│  STAGE 1 — PARSE                                              │
│  Library: unstructured[all-docs]                             │
│  File:    src/ingestion/parsers/unstructured_parser.py        │
│                                                               │
│  Input:  raw bytes (any format)                              │
│  Output: Block[] with element_type, depth, parent_id,        │
│          page, section, language (auto-detected)             │
└─────────────────────────────┬─────────────────────────────────┘
                              │ Block[]
┌─────────────────────────────▼─────────────────────────────────┐
│  STAGE 2 — CHUNK                                              │
│  Option A: UnstructuredElementChunker (langchain-text-splitters│
│            — already installed, fast, element-aware)          │
│  Option B: SemanticChunker (spacy + sentence-transformers,    │
│            best quality, semantic breakpoints)                │
│  File:    src/ingestion/chunker.py                           │
│                                                               │
│  Input:  Block[]                                             │
│  Output: Chunk[] preserving element_type, depth, parent_id   │
└─────────────────────────────┬─────────────────────────────────┘
                              │ Chunk[]
┌─────────────────────────────▼─────────────────────────────────┐
│  STAGE 3 — ENRICH                                             │
│  File:    src/ingestion/enricher.py (NEW)                    │
│                                                               │
│  3a. HierarchyEnricher    → ancestral_headings, hierarchy_path│
│      Library: built-in (uses parent_id from Unstructured)    │
│                                                               │
│  3b. KeywordEnricher      → keywords[]                       │
│      Library: keybert (reuses bge-m3 embeddings)             │
│                                                               │
│  3c. LanguageEnricher     → language (ISO 639-1)             │
│      Library: langdetect                                      │
│                                                               │
│  3d. ConfidenceEnricher   → confidence_score (0.0–1.0)       │
│      Library: built-in (rule-based, no deps)                 │
│                                                               │
│  Input:  Chunk[]                                             │
│  Output: Chunk[] with 5 new metadata fields                  │
└─────────────────────────────┬─────────────────────────────────┘
                              │ Enriched Chunk[]
┌─────────────────────────────▼─────────────────────────────────┐
│  STAGE 4 — DEDUPLICATE                                        │
│  Library: datasketch (MinHash LSH)                           │
│  File:    src/ingestion/deduplicator.py (NEW)                │
│                                                               │
│  Algorithm: MinHash + LSH (Jaccard similarity, O(1) lookup)  │
│  Threshold: 0.85 (configurable)                              │
│  Scale:     100K+ docs with no slowdown                      │
│                                                               │
│  Input:  Enriched Chunk[]                                    │
│  Output: Chunk[] (duplicates flagged, skip embedding for them)│
└─────────────────────────────┬─────────────────────────────────┘
                              │ Deduplicated Chunk[]
┌─────────────────────────────▼─────────────────────────────────┐
│  STAGE 5 — EMBED                                              │
│  Library: asyncio (stdlib) + langchain-ollama (existing)     │
│  File:    src/ingestion/embedder.py (AsyncEmbedder added)    │
│                                                               │
│  Model:   bge-m3 (1024-dim, same as current)                 │
│  Batch:   32 chunks per batch                                │
│  Strategy: asyncio.gather() — concurrent batches             │
│  Speed:   ~3-4x faster than current sequential               │
│                                                               │
│  Input:  Chunk texts (dupes skipped)                         │
│  Output: vectors list[list[float]]                           │
└─────────────────────────────┬─────────────────────────────────┘
                              │ IngestRecord[] (text + vector + all metadata)
┌─────────────────────────────▼─────────────────────────────────┐
│  STAGE 6 — STORE                                              │
│  Library: weaviate-client (existing)                         │
│  Files:   src/ingestion/sink.py (extended)                   │
│           src/retrieval/weaviate_client.py (schema extended) │
│                                                               │
│  Same "Document" collection, extended with new fields        │
│  Weaviate Docker: reranker-transformers module enabled        │
│                                                               │
│  Input:  IngestRecord[]                                      │
│  Output: Stored in Weaviate, ready to search                 │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                     WEAVIATE (optimised)
                     HNSW + BM25 + reranker-transformers
```

---

## Library Stack

### New Dependencies (add to `requirements.txt`)

```
# --- Best-of-Best Ingestion Pipeline (v2) ---
unstructured[all-docs]>=0.13.0     # Stage 1: Multi-format parsing + element types
spacy>=3.7.0                       # Stage 2: Sentence segmentation (SemanticChunker)
sentence-transformers>=3.0.0       # Stage 2: Semantic breakpoints (uses bge-m3)
keybert>=0.8.0                     # Stage 3b: Keyword extraction (reuses bge-m3)
langdetect>=1.0.9                  # Stage 3c: Language detection (55 languages)
datasketch>=1.0.8                  # Stage 4: MinHash LSH near-dedup (100K+ scale)
```

### Existing Dependencies (unchanged)

```
langchain, langchain-core, langchain-ollama  # Embedding + LLM
langchain-text-splitters                     # Stage 2 Option A (already installed)
weaviate-client                              # Stage 6
tenacity                                     # Retry logic
asyncio                                      # Stage 5 (stdlib)
pydantic, pydantic-settings                  # Config
tqdm                                         # Progress bars
```

---

## Stage 1 — Parse

**File:** `src/ingestion/parsers/unstructured_parser.py` *(replaces all 7 existing parsers)*

**Library:** `unstructured[all-docs]`

### What It Extracts

Each document element becomes a `Block` with:

| Field | Source | Example |
|-------|--------|---------|
| `text` | Element text | `"Always wear protective gloves."` |
| `page` | Page number | `12` |
| `section` | Parent heading text | `"Section 3.2: Equipment"` |
| `extra["element_type"]` | Unstructured type | `"NarrativeText"` |
| `extra["parent_id"]` | Parent element ID | `"h_002"` |
| `extra["depth"]` | Nesting depth | `2` |
| `extra["language"]` | Auto-detected lang | `"en"` |
| `extra["element_id"]` | Unique element ID | `"el_0042"` |

### Element Types

| Type | Meaning |
|------|---------|
| `Title` | Document or section title |
| `NarrativeText` | Body paragraph text |
| `Table` | Tabular data (kept intact) |
| `ListItem` | Bullet or numbered list item |
| `Header` | Page header |
| `Footer` | Page footer |
| `Image` | Image caption |

### Supported Formats

PDF, DOCX, PPTX, HTML, Markdown, CSV, JSON, TXT — **one parser, all formats**.

### Code Sketch

```python
# src/ingestion/parsers/unstructured_parser.py

from unstructured.partition.auto import partition
from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser
import tempfile, os

class UnstructuredParser:
    name = "unstructured"
    mime_types = ()       # handles all MIME types
    extensions = ()       # handles all extensions

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        # Write bytes to temp file (Unstructured needs file path)
        with tempfile.NamedTemporaryFile(
            suffix=self._suffix(doc.file_name), delete=False
        ) as f:
            f.write(doc.content)
            tmp_path = f.name

        try:
            elements = partition(filename=tmp_path)
            heading_stack: list[dict] = []  # for ancestral heading tracking

            for el in elements:
                el_type = type(el).__name__   # "Title", "NarrativeText", etc.
                text = str(el).strip()
                if not text:
                    continue

                # Track heading hierarchy
                if el_type == "Title":
                    depth = getattr(el.metadata, "category_depth", 0) or 0
                    # Pop stack to current depth
                    heading_stack = [h for h in heading_stack if h["depth"] < depth]
                    el_id = f"h_{id(el)}"
                    heading_stack.append({
                        "depth": depth,
                        "text": text,
                        "id": el_id
                    })
                    section = text
                else:
                    section = heading_stack[-1]["text"] if heading_stack else None

                yield Block(
                    text=text,
                    page=getattr(el.metadata, "page_number", None),
                    section=section,
                    extra={
                        "element_type": el_type,
                        "element_id": f"el_{id(el)}",
                        "parent_id": heading_stack[-1]["id"] if heading_stack else None,
                        "depth": getattr(el.metadata, "category_depth", 0) or 0,
                        "heading_chain": [h["id"] for h in heading_stack],
                        "heading_chain_texts": [h["text"] for h in heading_stack],
                        "language": getattr(el.metadata, "languages", [None])[0],
                    },
                )
        finally:
            os.unlink(tmp_path)

    def _suffix(self, file_name: str) -> str:
        return "." + file_name.rsplit(".", 1)[-1] if "." in file_name else ".txt"
```

---

## Stage 2 — Chunk

**File:** `src/ingestion/chunker.py`

Three chunkers available, selectable via `config.chunk_strategy`:

### Option A — `UnstructuredElementChunker` *(recommended starting point)*

**Library:** `langchain-text-splitters` (already installed)

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

class UnstructuredElementChunker:
    """
    Element-aware chunker. Tables and Titles are never split.
    NarrativeText/ListItem are split recursively on natural separators.
    """
    def __init__(self, size: int = 800, overlap: int = 120):
        self.size = size
        self.overlap = overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
        )

    def chunk(self, blocks: Iterable[Block]) -> Iterable[Chunk]:
        idx = 0
        for block in blocks:
            el_type = block.extra.get("element_type", "NarrativeText")

            # Never split Tables or Titles — keep as one chunk
            if el_type in ("Table", "Title", "Header"):
                yield Chunk(
                    text=block.text,
                    chunk_index=idx,
                    page=block.page,
                    section=block.section,
                    extra=dict(block.extra),
                )
                idx += 1
                continue

            # Split everything else
            for piece in self._splitter.split_text(block.text):
                if piece.strip():
                    yield Chunk(
                        text=piece,
                        chunk_index=idx,
                        page=block.page,
                        section=block.section,
                        extra=dict(block.extra),
                    )
                    idx += 1
```

**Pros:** Zero new dependencies, fast, element-aware.  
**Cons:** Not fully semantic (topic shifts inside a chunk possible).

---

### Option B — `SemanticChunker` *(best quality)*

**Libraries:** `spacy` + `sentence-transformers`

```python
import spacy
from sentence_transformers import SentenceTransformer
from scipy.spatial.distance import cosine as cosine_dist

class SemanticChunker:
    """
    Semantic breakpoint chunker.
    Splits on cosine similarity drops between adjacent sentences.
    Tables and Titles are never split.
    """
    def __init__(
        self,
        size: int = 800,
        overlap: int = 120,
        threshold: float = 0.5,   # tune per document type
    ):
        self.max_size = size
        self.overlap = overlap
        self.threshold = threshold
        self.nlp = spacy.load("en_core_web_sm")
        self.model = SentenceTransformer("BAAI/bge-m3")

    def chunk(self, blocks: Iterable[Block]) -> Iterable[Chunk]:
        idx = 0
        for block in blocks:
            el_type = block.extra.get("element_type", "NarrativeText")

            # Keep Tables/Titles intact
            if el_type in ("Table", "Title", "Header"):
                yield Chunk(
                    text=block.text, chunk_index=idx,
                    page=block.page, section=block.section,
                    extra=dict(block.extra)
                )
                idx += 1
                continue

            # Sentence segmentation
            sentences = [s.text for s in self.nlp(block.text).sents]
            if not sentences:
                continue

            # Embed all sentences
            embeddings = self.model.encode(sentences)

            # Group by similarity
            current: list[str] = [sentences[0]]
            for i in range(1, len(sentences)):
                sim = 1 - cosine_dist(embeddings[i - 1], embeddings[i])
                too_large = len(" ".join(current) + " " + sentences[i]) > self.max_size
                topic_shift = sim < self.threshold

                if topic_shift or too_large:
                    yield Chunk(
                        text=" ".join(current), chunk_index=idx,
                        page=block.page, section=block.section,
                        extra=dict(block.extra)
                    )
                    idx += 1
                    # Overlap: carry last sentence into next chunk
                    current = [current[-1], sentences[i]] if self.overlap else [sentences[i]]
                else:
                    current.append(sentences[i])

            if current:
                yield Chunk(
                    text=" ".join(current), chunk_index=idx,
                    page=block.page, section=block.section,
                    extra=dict(block.extra)
                )
                idx += 1
```

**Pros:** Semantic + element-aware, never splits mid-sentence, best quality.  
**Cons:** ~2x slower due to sentence embeddings.

---

### Strategy Selection (via config)

```python
# src/config.py
chunk_strategy: str = "element"  # "element" | "semantic" | "recursive"
semantic_chunk_threshold: float = 0.5

# src/ingestion/chunker.py
def get_chunker(settings) -> Chunker:
    if settings.chunk_strategy == "semantic":
        return SemanticChunker(
            size=settings.chunk_size,
            overlap=settings.chunk_overlap,
            threshold=settings.semantic_chunk_threshold,
        )
    elif settings.chunk_strategy == "element":
        return UnstructuredElementChunker(
            size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
    else:
        return RecursiveChunker(  # existing fallback
            size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
```

---

## Stage 3 — Enrich

**File:** `src/ingestion/enricher.py` *(new)*

### 3a — HierarchyEnricher (Ancestral Headings)

**Library:** None (built-in, uses Unstructured parent_id data)

Builds the full heading ancestry chain from root to current element:

```python
class HierarchyEnricher:
    """
    Builds ancestral_headings list from heading_chain_texts extracted
    by UnstructuredParser in Stage 1.
    """
    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        chain_texts = chunk.extra.get("heading_chain_texts", [])
        current_section = chunk.section or "Untitled"

        # Build full ancestry list
        ancestral_headings = [
            {"level": i, "text": text}
            for i, text in enumerate(chain_texts)
        ]

        # Add current section if not already last entry
        if not ancestral_headings or ancestral_headings[-1]["text"] != current_section:
            ancestral_headings.append({
                "level": len(ancestral_headings),
                "text": current_section,
            })

        hierarchy_path = " > ".join(h["text"] for h in ancestral_headings)
        breadcrumb = " / ".join(
            h["text"][:20] for h in ancestral_headings
        )

        chunk.extra["ancestral_headings"] = ancestral_headings
        chunk.extra["hierarchy_path"] = hierarchy_path
        chunk.extra["breadcrumb"] = breadcrumb
        chunk.extra["hierarchy_depth"] = len(ancestral_headings) - 1
        return chunk
```

**Example output:**
```json
{
  "ancestral_headings": [
    {"level": 0, "text": "Safety Guidelines"},
    {"level": 1, "text": "Chapter 3: Equipment"},
    {"level": 2, "text": "Section 3.2: Gloves"}
  ],
  "hierarchy_path": "Safety Guidelines > Chapter 3: Equipment > Section 3.2: Gloves",
  "breadcrumb": "Safety Guidelines / Chapter 3: Equipmen / Section 3.2: Gloves",
  "hierarchy_depth": 2
}
```

---

### 3b — KeywordEnricher

**Library:** `keybert`  
**Note:** Reuses `bge-m3` — no extra model download needed.

```python
from keybert import KeyBERT

class KeywordEnricher:
    def __init__(self, top_n: int = 5):
        self.model = KeyBERT(model="BAAI/bge-m3")
        self.top_n = top_n

    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        if len(chunk.text) < 30:   # skip very short chunks
            chunk.extra["keywords"] = []
            return chunk

        keywords = self.model.extract_keywords(
            chunk.text,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=self.top_n,
        )
        chunk.extra["keywords"] = [kw for kw, _ in keywords]
        return chunk
```

**Example output:**
```json
{"keywords": ["protective gloves", "nitrile", "safety equipment", "hand protection", "chemical resistance"]}
```

---

### 3c — LanguageEnricher

**Library:** `langdetect`  
**Replaces:** the no-op `_detect_language()` stub in `pipeline.py`

```python
from langdetect import detect, LangDetectException

class LanguageEnricher:
    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        # Use language from Unstructured if already detected
        if chunk.extra.get("language"):
            return chunk

        if len(chunk.text) < 20:
            return chunk

        try:
            lang = detect(chunk.text)
        except LangDetectException:
            lang = None

        chunk.extra["language"] = lang
        return chunk
```

---

### 3d — ConfidenceEnricher

**Library:** None (rule-based, no deps)

```python
_ELEMENT_CONFIDENCE = {
    "Title":          1.0,
    "Header":         0.95,
    "NarrativeText":  0.85,
    "ListItem":       0.80,
    "Table":          0.85,
    "Footer":         0.40,
    "Image":          0.30,
}

class ConfidenceEnricher:
    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        el_type = chunk.extra.get("element_type", "NarrativeText")
        depth = chunk.extra.get("hierarchy_depth", 0)
        base = _ELEMENT_CONFIDENCE.get(el_type, 0.75)

        # Deeper nesting slightly reduces confidence
        depth_penalty = min(depth * 0.03, 0.15)
        score = round(max(base - depth_penalty, 0.1), 3)

        chunk.extra["confidence_score"] = score
        return chunk
```

---

### EnricherChain (wire all 4 together)

```python
class EnricherChain:
    def __init__(self, enrichers: list):
        self.enrichers = enrichers

    def enrich_all(self, chunks: list[Chunk], doc: RawDocument) -> list[Chunk]:
        result = []
        for chunk in chunks:
            for enricher in self.enrichers:
                chunk = enricher.enrich(chunk, doc)
            result.append(chunk)
        return result

def build_enricher_chain() -> EnricherChain:
    return EnricherChain([
        HierarchyEnricher(),
        KeywordEnricher(top_n=5),
        LanguageEnricher(),
        ConfidenceEnricher(),
    ])
```

---

## Stage 4 — Deduplicate

**File:** `src/ingestion/deduplicator.py` *(new)*  
**Library:** `datasketch`

### How MinHash LSH Works

1. Compute MinHash signature for each chunk (character 3-grams, 128 hash functions)
2. Query LSH index: any existing chunk with Jaccard similarity ≥ 0.85?
3. If **YES** → flag chunk as duplicate, skip embedding, store with `duplicate_of` ref
4. If **NO** → add to LSH index, proceed to embedding

**O(1) lookup — scales to 100K+ documents without slowdown.**

```python
from datasketch import MinHash, MinHashLSH
import pickle, os

class MinHashDeduplicator:
    def __init__(
        self,
        threshold: float = 0.85,
        num_perm: int = 128,
        index_path: str = "./data/lsh_index.pkl",
    ):
        self.threshold = threshold
        self.num_perm = num_perm
        self.index_path = index_path
        self.lsh = self._load_or_create()

    def _load_or_create(self) -> MinHashLSH:
        if os.path.exists(self.index_path):
            with open(self.index_path, "rb") as f:
                return pickle.load(f)
        return MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)

    def _minhash(self, text: str) -> MinHash:
        m = MinHash(num_perm=self.num_perm)
        for ngram in self._ngrams(text, 3):
            m.update(ngram.encode("utf-8"))
        return m

    def _ngrams(self, text: str, n: int):
        text = text.lower()
        return [text[i:i+n] for i in range(len(text) - n + 1)]

    def process(self, chunks: list[Chunk]) -> list[Chunk]:
        result = []
        for chunk in chunks:
            mh = self._minhash(chunk.text)
            key = f"{chunk.extra.get('doc_sha256', '')}_{chunk.chunk_index}"

            candidates = self.lsh.query(mh)
            if candidates:
                # Near-duplicate found
                chunk.extra["is_duplicate"] = True
                chunk.extra["duplicate_of"] = candidates[0]
            else:
                chunk.extra["is_duplicate"] = False
                self.lsh.insert(key, mh)

            result.append(chunk)
        return result

    def save(self):
        with open(self.index_path, "wb") as f:
            pickle.dump(self.lsh, f)
```

### Integration in pipeline.py

```python
deduplicator = MinHashDeduplicator()
chunks = deduplicator.process(chunks)

# Only embed non-duplicate chunks
embed_chunks = [c for c in chunks if not c.extra.get("is_duplicate")]
skip_chunks  = [c for c in chunks if c.extra.get("is_duplicate")]

vectors = embedder.embed([c.text for c in embed_chunks])

# Duplicate chunks store reference but no vector
deduplicator.save()  # persist LSH index to disk
```

---

## Stage 5 — Embed

**File:** `src/ingestion/embedder.py` *(extended)*  
**Libraries:** `asyncio` (stdlib), `langchain-ollama` (existing), `tenacity` (existing)

### AsyncOllamaBatchEmbedder

Fires all batches concurrently instead of sequentially:

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
from langchain_ollama import OllamaEmbeddings

class AsyncOllamaBatchEmbedder:
    def __init__(self, batch_size: int = 32, max_concurrent: int = 4):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self._client = OllamaEmbeddings(model=get_settings().ollama_embed_model)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)

    async def _embed_all(self, texts: list[str]) -> list[list[float]]:
        batches = [
            texts[i:i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]
        # Run up to max_concurrent batches simultaneously
        results: list[list[float]] = []
        for i in range(0, len(batches), self.max_concurrent):
            group = batches[i:i + self.max_concurrent]
            group_results = await asyncio.gather(
                *[self._embed_batch_async(b) for b in group]
            )
            for gr in group_results:
                results.extend(gr)
        return results

    def embed(self, texts: list[str]) -> list[list[float]]:
        return asyncio.run(self._embed_all(texts))
```

**Speed gain:** ~3-4x vs. current sequential batching on the same hardware.

---

## Stage 6 — Store

### Extended Weaviate Schema

**File:** `src/retrieval/weaviate_client.py`

New properties added to the existing `"Document"` collection:

```python
# src/retrieval/weaviate_client.py

new_properties = [
    Property(
        name="element_type",
        data_type=DataType.TEXT,
        description="Unstructured element type: Title, NarrativeText, Table, ListItem, Header, Footer",
        tokenization=Tokenization.FIELD,
    ),
    Property(
        name="hierarchy_path",
        data_type=DataType.TEXT,
        description="Breadcrumb: 'Chapter 1 > Section 2 > Subsection'",
        tokenization=Tokenization.WHITESPACE,
    ),
    Property(
        name="ancestral_headings",
        data_type=DataType.TEXT,
        description="JSON array of {level, text} ancestor headings",
    ),
    Property(
        name="breadcrumb",
        data_type=DataType.TEXT,
        description="Short display breadcrumb for UI",
    ),
    Property(
        name="hierarchy_depth",
        data_type=DataType.INT,
        description="Nesting level from document root",
    ),
    Property(
        name="keywords",
        data_type=DataType.TEXT_ARRAY,
        description="Top-K keywords extracted by KeyBERT",
        tokenization=Tokenization.WHITESPACE,
    ),
    Property(
        name="confidence_score",
        data_type=DataType.NUMBER,
        description="Source reliability score 0.0–1.0",
    ),
    Property(
        name="is_duplicate",
        data_type=DataType.BOOL,
        description="Flagged as near-duplicate by MinHash LSH",
    ),
    Property(
        name="duplicate_of",
        data_type=DataType.TEXT,
        description="Key of original chunk if is_duplicate=True",
    ),
]
```

### Extended IngestRecord

**File:** `src/ingestion/interfaces.py`

```python
@dataclass
class IngestRecord:
    # --- existing fields ---
    text: str
    vector: list[float]
    tenant_id: str
    doc_sha256: str
    source_uri: str
    file_name: str
    mime_type: str
    format: str
    chunk_index: int
    page: int | None
    section: str | None
    language: str | None
    tags: list[str]
    created_at: datetime
    ingested_at: datetime
    extra: dict[str, Any]

    # --- NEW fields ---
    element_type: str | None = None
    hierarchy_path: str | None = None
    ancestral_headings: list[dict] = field(default_factory=list)
    breadcrumb: str | None = None
    hierarchy_depth: int = 0
    keywords: list[str] = field(default_factory=list)
    confidence_score: float = 0.75
    is_duplicate: bool = False
    duplicate_of: str | None = None
```

---

## Search Improvements

**File:** `src/retrieval/search.py`

### New Filter Options

```python
def _base_filter(tenant_id: str, filters: dict[str, Any] | None) -> Filter:
    f = Filter.by_property("tenant_id").equal(tenant_id)
    if not filters:
        return f

    # --- existing filters ---
    if v := filters.get("file_name"):
        f = f & Filter.by_property("file_name").equal(v)
    if v := filters.get("format"):
        f = f & Filter.by_property("format").equal(v)
    if v := filters.get("language"):
        f = f & Filter.by_property("language").equal(v)
    if v := filters.get("tags"):
        f = f & Filter.by_property("tags").contains_any(list(v))

    # --- NEW filters ---
    if v := filters.get("element_type"):
        # e.g. "Table" — only return table chunks
        f = f & Filter.by_property("element_type").equal(v)

    if v := filters.get("hierarchy_path_contains"):
        # e.g. "Chapter 3" — only return chunks under Chapter 3
        f = f & Filter.by_property("hierarchy_path").like(f"*{v}*")

    if v := filters.get("hierarchy_depth_max"):
        # e.g. 1 — only top-level sections
        f = f & Filter.by_property("hierarchy_depth").less_or_equal(int(v))

    if v := filters.get("confidence_min"):
        # e.g. 0.8 — only high-confidence chunks
        f = f & Filter.by_property("confidence_score").greater_or_equal(float(v))

    if v := filters.get("keywords"):
        # e.g. ["safety", "gloves"] — keyword-scoped search
        f = f & Filter.by_property("keywords").contains_any(list(v))

    # Always exclude near-duplicates from search results
    f = f & Filter.by_property("is_duplicate").equal(False)

    return f
```

### Weaviate Native Reranking

Enable in Docker Compose (one-time config change):

```yaml
# docker-compose.yml
services:
  weaviate:
    environment:
      ENABLE_MODULES: "text2vec-transformers,reranker-transformers"
      RERANKER_INFERENCE_API: "http://reranker-transformers:8080"

  reranker-transformers:
    image: semitechnologies/reranker-transformers:cross-encoder-ms-marco-MiniLM-L-6-v2
    ports:
      - "8082:8080"
```

Use in search:

```python
from weaviate.classes.query import Rerank

res = coll.query.hybrid(
    query=query,
    vector=qvec,
    alpha=alpha,
    limit=k,
    filters=_base_filter(tenant_id, filters),
    rerank=Rerank(prop="text", query=query),  # NEW
    return_metadata=MetadataQuery(score=True),
)
```

### Agent Usage Examples

```
# Researcher sub-agent can now use:

# Search only tables (for tabular queries)
hybrid_search("safety risk levels", filters={"element_type": "Table"})

# Search only within a specific section
hybrid_search("equipment requirements", filters={"hierarchy_path_contains": "Chapter 3"})

# Search high-confidence chunks only
hybrid_search("maximum temperature", filters={"confidence_min": 0.8})

# Keyword-scoped search
hybrid_search("gloves", filters={"keywords": ["protective", "nitrile"]})
```

---

## Files to Create / Modify / Delete

### CREATE

| File | Purpose |
|------|---------|
| `src/ingestion/parsers/unstructured_parser.py` | Stage 1: universal parser (replaces all 7) |
| `src/ingestion/enricher.py` | Stage 3: HierarchyEnricher, KeywordEnricher, LanguageEnricher, ConfidenceEnricher, EnricherChain |
| `src/ingestion/deduplicator.py` | Stage 4: MinHash LSH near-dedup |

### MODIFY

| File | Changes |
|------|---------|
| `src/ingestion/interfaces.py` | Extend `Block`, `Chunk`, `IngestRecord` with new fields |
| `src/ingestion/chunker.py` | Add `UnstructuredElementChunker`, `SemanticChunker`, `get_chunker()` factory |
| `src/ingestion/embedder.py` | Add `AsyncOllamaBatchEmbedder` |
| `src/ingestion/pipeline.py` | Wire all new stages, remove old parser imports |
| `src/ingestion/sink.py` | Write new metadata fields to Weaviate |
| `src/retrieval/weaviate_client.py` | Add 9 new schema properties |
| `src/retrieval/search.py` | Add new filters, add reranker to `hybrid_search()` |
| `src/config.py` | Add `chunk_strategy`, `semantic_chunk_threshold`, `embed_strategy`, `embed_max_concurrent_batches`, `dedup_threshold` |
| `requirements.txt` | Add 6 new packages |
| `docker-compose.yml` | Enable `reranker-transformers` module |

### DELETE

| File | Replaced By |
|------|-------------|
| `src/ingestion/parsers/pdf_parser.py` | `unstructured_parser.py` |
| `src/ingestion/parsers/docx_parser.py` | `unstructured_parser.py` |
| `src/ingestion/parsers/html_parser.py` | `unstructured_parser.py` |
| `src/ingestion/parsers/markdown_parser.py` | `unstructured_parser.py` |
| `src/ingestion/parsers/csv_parser.py` | `unstructured_parser.py` |
| `src/ingestion/parsers/json_parser.py` | `unstructured_parser.py` |
| `src/ingestion/parsers/text_parser.py` | `unstructured_parser.py` |

---

## Installation

```bash
# 1. Activate virtual environment
.\my_venvbot\Scripts\Activate.ps1

# 2. Install new packages
pip install unstructured[all-docs] spacy sentence-transformers keybert langdetect datasketch

# 3. Download spacy English model (one-time, ~40 MB)
python -m spacy download en_core_web_sm

# 4. Verify installations
python -c "from unstructured.partition.auto import partition; print('unstructured OK')"
python -c "import spacy; spacy.load('en_core_web_sm'); print('spacy OK')"
python -c "from sentence_transformers import SentenceTransformer; print('sentence-transformers OK')"
python -c "from keybert import KeyBERT; print('keybert OK')"
python -c "from langdetect import detect; print('langdetect OK')"
python -c "from datasketch import MinHash, MinHashLSH; print('datasketch OK')"
```

---

## Configuration

New settings in `src/config.py`:

```python
# Chunking
chunk_strategy: str = "element"       # "element" | "semantic" | "recursive"
semantic_chunk_threshold: float = 0.5 # lower = more chunks, higher = fewer

# Embedding
embed_strategy: str = "async"         # "async" | "sync"
embed_max_concurrent_batches: int = 4 # concurrent batches to Ollama

# Deduplication
dedup_enabled: bool = True
dedup_threshold: float = 0.85         # Jaccard similarity (0-1)
dedup_num_perm: int = 128             # MinHash permutations (higher = more accurate)
dedup_index_path: str = "./data/lsh_index.pkl"

# Enrichment
enrich_keywords_top_n: int = 5
enrich_enabled: bool = True
```

Corresponding `.env` keys:

```env
CHUNK_STRATEGY=element
SEMANTIC_CHUNK_THRESHOLD=0.5
EMBED_STRATEGY=async
EMBED_MAX_CONCURRENT_BATCHES=4
DEDUP_ENABLED=true
DEDUP_THRESHOLD=0.85
```

---

## Implementation Roadmap

### Week 1 — Foundation (highest impact)

```
[ ] pip install + spacy model download
[ ] Create src/ingestion/parsers/unstructured_parser.py
[ ] Create src/ingestion/enricher.py (all 4 enrichers + chain)
[ ] Extend src/ingestion/interfaces.py with new Block/Chunk/IngestRecord fields
[ ] Test with 10 sample documents — verify element_type, hierarchy_path output
```

### Week 2 — Chunking + Performance

```
[ ] Add UnstructuredElementChunker to chunker.py
[ ] Add AsyncOllamaBatchEmbedder to embedder.py
[ ] Add get_chunker() factory + config wiring
[ ] Wire new stages into pipeline.py
[ ] Benchmark ingestion speed (chunks/sec)
```

### Week 3 — Deduplication + Storage

```
[ ] Create src/ingestion/deduplicator.py (MinHash LSH)
[ ] Extend sink.py to write new metadata fields
[ ] Update weaviate_client.py schema (9 new properties)
[ ] Test deduplication with synthetic near-duplicate documents
[ ] Add LSH index persistence to ./data/
```

### Week 4 — Search + Reranking

```
[ ] Update search.py with new filters (element_type, hierarchy, confidence, keywords)
[ ] Enable reranker-transformers in Docker Compose
[ ] Update RESEARCHER_PROMPT to use new filter options
[ ] Run search quality benchmark (before vs. after)
[ ] Delete old 7 parsers after full validation
```

---

## Expected Results

| Metric | Current | After v2 | Improvement |
|--------|---------|----------|-------------|
| Ingestion speed | ~150 chunks/sec | ~400-600 chunks/sec | 3-4x faster |
| Chunk quality | ⭐⭐ (char-based) | ⭐⭐⭐⭐ (element-aware) | +100% |
| Metadata fields | 2 (page, section) | 11 (+ element_type, hierarchy, keywords, confidence, language, ancestry) | +450% |
| Deduplication | SHA256 exact only | MinHash 85% similarity | Near-dupes detected |
| Search precision | Hybrid only | Hybrid + reranking | +40-60% precision |
| Language detection | Stub (no-op) | 55 languages auto-detected | Full support |
| Table handling | Splits tables mid-row | Tables always kept intact | No broken tables |
| New dependencies | — | 6 focused packages | Minimal bloat |
