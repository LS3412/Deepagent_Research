I'll explain the **complete data ingestion pipeline** in simple steps:

---

## **COMPLETE DATA INGESTION PIPELINE — Simple Explanation**

### **OVERVIEW: Where Data Goes**

```
Your Files
    ↓
Parse (detect format)
    ↓
Chunk (split into pieces)
    ↓
Embed (create vectors)
    ↓
Store in Weaviate
    ↓
Ready to search
```

---

### **STEP 1: WHERE DOES DATA COME FROM?** (3 Entry Points)

```
FILE SOURCES:

A) CLI Command:
   python -m src.ingestion.cli ./data/watch
   └─ Manually ingest a folder

B) File Watcher (Automated):
   python -m src.ingestion.watcher
   └─ Monitors ./data/watch/ folder
   └─ Auto-ingests new files

C) Streamlit UI (User Upload):
   Sidebar → Upload files → Click "Ingest uploaded"
   └─ Upload directly from browser
```

---

### **STEP 2: CHECK IF ALREADY INGESTED (Deduplication)**

```
File arrives: document.pdf

1. Calculate SHA256 hash:
   SHA256(file_bytes) = "abc123def456..."
   
2. Check Weaviate:
   "Is this SHA256 already indexed for this tenant?"
   
   IF YES:
   └─ Skip ✗ (Already have this exact file)
   
   IF NO:
   └─ Continue ✓
```

**Why?** Prevents duplicate chunks in the database.

---

### **STEP 3: DETECT FILE FORMAT** (MIME Type Detection)

```
File: document.pdf

1. Get file extension: .pdf
2. Guess MIME type: application/pdf
3. Select Parser:
   
   ├─ PDF (.pdf) → pdf_parser
   ├─ Word (.docx) → docx_parser
   ├─ HTML (.html) → html_parser
   ├─ Markdown (.md) → markdown_parser
   ├─ JSON (.json) → json_parser
   ├─ CSV (.csv) → csv_parser
   └─ Text (.txt) → text_parser
   
4. If no match:
   └─ Fall back to text_parser (reads as plain text)
```

---

### **STEP 4: PARSE FILE TO BLOCKS** (Extract Text + Metadata)

Each parser extracts **structured blocks** from the raw file:

#### **PDF Parser Example:**
```
Input: document.pdf (raw bytes)
         ↓
Process: Extract text page by page + OCR if needed
         ↓
Output: [Block, Block, Block, ...]

Each Block contains:
├─ text: "This is content..."
├─ page: 3
├─ section: "Chapter 1: Introduction"
└─ extra: {font, size, etc.}
```

#### **CSV Parser Example:**
```
Input: data.csv
       col1,col2,col3
       value1,value2,value3
         ↓
Output: [Block, Block, ...]

Each Block:
├─ text: "col1: value1, col2: value2, col3: value3"
├─ page: None (no pages in CSV)
├─ section: "Row 1"
└─ extra: {original_row: 1}
```

#### **HTML Parser Example:**
```
Input: webpage.html
       <h1>Title</h1>
       <p>Content here</p>
         ↓
Output: [Block, Block, ...]

Each Block:
├─ text: "Title"
├─ page: None
├─ section: "h1"
└─ extra: {tag: h1}
```

**Result**: Format-agnostic! All become standard `Block` objects.

---

### **STEP 5: CHUNK INTO RETRIEVAL-SIZE PIECES** (Recursive Chunker)

Raw blocks might be too long for retrieval. Split intelligently:

```
Block text:
"Lorem ipsum dolor sit amet. Consectetur adipiscing elit. 
 Sed do eiusmod tempor. Incididunt ut labore et dolore magna aliqua."

Config:
├─ chunk_size: 800 characters
├─ chunk_overlap: 120 characters
└─ separators: ["\n\n", "\n", ". ", "? ", "! ", etc.]

Process (Recursive Splitting):

1. Try separator "\n\n" (paragraph)
   └─ If parts fit in 800 chars → use it
   
2. If too long, try "\n" (newline)
   └─ If parts fit → use it
   
3. If still too long, try ". " (sentence)
   └─ If parts fit → use it
   
4. If still too long, try " " (word)
   └─ If parts fit → use it
   
5. If still too long, split every 1 char
   └─ Last resort

Add Overlap (120 chars from previous chunk at start):
Chunk 1: "Lorem ipsum dolor sit amet. Consectetur adipiscing elit."
Chunk 2: "Consectetur adipiscing elit. Sed do eiusmod tempor."  ← Overlaps!
Chunk 3: "Sed do eiusmod tempor. Incididunt ut labore et dolore magna aliqua."

Output: [Chunk, Chunk, Chunk, ...]

Each Chunk:
├─ text: "Lorem ipsum dolor sit amet. Consectetur adipiscing elit."
├─ chunk_index: 0
├─ page: 3 (preserved from Block)
├─ section: "Introduction" (preserved from Block)
└─ extra: {...}
```

**Why Overlap?** If search hits chunk boundary, you get full context.

---

### **STEP 6: GENERATE EMBEDDINGS** (Vector Creation)

Each chunk converted to a **dense vector** (mathematical representation):

```
Chunk text: "The system uses bge-m3 embeddings"

Embedding Model: bge-m3 (via Ollama)

Process (Batch):
├─ Collect 32 chunks (batch_size=32)
├─ Send all 32 to bge-m3
├─ Retry up to 3 times if fails (exponential backoff)
└─ Return 32 vectors

Each vector:
├─ Dimensions: 1024
├─ Type: list of floats
└─ Example: [0.123, -0.456, 0.789, ..., 0.234]

This vector represents the MEANING of the text.
Allows semantic search (finding similar meaning).
```

**Why batching?** Faster than embedding one-by-one.

---

### **STEP 7: UPSERT TO WEAVIATE** (Store in Vector DB)

Each chunk + vector stored as one record:

```
Input: IngestRecord (chunk + vector + metadata)

IngestRecord contains:
├─ text: "The system uses bge-m3..."
├─ vector: [0.123, -0.456, ...]
├─ tenant_id: "default"
├─ doc_sha256: "abc123def456..."
├─ source_uri: "file:///path/to/doc.pdf"
├─ file_name: "doc.pdf"
├─ mime_type: "application/pdf"
├─ format: "pdf"
├─ chunk_index: 0
├─ page: 3
├─ section: "Introduction"
├─ language: "en"
├─ tags: ["important", "archived"]
├─ created_at: "2026-05-04T10:30:00Z"
├─ ingested_at: "2026-05-04T10:35:00Z"
└─ extra_json: "{...}"

Weaviate Process:
├─ Connect to collection "Document"
├─ Use dynamic batching (faster writes)
└─ Add object with vector + properties

Result:
└─ Record stored in Weaviate ✓
```

**Output of entire pipeline for ONE file:**

```
Input: 1 PDF file

Output: N records in Weaviate
(N = number of chunks created)

Example:
├─ Chunk 0 of doc.pdf → record 1
├─ Chunk 1 of doc.pdf → record 2
├─ Chunk 2 of doc.pdf → record 3
└─ ... (10 chunks = 10 records)
```

---

## **COMPLETE INGESTION FLOW (Visual)**

```
┌──────────────────────────────────────────┐
│  FILE SOURCE                             │
│  ├─ CLI, Watcher, or UI Upload          │
│  └─ File loaded as bytes                │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 1: DEDUPLICATION (SHA256)          │
│  ├─ Calculate hash                      │
│  ├─ Check if already in Weaviate       │
│  └─ If yes → SKIP ✗                    │
│     If no → CONTINUE ✓                 │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 2: MIME TYPE DETECTION             │
│  ├─ File extension + MIME guess         │
│  └─ Select appropriate parser           │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 3: PARSING (Format → Blocks)      │
│  ├─ PDF parser → Extract pages+text    │
│  ├─ CSV parser → Extract rows          │
│  ├─ HTML parser → Extract elements     │
│  └─ Output: List of Blocks             │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 4: CHUNKING (Blocks → Chunks)     │
│  ├─ Split by separators (¶, \n, ., etc)│
│  ├─ Size: 800 chars                    │
│  ├─ Overlap: 120 chars                 │
│  ├─ Preserve page/section metadata     │
│  └─ Output: List of Chunks             │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 5: EMBEDDING (Chunks → Vectors)  │
│  ├─ Batch 32 chunks at a time          │
│  ├─ bge-m3 model → 1024-dim vectors    │
│  ├─ Retry up to 3x on failure          │
│  └─ Output: Vectors for all chunks     │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 6: CREATE RECORDS                  │
│  ├─ Combine chunk + vector              │
│  ├─ Add metadata (page, section, etc)  │
│  ├─ Add tenant_id (multi-tenant)       │
│  └─ Output: IngestRecord list           │
└────────────────┬─────────────────────────┘
                 ↓
┌──────────────────────────────────────────┐
│  STEP 7: STORE IN WEAVIATE               │
│  ├─ Connect to "Document" collection    │
│  ├─ Batch upsert all records           │
│  ├─ Index for BM25 (full-text)         │
│  ├─ Index for HNSW (vector search)     │
│  └─ ✓ Done!                            │
└──────────────────────────────────────────┘
```

---

## **INGESTION EXAMPLE: REAL FILE**

### **Input:**
```
PDF File: user_guide.pdf (5 pages, 50 KB)
```

### **Processing:**

```
Step 1: Deduplicate
├─ SHA256 = "a1b2c3d4e5f6..."
├─ Check Weaviate: Not found ✓
└─ Continue

Step 2: MIME Detection
├─ Extension: .pdf
├─ MIME: application/pdf
├─ Parser: pdf_parser ✓

Step 3: Parse to Blocks
├─ Page 1: Extract text → Block 1
├─ Page 2: Extract text → Block 2
├─ Page 3: Extract text → Block 3
├─ Page 4: Extract text → Block 4
├─ Page 5: Extract text → Block 5
└─ Total: 5 Blocks

Step 4: Chunk (800 chars each)
├─ Block 1 (2000 chars) → Chunk 0 + Chunk 1 + Chunk 2
├─ Block 2 (1500 chars) → Chunk 3 + Chunk 4
├─ Block 3 (2200 chars) → Chunk 5 + Chunk 6 + Chunk 7
├─ Block 4 (1000 chars) → Chunk 8
├─ Block 5 (1800 chars) → Chunk 9 + Chunk 10
└─ Total: 11 Chunks

Step 5: Embed (Batch 32)
├─ Batch 1: Chunks 0-10 (all 11)
├─ Send to bge-m3
└─ Get 11 vectors (1024-dim each)

Step 6: Create Records
├─ Record 0: (Chunk 0 text + Vector 0 + metadata)
├─ Record 1: (Chunk 1 text + Vector 1 + metadata)
├─ Record 2: (Chunk 2 text + Vector 2 + metadata)
...
└─ Record 10: (Chunk 10 text + Vector 10 + metadata)

Step 7: Store
├─ Upsert 11 records to Weaviate
└─ ✓ INDEXED (11 chunks from 1 file)
```

### **Result:**
```
Input: 1 PDF file (5 pages)
Output: 11 searchable chunks in Weaviate

Later, when user searches:
"What does the user guide say?"
├─ Hybrid search runs
├─ Finds matching chunks
└─ Returns top 6 with citations
```

---

## **CONFIG PARAMETERS FOR INGESTION**

From config.py:

```python
chunk_size: int = 800              # Bytes per chunk
chunk_overlap: int = 120           # Overlap bytes
chunk_strategy: str = "recursive"  # Splitting strategy
embed_batch_size: int = 32         # Chunks per batch
```

---

## **ENTRY POINTS SUMMARY**

| Entry Point | Command | Auto? | Use Case |
|-------------|---------|-------|----------|
| **CLI** | `python -m src.ingestion.cli ./data/watch` | ❌ Manual | Bulk ingest |
| **Watcher** | `python -m src.ingestion.watcher` | ✅ Auto | Monitor folder |
| **UI** | Upload in Streamlit sidebar | ❌ Manual | Web upload |

---

## **KEY POINTS**

✅ **Idempotent**: SHA256 prevents re-ingesting same file  
✅ **Format-agnostic**: Any format → standard Blocks → standard Chunks  
✅ **Metadata preserved**: Page numbers, sections travel through entire pipeline  
✅ **Overlap**: Prevents losing context at chunk boundaries  
✅ **Batched embeddings**: Fast (32 at a time, with retries)  
✅ **Multi-tenant**: Each record tagged with tenant_id for isolation  
✅ **Hybrid-ready**: Stored for both BM25 + vector search  

---

## **SUMMARY IN 3 SENTENCES**

1. **File arrives** → Deduplicate by SHA256, detect format, select parser
2. **Parse & chunk** → Convert to standard blocks, split into 800-char pieces with overlap, preserve metadata
3. **Embed & store** → Create 1024-dim vectors (batched), upsert to Weaviate with full metadata → Ready to search

**That's the complete data ingestion pipeline!** 🎯