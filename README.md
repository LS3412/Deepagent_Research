# DeepAgent Research

A research repository exploring **Deep Agent architectures** for intelligent chatbot systems. It contains two complementary projects — one for querying **structured data** (tabular/product catalogs) and another for **unstructured data** (documents, PDFs, knowledge bases).

---

## Projects

### 1. `structured_chatbot/` — Deep Agents Product Search System

A **multi-agent orchestration system** for intelligent product search over structured/tabular data using LangChain Deep Agents, Weaviate, and Ollama.

**Architecture:**
- A `SearchLeadAgent` (orchestrator) coordinates four specialized sub-agents:
  - `IntentParserAgent` — Extracts search intent (category, brand, price, rating filters)
  - `VectorSearcherAgent` — Executes hybrid semantic + keyword (BM25) search
  - `ResultAnalyzerAgent` — Scores result quality and coverage
  - `SearchCriticAgent` — Validates results against the original query intent

**Key highlights:**
- 75% semantic + 25% keyword hybrid search ranking
- Supports 13 product categories and 25+ brands out of the box
- Data completeness scoring with quality badges (Excellent / Good / Fair)
- Full decision traceability across all agents
- Idempotent ingestion pipeline with versioned schema registry
- Streamlit UI (`app_deep_agents_ui.py`) for interactive search

**Data:** Includes structured datasets — products, orders, inventory, shipments, suppliers, employees, and locations.

---

### 2. `chatbot unstructured data/` — DeepAgent KB Chatbot

A **self-hosted RAG chatbot** for querying unstructured documents (PDFs, DOCX, HTML, Markdown, CSV, JSON, TXT) using LangChain Deep Agents, Weaviate, and Ollama.

**Architecture:**
- Ingestion pipeline: File upload → Parse → Chunk → Deduplicate → Embed → Store in Weaviate
- Agent stack: Planner → Retriever → Verifier → Writer
- Hybrid retrieval: BM25 + HNSW vector search

**Key highlights:**
- Format-agnostic ingestion (pluggable parser protocol)
- Watched-folder for continuous auto-ingestion
- Optional Langfuse tracing for full observability
- Streamlit UI for both chat and document ingestion
- LLM: `qwen3:14b` via Ollama | Embeddings: `bge-m3` via Ollama

---

## Repository Structure

```
DeepAgent_bot/
├── structured_chatbot/          # Multi-agent product search (structured data)
├── chatbot unstructured data/   # RAG KB chatbot (unstructured documents)
└── README.md                    # This file
```

---

## Common Prerequisites

- [Ollama](https://ollama.com/) running locally
- [Docker](https://www.docker.com/) (for Weaviate)
- Python 3.10+
- `pip install -r requirements.txt` (inside each project folder)
