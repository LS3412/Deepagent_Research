"""Ingestion Dashboard — live pipeline visualization + corpus overview.

Renders inside the "📥 Ingestion" tab of the main Streamlit app.

Layout
------
  Top   : Upload section  — file uploader + "Ingest with trace" button
  Middle: Pipeline trace  — 6 stage cards, each updates live as it runs
  Bottom: Corpus overview — charts + metrics + documents table
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from typing import Any

import streamlit as st

from src.config import get_settings
from src.ingestion.interfaces import RawDocument, now_utc
from src.ingestion.sink import WeaviateSink
from src.retrieval.search import get_corpus_stats

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_ingestion_page(tenant_id: str) -> None:
    st.subheader("📥 Ingest Documents")

    uploaded_files = st.file_uploader(
        "Upload files (PDF, DOCX, PPTX, HTML, MD, TXT, CSV, JSON, …)",
        type=None,
        accept_multiple_files=True,
        key="ingest_uploader",
    )

    col_btn, col_opt = st.columns([2, 3])
    with col_btn:
        run = st.button(
            "⚡ Ingest with live trace",
            type="primary",
            disabled=not uploaded_files,
        )
    with col_opt:
        st.caption(
            f"Strategy: **{get_settings().chunk_strategy}** | "
            f"Embed: **{get_settings().embed_strategy}** | "
            f"Dedup: **{get_settings().dedup_enabled}**"
        )

    if run and uploaded_files:
        for f in uploaded_files:
            st.divider()
            _visualize_ingest(f.getvalue(), f.name, tenant_id)

    st.divider()
    _render_corpus_dashboard(tenant_id)


# ─────────────────────────────────────────────────────────────────────────────
# Per-file visualized ingestion
# ─────────────────────────────────────────────────────────────────────────────

def _visualize_ingest(content: bytes, file_name: str, tenant_id: str) -> None:
    """Run each pipeline stage one-by-one with live Streamlit status cards."""
    import pandas as pd

    s = get_settings()
    sha = hashlib.sha256(content).hexdigest()
    mime, _ = mimetypes.guess_type(file_name)
    mime = mime or "application/octet-stream"

    st.markdown(f"#### 📄 `{file_name}`")
    st.caption(f"SHA256: `{sha[:20]}…`  |  MIME: `{mime}`  |  Size: `{len(content):,}` bytes")

    sink = WeaviateSink()
    sink.ensure_schema()

    if sink.already_indexed(sha, tenant_id):
        st.warning(
            f"⏭️ Already indexed. Delete the document first to re-ingest."
        )
        return

    raw = RawDocument(
        source_uri=f"upload://{file_name}",
        file_name=file_name,
        mime_type=mime,
        content=content,
        tenant_id=tenant_id,
    )

    chunks: list = []
    parser_name: str = "unstructured"

    # ── Stage 1: Parse ──────────────────────────────────────────────────────
    with st.status("**Stage 1 — Parse**  (Unstructured)", expanded=True) as st1:
        try:
            from src.ingestion.parsers.unstructured_parser import UnstructuredParser
            parser = UnstructuredParser()
        except ImportError:
            from src.ingestion.registry import load_builtin_parsers, select_parser
            load_builtin_parsers()
            parser = select_parser(file_name, mime)

        parser_name = parser.name
        blocks = list(parser.parse(raw))

        el_counts: dict[str, int] = {}
        for b in blocks:
            t = b.extra.get("element_type", "Unknown")
            el_counts[t] = el_counts.get(t, 0) + 1

        st1.update(
            label=f"**Stage 1 — Parse** ✅  {len(blocks)} blocks parsed",
            state="complete",
        )
        m1, m2 = st.columns(2)
        m1.metric("Blocks", len(blocks))
        m2.metric("Element types", len(el_counts))
        if el_counts:
            st.bar_chart(el_counts, x_label="Element type", y_label="Count")

    if not blocks:
        st.error("No content extracted — skipping remaining stages.")
        return

    # ── Stage 2: Chunk ──────────────────────────────────────────────────────
    with st.status("**Stage 2 — Chunk**", expanded=True) as st2:
        from src.ingestion.chunker import get_chunker
        chunker = get_chunker(s)
        chunks = list(chunker.chunk(blocks))

        st2.update(
            label=f"**Stage 2 — Chunk** ✅  {len(chunks)} chunks  [{type(chunker).__name__}]",
            state="complete",
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Chunks", len(chunks))
        m2.metric("Chunker", type(chunker).__name__)
        avg_len = int(sum(len(c.text) for c in chunks) / len(chunks)) if chunks else 0
        m3.metric("Avg chunk length", f"{avg_len} chars")

    # ── Stage 3: Enrich ─────────────────────────────────────────────────────
    with st.status(
        "**Stage 3 — Enrich**  (Hierarchy · Keywords · Language · Confidence)",
        expanded=True,
    ) as st3:
        from src.ingestion.enricher import build_enricher_chain
        chain = build_enricher_chain(top_n_keywords=s.enrich_keywords_top_n)
        chunks = chain.enrich_all(chunks, raw)

        langs = sorted(set(c.extra.get("language") for c in chunks if c.extra.get("language")))
        all_kw = [kw for c in chunks for kw in c.extra.get("keywords", [])]
        kw_freq: dict[str, int] = {}
        for kw in all_kw:
            kw_freq[kw] = kw_freq.get(kw, 0) + 1
        top_kw = dict(sorted(kw_freq.items(), key=lambda x: -x[1])[:15])

        conf_buckets = {"≥ 0.9": 0, "0.7–0.9": 0, "0.5–0.7": 0, "< 0.5": 0}
        for c in chunks:
            sc = c.extra.get("confidence_score", 0)
            if sc >= 0.9:
                conf_buckets["≥ 0.9"] += 1
            elif sc >= 0.7:
                conf_buckets["0.7–0.9"] += 1
            elif sc >= 0.5:
                conf_buckets["0.5–0.7"] += 1
            else:
                conf_buckets["< 0.5"] += 1

        st3.update(
            label=(
                f"**Stage 3 — Enrich** ✅  "
                f"lang={', '.join(langs) or '—'}  "
                f"keywords={len(set(all_kw))}"
            ),
            state="complete",
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Language(s)", ", ".join(langs) or "—")
        m2.metric("Unique keywords", len(set(all_kw)))
        m3.metric("Enricher steps", len(chain.enrichers))

        c_left, c_right = st.columns(2)
        with c_left:
            st.caption("**Confidence distribution**")
            st.bar_chart(conf_buckets, x_label="Band", y_label="Chunks")
        with c_right:
            if top_kw:
                st.caption("**Top keywords**")
                st.bar_chart(top_kw, x_label="Keyword", y_label="Freq")

    # ── Stage 4: Dedup ──────────────────────────────────────────────────────
    with st.status(
        "**Stage 4 — Deduplicate**  (MinHash LSH)", expanded=True
    ) as st4:
        from src.ingestion.deduplicator import MinHashDeduplicator
        dedup = MinHashDeduplicator(
            threshold=s.dedup_threshold,
            num_perm=s.dedup_num_perm,
            index_path=s.dedup_index_path,
        )
        chunks = dedup.process(chunks, sha)
        n_dupes = sum(1 for c in chunks if c.extra.get("is_duplicate"))
        n_unique = len(chunks) - n_dupes

        st4.update(
            label=(
                f"**Stage 4 — Deduplicate** ✅  "
                f"{n_unique} unique  {n_dupes} near-duplicate(s) skipped"
            ),
            state="complete",
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Unique", n_unique)
        m2.metric("Near-duplicates", n_dupes)
        m3.metric("LSH threshold", s.dedup_threshold)
        if n_dupes:
            st.info(
                f"ℹ️ {n_dupes} chunk(s) are near-duplicates of previously "
                "indexed content and will not be re-embedded."
            )

    # ── Stage 5: Embed ──────────────────────────────────────────────────────
    embed_chunks = [c for c in chunks if not c.extra.get("is_duplicate")]
    with st.status(
        f"**Stage 5 — Embed**  ({len(embed_chunks)} chunks → Ollama {s.ollama_embed_model})",
        expanded=True,
    ) as st5:
        from src.ingestion.embedder import AsyncOllamaBatchEmbedder, OllamaBatchEmbedder
        if s.embed_strategy == "async":
            embedder = AsyncOllamaBatchEmbedder(
                batch_size=s.embed_batch_size,
                max_concurrent=s.embed_max_concurrent_batches,
            )
        else:
            embedder = OllamaBatchEmbedder(batch_size=s.embed_batch_size)

        vectors = embedder.embed([c.text for c in embed_chunks]) if embed_chunks else []

        dim = len(vectors[0]) if vectors else 0
        st5.update(
            label=(
                f"**Stage 5 — Embed** ✅  "
                f"{len(vectors)} vectors  dim={dim}  "
                f"strategy={s.embed_strategy}"
            ),
            state="complete",
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Vectors", len(vectors))
        m2.metric("Dimensions", dim)
        m3.metric("Strategy", s.embed_strategy)

    # ── Stage 6: Store ──────────────────────────────────────────────────────
    with st.status("**Stage 6 — Store**  (Weaviate)", expanded=True) as st6:
        from src.ingestion.pipeline import _build_record
        created = ingested = now_utc()
        records = []
        for c, v in zip(embed_chunks, vectors):
            records.append(
                _build_record(
                    c, v, tenant_id, sha,
                    f"upload://{file_name}", file_name, mime,
                    parser_name, [], created, ingested,
                )
            )
        for c in [ch for ch in chunks if ch.extra.get("is_duplicate")]:
            records.append(
                _build_record(
                    c, [], tenant_id, sha,
                    f"upload://{file_name}", file_name, mime,
                    parser_name, [], created, ingested,
                )
            )
        written = sink.upsert(records)
        dedup.save()

        st6.update(
            label=f"**Stage 6 — Store** ✅  {written} records written to Weaviate",
            state="complete",
        )
        st.metric("Records written", written)

    # ── Summary banner ───────────────────────────────────────────────────────
    st.success(
        f"✅ **{file_name}** — {written} chunks indexed  "
        f"({n_dupes} duplicate(s) flagged, not re-embedded)"
    )

    # ── Chunk detail table ───────────────────────────────────────────────────
    with st.expander("🔍 Chunk detail table", expanded=False):
        rows = []
        for c in chunks:
            rows.append({
                "#": c.chunk_index,
                "type": c.extra.get("element_type", ""),
                "lang": c.extra.get("language", ""),
                "conf": round(c.extra.get("confidence_score", 0), 2),
                "dup": "✓" if c.extra.get("is_duplicate") else "",
                "keywords": ", ".join((c.extra.get("keywords") or [])[:3]),
                "breadcrumb": (c.extra.get("breadcrumb") or "")[:40],
                "text": c.text[:120].replace("\n", " "),
            })
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "conf": st.column_config.NumberColumn("conf", format="%.2f"),
                "text": st.column_config.TextColumn("text (preview)", width="large"),
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Corpus dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _render_corpus_dashboard(tenant_id: str) -> None:
    st.subheader("📊 Corpus Overview")

    try:
        stats = get_corpus_stats(tenant_id)
    except Exception as exc:
        st.warning(f"Could not load corpus stats: {exc}")
        return

    if stats["total_chunks"] == 0:
        st.caption("No documents indexed yet for this tenant.")
        return

    # ── Top metrics ─────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📄 Documents", stats["total_docs"])
    m2.metric("🧩 Chunks", stats["total_chunks"])
    m3.metric(
        "🌐 Languages",
        len(stats["unique_languages"]),
        help=", ".join(stats["unique_languages"]) or "—",
    )
    m4.metric("📈 Avg Confidence", f"{stats['avg_confidence']:.2f}")

    # ── Charts row ───────────────────────────────────────────────────────────
    c_left, c_mid, c_right = st.columns(3)

    with c_left:
        st.caption("**Element types**")
        if stats["element_type_counts"]:
            st.bar_chart(
                stats["element_type_counts"],
                x_label="Type",
                y_label="Chunks",
            )

    with c_mid:
        st.caption("**Confidence distribution**")
        if stats["confidence_buckets"]:
            st.bar_chart(
                stats["confidence_buckets"],
                x_label="Band",
                y_label="Chunks",
            )

    with c_right:
        st.caption("**Top 15 keywords**")
        if stats["top_keywords"]:
            st.bar_chart(
                stats["top_keywords"],
                x_label="Keyword",
                y_label="Frequency",
            )

    # ── Documents table ──────────────────────────────────────────────────────
    st.caption("**Indexed documents**")
    if stats["documents"]:
        import pandas as pd
        st.dataframe(
            pd.DataFrame(stats["documents"]),
            hide_index=True,
            use_container_width=True,
            column_config={
                "chunks": st.column_config.NumberColumn("chunks", format="%d"),
            },
        )
