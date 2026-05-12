"""
app_deep_agents_search.py
─────────────────────────
Deep Agents-based product search orchestration.

Architecture:
  Lead Agent (search_lead)
    ├─ Intent Parser Agent (intent_parser)
    │   └─ Understands query intent, extracts filters
    │
    ├─ Vector Searcher Agent (vector_searcher)
    │   └─ Executes hybrid search against Weaviate
    │
    ├─ Result Analyzer Agent (result_analyzer)
    │   └─ Interprets results, data quality assessment
    │
    └─ Search Critic Agent (search_critic)
        └─ Validates results against original intent

Deep Agents capabilities used:
  • Recursive agent delegation (lead → sub-agents)
  • Tool execution (Weaviate, Ollama, data analysis)
  • Multi-step planning and synthesis
  • Chain-of-thought reasoning
  • Result validation and iteration

Run:
    python app_deep_agents_search.py
    
Or use as a library:
    from app_deep_agents_search import AgentSearchPipeline
    pipeline = AgentSearchPipeline()
    result = pipeline.search("gaming laptop with RTX 4080 under $2000")
"""

import json
import re
from dataclasses import dataclass, asdict, replace as dc_replace
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

import weaviate
import weaviate.classes as wvc
import ollama
from weaviate.classes.query import Filter

# ═════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class SearchIntent:
    """Structured search intent extracted from natural language query."""
    query_text: str
    primary_category: Optional[str] = None
    brands: List[str] = None
    price_range: Dict[str, Optional[float]] = None
    min_rating: Optional[float] = None
    in_stock: bool = True
    exclude_discontinued: bool = True
    keywords: List[str] = None
    search_type: str = "hybrid"
    explanation: str = ""
    confidence_score: float = 0.0  # 0-100, how precisely the query was understood

    def __post_init__(self):
        if self.brands is None:
            self.brands = []
        if self.keywords is None:
            self.keywords = []
        if self.price_range is None:
            self.price_range = {"min": None, "max": None}


@dataclass
class SearchResult:
    """Single product search result."""
    product_id: str
    name: str
    category: str
    brand: str
    unit_price: float
    rating: float
    review_count: int
    stock_qty: int
    in_stock: bool
    discontinued: bool
    relevance_score: float
    description: str = ""
    search_metadata: str = ""  # pre-computed compact summary (fast agent reads)
    data_completeness: float = 0.0


@dataclass
class SearchResponse:
    """Final response from deep agents search pipeline."""
    query: str
    results: List[SearchResult]
    coverage_assessment: Dict[str, Any]
    data_quality_score: float
    ranking_explanation: str
    alternatives: List[str]
    agent_trace: List[str]  # Track agent decisions
    confidence_score: float = 0.0   # Intent parsing confidence (0-100)
    fallback_used: str = ""         # Non-empty if filters were relaxed to find results
    used_intent: Any = None         # The SearchIntent actually used (stored for session memory)


# ═════════════════════════════════════════════════════════════════════════════
# AGENT: INTENT PARSER
# ═════════════════════════════════════════════════════════════════════════════

class IntentParserAgent:
    """
    Extract structured search intent from natural language query.
    
    Responsibilities:
      • Detect primary category (Laptops, Monitors, etc.)
      • Extract brands from query
      • Parse price ranges
      • Identify rating requirements
      • Extract hardware specifications
      • Determine search strategy
    """

    CATEGORIES = [
        "Laptops", "Monitors", "Keyboards", "Mice", "Headphones",
        "Webcams", "Office Chairs", "Storage", "Printers", "Networking",
        "Smartphones", "Tablets", "Speakers"
    ]

    BRANDS = [
        "Dell", "HP", "Lenovo", "Apple", "Sony", "Samsung", "Canon",
        "Nikon", "Intel", "AMD", "NVIDIA", "Corsair", "Razer", "Logitech",
        "Microsoft", "Google", "ASUS", "Acer", "MSI", "Alienware",
        "Steelseries", "HyperX", "SanDisk", "Western Digital", "Seagate",
        "Crucial", "Kingston"
    ]

    def parse(self, query: str) -> SearchIntent:
        """Parse natural language query into structured intent."""
        trace = []
        query_lower = query.lower()

        # 1. Detect primary category
        primary_category = None
        for cat in self.CATEGORIES:
            if cat.lower() in query_lower:
                primary_category = cat
                trace.append(f"[INTENT] Detected category: {cat}")
                break

        # 2. Extract brands
        brands = []
        for brand in self.BRANDS:
            if brand.lower() in query_lower:
                brands.append(brand)
        if brands:
            trace.append(f"[INTENT] Found brands: {', '.join(brands)}")

        # 3. Parse price range
        price_range = {"min": None, "max": None}
        price_patterns = [
            (r"under\s*\$?(\d+(?:,\d{3}|\d{2})?)", "max"),
            (r"less than\s*\$?(\d+(?:,\d{3}|\d{2})?)", "max"),
            (r"\$?(\d+(?:,\d{3}|\d{2})?)\s*-\s*\$?(\d+(?:,\d{3}|\d{2})?)", "range"),
            (r"between\s*\$?(\d+)\s*and\s*\$?(\d+)", "range"),
        ]

        for pattern, ptype in price_patterns:
            match = re.search(pattern, query_lower)
            if match:
                if ptype == "max":
                    price_range["max"] = float(match.group(1).replace(",", ""))
                    trace.append(f"[INTENT] Max price: ${price_range['max']}")
                elif ptype == "range":
                    price_range["min"] = float(match.group(1).replace(",", ""))
                    price_range["max"] = float(match.group(2).replace(",", ""))
                    trace.append(f"[INTENT] Price range: ${price_range['min']}-${price_range['max']}")

        # 4. Rating filter
        min_rating = None
        if "5 star" in query_lower or "five star" in query_lower:
            min_rating = 5.0
            trace.append("[INTENT] Looking for 5-star products")
        elif "4 star" in query_lower or "highly rated" in query_lower or "best" in query_lower:
            min_rating = 4.0
            trace.append("[INTENT] Looking for highly-rated products (4+)")

        # 5. Stock status
        in_stock = "out of stock" not in query_lower
        exclude_discontinued = "discontinued" not in query_lower

        # 6. Extract keywords (specs, adjectives)
        spec_keywords = [
            "RTX", "GPU", "RAM", "SSD", "CPU", "i9", "i7", "i5",
            "16GB", "32GB", "4K", "HD", "wireless", "mechanical",
            "noise cancelling", "RGB", "gaming", "professional",
            "budget", "affordable", "premium", "portable"
        ]
        keywords = [kw for kw in spec_keywords if kw.lower() in query_lower]
        if keywords:
            trace.append(f"[INTENT] Keywords: {', '.join(keywords)}")

        explanation = (
            f"Searching for {primary_category or 'products'}"
            f"{f' from {', '.join(brands)}'if brands else ''}"
            f"{f' under ${price_range['max']}'if price_range['max'] else ''}"
            f"{f' with {min_rating}+ rating'if min_rating else ''}"
            f". Query contains {len(keywords)} specification keywords."
        )

        # Confidence score: how well-defined is this query (0-100)
        confidence = 0
        if primary_category: confidence += 30
        if brands: confidence += 20
        if price_range.get("max") or price_range.get("min"): confidence += 20
        if min_rating: confidence += 15
        confidence += min(15, len(keywords) * 5)
        level = "High" if confidence >= 60 else "Medium" if confidence >= 30 else "Low"
        trace.append(f"[INTENT] Confidence: {confidence}% ({level}) — {intent_summary(primary_category, brands, price_range, keywords)}")

        intent = SearchIntent(
            query_text=query,
            primary_category=primary_category,
            brands=brands,
            price_range=price_range,
            min_rating=min_rating,
            in_stock=in_stock,
            exclude_discontinued=exclude_discontinued,
            keywords=keywords,
            explanation=explanation,
            confidence_score=float(confidence),
        )

        return intent, trace


def intent_summary(category, brands, price_range, keywords) -> str:
    """One-line summary of what was extracted."""
    parts = []
    if category: parts.append(category)
    if brands: parts.append("+".join(brands))
    if price_range.get("max"): parts.append(f"<${price_range['max']:.0f}")
    if keywords: parts.append(",".join(keywords[:3]))
    return " | ".join(parts) if parts else "generic query"


# ═════════════════════════════════════════════════════════════════════════════
# AGENT: VECTOR SEARCHER
# ═════════════════════════════════════════════════════════════════════════════

class VectorSearcherAgent:
    """
    Execute hybrid search against Weaviate RealProductCatalog.
    
    Responsibilities:
      • Connect to Weaviate
      • Embed query using Ollama
      • Build Weaviate filters
      • Execute hybrid search (dense + keyword)
      • Extract and rank results
    """

    EMBED_MODEL = "bge-m3"
    EMBED_FALLBACK = "nomic-embed-text"
    WEAVIATE_HOST = "localhost"
    WEAVIATE_PORT = 8080
    WEAVIATE_GRPC = 50051
    COLLECTION_NAME = "RealProductCatalog"

    def search(self, intent: SearchIntent, limit: int = 10) -> tuple[List[Dict], List[str]]:
        """Execute hybrid search."""
        trace = []

        try:
            # 1. Connect to Weaviate
            client = weaviate.connect_to_local(
                host=self.WEAVIATE_HOST,
                port=self.WEAVIATE_PORT,
                grpc_port=self.WEAVIATE_GRPC
            )
            trace.append("[SEARCH] Connected to Weaviate")

            coll = client.collections.get(self.COLLECTION_NAME)
            trace.append(f"[SEARCH] Collection: {self.COLLECTION_NAME}")

            # 2. Embed query with Ollama
            try:
                embed_response = ollama.embed(model=self.EMBED_MODEL, input=intent.query_text)
                query_vector = embed_response.embeddings[0]
                trace.append(f"[SEARCH] Embedded query ({len(query_vector)}-dim)")
            except Exception as e:
                trace.append(f"[SEARCH] Embedding failed, falling back to keyword search")
                query_vector = None

            # 3. Build filters
            filters = []

            if intent.primary_category:
                cat_filter = Filter.by_property("category").equal(intent.primary_category)
                filters.append(cat_filter)
                trace.append(f"[SEARCH] Filter: category = {intent.primary_category}")

            if intent.brands:
                brand_filters = [Filter.by_property("brand").equal(b) for b in intent.brands]
                if brand_filters:
                    if len(brand_filters) == 1:
                        filters.append(brand_filters[0])
                    else:
                        brand_combined = brand_filters[0]
                        for bf in brand_filters[1:]:
                            brand_combined = brand_combined | bf
                        filters.append(brand_combined)
                    trace.append(f"[SEARCH] Filter: brand in {intent.brands}")

            if intent.price_range.get("max"):
                price_filter = Filter.by_property("unit_price").less_or_equal(
                    intent.price_range["max"]
                )
                filters.append(price_filter)
                trace.append(f"[SEARCH] Filter: price <= ${intent.price_range['max']}")

            if intent.min_rating:
                rating_filter = Filter.by_property("rating").greater_or_equal(intent.min_rating)
                filters.append(rating_filter)
                trace.append(f"[SEARCH] Filter: rating >= {intent.min_rating}")

            if intent.in_stock:
                stock_filter = Filter.by_property("in_stock").equal(True)
                filters.append(stock_filter)
                trace.append("[SEARCH] Filter: in_stock = true")

            if intent.exclude_discontinued:
                disc_filter = Filter.by_property("discontinued").equal(False)
                filters.append(disc_filter)
                trace.append("[SEARCH] Filter: discontinued = false")

            # 4. Build combined filter
            combined_filter = None
            if filters:
                combined_filter = filters[0]
                for f in filters[1:]:
                    combined_filter = combined_filter & f

            # 5. Execute hybrid search
            if query_vector:
                results = coll.query.hybrid(
                    query=intent.query_text,
                    vector=query_vector,
                    alpha=0.75,  # 75% dense, 25% keyword
                    filters=combined_filter,
                    limit=limit,
                    return_metadata=wvc.query.MetadataQuery(score=True),
                )
            else:
                # Fallback to keyword-only search
                results = coll.query.bm25(
                    query=intent.query_text,
                    filters=combined_filter,
                    limit=limit,
                    return_metadata=wvc.query.MetadataQuery(score=True),
                )

            trace.append(f"[SEARCH] Found {len(results.objects)} results")

            # 6. Extract and rank results
            product_results = []
            for obj in results.objects:
                props = obj.properties
                score = obj.metadata.score if obj.metadata and obj.metadata.score else 0.0

                # Calculate data completeness
                non_null_fields = sum(1 for v in props.values() if v is not None and v != "")
                total_fields = len(props)
                completeness = (non_null_fields / total_fields) if total_fields > 0 else 0.0

                result = {
                    "product_id": props.get("product_id", ""),
                    "name": props.get("name", ""),
                    "category": props.get("category", ""),
                    "brand": props.get("brand", ""),
                    "unit_price": props.get("unit_price", 0.0),
                    "rating": props.get("rating", 0.0),
                    "review_count": props.get("review_count", 0),
                    "stock_qty": props.get("stock_qty", 0),
                    "in_stock": props.get("in_stock", True),
                    "discontinued": props.get("discontinued", False),
                    "relevance_score": float(score),
                    "description": props.get("description", "")[:200],
                    "search_metadata": props.get("search_metadata", ""),  # pre-computed compact summary
                    "data_completeness": completeness,
                }
                product_results.append(result)

            client.close()
            return product_results, trace

        except Exception as e:
            trace.append(f"[SEARCH] Error: {str(e)}")
            return [], trace


# ═════════════════════════════════════════════════════════════════════════════
# AGENT: RESULT ANALYZER
# ═════════════════════════════════════════════════════════════════════════════

class ResultAnalyzerAgent:
    """
    Analyze search results and produce business-ready insights.
    
    Responsibilities:
      • Assess filter coverage
      • Calculate data quality score
      • Rank products by relevance
      • Suggest alternatives
    """

    def analyze(self, intent: SearchIntent, results: List[Dict]) -> tuple[Dict, List[str]]:
        """Analyze search results."""
        trace = []

        # 1. Coverage assessment
        coverage = {
            "category_matched": False,
            "brands_applied": len(intent.brands) > 0,
            "price_respected": intent.price_range.get("max") is not None,
            "rating_applied": intent.min_rating is not None,
            "stock_filtered": intent.in_stock,
        }

        if results:
            # Check if category matches
            if intent.primary_category:
                matching_cats = [
                    r for r in results if r["category"] == intent.primary_category
                ]
                coverage["category_matched"] = len(matching_cats) > 0

        trace.append(f"[ANALYZE] Coverage: {sum(coverage.values())}/{len(coverage)} criteria")

        # 2. Data quality assessment
        if results:
            avg_completeness = sum(r["data_completeness"] for r in results) / len(results)
            results_with_descriptions = sum(
                1 for r in results if r.get("description") and len(r["description"]) > 10
            )
            desc_rate = results_with_descriptions / len(results)

            if avg_completeness > 0.8:
                quality = "🟢 Excellent"
            elif avg_completeness > 0.6:
                quality = "🟡 Good"
            else:
                quality = "🔴 Fair"

            data_quality_score = avg_completeness
            trace.append(f"[ANALYZE] Data quality: {quality} ({avg_completeness:.1%} complete)")
            trace.append(f"[ANALYZE] Descriptions present: {desc_rate:.0%} of results")
        else:
            data_quality_score = 0.0
            trace.append("[ANALYZE] No results to analyze")

        # 3. Ranking quality check
        ranking_ok = True
        if len(results) > 1:
            scores = [r["relevance_score"] for r in results]
            is_monotonic = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
            ranking_ok = is_monotonic
            if ranking_ok:
                trace.append(
                    f"[ANALYZE] Ranking quality: ✅ (scores {scores[0]:.3f} → {scores[-1]:.3f})"
                )
            else:
                trace.append("[ANALYZE] Ranking quality: ⚠️ (scores not monotonic)")

        # 4. Alternative suggestions
        alternatives = []
        if len(results) < 3:
            alternatives.append("Few results found. Consider relaxing price or rating filters.")
            trace.append("[ANALYZE] Suggestion: Try relaxing filters")

        if not coverage["brands_applied"] and results:
            trace.append("[ANALYZE] No brand filter applied—showing all brands")

        return {
            "coverage": coverage,
            "data_quality_score": data_quality_score,
            "ranking_quality": "Good" if ranking_ok else "Check sorting",
            "alternatives": alternatives,
        }, trace


# ═════════════════════════════════════════════════════════════════════════════
# AGENT: SEARCH CRITIC
# ═════════════════════════════════════════════════════════════════════════════

class SearchCriticAgent:
    """
    Validate search results against original query intent.
    
    Responsibilities:
      • Check filter application correctness
      • Verify ranking relevance
      • Identify obvious mismatches
      • Flag data quality issues
    """

    def critique(
        self, intent: SearchIntent, results: List[Dict], analysis: Dict
    ) -> tuple[str, List[str]]:
        """Critique search results."""
        trace = []
        issues = []

        # 1. Check filter application
        if intent.primary_category and results:
            mismatched_cats = [
                r for r in results if r["category"] != intent.primary_category
            ]
            if mismatched_cats:
                issues.append(
                    f"Category filter issue: {len(mismatched_cats)} results "
                    f"outside '{intent.primary_category}'"
                )

        if intent.price_range.get("max") and results:
            overpriced = [r for r in results if r["unit_price"] > intent.price_range["max"]]
            if overpriced:
                issues.append(
                    f"Price filter failed: {len(overpriced)} items exceed ${intent.price_range['max']}"
                )

        if intent.min_rating and results:
            low_rated = [r for r in results if r["rating"] < intent.min_rating]
            if low_rated:
                issues.append(
                    f"Rating filter failed: {len(low_rated)} items below {intent.min_rating} stars"
                )

        # 2. Check relevance of top result
        if results and results[0]["relevance_score"] < 0.5:
            issues.append(f"Low top result score: {results[0]['relevance_score']:.3f}")

        # 3. No results
        if not results:
            issues.append("No results found—consider broadening search criteria")

        # 4. Data quality flags
        if results:
            sparse_results = [r for r in results if r["data_completeness"] < 0.5]
            if sparse_results:
                trace.append(
                    f"[CRITIC] ⚠️ {len(sparse_results)} sparse records "
                    f"(< 50% complete)"
                )

        if issues:
            status = f"⚠️ {len(issues)} issues found"
            trace.append(f"[CRITIC] {status}: {'; '.join(issues)}")
        else:
            status = "✅ APPROVED"
            trace.append("[CRITIC] Results validated")

        return status, trace


# ═════════════════════════════════════════════════════════════════════════════
# FALLBACK SEARCH AGENT
# ═════════════════════════════════════════════════════════════════════════════

class FallbackSearchAgent:
    """
    Progressively relax filters when zero results are found.

    Stages (each drops more constraints than the previous):
      1. drop_brand    → Remove brand filter only
      2. drop_rating   → Also remove rating filter
      3. drop_price    → Also remove price filter
      4. category_only → Keep only category; drop stock/discontinued limits
      5. no_filters    → Pure semantic search (no filters at all)

    This ensures users always get *something* useful rather than a blank page.
    The fallback stage used is recorded in SearchResponse.fallback_used so the
    UI can show a transparent notice like "Relaxed price filter to show results".
    """

    def relax_and_search(
        self, intent: "SearchIntent", searcher: "VectorSearcherAgent"
    ) -> tuple[List[Dict], str, List[str]]:
        """Try progressively relaxed searches until results are found."""
        trace = []
        stages = [
            ("drop_brand",    dc_replace(intent, brands=[])),
            ("drop_rating",   dc_replace(intent, brands=[], min_rating=None)),
            ("drop_price",    dc_replace(intent, brands=[], min_rating=None,
                                         price_range={"min": None, "max": None})),
            ("category_only", dc_replace(intent, brands=[], min_rating=None,
                                         price_range={"min": None, "max": None},
                                         in_stock=False, exclude_discontinued=False)),
            ("no_filters",    dc_replace(intent, brands=[], min_rating=None,
                                         price_range={"min": None, "max": None},
                                         in_stock=False, exclude_discontinued=False,
                                         primary_category=None)),
        ]
        for stage_name, relaxed_intent in stages:
            trace.append(f"[FALLBACK] Trying stage: {stage_name}")
            results, search_traces = searcher.search(relaxed_intent)
            trace.extend(search_traces)
            if results:
                trace.append(
                    f"[FALLBACK] ✅ {len(results)} results found at stage: {stage_name}"
                )
                return results, stage_name, trace
        trace.append("[FALLBACK] ❌ No results after all fallback stages")
        return [], "exhausted", trace


# ═════════════════════════════════════════════════════════════════════════════
# SESSION MEMORY AGENT
# ═════════════════════════════════════════════════════════════════════════════

class SessionMemoryAgent:
    """
    Detects refinement queries and merges them with the prior search intent.

    Examples
    --------
    prev: "gaming laptop"   + new: "now under $1500"      → gaming laptop ≤ $1500
    prev: "headphones"      + new: "just Sony"            → Sony headphones
    prev: "laptops $2000"   + new: "add noise cancelling" → merged keywords

    Refinement is detected when the query is ≤ 5 words AND starts with a
    refinement signal word, or looks like a standalone price.
    """

    REFINEMENT_SIGNALS = {
        "now", "just", "only", "but", "also", "add", "more", "with",
        "under", "above", "below", "less", "cheaper", "from", "by",
        "make", "actually", "change", "switch", "instead",
    }

    def is_refinement(self, query: str, last_intent: Any) -> bool:
        if last_intent is None:
            return False
        words = query.lower().strip().split()
        if not words:
            return False
        if len(words) <= 5 and words[0] in self.REFINEMENT_SIGNALS:
            return True
        # Bare price like "$1500" used as a standalone query
        if re.match(r"^\$?[\d,]+$", query.strip()):
            return True
        return False

    def merge(self, new_intent: Any, last_intent: Any, trace: list) -> Any:
        """Override only explicitly set fields; carry everything else from last_intent."""
        merged = dc_replace(last_intent, query_text=new_intent.query_text)
        if new_intent.primary_category:
            merged = dc_replace(merged, primary_category=new_intent.primary_category)
        if new_intent.brands:
            merged = dc_replace(merged, brands=new_intent.brands)
        if new_intent.price_range.get("max") or new_intent.price_range.get("min"):
            merged = dc_replace(merged, price_range=new_intent.price_range)
        if new_intent.min_rating:
            merged = dc_replace(merged, min_rating=new_intent.min_rating)
        if new_intent.keywords:
            combined = list(set((last_intent.keywords or []) + new_intent.keywords))
            merged = dc_replace(merged, keywords=combined)
        merged = dc_replace(
            merged,
            confidence_score=new_intent.confidence_score,
            explanation=f"Refined from: '{last_intent.query_text}'",
        )
        trace.append(
            f"[MEMORY] Merged → cat={merged.primary_category} | "
            f"brands={merged.brands} | price_max={merged.price_range.get('max')} | "
            f"kw={merged.keywords[:3]}"
        )
        return merged


def _self_heal_results(
    intent: Any, results: List[Dict], critique_status: str, trace: list
) -> tuple[List[Dict], str]:
    """
    Post-filter results that violate hard constraints flagged by the critic.
    Safety guard: only strip if ≥ 3 results remain after removal.
    Returns (healed_results, summary_note).
    """
    healed = list(results)
    notes: List[str] = []

    if "Price filter failed" in critique_status and intent.price_range.get("max"):
        max_p = intent.price_range["max"]
        filtered = [r for r in healed if r["unit_price"] <= max_p]
        if len(filtered) >= 3:
            removed = len(healed) - len(filtered)
            healed = filtered
            trace.append(f"[HEAL] ✂️ Removed {removed} overpriced result(s) (>${max_p:.0f})")
            notes.append(f"removed {removed} item(s) over ${max_p:.0f}")
        else:
            trace.append("[HEAL] ⚠️ Skipped price healing — would leave < 3 results")

    if "Rating filter failed" in critique_status and intent.min_rating:
        filtered = [r for r in healed if r["rating"] >= intent.min_rating]
        if len(filtered) >= 3:
            removed = len(healed) - len(filtered)
            healed = filtered
            trace.append(f"[HEAL] ✂️ Removed {removed} low-rated result(s) (< {intent.min_rating}★)")
            notes.append(f"removed {removed} low-rated item(s)")
        else:
            trace.append("[HEAL] ⚠️ Skipped rating healing — would leave < 3 results")

    if not notes:
        trace.append("[HEAL] ✅ No constraint violations — results are clean")
    return healed, "; ".join(notes)


# ═════════════════════════════════════════════════════════════════════════════
# LEAD AGENT: ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════════════

class SearchLeadAgent:
    """
    Lead orchestration agent for product search.
    
    Responsibilities:
      • Parse user query
      • Plan search strategy
      • Delegate to sub-agents
      • Synthesize results
      • Return final response
    """

    def __init__(self):
        self.intent_parser = IntentParserAgent()
        self.searcher = VectorSearcherAgent()
        self.analyzer = ResultAnalyzerAgent()
        self.critic = SearchCriticAgent()
        self.fallback = FallbackSearchAgent()
        self.session_memory = SessionMemoryAgent()

    def search(self, query: str, last_intent: Optional[Any] = None) -> SearchResponse:
        """Orchestrate full search pipeline."""
        all_traces = []

        # STEP 0 / STEP 1: Intent Parsing (with session memory check)
        if self.session_memory.is_refinement(query, last_intent):
            all_traces.append("\n=== STEP 0: SESSION MEMORY — REFINEMENT ===")
            all_traces.append(f"[MEMORY] Refinement query detected: '{query}'")
            raw_intent, intent_traces = self.intent_parser.parse(query)
            all_traces.extend(intent_traces)
            intent = self.session_memory.merge(raw_intent, last_intent, all_traces)
        else:
            all_traces.append("\n=== STEP 1: INTENT PARSING ===")
            intent, intent_traces = self.intent_parser.parse(query)
            all_traces.extend(intent_traces)

        # STEP 2: Vector Search
        all_traces.append("\n=== STEP 2: VECTOR SEARCH ===")
        raw_results, search_traces = self.searcher.search(intent)
        all_traces.extend(search_traces)
        fallback_used = ""

        # STEP 2b: Fallback — relax filters progressively if nothing found
        if not raw_results:
            all_traces.append("\n=== STEP 2b: FALLBACK SEARCH ===")
            all_traces.append("[FALLBACK] 0 results with full filters — relaxing progressively")
            raw_results, fallback_used, fb_traces = self.fallback.relax_and_search(
                intent, self.searcher
            )
            all_traces.extend(fb_traces)

        # STEP 3: Result Analysis
        all_traces.append("\n=== STEP 3: ANALYSIS ===")
        analysis, analysis_traces = self.analyzer.analyze(intent, raw_results)
        all_traces.extend(analysis_traces)

        # STEP 4: Result Critique
        all_traces.append("\n=== STEP 4: VALIDATION ===")
        critique_status, critique_traces = self.critic.critique(intent, raw_results, analysis)
        all_traces.extend(critique_traces)

        # STEP 4b: Self-Heal — post-filter results violating hard constraints
        all_traces.append("\n=== STEP 4b: SELF-HEAL ===")
        raw_results, heal_note = _self_heal_results(intent, raw_results, critique_status, all_traces)

        # STEP 5: Format response
        results = [SearchResult(**r) for r in raw_results]

        ranking_explanation = (
            f"Top product '{results[0].name}' (score: {results[0].relevance_score:.3f}) "
            f"matches query intent for {intent.primary_category or 'products'}"
            if results
            else "No products matched the search criteria."
        )

        response = SearchResponse(
            query=query,
            results=results,
            coverage_assessment=analysis.get("coverage", {}),
            data_quality_score=analysis.get("data_quality_score", 0.0),
            ranking_explanation=ranking_explanation,
            alternatives=analysis.get("alternatives", []),
            agent_trace=all_traces,
            confidence_score=intent.confidence_score,
            fallback_used=fallback_used,
            used_intent=intent,
        )

        return response


# ═════════════════════════════════════════════════════════════════════════════
# MAIN INTERFACE
# ═════════════════════════════════════════════════════════════════════════════

def main():
    """Demo: Interactive deep agents search."""
    import sys

    print("\n" + "=" * 80)
    print("DEEP AGENTS PRODUCT SEARCH ORCHESTRATOR")
    print("=" * 80)
    print("\nUsing deep agents pipeline:")
    print("  1. Intent Parser Agent -> Extracts search intent")
    print("  2. Vector Searcher Agent -> Executes hybrid search")
    print("  3. Result Analyzer Agent -> Interprets results")
    print("  4. Search Critic Agent -> Validates findings")
    print("=" * 80)

    lead_agent = SearchLeadAgent()

    # Example queries
    example_queries = [
        "gaming laptop with RTX 4080 under $2000",
        "budget office chair under 500",
        "4K monitor for video editing",
    ]

    for query in example_queries:
        print(f"\n{'=' * 80}")
        print(f"QUERY: {query}")
        print("=" * 80)

        response = lead_agent.search(query)

        # Print agent trace
        for trace in response.agent_trace:
            print(trace)

        # Print results
        print("\n" + "─" * 80)
        print("TOP RESULTS:")
        print("─" * 80)

        for i, result in enumerate(response.results[:3], 1):
            print(
                f"\n{i}. [{result.relevance_score:.3f}] {result.name}"
            )
            print(f"   Product: {result.product_id} | {result.category} | {result.brand}")
            print(
                f"   Price: ${result.unit_price:.2f} | Rating: {result.rating}⭐ | Stock: {result.stock_qty}"
            )
            if result.description:
                print(f"   {result.description[:100]}...")

        print("\n" + "─" * 80)
        print("ANALYSIS:")
        print("─" * 80)
        print(f"Data Quality Score: {response.data_quality_score:.1%}")
        print(f"Ranking Explanation: {response.ranking_explanation}")
        if response.alternatives:
            print(f"Suggestions: {'; '.join(response.alternatives)}")


if __name__ == "__main__":
    main()
