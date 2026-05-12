# DEEP AGENTS SYSTEM - TOOLS & DEPENDENCIES

## Overview

The Deep Agents system uses a combination of **external tools**, **libraries**, and **infrastructure services** to operate.

---

## 🎯 TOOL CATEGORIES

1. **Vector Database Tool** - Weaviate
2. **Embedding Service Tool** - Ollama
3. **Python Libraries** - Core & supporting
4. **Infrastructure** - Docker
5. **External Services** - Optional

---

## 🔧 PRIMARY TOOLS

### Tool 1: WEAVIATE (Vector Database)

**What it is**: Powerful vector database for similarity search  
**Location**: localhost:8080 (HTTP), localhost:50051 (gRPC)  
**Deployment**: Docker container (via docker-compose.yml)

#### Purpose in Deep Agents
- Store 1024-dimensional product vectors (bge-m3 embeddings)
- Execute hybrid search (75% semantic + 25% keyword)
- Apply complex filters (category, price, brand, rating, stock)
- Return scored results

#### Configuration
```yaml
# docker-compose.yml
services:
  weaviate:
    image: semitechnologies/weaviate:latest
    ports:
      - "8080:8080"      # HTTP
      - "50051:50051"    # gRPC
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"
    volumes:
      - weaviate_data:/var/lib/weaviate
```

#### Python Integration
```python
import weaviate
import weaviate.classes as wvc
from weaviate.classes.query import Filter

# Connect
client = weaviate.connect_to_local(
    host="localhost",
    port=8080,
    grpc_port=50051
)

# Access collection
coll = client.collections.get("RealProductCatalog")

# Hybrid search with filters
results = coll.query.hybrid(
    query="gaming laptop",
    vector=query_vector,
    alpha=0.75,  # 75% dense, 25% keyword
    filters=Filter.by_property("category").equal("Laptops"),
    limit=10,
    return_metadata=wvc.query.MetadataQuery(score=True)
)

# Close connection
client.close()
```

#### Collection Schema
```
RealProductCatalog {
    product_id: string
    sku: string
    name: string (indexed)
    category: string (filterable)
    brand: string (filterable)
    unit_price: number (filterable)
    sale_price: number
    rating: number (filterable)
    review_count: number
    description: string (text indexed)
    tags: string[]
    stock_qty: number
    in_stock: boolean (filterable)
    discontinued: boolean (filterable)
    ... (26+ fields total)
}
```

#### Data Loaded
- **Products**: 50 items from `data/real_products.jsonl`
- **Vectors**: 1024-dim (bge-m3)
- **Hybrid search**: alpha=0.75 (75% semantic, 25% BM25 keyword)

#### Operations Used by Deep Agents
| Operation | Agent | Purpose |
|-----------|-------|---------|
| `coll.query.hybrid()` | VectorSearcherAgent | Main search with vectors |
| `Filter.by_property()` | VectorSearcherAgent | Build filters |
| `Filter...equal()` | VectorSearcherAgent | Category, in_stock filters |
| `Filter...less_or_equal()` | VectorSearcherAgent | Price filter |
| `Filter...greater_or_equal()` | VectorSearcherAgent | Rating filter |
| `&` operator | VectorSearcherAgent | AND filters |
| `\|` operator | VectorSearcherAgent | OR filters (e.g., multiple brands) |
| `return_metadata=MetadataQuery(score=True)` | VectorSearcherAgent | Get relevance scores |
| `coll.query.bm25()` | VectorSearcherAgent | Fallback keyword search |

#### Health Check
```bash
# Check if running
curl http://localhost:8080/v1/.well-known/ready

# Get collection stats
python -c "
import weaviate
client = weaviate.connect_to_local()
coll = client.collections.get('RealProductCatalog')
print(f'Products: {coll.aggregate.over_all().total_count}')
client.close()
"
```

---

### Tool 2: OLLAMA (Local Embedding Service)

**What it is**: Local LLM and embedding service (no API keys required)  
**Location**: localhost:11434  
**Installation**: Download from ollama.ai

#### Purpose in Deep Agents
- Convert queries to 1024-dimensional vectors (bge-m3)
- Fallback to 768-dim (nomic-embed-text) if primary fails
- Runs locally—no cloud dependencies, no rate limits

#### Models Used

##### Model 1: bge-m3 (Primary)
```
Dimensions: 1024
Performance: State-of-the-art semantic understanding
Speed: ~100ms per query
Use case: Product search queries
Command: ollama pull bge-m3
```

##### Model 2: nomic-embed-text (Fallback)
```
Dimensions: 768
Performance: Fast, good semantic understanding
Speed: ~50ms per query
Use case: Fallback if bge-m3 unavailable
Command: ollama pull nomic-embed-text
```

#### Python Integration
```python
import ollama

# Primary embedding
response = ollama.embed(
    model="bge-m3",
    input="gaming laptop with RTX 4080"
)
query_vector = response.embeddings[0]  # 1024-dim vector

# Fallback embedding
try:
    response = ollama.embed(model="bge-m3", input=query_text)
except:
    response = ollama.embed(model="nomic-embed-text", input=query_text)
```

#### Setup Commands
```bash
# Download Ollama
# Visit https://ollama.ai and download

# Pull models
ollama pull bge-m3
ollama pull nomic-embed-text

# Run Ollama server
ollama serve

# Test embedding
python -c "
import ollama
r = ollama.embed(model='bge-m3', input='test')
print(len(r.embeddings[0]))  # Should print 1024
"
```

#### Health Check
```bash
# Check if running
curl http://localhost:11434/api/tags

# Verify models installed
ollama list

# Test embedding
python test_search.py  # Uses Ollama
```

#### Operations Used by Deep Agents
```python
# In VectorSearcherAgent.search()
embed_response = ollama.embed(model="bge-m3", input=intent.query_text)
query_vector = embed_response.embeddings[0]  # Extract vector

# Store vector statistics
vector_dim = len(query_vector)  # 1024
trace.append(f"[SEARCH] Embedded query ({vector_dim}-dim)")
```

---

## 📚 PYTHON LIBRARIES & DEPENDENCIES

### Core Dependencies

#### 1. **weaviate-client**
```bash
pip install weaviate-client
```
**Purpose**: Communicate with Weaviate database  
**Usage in Deep Agents**:
- Connect to Weaviate
- Execute hybrid searches
- Build and apply filters
- Retrieve results with metadata

**Key Classes**:
```python
from weaviate.classes.query import Filter, MetadataQuery
```

#### 2. **ollama**
```bash
pip install ollama
```
**Purpose**: Communicate with Ollama embedding service  
**Usage in Deep Agents**:
- Embed queries to vectors
- Handle model fallbacks

**Key Functions**:
```python
import ollama
ollama.embed(model="bge-m3", input=text)
```

#### 3. **streamlit**
```bash
pip install streamlit
```
**Purpose**: Build web UI for Deep Agents  
**Usage**: `app_deep_agents_ui.py` runs on `streamlit run`  
**Version**: Latest stable  

#### 4. **pandas**
```bash
pip install pandas
```
**Purpose**: Data manipulation and CSV export  
**Usage in Deep Agents**:
- Format results for display
- Export to CSV
- Aggregate metrics

#### 5. **plotly**
```bash
pip install plotly
```
**Purpose**: Interactive visualizations  
**Usage**:
- Analytics dashboard (`analytics_dashboard.py`)
- Trend charts
- Metrics visualization

#### 6. **python-dotenv**
```bash
pip install python-dotenv
```
**Purpose**: Load environment variables  
**Usage**: Configuration management

### Standard Library Modules

#### 1. **json**
```python
import json
```
**Purpose**: Parse/serialize JSON  
**Usage**: Read JSONL files, format responses

#### 2. **re** (regex)
```python
import re
```
**Purpose**: Pattern matching  
**Usage**:
- Price parsing: `r"under\s*\$?(\d+)"`
- Brand extraction
- Spec keyword detection

#### 3. **dataclasses**
```python
from dataclasses import dataclass, asdict
```
**Purpose**: Structured data representation  
**Usage**:
- `SearchIntent` - Query intent
- `SearchResult` - Product result
- `SearchResponse` - Final response

#### 4. **datetime**
```python
from datetime import datetime
```
**Purpose**: Timestamps  
**Usage**:
- Log timestamps
- Metrics tracking
- Trace generation

#### 5. **pathlib**
```python
from pathlib import Path
```
**Purpose**: File path operations  
**Usage**: Read JSONL files, manage paths

#### 6. **typing**
```python
from typing import Optional, List, Dict, Any, Tuple
```
**Purpose**: Type hints  
**Usage**: Function signatures for code clarity

---

## 🐳 INFRASTRUCTURE TOOLS

### Docker & Docker Compose

**Purpose**: Containerize Weaviate vector database  
**File**: `docker-compose.yml`

```yaml
version: '3.4'
services:
  weaviate:
    image: semitechnologies/weaviate:latest
    restart: always
    ports:
      - "8080:8080"
      - "50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"
    volumes:
      - weaviate_data:/var/lib/weaviate
      
volumes:
  weaviate_data:
    driver: local
```

#### Commands
```bash
# Start containers
docker compose up -d

# Stop containers
docker compose down

# View logs
docker compose logs -f weaviate

# Check status
docker compose ps
```

#### Health Check
```bash
# Verify Weaviate is running
curl http://localhost:8080/v1/.well-known/ready

# Should return:
# {"status":"ok"}
```

---

## 🔄 EXTERNAL SERVICES & OPTIONAL TOOLS

### Service 1: LangChain (Optional Deep Agents Framework)
```python
# Not explicitly used in current implementation
# But architecture follows LangChain agent patterns
```

### Service 2: HuggingFace (Embedding Models Source)
```
bge-m3 downloaded via Ollama
# Originally from: https://huggingface.co/BAAI/bge-m3
```

---

## 📋 COMPLETE TOOL DEPENDENCY MAP

```
Deep Agents Search Pipeline
│
├─ VectorSearcherAgent
│   ├─ Weaviate Client (weaviate-client package)
│   │   └─ Weaviate Service (localhost:8080)
│   │       └─ RealProductCatalog (50 products)
│   │
│   └─ Ollama Embedding (ollama package)
│       └─ Ollama Service (localhost:11434)
│           ├─ bge-m3 (1024-dim) - Primary
│           └─ nomic-embed-text (768-dim) - Fallback
│
├─ IntentParserAgent
│   └─ Python re (regex) module
│
├─ ResultAnalyzerAgent
│   └─ Python statistics
│
├─ SearchCriticAgent
│   └─ Python built-ins
│
└─ SearchLeadAgent
    ├─ Python dataclasses
    ├─ Python json
    └─ Python datetime

Streamlit UI (app_deep_agents_ui.py)
├─ Streamlit framework
├─ Pandas (data export)
├─ Plotly (visualizations)
└─ Deep Agents Search

Tests
├─ pytest (unit testing)
├─ test_ui_search.py
├─ test_ingestion_suite.py
└─ test_search.py
```

---

## 🚀 INSTALLATION & SETUP

### Step 1: Python Virtual Environment
```bash
cd c:\Users\ls3412\deep_agents

# Create venv
python -m venv venv

# Activate
.\venv\Scripts\activate.ps1

# Verify
python --version  # Should be 3.11+
```

### Step 2: Install Python Packages
```bash
pip install -r requirements.txt

# OR manual install
pip install weaviate-client ollama streamlit pandas plotly python-dotenv
```

### Step 3: Start Weaviate
```bash
# Ensure Docker is running
docker compose up -d

# Verify
curl http://localhost:8080/v1/.well-known/ready
```

### Step 4: Start Ollama
```bash
# In new terminal
ollama serve

# Verify (in another terminal)
python -c "import ollama; print(ollama.embed(model='bge-m3', input='test'))"
```

### Step 5: Load Data (First Time Only)
```bash
# Ingest 50 products
python indexer/build_real_catalog.py --rebuild

# Verify
python check_products.py  # Should show 50 products
```

### Step 6: Run Streamlit UI
```bash
streamlit run app_deep_agents_ui.py --server.port 8504

# Access at: http://localhost:8504
```

---

## ✅ TOOL REQUIREMENTS CHECKLIST

### Required Tools (MUST HAVE)
```
[ ] Weaviate v4+          - docker compose up -d
[ ] Ollama               - ollama serve
[ ] Python 3.11+         - python --version
[ ] weaviate-client      - pip install weaviate-client
[ ] ollama               - pip install ollama
[ ] streamlit            - pip install streamlit
```

### Highly Recommended Tools
```
[ ] pandas               - pip install pandas (CSV export)
[ ] plotly              - pip install plotly (dashboards)
[ ] Docker              - Download from docker.com
```

### Optional Tools
```
[ ] pytest              - pip install pytest (testing)
[ ] black               - Code formatting
[ ] pylint              - Code linting
```

---

## 🔍 TOOL VERIFICATION COMMANDS

```bash
# Check Python version
python --version
# Expected: Python 3.11+

# Check Weaviate
curl http://localhost:8080/v1/.well-known/ready
# Expected: {"status":"ok"}

# Check Ollama
ollama list
# Expected: bge-m3, nomic-embed-text listed

# Check weaviate-client package
python -c "import weaviate; print('✅ weaviate-client OK')"

# Check ollama package
python -c "import ollama; print('✅ ollama OK')"

# Check streamlit
streamlit --version
# Expected: Streamlit, version X.X.X

# Check pandas
python -c "import pandas; print('✅ pandas OK')"

# Run integration test
python test_ui_search.py
# Expected: 5/5 tests PASSED
```

---

## 🎯 TOOL USAGE BY AGENT

| Tool | IntentParser | VectorSearcher | ResultAnalyzer | SearchCritic |
|------|---|---|---|---|
| Python `re` | ✅ | ⭕ | ⭕ | ⭕ |
| Python `dataclasses` | ✅ | ✅ | ✅ | ✅ |
| Python `json` | ⭕ | ⭕ | ⭕ | ⭕ |
| Weaviate Client | ⭕ | ✅ | ⭕ | ⭕ |
| Ollama | ⭕ | ✅ | ⭕ | ⭕ |
| Streamlit (UI) | ⭕ | ⭕ | ⭕ | ⭕ |

---

## 📊 TOOL PERFORMANCE METRICS

| Tool | Latency | Reliability | Ease of Setup |
|------|---------|-------------|---|
| Weaviate | 150-200ms/query | ✅ Very high | Medium |
| Ollama (bge-m3) | 100ms/query | ✅ Very high | Medium |
| Ollama (nomic) | 50ms/query | ✅ Very high | Medium |
| Python libraries | <5ms | ✅ Very high | Easy |
| Streamlit | 200-300ms/refresh | ✅ High | Easy |

---

## 🚨 TROUBLESHOOTING TOOLS

### If Weaviate not connecting
```bash
# Restart
docker compose down
docker compose up -d

# Check logs
docker compose logs weaviate

# Verify connectivity
curl http://localhost:8080/v1/.well-known/ready
```

### If Ollama not responding
```bash
# Restart
# Kill ollama process
ollama serve

# Check models
ollama list

# Re-pull if missing
ollama pull bge-m3
ollama pull nomic-embed-text
```

### If Python packages missing
```bash
# Activate venv
.\venv\Scripts\activate.ps1

# Reinstall all
pip install -r requirements.txt

# Or individual
pip install weaviate-client ollama streamlit
```

---

## 📦 REQUIREMENTS.TXT

```
weaviate-client==4.0.0
ollama==0.1.0
streamlit==1.28.0
pandas==2.0.0
plotly==5.17.0
python-dotenv==1.0.0
```

---

## ✨ SUMMARY

**3 Core Tools Required**:
1. ✅ Weaviate (Vector DB) - localhost:8080
2. ✅ Ollama (Embeddings) - localhost:11434
3. ✅ Python 3.11+ (Runtime)

**6 Essential Packages**:
1. weaviate-client
2. ollama
3. streamlit
4. pandas
5. plotly
6. python-dotenv

**Total Setup Time**: ~15-20 minutes (first time)

**Ongoing Operations**: All tools run locally—no cloud dependencies! 🎉

---

## 🔗 TOOL DOCUMENTATION LINKS

- **Weaviate**: https://weaviate.io/developers/weaviate
- **Ollama**: https://ollama.ai/
- **Streamlit**: https://docs.streamlit.io/
- **Docker**: https://docs.docker.com/
- **Python**: https://docs.python.org/3.11/

---

## 📞 TOOL SUPPORT CONTACTS

If tools fail:
1. **Weaviate**: Check docker logs, verify connectivity
2. **Ollama**: Verify models installed, restart service
3. **Python**: Verify venv activated, check pip packages
4. **Streamlit**: Clear cache, restart terminal
