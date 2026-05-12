# DEEP AGENTS SYSTEM - AGENT DEFINITIONS

## Overview

The Deep Agents product search system uses **5 specialized agents** in a hierarchical orchestration:
- **1 Lead Agent** (SearchLeadAgent) → Orchestrates overall pipeline
- **4 Sub-Agents** → Specialized task execution

---

## 🎯 LEAD AGENT: SearchLeadAgent

### Purpose
Central orchestrator that manages the entire search pipeline. Delegates tasks to sub-agents and synthesizes results.

### File
`app_deep_agents_search.py` (lines 575-645)

### Responsibilities
1. Accept natural language user query
2. Delegate to sub-agents sequentially
3. Collect trace information from all agents
4. Format and return final SearchResponse

### Execution Flow
```
User Query
    ↓
SearchLeadAgent.search()
    ├─ Step 1: IntentParserAgent.parse()
    ├─ Step 2: VectorSearcherAgent.search()
    ├─ Step 3: ResultAnalyzerAgent.analyze()
    ├─ Step 4: SearchCriticAgent.critique()
    └─ Step 5: Format SearchResponse
        ↓
    Final Results + Traces
```

### Key Methods
```python
def __init__(self):
    """Initialize all sub-agents"""
    self.intent_parser = IntentParserAgent()
    self.searcher = VectorSearcherAgent()
    self.analyzer = ResultAnalyzerAgent()
    self.critic = SearchCriticAgent()

def search(self, query: str) -> SearchResponse:
    """Main orchestration method. Returns complete SearchResponse."""
```

### Output
Returns `SearchResponse` containing:
- `query`: Original user query
- `results`: List of SearchResult objects
- `coverage_assessment`: Filter coverage metrics
- `data_quality_score`: Data completeness score (0-1)
- `ranking_explanation`: Why top result ranked highest
- `alternatives`: Suggestions for improving search
- `agent_trace`: Complete decision log from all 4 agents

### Example
```python
lead_agent = SearchLeadAgent()
response = lead_agent.search("gaming laptop with RTX 4080 under $2000")
print(response.agent_trace)  # Full decision log
print(response.results[0])   # Top result
```

---

## 🧠 SUB-AGENT 1: IntentParserAgent

### Purpose
Extract structured search intent from natural language queries.

### File
`app_deep_agents_search.py` (lines 125-230)

### Responsibilities
1. **Detect primary category** → Match against 13 known categories
2. **Extract brands** → Match against 25+ known brands
3. **Parse price ranges** → Extract min/max from query text
4. **Identify ratings** → Detect quality requirements
5. **Extract keywords** → Hardware specs, adjectives, modifiers
6. **Determine strategy** → Hybrid vs keyword-only search

### Input
- `query` (str): Natural language search query

### Output
- `SearchIntent` object with:
  - `query_text`: Original query
  - `primary_category`: Detected category (e.g., "Laptops")
  - `brands`: List of extracted brands
  - `price_range`: Dict with min/max
  - `min_rating`: Minimum rating requirement
  - `in_stock`: Boolean flag
  - `exclude_discontinued`: Boolean flag
  - `keywords`: List of spec keywords
  - `explanation`: Human-readable intent summary

### Supported Categories (13)
```
Laptops, Monitors, Keyboards, Mice, Headphones,
Webcams, Office Chairs, Storage, Printers, Networking,
Smartphones, Tablets, Speakers
```

### Supported Brands (25+)
```
Dell, HP, Lenovo, Apple, Sony, Samsung, Canon,
Nikon, Intel, AMD, NVIDIA, Corsair, Razer, Logitech,
Microsoft, Google, ASUS, Acer, MSI, Alienware,
Steelseries, HyperX, SanDisk, Western Digital, Seagate,
Crucial, Kingston
```

### Supported Spec Keywords
```
RTX, GPU, RAM, SSD, CPU, i9, i7, i5,
16GB, 32GB, 4K, HD, wireless, mechanical,
noise cancelling, RGB, gaming, professional,
budget, affordable, premium, portable
```

### Example
```python
parser = IntentParserAgent()
intent, traces = parser.parse("gaming laptop with RTX 4080 under $2000")

# Output:
# intent.primary_category = "Laptops"
# intent.brands = []
# intent.price_range = {"min": None, "max": 2000}
# intent.keywords = ["RTX", "gaming"]
# intent.explanation = "Searching for Laptops under $2000 with 2 specification keywords."
```

---

## 🔍 SUB-AGENT 2: VectorSearcherAgent

### Purpose
Execute hybrid search (semantic + keyword) against Weaviate vector database.

### File
`app_deep_agents_search.py` (lines 232-370)

### Responsibilities
1. **Connect to Weaviate** → Establish connection to vector DB
2. **Embed query** → Convert query to 1024-dim vector via Ollama
3. **Build filters** → Create Weaviate filters from SearchIntent
4. **Execute search** → Hybrid search with alpha=0.75 (75% semantic, 25% keyword)
5. **Extract results** → Format Weaviate objects to SearchResult dicts
6. **Calculate completeness** → Data quality per result

### Configuration
```python
EMBED_MODEL = "bge-m3"                    # Primary embedding model (1024-dim)
EMBED_FALLBACK = "nomic-embed-text"       # Fallback (768-dim)
WEAVIATE_HOST = "localhost"
WEAVIATE_PORT = 8080
WEAVIATE_GRPC = 50051
COLLECTION_NAME = "RealProductCatalog"
```

### Hybrid Search Parameters
```python
alpha = 0.75  # 75% dense (semantic), 25% keyword (BM25)
```

### Filter Building
Supports these filter types:
- **Category**: `Filter.by_property("category").equal(category)`
- **Brands**: Multiple brands combined with `|` (OR)
- **Price**: `Filter.by_property("unit_price").less_or_equal(max_price)`
- **Rating**: `Filter.by_property("rating").greater_or_equal(min_rating)`
- **Stock**: `Filter.by_property("in_stock").equal(True)`
- **Discontinued**: `Filter.by_property("discontinued").equal(False)`

### Input
- `intent` (SearchIntent): Structured search intent
- `limit` (int): Number of results to return (default 10)

### Output
- Tuple of:
  - `List[Dict]`: Product results with scores and metadata
  - `List[str]`: Execution traces

### Key Methods
```python
def search(self, intent: SearchIntent, limit: int = 10) -> tuple[List[Dict], List[str]]:
    """Execute hybrid search and return results."""
```

### Example Output
```python
[
    {
        "product_id": "P001",
        "name": "ProBook 450 G9",
        "category": "Laptops",
        "brand": "HP",
        "unit_price": 1899.99,
        "rating": 4.5,
        "relevance_score": 0.982,
        "data_completeness": 0.92,
        ...
    },
    ...
]
```

---

## 📊 SUB-AGENT 3: ResultAnalyzerAgent

### Purpose
Interpret search results and assess quality.

### File
`app_deep_agents_search.py` (lines 372-456)

### Responsibilities
1. **Coverage assessment** → Track which filters were applied
2. **Data quality scoring** → Calculate completeness percentage
3. **Ranking validation** → Check if scores are monotonically decreasing
4. **Suggest alternatives** → Offer hints to improve search

### Input
- `intent` (SearchIntent): Original search intent
- `results` (List[Dict]): Search results from VectorSearcherAgent

### Output
- Tuple of:
  - Analysis Dict with:
    - `coverage`: Filter coverage metrics
    - `data_quality_score`: Float (0-1)
    - `ranking_quality`: Status string
    - `alternatives`: Suggestions list
  - `List[str]`: Execution traces

### Coverage Metrics
```python
{
    "category_matched": bool,      # If category filter was applied
    "brands_applied": bool,         # If brand filters were used
    "price_respected": bool,        # If price filter exists
    "rating_applied": bool,         # If rating filter exists
    "stock_filtered": bool,         # If stock filter applied
}
```

### Data Quality Assessment
```
🟢 Excellent: > 80% field completeness
🟡 Good:      60-80% completeness
🔴 Fair:      < 60% completeness
```

### Key Methods
```python
def analyze(self, intent: SearchIntent, results: List[Dict]) -> tuple[Dict, List[str]]:
    """Analyze results and produce insights."""
```

### Example Output
```python
{
    "coverage": {
        "category_matched": True,
        "brands_applied": False,
        "price_respected": True,
        "rating_applied": False,
        "stock_filtered": True,
    },
    "data_quality_score": 0.91,           # 91% completeness
    "ranking_quality": "Good",             # Scores monotonic
    "alternatives": [],                    # No suggestions
}
```

---

## ✅ SUB-AGENT 4: SearchCriticAgent

### Purpose
Validate search results against original intent. Detect and flag issues.

### File
`app_deep_agents_search.py` (lines 458-540)

### Responsibilities
1. **Check filter application** → Verify filters were actually applied
2. **Validate ranking** → Ensure results make sense
3. **Identify mismatches** → Flag results that don't match intent
4. **Assess data quality** → Check for sparse records
5. **Approve/reject** → Overall validation status

### Input
- `intent` (SearchIntent): Original search intent
- `results` (List[Dict]): Search results
- `analysis` (Dict): Analysis from ResultAnalyzerAgent

### Output
- Tuple of:
  - `critique_status` (str): "✅ APPROVED" or "⚠️ N issues found"
  - `List[str]`: Execution traces

### Validation Checks

#### 1. Filter Application
```python
# Checks if category filter actually worked
if intent.primary_category:
    matching_cats = [r for r in results if r["category"] == intent.primary_category]
    if not matching_cats:
        issues.append("Category filter issue")
```

#### 2. Price Validation
```python
# Checks if all prices respect max filter
if intent.price_range.get("max"):
    overpriced = [r for r in results if r["unit_price"] > intent.price_range["max"]]
    if overpriced:
        issues.append(f"Price filter failed: {len(overpriced)} items over budget")
```

#### 3. Rating Validation
```python
# Checks if ratings meet minimum
if intent.min_rating:
    low_rated = [r for r in results if r["rating"] < intent.min_rating]
    if low_rated:
        issues.append(f"Rating filter failed")
```

#### 4. Relevance Check
```python
# Flag if top result has very low score
if results[0]["relevance_score"] < 0.5:
    issues.append(f"Low top result score: {score:.3f}")
```

#### 5. No Results
```python
# Flag if no results found
if not results:
    issues.append("No results found")
```

#### 6. Data Quality Flags
```python
# Check for sparse (< 50% complete) records
sparse_results = [r for r in results if r["data_completeness"] < 0.5]
if sparse_results:
    trace.append(f"{len(sparse_results)} sparse records detected")
```

### Key Methods
```python
def critique(self, intent: SearchIntent, results: List[Dict], analysis: Dict) -> tuple[str, List[str]]:
    """Validate results and return approval status."""
```

### Example Output
```
"✅ APPROVED"  # If all checks pass
"⚠️ 2 issues found: Price filter failed for 1 item; Category filter issue"
```

---

## 🔄 AGENT ORCHESTRATION SEQUENCE

### Timing
Each step typically takes:
- Intent parsing: ~10ms
- Vector search: ~200-300ms
- Analysis: ~5ms
- Criticism: ~5ms
- **Total: ~700ms per query**

### Data Flow
```
┌─────────────────────────────────────┐
│ User Query                          │
│ "gaming laptop under $2000"         │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ IntentParserAgent.parse()           │
│ Output: SearchIntent                │
│ {category: "Laptops",               │
│  price_range: {max: 2000},          │
│  keywords: ["gaming"]}              │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ VectorSearcherAgent.search()        │
│ Output: List[Dict] (raw results)    │
│ [{id: P001, score: 0.98, ...},      │
│  {id: P002, score: 0.92, ...}]      │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ ResultAnalyzerAgent.analyze()       │
│ Output: Analysis Dict               │
│ {coverage: {...},                   │
│  data_quality_score: 0.91,          │
│  alternatives: [...]}               │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ SearchCriticAgent.critique()        │
│ Output: critique_status, traces     │
│ "✅ APPROVED"                       │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ SearchLeadAgent (Synthesis)         │
│ Output: SearchResponse              │
│ {results: [...],                    │
│  agent_trace: [...],                │
│  data_quality_score: 0.91, ...}     │
└─────────────────────────────────────┘
```

---

## 📈 AGENT CAPABILITIES MATRIX

| Capability | IntentParser | VectorSearcher | ResultAnalyzer | SearchCritic |
|-----------|-------------|----------------|----------------|-------------|
| Query parsing | ✅ | ✅ | ⭕ | ⭕ |
| Category detection | ✅ | ⭕ | ⭕ | ⭕ |
| Brand extraction | ✅ | ⭕ | ⭕ | ⭕ |
| Price parsing | ✅ | ✅ | ⭕ | ✅ |
| Vector embedding | ⭕ | ✅ | ⭕ | ⭕ |
| Filter building | ⭕ | ✅ | ⭕ | ⭕ |
| Database search | ⭕ | ✅ | ⭕ | ⭕ |
| Data quality calc | ⭕ | ✅ | ✅ | ✅ |
| Coverage analysis | ⭕ | ⭕ | ✅ | ⭕ |
| Result validation | ⭕ | ⭕ | ⭕ | ✅ |
| Ranking assessment | ⭕ | ✅ | ✅ | ✅ |
| Suggestions | ⭕ | ⭕ | ✅ | ⭕ |

**Legend**: ✅ = Primary responsibility, ⭕ = Supporting role, (blank) = Not involved

---

## 🔧 INTEGRATION WITH STREAMLIT UI

The Lead Agent is called from `app_deep_agents_ui.py`:

```python
from app_deep_agents_search import SearchLeadAgent

# Initialize
search_agent = SearchLeadAgent()

# In Streamlit callback
response = search_agent.search(user_query)

# Display results
for result in response.results:
    st.metric(result.name, f"${result.unit_price:.2f}")

# Show traces
with st.expander("📊 Agent Decision Trace"):
    for trace_line in response.agent_trace:
        st.text(trace_line)
```

---

## 📋 AGENT RESPONSIBILITIES SUMMARY

| Agent | Responsibility | Success Criteria |
|-------|---|---|
| **IntentParserAgent** | Understand user intent | Extract all filter parameters accurately |
| **VectorSearcherAgent** | Execute search | Return 10+ relevant results with scores |
| **ResultAnalyzerAgent** | Assess quality | Provide actionable insights and suggestions |
| **SearchCriticAgent** | Validate results | Identify and flag any discrepancies |
| **SearchLeadAgent** | Orchestrate | Synthesize all steps into coherent response |

---

## 🚀 USAGE EXAMPLE

```python
from app_deep_agents_search import SearchLeadAgent, SearchResponse

# Create lead agent
lead = SearchLeadAgent()

# Search
response: SearchResponse = lead.search("gaming laptop RTX 4080 under $2000")

# Access results
for i, result in enumerate(response.results[:5], 1):
    print(f"{i}. {result.name} - ${result.unit_price} ({result.relevance_score:.2%})")

# View decision process
print("\n--- Agent Decision Trace ---")
for line in response.agent_trace:
    print(line)

# Get metrics
print(f"\nData Quality: {response.data_quality_score:.0%}")
print(f"Coverage: {sum(response.coverage_assessment.values())}/5 filters")
```

---

## ✨ KEY FEATURES

✅ **Hierarchical Orchestration** → Lead agent manages sub-agents  
✅ **Task Specialization** → Each agent has clear focus  
✅ **Fallback Strategies** → Graceful degradation (e.g., keyword-only if embedding fails)  
✅ **Full Traceability** → Every decision logged and returned  
✅ **Validation Layer** → Critic agent catches issues  
✅ **Quality Metrics** → Data completeness and coverage assessment  
✅ **Flexible Output** → Results accessible programmatically and via UI  

---

## 📞 CONTACT / DEBUG

**If agents aren't working**:
1. Check `app_deep_agents_search.py` for syntax errors
2. Verify Weaviate running: `docker compose ps`
3. Verify Ollama running: `ollama serve`
4. Run `python test_ui_search.py` to verify integration
5. Check agent traces in response for error messages
