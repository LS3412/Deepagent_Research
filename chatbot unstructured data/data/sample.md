# Sample Product Documentation

## Overview
The DeepAgent KB Chatbot is a self-hosted RAG system that ingests unstructured data
(PDFs, DOCX, HTML, Markdown, CSV, JSON, etc.) into Weaviate and allows you to chat
over them using LangChain Deep Agents.

## Architecture
The system uses:
- **Agent**: LangChain Deep Agents with planning, retrieval, verification, and writing sub-agents
- **LLM**: qwen3:14b via Ollama (local, no cloud)
- **Embeddings**: bge-m3 via Ollama (multilingual, 1024-dim vectors)
- **Vector DB**: Weaviate with hybrid search (BM25 + HNSW)
- **Tracing**: Langfuse (optional, for observability)

## Features
1. Format-agnostic ingestion: drop any file, the system figures out the parser
2. Idempotent pipeline: re-ingest the same file = no-op (SHA-256 dedup)
3. Tenant isolation: every query includes a tenant filter
4. Multi-hop retrieval: agent can call retriever → verifier → writer sub-agents
5. Citation tracking: every answer includes `[file_name p.<page>]` citations

## Installation
```
pip install -r requirements.txt
python scripts/healthcheck.py
python -m src.ingestion.cli ./data/watch
streamlit run app.py
```

## Supported Formats (v1)
- PDF (text + tables via Docling with OCR fallback)
- DOCX (paragraphs + tables)
- HTML (via trafilatura)
- Markdown
- Plain text
- CSV / TSV
- JSON / JSONL

## Query Example
**User**: "What are the key features of this system?"
**Agent**: 
  1. Calls list_documents() to see what's indexed
  2. Delegates to researcher sub-agent to search for "features"
  3. Researcher runs hybrid_search, saves results to /retrieved/hash.json
  4. Delegates to writer to compose answer from /retrieved/hash.json
  5. Delegates to verifier to check citations are correct
  6. Returns final answer: "Key features are [1] format-agnostic ingestion (sample.md p.1), ..."
