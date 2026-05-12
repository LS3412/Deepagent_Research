"""Streamlit chat UI with PDF/file upload and live tool-call trace."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

import streamlit as st

from src.agent.build import build_agent
from src.agent.skills_loader import load_agent_files
from src.chat_history import (
    load_recent_sessions,
    load_session_messages,
    prune_old_messages,
    save_message,
)
from src.config import get_settings
from src.ingestion.pipeline import ingest_bytes, ingest_directory
from src.retrieval.search import list_documents
from src.tracing import callbacks_with_langfuse, flush_langfuse
from src.ui.ingestion_page import render_ingestion_page

log = logging.getLogger(__name__)

# Regex that matches KB inline citations like [filename], [file.pdf p.3], [doc §Section]
_CITATION_RE = re.compile(r'\[[^\]]{1,120}\]')

# Stop words ignored when extracting topic keywords from a question
_STOP_WORDS = {
    "what", "is", "are", "was", "were", "a", "an", "the", "be", "been", "being",
    "how", "why", "when", "where", "who", "which", "does", "do", "did", "can",
    "could", "would", "should", "tell", "me", "about", "explain", "describe",
    "give", "show", "list", "find", "get", "please", "and", "or", "in", "on",
    "at", "to", "for", "of", "with", "by", "from", "this", "that", "it", "its",
    "have", "has", "had", "will", "shall", "may", "might", "must", "just",
}


def _question_keywords(question: str) -> set[str]:
    """Extract content-bearing keywords from a question (length ≥ 4, not stop words)."""
    words = re.findall(r'\b[a-z]{4,}\b', question.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _topics_match(question: str, answer: str) -> bool:
    """Return True if the answer appears to be about the same topic as the question.

    Extracts content keywords from the question and checks whether at least one
    appears in the answer. Catches cases where the agent searched, got off-topic
    chunks (e.g. battery docs for a black hole question), and answered from them.
    Returns True for short/conversational answers and valid not-found replies.
    """
    answer_lower = answer.lower()
    # Always pass for valid not-found or short conversational answers
    if "knowledge base" in answer_lower or len(answer.strip()) <= 200:
        return True
    keywords = _question_keywords(question)
    if not keywords:
        return True  # Can't check — allow through
    # At least one keyword from the question must appear in the answer
    matched = any(kw in answer_lower for kw in keywords)
    if not matched:
        log.warning(
            "topic-mismatch: question keywords %s not found in answer (len=%d)",
            keywords, len(answer),
        )
    return matched


def _is_grounded(answer: str, trace_lines: list[str]) -> bool:
    """Return True if the answer is grounded in the KB or is a valid not-found reply."""
    lower = answer.lower()
    # Valid not-found reply
    if "knowledge base" in lower or "not yet indexed" in lower:
        return True
    # Has citation markers
    if _CITATION_RE.search(answer):
        return True
    # Short conversational answer
    if len(answer.strip()) <= 200:
        return True
    return False


def _init_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "tenant_id" not in st.session_state:
        st.session_state.tenant_id = get_settings().default_tenant_id
    # Prune stale messages once per session start.
    if "_pruned" not in st.session_state:
        prune_old_messages(days=2)
        st.session_state._pruned = True


def _sidebar() -> None:
    s = get_settings()
    with st.sidebar:
        st.header("Knowledge base")

        st.text_input(
            "Tenant ID",
            key="tenant_id",
            help="Documents and queries are isolated per tenant.",
        )

        uploaded = st.file_uploader(
            "Upload files",
            type=None,
            accept_multiple_files=True,
            help="PDF, DOCX, HTML, MD, TXT, CSV, JSON, and more.",
        )
        if uploaded and st.button("Ingest uploaded", type="primary"):
            results_summary: list[str] = []
            with st.spinner(f"Ingesting {len(uploaded)} file(s)..."):
                for f in uploaded:
                    log.info("ingesting upload  file=%s  tenant=%s", f.name, st.session_state.tenant_id)
                    res = ingest_bytes(
                        content=f.getvalue(),
                        file_name=f.name,
                        tenant_id=st.session_state.tenant_id,
                    )
                    if res.skipped:
                        log.info("skipped %s: %s", f.name, res.reason)
                        st.info(f"{f.name}: skipped ({res.reason})")
                        results_summary.append(f"⏭ {f.name}: skipped ({res.reason})")
                    elif res.chunks_indexed == 0:
                        st.warning(f"{f.name}: 0 chunks — check if file is empty or unsupported")
                        results_summary.append(f"⚠️ {f.name}: 0 chunks indexed")
                    else:
                        log.info("ingested %s: %d chunks", f.name, res.chunks_indexed)
                        st.success(f"{f.name}: {res.chunks_indexed} chunks indexed")
                        results_summary.append(f"✅ {f.name}: {res.chunks_indexed} chunks")
            # Toast visible from any tab
            if results_summary:
                st.toast("Ingestion complete: " + " | ".join(results_summary))

        st.divider()
        if st.button("Re-index watch folder"):
            with st.spinner(f"Indexing {s.watch_dir}..."):
                results = ingest_directory(
                    s.watch_dir, tenant_id=st.session_state.tenant_id
                )
                new = sum(r.chunks_indexed for r in results)
                st.success(f"Indexed {len(results)} file(s), {new} new chunks")

        st.divider()
        st.subheader("Indexed documents")
        try:
            docs = list_documents(st.session_state.tenant_id, limit=200)
            if docs:
                st.dataframe(docs, hide_index=True, width="stretch")
            else:
                st.caption("No documents indexed yet for this tenant.")
        except Exception as e:
            st.warning(f"Could not list documents: {e}")

        st.divider()
        st.caption(f"Chat model: `{s.ollama_chat_model}`")
        st.caption(f"Embeddings: `{s.ollama_embed_model}`")

        st.checkbox("Show agent trace", value=True, key="show_trace")

        # ── Chat history (last 2 days) ──
        st.divider()
        st.subheader("Chat history")
        if st.button("➕ New chat"):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()

        recent = load_recent_sessions(st.session_state.tenant_id, days=2)
        if recent:
            for sess in recent:
                label = sess["preview"] or "(empty)"
                count = sess["message_count"]
                sid = sess["session_id"]
                is_current = sid == st.session_state.session_id
                btn_label = f"{'▶ ' if is_current else ''}{label}  ({count} msgs)"
                if st.button(btn_label, key=f"sess_{sid}", disabled=is_current):
                    st.session_state.session_id = sid
                    st.session_state.messages = load_session_messages(sid)
                    log.info("switched to session %s (%d msgs)", sid, count)
                    st.rerun()
        else:
            st.caption("No recent chats.")


def _render_history() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            if m.get("trace"):
                with st.expander("🔎 Agent trace", expanded=False):
                    for line in m["trace"]:
                        st.markdown(line)
            st.markdown(m["content"])


def _short(obj: Any, limit: int = 600) -> str:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False, indent=2)
    except Exception:
        s = str(obj)
    if len(s) > limit:
        s = s[:limit] + f"\n... (+{len(s) - limit} chars)"
    return s


# Counters stored in session state so labels are unique per run.
_NODE_ICONS = {
    "agent": "🤖",
    "researcher": "🔬",
    "writer": "✍️",
    "verifier": "✅",
    "tools": "🔧",
}


def _node_icon(node: str) -> str:
    for k, v in _NODE_ICONS.items():
        if k in node.lower():
            return v
    return "⚙️"


def _format_event(event: dict[str, Any]) -> list[str]:
    """Turn a LangGraph stream event into clearly labelled markdown lines."""
    lines: list[str] = []
    for node, payload in event.items():
        icon = _node_icon(node)
        msgs = payload.get("messages") if isinstance(payload, dict) else None
        if not msgs:
            # Some payloads (skills reads, memory loads) don't carry messages.
            # Surface them as a generic node activity line.
            if isinstance(payload, dict) and payload:
                summary = ", ".join(
                    f"{k}={repr(v)[:60]}" for k, v in list(payload.items())[:4]
                )
                lines.append(f"{icon} **[{node}]** _{summary}_")
            continue
        for msg in msgs:
            mtype = type(msg).__name__
            content = getattr(msg, "content", "") or ""
            tool_calls = getattr(msg, "tool_calls", None) or []
            name = getattr(msg, "name", None)

            if mtype == "AIMessage":
                if tool_calls:
                    for tc in tool_calls:
                        tname = (
                            tc.get("name") if isinstance(tc, dict)
                            else getattr(tc, "name", "?")
                        )
                        targs = (
                            tc.get("args") if isinstance(tc, dict)
                            else getattr(tc, "args", {})
                        )
                        lines.append(
                            f"**🛠 [{node}] → tool call: `{tname}`**"
                            f"\n```json\n{_short(targs, 400)}\n```"
                        )
                elif content.strip():
                    # Thinking / reasoning text
                    lines.append(
                        f"{icon} **[{node}] reasoning**\n\n> {content[:800]}"
                    )
            elif mtype == "ToolMessage":
                lines.append(
                    f"**📦 tool result: `{name or '?'}`**"
                    f"\n```\n{_short(content, 800)}\n```"
                )
            elif mtype == "HumanMessage":
                pass  # already rendered in chat
    return lines


def _run_agent_stream(user_input: str, trace_box) -> tuple[str, list[str]]:
    agent = build_agent(st.session_state.tenant_id)
    callbacks = callbacks_with_langfuse()
    config = {
        "callbacks": callbacks,
        "configurable": {"thread_id": st.session_state.session_id},
        "metadata": {
            # Standard keys for Langfuse v4 LangChain integration.
            "langfuse_session_id": st.session_state.session_id,
            "langfuse_user_id": st.session_state.tenant_id,
            "langfuse_tags": ["chat", st.session_state.tenant_id],
            # Extra context (not Langfuse-specific).
            "tenant_id": st.session_state.tenant_id,
            "route": "chat",
        },
        "recursion_limit": 50,
    }

    trace_lines: list[str] = []
    final_answer = "(no response)"

    # Seed the StateBackend in-memory FS with skill + memory files.
    skill_files = load_agent_files()
    log.info(
        "agent stream start  tenant=%s  session=%s  skill_files=%d  query=%r",
        st.session_state.tenant_id,
        st.session_state.session_id,
        len(skill_files),
        user_input[:120],
    )

    stream_input: dict[str, Any] = {
        "messages": [{"role": "user", "content": user_input}],
    }
    if skill_files:
        stream_input["files"] = skill_files

    t0 = time.time()
    event_count = 0
    for event in agent.stream(
        stream_input,
        config=config,
        stream_mode="updates",
    ):
        event_count += 1
        log.debug("stream event #%d  nodes=%s", event_count, list(event.keys()))
        new_lines = _format_event(event)
        if new_lines:
            trace_lines.extend(new_lines)
            if st.session_state.get("show_trace", True) and trace_box is not None:
                trace_box.markdown("\n\n---\n\n".join(trace_lines))

        # Capture the latest assistant content as the running answer.
        for _, payload in event.items():
            if not isinstance(payload, dict):
                continue
            for msg in payload.get("messages", []) or []:
                if type(msg).__name__ == "AIMessage":
                    c = getattr(msg, "content", "") or ""
                    if c.strip() and not getattr(msg, "tool_calls", None):
                        final_answer = c

    elapsed = time.time() - t0
    log.info(
        "agent stream done  tenant=%s  events=%d  elapsed=%.1fs  answer_len=%d",
        st.session_state.tenant_id, event_count, elapsed, len(final_answer),
    )

    # ── KB-grounding guardrail ────────────────────────────────────────────────
    # Fire the guardrail if:
    # (a) answer has no citations and no not-found language, OR
    # (b) tool explicitly returned NO_RELEVANT_RESULTS but agent answered, OR
    # (c) answer topic doesn't match the question (off-topic KB results used)
    no_results_signal = "no_relevant_results" in " ".join(trace_lines).lower()
    already_not_found = "knowledge base" in final_answer.lower()

    should_block = (
        not _is_grounded(final_answer, trace_lines)
        or (no_results_signal and not already_not_found)
        or (not already_not_found and not _topics_match(user_input, final_answer))
    )

    if should_block:
        log.warning(
            "guardrail triggered for query=%r  grounded=%s  topic_match=%s  no_results=%s",
            user_input[:80],
            _is_grounded(final_answer, trace_lines),
            _topics_match(user_input, final_answer),
            no_results_signal,
        )
        try:
            docs = list_documents(st.session_state.tenant_id, limit=50)
            doc_names = [d.get("file_name", "") for d in docs if d.get("file_name")] if docs else []
        except Exception:
            doc_names = []

        if doc_names:
            doc_list_str = "\n".join(f"- {name}" for name in doc_names)
            final_answer = (
                "I'm sorry, but I couldn't find information about that topic in the knowledge base.\n\n"
                "Please ask questions related to the indexed documents:\n"
                f"{doc_list_str}\n\n"
                "You can also upload new documents using the sidebar."
            )
        else:
            final_answer = (
                "I'm sorry, but I couldn't find information about that topic in the knowledge base.\n\n"
                "No documents are indexed yet. Please upload relevant documents using the sidebar "
                "and then ask your question."
            )
    # ───────────────────────────────────────────────────────────────────────

    # Flush buffered Langfuse traces — without this they may never be sent.
    flush_langfuse()

    return final_answer, trace_lines


def main() -> None:
    st.set_page_config(page_title="DeepAgent KB Chatbot", layout="wide")
    _init_state()
    _sidebar()

    st.title("DeepAgent Knowledge-Base Chatbot")

    tab_chat, tab_ingest = st.tabs(["💬 Chat", "📥 Ingestion Dashboard"])

    with tab_chat:
        st.caption(
            "Ask questions about the documents in your tenant. The agent plans, "
            "retrieves with citations, verifies, and writes the answer."
        )

        _render_history()

        user_input = st.chat_input("Ask a question about your documents...")
        if user_input:
            st.session_state.messages.append({"role": "user", "content": user_input})
            save_message(st.session_state.session_id, st.session_state.tenant_id, "user", user_input)
            with st.chat_message("user"):
                st.markdown(user_input)

            log.info("user query  tenant=%s  query=%r", st.session_state.tenant_id, user_input[:120])

            with st.chat_message("assistant"):
                trace_expander = (
                    st.expander("🔎 Agent trace (live)", expanded=True)
                    if st.session_state.get("show_trace", True)
                    else None
                )
                trace_box = trace_expander.empty() if trace_expander is not None else None

                answer_box = st.empty()
                t0 = time.time()
                try:
                    answer, trace_lines = _run_agent_stream(user_input, trace_box)
                except Exception as e:
                    log.exception("agent stream failed  tenant=%s  query=%r", st.session_state.tenant_id, user_input[:120])
                    answer = f"**Error:** {e}"
                    trace_lines = []
                dt = time.time() - t0
                answer_box.markdown(answer)
                st.caption(f"⏱ {dt:.1f}s")

            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "trace": trace_lines}
            )
            save_message(
                st.session_state.session_id,
                st.session_state.tenant_id,
                "assistant",
                answer,
                trace=trace_lines,
            )

    with tab_ingest:
        render_ingestion_page(st.session_state.tenant_id)


if __name__ == "__main__":
    main()
