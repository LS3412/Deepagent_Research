# DeepAgent KB Chatbot — Complete Architecture & Ingestion Guide

> **Last updated:** May 12, 2026

## Table of Contents
1. [End-to-End System Architecture](#end-to-end-system-architecture)
2. [Data Ingestion Pipeline](#data-ingestion-pipeline)
3. [Query Processing Flow](#query-processing-flow)
4. [KB Grounding & Guardrails](#kb-grounding--guardrails)
5. [Skills System](#skills-system)
6. [ReAct Agent Model Call Pattern](#react-agent-model-call-pattern)
7. [Technology Stack](#technology-stack)

---

## End-to-End System Architecture

### Overview Diagram

```
+-------------------------------------------------------------------------+
|                      DEEPAGENT KB CHATBOT SYSTEM                        |
+-------------------------------------------------------------------------+

                       +---------------------------+
                       |     DATA ENTRY POINTS     |
                       +-----------+---------------+
                                   |
               +-------------------+-------------------+
               |                   |                   |
       +-------+------+    +-------+------+    +-------+------+
       |     CLI      |    |   Watcher    |    |  Streamlit   |
       |   Upload     |    |  (Monitor    |    |   Upload     |
       |              |    |   Folder)    |    |   Files      |
       +-----------+--+    +-----+--------+    +------+-------+
               |                 |                    |
               +-----------------+--------------------+
                                 |
               +-----------------v--------------------+
               |         INGESTION PIPELINE           |
               |  Parse -> Chunk -> Enrich            |
               |  Dedup -> Embed -> Store             |
               +------------------+-------------------+
                                  |
               +------------------v-------------------+
               |        WEAVIATE VECTOR DB            |
               |  BM25 + HNSW hybrid search           |
               |  Score filter: min 0.45              |
               |  Returns NO_RELEVANT_RESULTS         |
               |  when nothing passes threshold       |
               +------------------+-------------------+
                                  |
               +------------------v-------------------+
               |      USER QUERY (STREAMLIT)          |
               +------------------+-------------------+
                                  |
               +------------------v-------------------------------+
               |       DEEPAGENTS ORCHESTRATION                  |
               |   MAIN AGENT (ReAct loop)                       |
               |   + Skill selector (7 skills)                   |
               |   + KB-only system prompt                       |
               +------------------+------------------------------+
                                  |
                                  |  ReAct MODEL CALL #1
                                  |  (decides which tool to call)
                                  |
               +------------------v------------------------------+
               |  hybrid_search(query, k=6)                     |
               |  ______________________________________________ |
               |  Score >= 0.45  ->  return relevant chunks     |
               |  Score <  0.45  ->  return NO_RELEVANT_RESULTS |
               +------------------+------------------------------+
                                  |
                                  |  ReAct MODEL CALL #2
                                  |  (writes answer from tool results)
                                  |
               +------------------v------------------------------+
               |       KB GROUNDING GUARDRAIL                   |
               |  ______________________________________________ |
               |  Check 1: Citation brackets present?           |
               |  Check 2: "knowledge base" language?           |
               |  Check 3: Topic keywords match answer?         |
               |  Check 4: NO_RELEVANT_RESULTS in trace?        |
               |                                                |
               |  FAIL -> polite not-found reply                |
               |  PASS -> show answer to user                   |
               +------------------+------------------------------+
                                  |
               +------------------v-------------------+
               |      FINAL RESPONSE TO USER          |
               |  Cited Answer + Sources section      |
               +--------------------------------------+
```

---

## Data Ingestion Pipeline

### Complete Ingestion Flow

```
FILE SOURCE
   |
   +- Manually via CLI:        python -m src.ingestion.cli ./data/watch
   +- Auto via Watcher:        python -m src.ingestion.watcher
   +- Upload via Streamlit UI: Sidebar -> Upload Files -> Ingest

   |
   v

+------------------------------------------------------------------+
| STAGE 1: PARSE -- Extract structured blocks from raw bytes       |
+------------------------------------------------------------------+
|  Library: unstructured[all-docs]                                 |
|  File:    src/ingestion/parsers/unstructured_parser.py           |
|                                                                  |
|  INPUT:   Raw file bytes (any format)                            |
|  PROCESS: Detect format -> Extract elements + metadata           |
|  OUTPUT:  Block[] with:                                          |
|           - text (element content)                               |
|           - page (page number)                                   |
|           - section (parent heading)                             |
|           - element_type (Title, NarrativeText, Table, etc.)     |
|           - element_id, parent_id, depth, language               |
|                                                                  |
|  SUPPORTED: PDF, DOCX, PPTX, HTML, Markdown, CSV, JSON, TXT     |
+------------------------------------------------------------------+
   |
   v

+------------------------------------------------------------------+
| STAGE 2: CHUNK -- Split elements into semantic chunks            |
+------------------------------------------------------------------+
|  Library: langchain-text-splitters                               |
|  File:    src/ingestion/chunker.py                               |
|                                                                  |
|  - Keep tables/code blocks whole                                 |
|  - Split long text at sentences/paragraphs                       |
|  - Max chunk size: 512-1024 tokens                               |
|  - Preserve element_type, depth, parent_id                       |
+------------------------------------------------------------------+
   |
   v

+------------------------------------------------------------------+
| STAGE 3: ENRICH -- Add semantic metadata                         |
+------------------------------------------------------------------+
|  File: src/ingestion/enricher.py                                 |
|                                                                  |
|  3a. HierarchyEnricher  -> ancestral_headings, hierarchy_path   |
|  3b. KeywordEnricher    -> keywords[] (KeyBERT + bge-m3)         |
|  3c. LanguageEnricher   -> language ISO 639-1 (langdetect)       |
|  3d. ConfidenceEnricher -> confidence_score 0.0-1.0 (rule-based) |
+------------------------------------------------------------------+
   |
   v

+------------------------------------------------------------------+
| STAGE 4: DEDUPLICATE -- Remove near-duplicate chunks             |
+------------------------------------------------------------------+
|  Library: datasketch (MinHash LSH)                               |
|  File:    src/ingestion/deduplicator.py                          |
|                                                                  |
|  LEVEL 1 -- File-level (fast path):                              |
|    SHA256(file_bytes) already seen? -> skip entire file          |
|                                                                  |
|  LEVEL 2 -- Chunk-level (near-dedup):                            |
|    MinHash signature -> LSH bucket lookup                        |
|    Jaccard similarity >= 0.85 -> mark duplicate, skip embedding  |
|                                                                  |
|  Scale: O(1) lookup, handles 100K+ docs                          |
+------------------------------------------------------------------+
   |
   v

+------------------------------------------------------------------+
| STAGE 5: EMBED -- Generate vector embeddings                     |
+------------------------------------------------------------------+
|  Library: langchain-ollama  Model: bge-m3 (1024-dim)             |
|  File:    src/ingestion/embedder.py                              |
|                                                                  |
|  - Batch size: 32 chunks per batch                               |
|  - Async concurrent batching (asyncio.gather) -- 3-4x faster    |
|  - Duplicates skipped, already-stored chunks skipped            |
+------------------------------------------------------------------+
   |
   v

+------------------------------------------------------------------+
| STAGE 6: STORE -- Persist to Weaviate Vector DB                  |
+------------------------------------------------------------------+
|  Library: weaviate-client   File: src/ingestion/sink.py          |
|  Collection: "Document"                                          |
|                                                                  |
|  TEXT FIELDS:   text, source_file, section, element_type         |
|  VECTOR FIELD:  vector (1024-dim)                                |
|  METADATA:      page_number, ancestral_headings, keywords,       |
|                 language, confidence_score, chunk_id,            |
|                 file_hash (SHA256), ingestion_timestamp          |
|                                                                  |
|  SEARCH: BM25 (keyword) + HNSW (vector) + reranker-transformers  |
|  FILTER: By language, confidence, date, section, file            |
|  MULTI-TENANT: each tenant_id is isolated                        |
+------------------------------------------------------------------+
   |
   v
+------------------------------------------------------------------+
|  OK READY FOR SEARCH                                             |
+------------------------------------------------------------------+
```

### File Format Support Matrix

| Format   | Parser       | Element Extraction | Table Support | Notes               |
|----------|--------------|--------------------|---------------|---------------------|
| PDF      | Unstructured | Excellent          | Intact        | OCR support         |
| DOCX     | Unstructured | Full               | Intact        | Preserves formatting|
| PPTX     | Unstructured | Slides             | Limited       | Speaker notes OK    |
| HTML     | Unstructured | DOM elements       | Intact        | Strips scripts      |
| Markdown | Unstructured | Headers, lists     | GFM           | Structure-aware     |
| CSV      | Unstructured | Rows               | Full          | Header as metadata  |
| JSON     | Unstructured | Key-value trees    | Nested        | Flattened to blocks |
| TXT      | Unstructured | Paragraphs         | None          | Fallback option     |

---

## Query Processing Flow

```
USER TYPES QUESTION
  "what are the battery insertion steps?"
  |
  v

STREAMLIT UI
  +- Pre-processing: load indexed doc list
  +- Pass question + skill files to DeepAgent

  |
  v

PHASE 1: SKILL SELECTION (SkillsMiddleware)
  +- Match question against 7 skill descriptions
  +- "steps / insertion" -> procedure-qa skill activated
  +- citation-style activated at write time only

  |
  v

PHASE 2: MAIN AGENT -- MODEL CALL #1  (ReAct: decide tool)
  +- Read MAIN_PROMPT + selected skill instructions
  +- Absolute rule: NEVER answer from training knowledge
  +- Must call hybrid_search BEFORE answering
  +- Output: tool call -> hybrid_search("battery insertion steps", k=6)

  |
  v

PHASE 3: hybrid_search EXECUTES  (Weaviate)
  +- BM25 keyword match + HNSW vector similarity
  +- Merge + score results
  +- Drop all chunks with score < 0.45  (score filter)
  |
  +- IF relevant chunks found (score >= 0.45):
  |     Return list of hit dicts [{text, file_name, page, score, ...}]
  |
  +- IF nothing passes threshold:
        Return "NO_RELEVANT_RESULTS: ..." string

  |
  v

PHASE 4: MAIN AGENT -- MODEL CALL #2  (ReAct: write answer)
  +- Input: original question + tool result
  |
  +- IF tool returned NO_RELEVANT_RESULTS:
  |     -> Must use not-found reply template
  |     -> Call list_documents() to list indexed files
  |     -> Reply: "I am sorry, but the knowledge base does not
  |               contain information about [topic]..."
  |
  +- IF tool returned hits:
        -> Synthesise answer from chunk text only
        -> Add [file p.N] inline citations on every claim
        -> End with Sources section

  |
  v

PHASE 5: KB GROUNDING GUARDRAIL  (Streamlit post-processing)
  +- Check 1: Does answer contain [citation] brackets?
  +- Check 2: Does answer contain "knowledge base" language?
  +- Check 3: Do question keywords appear in answer?
  |           e.g. "black hole" -> answer talks about batteries
  |           -> TOPIC MISMATCH -> block
  +- Check 4: Did trace show NO_RELEVANT_RESULTS but agent answered?
  |           -> block
  |
  +- GUARDRAIL PASSES -> show answer to user
  +- GUARDRAIL BLOCKS -> replace with polite not-found reply:
       "I am sorry, but I could not find information about that
        topic in the knowledge base.
        Please ask questions related to the indexed documents:
        - [file 1], [file 2], ...
        You can also upload new documents using the sidebar."

  |
  v

PHASE 6: DISPLAY TO USER
  +- Render final answer (Markdown)
  +- Show agent trace (expandable)
  +- Save to chat history (SQLite)
  +- Log to Langfuse (if enabled)
```

---

## KB Grounding & Guardrails

### Three-Layer Defence Against Off-Topic Answers

```
LAYER 1 -- PROMPT  (src/agent/prompts.py)
-----------------------------------------
Absolute rule at top of MAIN_PROMPT:
  "NEVER use training data, world knowledge, or pre-trained facts
   to answer ANY factual question."
  "If hybrid_search returns NO_RELEVANT_RESULTS -> use not-found reply."
  "If results are about a different topic -> treat as NO_RELEVANT_RESULTS."
  Explicit examples: "What is a black hole? -> NO answer from training data."

LAYER 2 -- SEARCH FILTER  (src/retrieval/search.py + src/config.py)
--------------------------------------------------------------------
retrieval_min_score = 0.45  (configurable via .env)

After every hybrid_search:
  chunks = [c for c in results if c["score"] >= 0.45]

  IF chunks is empty:
    tool returns "NO_RELEVANT_RESULTS: The knowledge base contains
    no chunks relevant to this query. Use the standard not-found reply."

  ELSE:
    tool returns the filtered chunk list

LAYER 3 -- STREAMLIT GUARDRAIL  (src/ui/streamlit_app.py)
----------------------------------------------------------
After agent finishes streaming, inspect final_answer:

  _is_grounded(answer):
    - Has [citation] brackets?     -> PASS
    - Contains "knowledge base"?   -> PASS
    - Length <= 200 chars (conv)?  -> PASS
    - Otherwise                    -> FAIL

  _topics_match(question, answer):
    - Extract keywords (>=4 chars, not stop words) from question
    - Check if at least one keyword appears in answer
    - "black hole" -> {"black","hole"} -> not in battery answer -> FAIL

  should_block = (
    not _is_grounded(answer)
    OR (NO_RELEVANT_RESULTS in trace AND "knowledge base" not in answer)
    OR (not already_not_found AND not _topics_match(question, answer))
  )

  IF should_block:
    replace answer with polite not-found reply
    log warning with reason
```

### Not-Found Reply Template

```
I am sorry, but I could not find information about that topic
in the knowledge base.

Please ask questions related to the indexed documents:
- BatteryTestingSWIs_BatteryManager...
- BatteryTestingSWIs_BatteryShopIns...
- ...

You can also upload new documents using the sidebar.
```

---

## Skills System

### Skill Selection (7 Skills)

The `SkillsMiddleware` matches the user question against each skill description.
`citation-style` is used **only at write time** -- not for every question.

| Question Type                         | Trigger Words                                | Skill           |
|---------------------------------------|----------------------------------------------|-----------------|
| Factual lookup, "tell me about X"     | what, explain, describe, find                | kb-retrieval    |
| Steps, procedure, how-to             | how to, steps to, install, configure, run    | procedure-qa    |
| Numbers, tables, CSV, statistics      | how many, total, average, compare values     | table-qa        |
| Compare / contrast                    | compare, vs, difference between, pros/cons   | comparison      |
| Error / issue / fix                   | error, issue, not working, fix, debug        | troubleshooting |
| Nothing found in KB                   | NO_RELEVANT_RESULTS returned                 | not-found       |
| Writing the final answer (always last)| (applied at write time, any question type)   | citation-style  |

### Skills Directory

```
skills/
  citation-style/    Final answer formatting & citation rules
  kb-retrieval/      Primary retrieval workflow (default for factual Qs)
  table-qa/          Numeric & tabular data questions
  procedure-qa/      Step-by-step procedure questions
  comparison/        Compare two or more items side-by-side
  troubleshooting/   Diagnose and resolve errors/issues
  not-found/         Polite not-found reply template
```

---

## ReAct Agent Model Call Pattern

Every tool use requires **two separate LLM calls**. This is the standard
ReAct (Reason + Act) pattern -- not a bug or inefficiency.

```
+------------------------------------------------------+
|  MODEL CALL #1  (~3 min on CPU for qwen3:14b)        |
|                                                      |
|  Input:  user question + system prompt + skills      |
|  Output: tool-call decision                          |
|          -> hybrid_search("battery insertion", k=6)  |
|  Tokens: ~4096 in -> ~500 out                        |
+----------------------+-------------------------------+
                       |
              +--------v--------+
              |  hybrid_search  |  (~9s -- Weaviate query)
              |  tool executes  |
              +--------+--------+
                       |
+----------------------v-------------------------------+
|  MODEL CALL #2  (~3 min on CPU for qwen3:14b)        |
|                                                      |
|  Input:  original question + tool results (chunks)   |
|  Output: final cited answer shown to user            |
|  Tokens: ~4096 in -> ~450 out                        |
+------------------------------------------------------+

Formula: N tools called -> N+1 total model calls
```

**Why two calls?** The LLM is stateless -- it cannot pause mid-generation
to run a tool. Call 1 decides what to search; the tool executes; Call 2
reads the results and writes the answer.

**The ~6 min total** is model inference time (3m18s + 2m57s), not the
search (only ~9s). This is a qwen3:14b CPU inference characteristic.

---

## Technology Stack

### Architecture Components

| Component            | Technology                | Role                              | Why                                  |
|----------------------|---------------------------|-----------------------------------|--------------------------------------|
| Agent Orchestration  | LangChain DeepAgents      | Planning + ReAct + skill routing  | Multi-step reasoning, state mgmt     |
| LLM                  | Qwen 3 (14B) via Ollama   | Language understanding + writing  | Local inference, no external API     |
| Embeddings           | BGE-M3 (1024-dim) Ollama  | Vector representations            | Fast local, 55+ language support     |
| Vector DB            | Weaviate + Docker         | Persistent storage + hybrid search| HNSW + BM25 + reranking built-in     |
| Parsing              | Unstructured[all-docs]    | Multi-format document extraction  | One parser for all formats           |
| Chunking             | langchain-text-splitters  | Element-aware text segmentation   | Preserves document structure         |
| Enrichment           | KeyBERT + langdetect      | Keyword + language metadata       | Improves search recall               |
| Deduplication        | MinHash LSH (datasketch)  | Near-duplicate detection          | O(1) lookup, 100K+ docs              |
| Score Filter         | Custom (config: 0.45)     | Block low-relevance results       | Prevents off-topic answers           |
| Guardrail            | Custom (streamlit_app.py) | Topic-match + citation check      | Last-line defence vs hallucination   |
| Skills               | 7 SKILL.md files          | Per-question-type guidance        | Precise selection, no global default |
| Tracing              | Langfuse (Docker, opt.)   | LLM observability                 | Debug agent decisions                |
| UI                   | Streamlit                 | Interactive chat                  | Real-time streaming                  |
| Chat History         | SQLite                    | Conversation persistence          | Simple, file-based                   |

### Data Flow Architecture

```
LOCAL MACHINE (Your Laptop/Server)
+- Python Application (Streamlit)
|  +- Agent Orchestration (DeepAgents + ReAct)
|  +- Ingestion Pipeline (6 stages)
|  +- KB Grounding Guardrail (3 layers)
|  +- Retrieval & Search (score-filtered)
|
+- Docker Containers (localhost)
|  +- Ollama      ->  qwen3:14b (chat) + bge-m3 (embeddings)
|  +- Weaviate    ->  Vector DB (hybrid search)
|  +- Langfuse    ->  Tracing (optional)
|
+- Local Storage
   +- SQLite        ->  chat_history.db
   +- data/watch/   ->  drop files here for auto-ingest
   +- skills/       ->  7 SKILL.md files
   +- memory/       ->  AGENTS.md (agent context)

ALL SELF-HOSTED -- No external API calls needed
```

---

## Quick Reference

### Environment Setup
```bash
cp .env.example .env            # fill in Langfuse keys if needed
pip install -r requirements.txt
ollama pull qwen3:14b
ollama pull bge-m3
python scripts/healthcheck.py
```

### Running the System
```bash
docker-compose up -d                     # Weaviate + Langfuse
python -m src.ingestion.watcher          # auto-ingest watch folder
streamlit run app.py --server.port 8501  # chat UI
```

### Data Ingestion Methods
```bash
# CLI
python -m src.ingestion.cli ./data/watch

# Drop files for auto-ingest
cp document.pdf ./data/watch/

# Streamlit UI
# -> Sidebar -> Upload Files -> Click "Ingest uploaded"
```

### Tunable Settings (src/config.py or .env)

| Setting               | Default | Effect                                          |
|-----------------------|---------|-------------------------------------------------|
| retrieval_min_score   | 0.45    | Lower = more results; higher = stricter         |
| retrieval_top_k       | 6       | Chunks returned per search                      |
| hybrid_alpha          | 0.5     | 0=pure BM25, 1=pure vector, 0.5=balanced        |
| chunk_size            | 800     | Max tokens per chunk                            |
| chunk_overlap         | 120     | Overlap between adjacent chunks                 |
| dedup_threshold       | 0.85    | Jaccard similarity threshold for near-dedup     |

---

## Key Features

- Multi-Format Support: PDF, DOCX, PPTX, HTML, MD, CSV, JSON, TXT
- Hybrid Search: BM25 + Vector + Score Filter (0.45) + Reranking
- Smart Chunking: Element-aware, preserves document structure
- Semantic Enrichment: Keywords, language, confidence scores
- Two-Level Deduplication: File SHA256 + Chunk MinHash LSH
- 3-Layer KB Guardrail: Prompt + Score filter + Topic-match check
- 7 Targeted Skills: Selected per question type, not applied globally
- ReAct Agent: 2 model calls per tool use (standard pattern)
- Polite Not-Found Reply: Lists indexed docs, suggests upload
- Completely Self-Hosted: No external APIs needed
- Observable: Langfuse tracing + Streamlit agent trace
- Persistent: Chat history (SQLite) + Vector DB (Weaviate)
