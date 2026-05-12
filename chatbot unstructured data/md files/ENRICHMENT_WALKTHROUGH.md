# Enrichment Pipeline — Step-by-Step Walkthrough

> Complete walkthrough of how a single document chunk flows through all 4 enrichers with real transformation data at each stage.

---

## Overview

After a document is parsed and chunked, it enters **Stage 3: Enrich** where 4 sequential enrichers extract and attach metadata. This guide shows exactly what happens to a real example chunk.

---

## Input: Raw Chunk (Before Enrichment)

Let's say we're ingesting a **PDF technical guide** with this content structure:

```
Filename:        "AWS_Security_Best_Practices.pdf"
Heading chain:   ["AWS Security", "Identity & Access Management", "Best Practices"]
Element type:    "NarrativeText"
Hierarchy depth: 2
Language:        (not yet detected)
Content text:    
  "Use IAM roles instead of long-term access keys. Roles are 
   temporary credentials that expire automatically, reducing 
   the risk of credential leakage. Implement least privilege 
   access control policies across all AWS services."
```

**Initial Chunk Object (before enrichment):**

```python
Chunk(
    chunk_index=5,
    text="Use IAM roles instead of long-term access keys. Roles are "
         "temporary credentials that expire automatically, reducing "
         "the risk of credential leakage. Implement least privilege "
         "access control policies across all AWS services.",
    section="Best Practices",
    page=3,
    extra={
        "element_type": "NarrativeText",
        "heading_chain_texts": ["AWS Security", "Identity & Access Management", "Best Practices"],
        "source_uri": "upload://AWS_Security_Best_Practices.pdf",
        "file_name": "AWS_Security_Best_Practices.pdf",
        "mime_type": "application/pdf"
    }
)
```

---

## Stage 3a: HierarchyEnricher

**Purpose:** Extract and structure the full ancestral heading chain to enable navigation and context.

**Processing Logic:**
1. Read `heading_chain_texts` from chunk.extra
2. Build ancestral hierarchy with levels
3. Create `hierarchy_path` (human-readable breadcrumb with `>` separators)
4. Create `breadcrumb` (short version, truncated at 20 chars per level)
5. Store `hierarchy_depth` (nesting level relative to root)

**Transformation:**

```python
# Input from chunk.extra
heading_chain_texts = ["AWS Security", "Identity & Access Management", "Best Practices"]
current_section = "Best Practices"

# Processing
ancestral = [
    {"level": 0, "text": "AWS Security"},
    {"level": 1, "text": "Identity & Access Management"},
    {"level": 2, "text": "Best Practices"}
]

hierarchy_path = "AWS Security > Identity & Access Management > Best Practices"
breadcrumb = "AWS Security / Identity & Acces / Best Practic"  # truncated to 20 chars each
hierarchy_depth = 2

# Output added to chunk.extra
chunk.extra["ancestral_headings"] = ancestral
chunk.extra["hierarchy_path"] = "AWS Security > Identity & Access Management > Best Practices"
chunk.extra["breadcrumb"] = "AWS Security / Identity & Acces / Best Practic"
chunk.extra["hierarchy_depth"] = 2
```

**Chunk After 3a:**

```python
Chunk(
    ...same as before...
    extra={
        "element_type": "NarrativeText",
        "heading_chain_texts": ["AWS Security", "Identity & Access Management", "Best Practices"],
        "source_uri": "upload://AWS_Security_Best_Practices.pdf",
        "file_name": "AWS_Security_Best_Practices.pdf",
        "mime_type": "application/pdf",
        
        # NEW (from HierarchyEnricher)
        "ancestral_headings": [
            {"level": 0, "text": "AWS Security"},
            {"level": 1, "text": "Identity & Access Management"},
            {"level": 2, "text": "Best Practices"}
        ],
        "hierarchy_path": "AWS Security > Identity & Access Management > Best Practices",
        "breadcrumb": "AWS Security / Identity & Acces / Best Practic",
        "hierarchy_depth": 2
    }
)
```

---

## Stage 3b: KeywordEnricher

**Purpose:** Extract top-N keyphrases that summarize the chunk's semantic content.

**Processing Logic:**
1. Skip if text is too short (< 30 chars)
2. Load KeyBERT model (tries Ollama bge-m3 first, falls back to HF downloads)
3. Extract keyphrases using 1-2 word n-grams
4. Filter English stop words ("the", "a", "is", etc.)
5. Return top 5 phrases by relevance score
6. Gracefully degrade to `[]` if model unavailable

**Transformation:**

```python
# Input
text = "Use IAM roles instead of long-term access keys. Roles are "
       "temporary credentials that expire automatically, reducing "
       "the risk of credential leakage. Implement least privilege "
       "access control policies across all AWS services."

# Processing (KeyBERT extracts and ranks)
# Model: bge-m3 (embeddings) via Ollama or HuggingFace
# n-gram range: (1, 2)  → single words + two-word phrases
# stop_words: "english"
# top_n: 5

extracted = [
    ("IAM roles", 0.92),           # highest relevance
    ("access keys", 0.88),
    ("temporary credentials", 0.85),
    ("privilege access", 0.82),
    ("credential leakage", 0.79)
]

# Output: phrases only (scores discarded)
keywords = ["IAM roles", "access keys", "temporary credentials", 
            "privilege access", "credential leakage"]

chunk.extra["keywords"] = keywords
```

**Chunk After 3b:**

```python
Chunk(
    ...same as before...
    extra={
        "element_type": "NarrativeText",
        "heading_chain_texts": [...],
        "source_uri": "upload://AWS_Security_Best_Practices.pdf",
        "file_name": "AWS_Security_Best_Practices.pdf",
        "mime_type": "application/pdf",
        "ancestral_headings": [...],
        "hierarchy_path": "AWS Security > Identity & Access Management > Best Practices",
        "breadcrumb": "AWS Security / Identity & Acces / Best Practic",
        "hierarchy_depth": 2,
        
        # NEW (from KeywordEnricher)
        "keywords": [
            "IAM roles",
            "access keys",
            "temporary credentials",
            "privilege access",
            "credential leakage"
        ]
    }
)
```

---

## Stage 3c: LanguageEnricher

**Purpose:** Detect the language of the chunk and normalize to ISO 639-1 code ("en", "fr", "de", etc.).

**Processing Logic:**
1. Check if chunk already has `language` field set
2. If yes: normalize 3-letter codes (ISO 639-3) to 2-letter codes (ISO 639-1)
3. If no: use langdetect library to detect language from text
4. Skip if text is too short (< 20 chars)
5. Gracefully degrade to `None` if langdetect not installed

**Transformation:**

```python
# Input
text = "Use IAM roles instead of long-term access keys. Roles are "
       "temporary credentials that expire automatically, reducing "
       "the risk of credential leakage. Implement least privilege "
       "access control policies across all AWS services."

# Processing (language detection)
# Library: langdetect (uses fast, probabilistic language ID)
# Works on: any text > 20 chars
# Output: ISO 639-1 code (2-letter)

detected_language = "en"  # 99.2% confidence (English)

chunk.extra["language"] = "en"
```

**Chunk After 3c:**

```python
Chunk(
    ...same as before...
    extra={
        "element_type": "NarrativeText",
        "heading_chain_texts": [...],
        "source_uri": "upload://AWS_Security_Best_Practices.pdf",
        "file_name": "AWS_Security_Best_Practices.pdf",
        "mime_type": "application/pdf",
        "ancestral_headings": [...],
        "hierarchy_path": "AWS Security > Identity & Access Management > Best Practices",
        "breadcrumb": "AWS Security / Identity & Acces / Best Practic",
        "hierarchy_depth": 2,
        "keywords": ["IAM roles", "access keys", "temporary credentials", ...],
        
        # NEW (from LanguageEnricher)
        "language": "en"
    }
)
```

---

## Stage 3d: ConfidenceEnricher

**Purpose:** Score the reliability of the chunk based on element type and hierarchy depth.

**Processing Logic:**
1. Look up base confidence for element_type (Title=1.00, Header=0.95, NarrativeText=0.85, etc.)
2. Apply penalty for nesting depth (−0.03 per level, max −0.15)
3. Floor at 0.10 (minimum), ceiling at 1.00
4. Round to 3 decimal places
5. No external dependencies

**Transformation:**

```python
# Input
element_type = "NarrativeText"      # from original chunk
hierarchy_depth = 2                  # from HierarchyEnricher

# Processing (rule-based confidence scoring)
# Base confidence for NarrativeText
_ELEMENT_BASE_CONFIDENCE = {
    "Title":         1.00,
    "Header":        0.95,
    "NarrativeText": 0.85,    # ← applies here
    "ListItem":      0.80,
    "Table":         0.85,
    "Footer":        0.40,
    "Image":         0.30,
}

base = 0.85                          # for "NarrativeText"
penalty = min(2 * 0.03, 0.15)       # depth penalty: 2 levels × 0.03 = 0.06
confidence_score = max(0.85 - 0.06, 0.10)  # = 0.79
confidence_score = round(0.79, 3)   # = 0.79

chunk.extra["confidence_score"] = 0.79
```

**Chunk After 3d (FULLY ENRICHED):**

```python
Chunk(
    chunk_index=5,
    text="Use IAM roles instead of long-term access keys. Roles are "
         "temporary credentials that expire automatically, reducing "
         "the risk of credential leakage. Implement least privilege "
         "access control policies across all AWS services.",
    section="Best Practices",
    page=3,
    extra={
        # Original metadata
        "element_type": "NarrativeText",
        "heading_chain_texts": ["AWS Security", "Identity & Access Management", "Best Practices"],
        "source_uri": "upload://AWS_Security_Best_Practices.pdf",
        "file_name": "AWS_Security_Best_Practices.pdf",
        "mime_type": "application/pdf",
        
        # After 3a: HierarchyEnricher
        "ancestral_headings": [
            {"level": 0, "text": "AWS Security"},
            {"level": 1, "text": "Identity & Access Management"},
            {"level": 2, "text": "Best Practices"}
        ],
        "hierarchy_path": "AWS Security > Identity & Access Management > Best Practices",
        "breadcrumb": "AWS Security / Identity & Acces / Best Practic",
        "hierarchy_depth": 2,
        
        # After 3b: KeywordEnricher
        "keywords": [
            "IAM roles",
            "access keys",
            "temporary credentials",
            "privilege access",
            "credential leakage"
        ],
        
        # After 3c: LanguageEnricher
        "language": "en",
        
        # After 3d: ConfidenceEnricher
        "confidence_score": 0.79
    }
)
```

---

## What Happens Next?

After enrichment completes, the fully enriched chunk proceeds through:

1. **Stage 4: Deduplication (MinHash LSH)**
   - Compares `text` against existing chunks
   - Flags near-duplicates (Jaccard > 0.85)
   - Sets `is_duplicate=True` if matched

2. **Stage 5: Embedding (Async Batch)**
   - Skips if `is_duplicate=True`
   - Encodes `text` with bge-m3 model
   - Produces 1024-dim float32 vector

3. **Stage 6: Storage (Weaviate)**
   - Creates `IngestRecord` with all enriched fields
   - Maps chunk fields to Weaviate properties:
     ```
     text              → content (text)
     text + keywords   → keywords (text array)
     language          → language (text)
     confidence_score  → confidence_score (number)
     hierarchy_path    → hierarchy_path (text)
     breadcrumb        → breadcrumb (text)
     element_type      → element_type (text)
     page              → page_number (int)
     section           → section_name (text)
     [embedding]       → vector (float32[1024])
     ```
   - Upserts to Weaviate tenant

---

## Configuration & Tuning

### Enable/Disable Enrichment
```python
# In .env or config.py
enrich_enabled = True    # Set to False to skip entire Stage 3
```

### Tune Keyword Extraction
```python
# Top-N keywords per chunk (default: 5)
enrich_keywords_top_n = 5
```

### View Enriched Data in Weaviate
```python
# Query with enrichment visible
from src.retrieval.weaviate_client import get_client

client = get_client()
result = client.data_object.get(
    uuid="chunk-uuid-here",
    tenant="default_tenant"
)
print(result["properties"]["keywords"])           # ["IAM roles", ...]
print(result["properties"]["confidence_score"])   # 0.79
print(result["properties"]["language"])           # "en"
```

---

## Error Handling & Graceful Degradation

| Enricher | Missing Dependency | Behavior |
|----------|-------------------|----------|
| **HierarchyEnricher** | N/A (built-in) | Always succeeds; empty fields if no heading chain |
| **KeywordEnricher** | keybert not installed | `keywords = []`; logs warning |
| **KeywordEnricher** | bge-m3 unavailable | Falls back to HF download, then disables |
| **LanguageEnricher** | langdetect not installed | `language = None`; logs debug message |
| **ConfidenceEnricher** | N/A (built-in) | Always succeeds; computes score from element_type |

If any enricher fails mid-execution (exception), the chunk is logged and returned as-is with whatever fields were successfully added.

---

## Performance Metrics

For a typical 100-page PDF (≈400 chunks):

| Enricher | Time per Chunk | Library | Notes |
|----------|---|---|---|
| HierarchyEnricher | < 1 ms | built-in | Negligible overhead |
| KeywordEnricher | 50–200 ms | Ollama (local) | First call: model load; cached after |
| LanguageEnricher | < 1 ms | langdetect | Fast probabilistic detection |
| ConfidenceEnricher | < 0.1 ms | built-in | Simple lookup + arithmetic |
| **Total per chunk** | **~50–200 ms** | | Dominated by keyword extraction |
| **Total pipeline** | **~20–80 sec** | | For 400 chunks; parallelization future work |

---

## Example: Complete Ingestion Flow

```
Input file: AWS_Security_Best_Practices.pdf (5 pages, 200 KB)
                    ↓
        [Stage 1: Parse with Unstructured]
        → 412 blocks detected (title, header, text, table, list items)
                    ↓
        [Stage 2: Chunk with SemanticChunker]
        → 127 chunks created (~500 words avg)
                    ↓
        [Stage 3: Enrich ALL CHUNKS]
        → 3a. HierarchyEnricher     (127 chunks, ~127 ms)
        → 3b. KeywordEnricher       (127 chunks, ~12 sec)
        → 3c. LanguageEnricher      (127 chunks, ~0.5 sec)
        → 3d. ConfidenceEnricher    (127 chunks, ~0.1 sec)
                    ↓
        [Stage 4: Deduplication]
        → MinHash LSH: 3 near-duplicates found
        → 124 unique chunks, 3 marked duplicate
                    ↓
        [Stage 5: Embedding]
        → 124 chunks embedded (3 duplicates skipped)
        → ~12 sec (Ollama bge-m3 async batches)
                    ↓
        [Stage 6: Storage]
        → 127 IngestRecords upserted to Weaviate
        → All metadata (keywords, hierarchy, language, confidence) stored
                    ↓
        COMPLETE — Ready for retrieval & search
        
Total time: ~25 seconds for 200 KB PDF
```

---

## Summary

The **4-stage enrichment pipeline** transforms raw chunks into richly annotated, searchable documents:

1. **HierarchyEnricher** → Document navigation & context
2. **KeywordEnricher** → Semantic search targets
3. **LanguageEnricher** → Multi-language support
4. **ConfidenceEnricher** → Relevance scoring

All metadata is stored in Weaviate and available for:
- Filtering (e.g., "only English documents")
- Ranking (e.g., "prefer high-confidence sources")
- Display (e.g., breadcrumb navigation)
- Analytics (e.g., "which sections are most queried?")
