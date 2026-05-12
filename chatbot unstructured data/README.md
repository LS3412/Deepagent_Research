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

## Optional: watched-folder ingestion

Drop files into `./data/watch/`:
```
python -m src.ingestion.watcher
```

## Adding a new file format

1. Create `src/ingestion/parsers/<your>_parser.py` implementing the `Parser` protocol.
2. Call `register_parser(YourParser())` at module bottom.
3. Add the import to `src/ingestion/registry.py::load_builtin_parsers`.

The agent and Weaviate schema do not change.
