# Deep Agents Product Search System

A sophisticated **multi-agent orchestration system** for intelligent product search using LangChain Deep Agents, Weaviate vector database, and Ollama embeddings.

## 🎯 Overview

This system implements a hierarchical agent architecture where a **Lead Agent** orchestrates four specialized **Sub-Agents** to understand user queries, execute hybrid searches, analyze results, and validate findings. The result is a robust, interpretable product search experience with full decision traceability.

### Architecture

```
User Query
    ↓
SearchLeadAgent (Orchestrator)
    ├─ IntentParserAgent     → Extract search intent (category, brand, price, rating)
    ├─ VectorSearcherAgent   → Hybrid semantic + keyword search
    ├─ ResultAnalyzerAgent   → Quality assessment and coverage metrics
    ├─ SearchCriticAgent     → Validate results against original intent
    └─ Synthesis             → Return complete SearchResponse
        ↓
    Results + Coverage + Quality + Full Trace
```

## ✨ Key Features

- **Multi-Agent Orchestration**: 5-agent hierarchical system for robust search
- **Hybrid Search**: 75% semantic + 25% keyword (BM25) ranking
- **Intent Understanding**: Automatic extraction of:
  - 13 product categories (Laptops, Monitors, Keyboards, etc.)
  - 25+ recognized brands (Dell, HP, Apple, NVIDIA, etc.)
  - Price ranges, minimum ratings, stock status
  - Hardware specifications and modifiers
- **Quality Metrics**:
  - Data completeness scoring (0-1)
  - Filter coverage assessment
  - Ranking validation
  - Data quality badges (🟢 Excellent / 🟡 Good / 🔴 Fair)
- **Full Traceability**: Complete decision log from all agents
- **Production-Ready Data Pipeline**:
  - Idempotent ingestion (no duplicates on re-runs)
  - Schema evolution with versioned registry
  - Comprehensive monitoring and observability

## 📁 Project Structure

```
.
├── README.md                          # This file
├── docker-compose.yml                 # Weaviate + volumes configuration
├── agents.md                          # Agent definitions and specifications
├── skills.md                          # Skill registry and descriptions
├── tools.md                           # Tool specifications
├── app_deep_agents_search.py         # Main search orchestration engine
├── app_deep_agents_ui.py             # Streamlit web interface
│
├── data/                              # Raw product datasets
│   ├── products.csv                   # Sample product catalog
│   ├── real_products.jsonl            # Full product catalog (JSONL)
│   ├── products.jsonl                 # Legacy format
│   ├── employees.csv                  # Employee directory
│   ├── orders.csv                     # Order history
│   ├── order_items.csv                # Order line items
│   ├── inventory.csv                  # Inventory levels
│   ├── shipments.csv                  # Shipment tracking
│   ├── suppliers.csv                  # Supplier information
│   ├── locations.csv                  # Warehouse locations
│   └── table_metadata.csv             # Data catalog metadata
│
├── indexer/                           # Data ingestion pipeline
│   ├── __init__.py
│   ├── build_real_catalog.py         # Production ingestion engine
│   └── schema_registry.json           # Versioned schema definitions
│
└── metrics/                           # Observability and monitoring
    └── ingestion_runs.jsonl           # Historical ingestion metrics
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Docker & Docker Compose
- Ollama (for embeddings)
- git

### Setup

1. **Clone the repository** (after pushing):
```bash
git clone https://github.com/LS3412/Deepagent_Research.git
cd structured_data_chatbot
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Start services**:
```bash
# Terminal 1: Start Weaviate vector database
docker-compose up weaviate

# Terminal 2: Start Ollama (if not already running)
ollama serve

# Terminal 3: Pull embedding model
ollama pull bge-m3
```

4. **Ingest product catalog**:
```bash
python indexer/build_real_catalog.py
```

5. **Run search API**:
```bash
python app_deep_agents_search.py
```

6. **Launch UI** (in another terminal):
```bash
streamlit run app_deep_agents_ui.py --server.port 8504
```

Open browser to: http://localhost:8504

## 💻 Usage Examples

### Python API

```python
from app_deep_agents_search import SearchLeadAgent

# Create agent
lead = SearchLeadAgent()

# Search
response = lead.search("gaming laptop with RTX 4080 under $2000")

# Access results
for i, result in enumerate(response.results[:5], 1):
    print(f"{i}. {result['name']} - ${result['unit_price']} ({result['relevance_score']:.0%})")

# View quality metrics
print(f"Data Quality: {response.data_quality_score:.0%}")
print(f"Coverage: {sum(response.coverage_assessment.values())}/5 filters")

# Inspect agent decision process
print("\n--- Agent Reasoning ---")
for line in response.agent_trace:
    print(line)
```

### Web UI (Streamlit)

Simply type a query in the interface:
- `"gaming laptop RTX 4080 budget"`
- `"Dell monitor under $500 for coding"`
- `"wireless keyboard mechanical"`
- `"NVIDIA graphics card 24GB VRAM"`

The system will:
1. Parse your intent (brand, category, price, specs)
2. Execute hybrid semantic+keyword search
3. Assess data quality
4. Validate results against intent
5. Display results with reasoning trace

## 🔧 Agent Responsibilities

| Agent | Role | Input | Output |
|-------|------|-------|--------|
| **SearchLeadAgent** | Orchestrator | User query | Complete SearchResponse |
| **IntentParserAgent** | Query understanding | Query text | Structured SearchIntent |
| **VectorSearcherAgent** | Search execution | SearchIntent | Ranked product list |
| **ResultAnalyzerAgent** | Quality assessment | Results + Intent | Analysis with metrics |
| **SearchCriticAgent** | Validation | Results + Analysis | Approval status |

## 📊 Supported Categories & Brands

### Categories (13)
Laptops, Monitors, Keyboards, Mice, Headphones, Webcams, Office Chairs, Storage, Printers, Networking, Smartphones, Tablets, Speakers

### Brands (25+)
Dell, HP, Lenovo, Apple, Sony, Samsung, Canon, Nikon, Intel, AMD, NVIDIA, Corsair, Razer, Logitech, Microsoft, Google, ASUS, Acer, MSI, Alienware, Steelseries, HyperX, SanDisk, Western Digital, Seagate, Crucial, Kingston

### Supported Specs
RTX, GPU, RAM, SSD, CPU, i9, i7, i5, 16GB, 32GB, 4K, HD, wireless, mechanical, noise cancelling, RGB, gaming, professional, portable

## ⚙️ Configuration

### Vector Search Settings
```python
# app_deep_agents_search.py
EMBED_MODEL = "bge-m3"                  # Primary embedding (1024-dim)
EMBED_FALLBACK = "nomic-embed-text"     # Fallback (768-dim)
WEAVIATE_HOST = "localhost"
WEAVIATE_PORT = 8080
WEAVIATE_GRPC = 50051
COLLECTION_NAME = "RealProductCatalog"
```

### Hybrid Search Parameters
```python
alpha = 0.75  # 75% semantic + 25% keyword (BM25)
```

### Ingestion Pipeline
Configure in `indexer/build_real_catalog.py`:
- Idempotency via UUID5 deterministic hashing
- Schema evolution tracking in `schema_registry.json`
- Run monitoring in `metrics/ingestion_runs.jsonl`

## 📈 Performance

- **Intent Parsing**: ~50ms
- **Embedding**: ~420ms
- **Vector Search**: ~200ms
- **Analysis & Critique**: ~40ms
- **Total Latency**: ~710ms per query

## 🔍 Monitoring

### Ingestion Metrics
Every ingestion run logs metrics to `metrics/ingestion_runs.jsonl`:
- Run ID, duration
- Insert/update/skip counts
- Throughput (records/second)
- Latency stats (min/max/avg)
- Data quality statistics

### Application Monitoring
Enable debug traces in code:
```python
response.agent_trace  # Full decision log from all agents
response.coverage_assessment  # Which filters were applied
response.ranking_explanation  # Why top result ranked first
response.alternatives  # Suggestions to improve search
```

## 🧪 Testing

Run the ingestion pipeline tests:
```bash
pytest indexer/  -v
```

Test the search system:
```bash
python -c "
from app_deep_agents_search import SearchLeadAgent
lead = SearchLeadAgent()
result = lead.search('laptop')
print(f'✅ Found {len(result.results)} results')
"
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Weaviate connection failed | Check `docker-compose up` is running |
| Ollama connection failed | Verify `ollama serve` is running |
| No embedding model | Run `ollama pull bge-m3` |
| No results found | Check product catalog ingestion with `python indexer/build_real_catalog.py` |
| Low relevance scores | Review query keywords - more specific queries work better |

## 📚 Documentation

- **agents.md** - Detailed agent specifications and capabilities
- **skills.md** - Skill definitions and tool registry
- **tools.md** - Tool specifications and usage
- **indexer/** - Production data pipeline documentation

## 🤝 Contributing

- Follow existing code style
- Add tests for new features
- Update README and documentation
- Run full test suite before submitting

## 📝 License

This project is part of the Deepagent Research initiative.

## 👥 Contact

For questions or contributions, reach out via GitHub issues.

---

**Built with**: Python 3.9+ | LangChain | Weaviate | Ollama | Streamlit
