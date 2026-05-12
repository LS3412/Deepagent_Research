# DeepAgent KB Chatbot

A self-hosted, format-agnostic RAG chatbot built on **LangChain Deep Agents**, **Weaviate**, **Ollama**, and **Langfuse**. Ingest PDFs (and DOCX, HTML, MD, TXT, CSV, JSON…) and chat over them with a planner + retriever + verifier + writer agent stack.

## Stack
- **Agent harness**: `deepagents` (planning, virtual FS, sub-agents)
- **LLM**: `qwen3:14b` via Ollama
- **Embeddings**: `bge-m3` via Ollama
- **Vector DB**: Weaviate (Docker), `vectorizer=none`, hybrid (BM25 + HNSW)
- **Tracing**: Langfuse (Docker, optional)
- **UI**: Streamlit

## Quick start

1. **Copy env**: `cp .env.example .env` (Windows: `copy .env.example .env`) and fill in Langfuse keys if you want tracing.
2. **Install**: `pip install -r requirements.txt`
3. **Pre-pull models** (one-time): `ollama pull qwen3:14b && ollama pull bge-m3`
4. **Health check**: `python scripts/healthcheck.py`
5. **Ingest**: `python -m src.ingestion.cli ./data/watch` (or use the UI uploader)
6. **Chat**: `streamlit run app.py`

## End-to-End Pipeline

### Data Ingestion Flow
1. **File Upload** → Files ingested via CLI or Streamlit UI
2. **Parsing** → Format-specific parser (PDF, DOCX, HTML, MD, TXT, CSV, JSON) converts to text
3. **Chunking** → Large documents split into manageable chunks with overlap
4. **Deduplication** → Duplicate chunks removed to optimize storage
5. **Enrichment** → Optional metadata enrichment (summaries, keywords)
6. **Embedding** → Text converted to vectors using `bge-m3`
7. **Vector Storage** → Chunks indexed in Weaviate (hybrid BM25 + HNSW search)

### Query-to-Response Flow
1. **User Query** → Entered in Streamlit chat interface
2. **Agent Planning** → Deep Agent planner breaks down query intent
3. **Retrieval** → Hybrid search queries Weaviate for relevant chunks
4. **Verification** → Verifier agent checks relevance and accuracy
5. **Writing** → Writer agent synthesizes response from retrieved context
6. **Response** → Answer streamed back to user with sources

## Data Ingestion Pipeline

### Supported Formats
- **Documents**: PDF, DOCX, HTML, Markdown
- **Structured**: CSV, JSON
- **Text**: Plain text, RTF

### Ingestion Methods

#### CLI Ingestion
```bash
python -m src.ingestion.cli ./data/watch
```

#### Watched-Folder Ingestion
Drop files into `./data/watch/`:
```bash
python -m src.ingestion.watcher
```
The watcher monitors the folder and automatically ingests new files.

#### Streamlit UI Ingestion
Use the "Ingestion" page in the Streamlit app to upload files directly.

### Pipeline Stages
- **Registry**: Auto-discovers all registered parsers
- **Pipeline**: Orchestrates parsing → chunking → dedup → embedding → storage
- **Sink**: Writes vectors and metadata to Weaviate
- **Watcher** (optional): Long-running process for continuous ingestion

## Adding a new file format

1. Create `src/ingestion/parsers/<your>_parser.py` implementing the `Parser` protocol.
2. Call `register_parser(YourParser())` at module bottom.
3. Add the import to `src/ingestion/registry.py::load_builtin_parsers`.

The agent and Weaviate schema do not change.
