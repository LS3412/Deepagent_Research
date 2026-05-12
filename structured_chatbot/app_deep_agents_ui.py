"""
DEEP AGENTS PRODUCT SEARCH - STREAMLIT UI
==========================================
Interactive chatbot interface for the multi-agent product search system.

Port: 8504 (streamlit run app_deep_agents_ui.py --server.port 8504)

Features:
- Natural language query input
- Real-time agent orchestration
- Results display with quality badges
- Full agent reasoning trace
- Coverage assessment visualization
- Alternative suggestions
"""

import re
import streamlit as st
import pandas as pd
from datetime import datetime
from app_deep_agents_search import SearchLeadAgent, SearchIntent, SearchResponse
import json

# Page configuration
st.set_page_config(
    page_title="Deep Agents Product Search",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom styling
st.markdown("""
<style>
    .metric-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        margin: 2px 4px 2px 0;
    }
    .quality-good { background: #d4edda; color: #155724; }
    .quality-fair { background: #fff3cd; color: #856404; }
    .quality-poor { background: #f8d7da; color: #721c24; }
    .result-card {
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        background: white;
    }
    .trace-box {
        background: #f8f9fa;
        border-left: 4px solid #007bff;
        padding: 12px;
        margin: 8px 0;
        font-family: monospace;
        font-size: 11px;
        max-height: 400px;
        overflow-y: auto;
    }
    .badge-category { background: #e7f3ff; color: #004085; padding: 4px 8px; border-radius: 4px; font-size: 11px; }
    .badge-price { background: #fff3e0; color: #e65100; padding: 4px 8px; border-radius: 4px; font-size: 11px; }
    .badge-rating { background: #fce4ec; color: #880e4f; padding: 4px 8px; border-radius: 4px; font-size: 11px; }
</style>
""", unsafe_allow_html=True)


def get_quality_class(score):
    """Determine CSS class based on quality score."""
    if score >= 0.80:
        return "quality-good", "🟢 Excellent"
    elif score >= 0.60:
        return "quality-fair", "🟡 Good"
    else:
        return "quality-poor", "🔴 Fair"


def format_price(price):
    """Format price with currency."""
    if price is None or price == 0:
        return "N/A"
    return f"${price:,.2f}"


def render_product_card(product, index):
    """Render individual product result card."""
    # Stock status
    if product.discontinued:
        stock_badge = "🚫 Discontinued"
        stock_color = "red"
    elif product.stock_qty == 0 or not product.in_stock:
        stock_badge = "⚠️ Out of Stock"
        stock_color = "orange"
    elif product.stock_qty < 5:
        stock_badge = f"⚠️ Low Stock ({product.stock_qty})"
        stock_color = "orange"
    else:
        stock_badge = f"✅ In Stock ({product.stock_qty})"
        stock_color = "green"

    # Quality badge
    quality_class, quality_label = get_quality_class(product.data_completeness)

    col1, col2, col3 = st.columns([3, 1, 1])
    
    with col1:
        st.markdown(f"### #{index}. {product.name}")
        st.markdown(f"**{product.brand}** · {product.category}")
        st.markdown(product.description[:150] + "..." if len(product.description or "") > 150 else product.description or "No description")
        # ⚡ Pre-computed metadata: agents read this instead of the full description (fast)
        if getattr(product, 'search_metadata', ''):
            meta_parts = {
                p.split(':', 1)[0].strip(): p.split(':', 1)[1].strip()
                for p in product.search_metadata.split(' | ') if ':' in p
            }
            if 'Specs' in meta_parts:
                st.caption(f"⚡ {meta_parts['Specs']}")
            elif 'Tags' in meta_parts:
                st.caption(f"🏷️ {meta_parts['Tags']}")
    
    with col2:
        st.metric("Price", format_price(product.unit_price))
        st.metric("Rating", f"{product.rating}⭐" if product.rating else "N/A")
    
    with col3:
        st.metric("Match Score", f"{product.relevance_score:.1%}")
        st.markdown(f"<div class='{quality_class} metric-badge'>{quality_label}</div>", unsafe_allow_html=True)

    col_info1, col_info2, col_info3, col_fb1, col_fb2 = st.columns([2, 2, 2, 1, 1])
    with col_info1:
        st.markdown(f"<span class='badge-category'>🏷️ {product.category}</span>", unsafe_allow_html=True)
    with col_info2:
        st.markdown(f"<span class='badge-price'>{format_price(product.unit_price)}</span>", unsafe_allow_html=True)
    with col_info3:
        if product.rating:
            st.markdown(f"<span class='badge-rating'>⭐ {product.rating:.1f} ({product.review_count} reviews)</span>", unsafe_allow_html=True)

    # Feedback buttons (👍/👎)
    current_fb = st.session_state.get("feedback", {}).get(product.product_id, "")
    with col_fb1:
        up_icon = "👍✓" if current_fb == "up" else "👍"
        if st.button(up_icon, key=f"up_{product.product_id}_{index}", help="Relevant result"):
            if "feedback" not in st.session_state:
                st.session_state.feedback = {}
            st.session_state.feedback[product.product_id] = "up"
            _save_feedback(product.product_id, product.name, "up", st.session_state.get("last_query", ""))
            st.rerun()
    with col_fb2:
        dn_icon = "👎✓" if current_fb == "down" else "👎"
        if st.button(dn_icon, key=f"dn_{product.product_id}_{index}", help="Not relevant"):
            if "feedback" not in st.session_state:
                st.session_state.feedback = {}
            st.session_state.feedback[product.product_id] = "down"
            _save_feedback(product.product_id, product.name, "down", st.session_state.get("last_query", ""))
            st.rerun()

    st.markdown(f"<span style='color:{stock_color}; font-weight: 600;'>{stock_badge}</span>", unsafe_allow_html=True)
    st.divider()


def render_agent_trace(trace):
    """Render agent decision trace."""
    trace_text = "\n".join(trace)
    st.markdown(f"<div class='trace-box'>{trace_text}</div>", unsafe_allow_html=True)


def _save_feedback(product_id: str, name: str, vote: str, query: str) -> None:
    """Persist a feedback vote to metrics/feedback.jsonl."""
    from pathlib import Path
    path = Path("metrics/feedback.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "product_id": product_id,
        "product_name": name,
        "vote": vote,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def render_coverage_assessment(coverage):
    """Render filter coverage visualization."""
    col1, col2, col3, col4, col5 = st.columns(5)
    
    checks = [
        ("Category", coverage.get("category_matched", False)),
        ("Brands", coverage.get("brands_applied", False)),
        ("Price", coverage.get("price_respected", False)),
        ("Rating", coverage.get("rating_applied", False)),
        ("Stock", coverage.get("stock_filtered", False)),
    ]
    
    columns = [col1, col2, col3, col4, col5]
    for (label, applied), col in zip(checks, columns):
        with col:
            if applied:
                st.markdown(f"✅ {label}")
            else:
                st.markdown(f"⭕ {label}")


# Sidebar - Configuration and Examples
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    
    st.markdown("### Example Queries")
    example_queries = {
        "Gaming Laptop": "gaming laptop with RTX 4080 under $2000",
        "Budget Office": "budget office chair under $500",
        "4K Monitor": "4K monitor for video editing with high reviews",
        "Wireless Audio": "wireless headphones with noise cancelling",
        "High Performance": "premium tablet high performance",
        "Dell Laptop": "Dell laptop professional business",
        "Storage Device": "external SSD 2TB fast storage",
        "Mechanical Keyboard": "mechanical keyboard RGB under $200",
    }
    
    selected_example = st.selectbox(
        "Quick examples:",
        ["-- Select example --"] + list(example_queries.keys())
    )
    
    st.markdown("### Search Filters (Optional)")
    st.info("💡 Filters can be mentioned naturally in your query, or set here for refinement")
    
    with st.expander("Price Range"):
        col_min, col_max = st.columns(2)
        with col_min:
            min_price = st.number_input("Min ($)", value=0, min_value=0)
        with col_max:
            max_price = st.number_input("Max ($)", value=5000, min_value=0)
    
    with st.expander("Categories"):
        categories = {
            "Laptops": "Laptops",
            "Monitors": "Monitors",
            "Keyboards": "Keyboards",
            "Mice": "Mice",
            "Headphones": "Headphones",
            "Webcams": "Webcams",
            "Office Chairs": "Office Chairs",
            "Storage": "Storage",
            "Printers": "Printers",
            "Networking": "Networking",
            "Smartphones": "Smartphones",
            "Tablets": "Tablets",
            "Speakers": "Speakers",
        }
        selected_category = st.selectbox("Category:", ["Any"] + list(categories.keys()))
    
    with st.expander("Other Filters"):
        min_rating = st.slider("Minimum Rating (⭐)", 0, 5, 0, 1)
        in_stock_only = st.checkbox("In Stock Only", value=True)
        exclude_discontinued = st.checkbox("Exclude Discontinued", value=True)
    
    # Session history
    if "query_history" in st.session_state and len(st.session_state.query_history) > 1:
        st.markdown("### 🕑 Recent Searches")
        for past_q in reversed(st.session_state.query_history[-5:]):
            if st.button(f"↩ {past_q[:40]}", key=f"hist_{past_q[:20]}", use_container_width=True):
                st.session_state["_rerun_query"] = past_q
                st.rerun()

    st.divider()
    
    with st.expander("🔍 About Deep Agents"):
        st.markdown("""
        This system uses **4 specialized AI agents** orchestrated by a lead agent:
        
        1. **Intent Parser** - Understands your query
        2. **Vector Searcher** - Finds relevant products
        3. **Analyzer** - Evaluates quality
        4. **Critic** - Validates results
        
        Each agent contributes reasoning that's shown in the trace below.
        """)


# Main Content
st.markdown("# 🤖 Deep Agents Product Search")
st.markdown("*Multi-agent AI orchestration for intelligent product discovery*")

# Query Input
st.markdown("## Search Products")

query_input = st.text_input(
    "What are you looking for?",
    value=st.session_state.pop("_rerun_query", None)
          or (example_queries[selected_example] if selected_example != "-- Select example --" else ""),
    placeholder="e.g., gaming laptop with RTX 4080 under $2000",
    help="Describe what you want. The AI will understand category, brand, price, ratings, and specs."
)

col_search, col_clear = st.columns([4, 1])
with col_search:
    search_button = st.button("🔍 Search", use_container_width=True, type="primary")
with col_clear:
    if st.button("Clear", use_container_width=True):
        st.rerun()

st.divider()

# Execute Search
if search_button and query_input:
    with st.spinner("🤖 Orchestrating agents..."):
        try:
            # Initialize lead agent
            lead_agent = SearchLeadAgent()
            
            # Execute search
            response = lead_agent.search(query_input, last_intent=st.session_state.get("last_intent"))
            
            # Store in session state for later display
            st.session_state.last_response = response
            st.session_state.last_query = query_input
            st.session_state.last_intent = getattr(response, "used_intent", None)
            # Session memory: track query history
            if "query_history" not in st.session_state:
                st.session_state.query_history = []
            if not st.session_state.query_history or st.session_state.query_history[-1] != query_input:
                st.session_state.query_history.append(query_input)
            
        except Exception as e:
            st.error(f"❌ Search failed: {str(e)}")
            st.session_state.last_response = None


# Display Results
if "last_response" in st.session_state and st.session_state.last_response:
    response = st.session_state.last_response
    
    # Summary Section
    st.markdown("## 📊 Search Summary")
    
    col_summary1, col_summary2, col_summary3, col_summary4 = st.columns(4)
    
    with col_summary1:
        st.metric("Results Found", len(response.results))
    
    with col_summary2:
        quality_class, quality_label = get_quality_class(response.data_quality_score)
        st.markdown(f"**Data Quality**\n{response.data_quality_score:.1%}")
    
    with col_summary3:
        st.metric("Top Match", f"{response.results[0].relevance_score:.1%}" if response.results else "N/A")
    
    with col_summary4:
        coverage_count = sum(1 for v in response.coverage_assessment.values() if v)
        st.metric("Filters Applied", f"{coverage_count}/5")

    # Confidence score + fallback notice
    conf = getattr(response, 'confidence_score', 0)
    if conf:
        conf_label = "🟢 High" if conf >= 60 else "🟡 Medium" if conf >= 30 else "🔴 Low"
        st.caption(f"🎯 Query confidence: {conf:.0f}% ({conf_label}) — higher means the intent was clearly understood")
    if conf < 30 and st.session_state.get("last_intent"):
        st.info("💭 **Refine tip**: Your query was vague — try: 'now under $1000', 'just Dell', 'add noise cancelling', or 'only in stock'")
    if getattr(response, 'fallback_used', ''):
        stage = response.fallback_used.replace('_', ' ')
        st.warning(f"💡 No exact matches. Showing closest results after relaxing: **{stage}**. Narrow your query for stricter results.")
    
    st.divider()
    
    # Filter Coverage
    st.markdown("## ✅ Filter Coverage")
    st.markdown("*Which search criteria were successfully applied*")
    render_coverage_assessment(response.coverage_assessment)
    st.divider()
    
    # Ranking Explanation
    if response.ranking_explanation:
        st.markdown("## 🎯 Why These Results?")
        st.info(response.ranking_explanation)
        st.divider()
    
    # Results
    if response.results:
        st.markdown(f"## 🏆 Top Results ({len(response.results)} found)")
        
        for idx, product in enumerate(response.results, 1):
            with st.container():
                render_product_card(product, idx)

        # Feedback summary for this search
        fb_data = st.session_state.get("feedback", {})
        if fb_data:
            liked = sum(1 for v in fb_data.values() if v == "up")
            disliked = sum(1 for v in fb_data.values() if v == "down")
            st.caption(f"📊 Session feedback: 👍 {liked} helpful · 👎 {disliked} not helpful · saved to metrics/feedback.jsonl")

        st.divider()
    else:
        st.warning("⚠️ No products matched your criteria. Try relaxing your filters.")
    
    # Alternatives
    if response.alternatives:
        st.markdown("## 💡 Suggestions")
        for alt in response.alternatives:
            st.info(alt)
        st.divider()
    
    # Agent Trace
    with st.expander("🔍 Agent Decision Trace (Advanced)", expanded=False):
        st.markdown("*Full reasoning log from all 4 agents*")
        render_agent_trace(response.agent_trace)
    
    # Detailed Results Table
    with st.expander("📋 Detailed Results Table", expanded=False):
        if response.results:
            df = pd.DataFrame([
                {
                    "Product ID": r.product_id,
                    "Name": r.name,
                    "Category": r.category,
                    "Brand": r.brand,
                    "Price": format_price(r.unit_price),
                    "Rating": f"{r.rating}⭐" if r.rating else "N/A",
                    "Stock": r.stock_qty if not r.discontinued else "Discontinued",
                    "Match Score": f"{r.relevance_score:.1%}",
                    "Completeness": f"{r.data_completeness:.1%}",
                }
                for r in response.results
            ])
            st.dataframe(df, use_container_width=True)

else:
    # Initial State
    st.markdown("""
    ## 👋 Welcome to Deep Agents Product Search!
    
    This intelligent chatbot uses **4 specialized AI agents** to understand your queries and find the perfect products:
    
    ### How It Works:
    1. **🧠 Intent Parser** - Understands what you're looking for (category, brand, price, specs)
    2. **🔍 Vector Searcher** - Finds semantically similar products using AI embeddings
    3. **📊 Analyzer** - Evaluates result quality and coverage
    4. **✅ Critic** - Validates that results match your intent
    
    ### Try These Queries:
    - "gaming laptop with RTX 4080 under $2000"
    - "budget office chair under $500"
    - "4K monitor for video editing"
    - "wireless headphones with noise cancelling"
    
    Select an example from the sidebar or type your own query above!
    """)
    
    # Show system status
    st.divider()
    st.markdown("### 🔧 System Status")
    
    try:
        # Test connections
        from weaviate_tools import connect_weaviate
        import ollama
        
        col_weaviate, col_ollama = st.columns(2)
        
        try:
            c = connect_weaviate()
            c.close()
            col_weaviate.success("✅ Weaviate Connected (50 products indexed)")
        except:
            col_weaviate.error("❌ Weaviate Disconnected")
        
        try:
            ollama.embed(model='bge-m3', input='test')
            col_ollama.success("✅ Ollama Embedding (bge-m3 active)")
        except:
            col_ollama.error("❌ Ollama Unavailable")
    
    except Exception as e:
        st.warning(f"⚠️ Could not verify system status: {str(e)}")


# Footer
st.divider()
st.markdown("""
---
*Deep Agents Product Search System | Powered by LangChain + Weaviate + Ollama*

**Ingestion Pipeline:** Unchanged and stable | **Deep Agents:** Active and orchestrating
""")
