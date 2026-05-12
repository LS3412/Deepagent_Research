"""Universal document parser using Unstructured.io (v2 pipeline).

Replaces all 7 format-specific parsers (PDF, DOCX, HTML, MD, CSV, JSON, TXT)
with a single API that also extracts element types, hierarchy, and language.

The pipeline selects this parser automatically when chunk_strategy is
"element" or "semantic".  Falls back to legacy parsers if unstructured
is not installed.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Iterable

from src.ingestion.interfaces import Block, RawDocument
from src.ingestion.registry import register_parser

log = logging.getLogger(__name__)

# Element types that must never be split by a chunker
INTACT_ELEMENT_TYPES = frozenset({"Table", "Title", "Header", "Footer", "Image"})


class UnstructuredParser:
    """Parse any document format via Unstructured with full element-type metadata.

    Each document element becomes a Block whose ``extra`` dict contains::

        element_type         — Title, NarrativeText, Table, ListItem, …
        element_id           — unique element identifier
        parent_id            — ID of the nearest ancestor heading
        depth                — nesting depth from document root
        heading_chain        — list of ancestor heading IDs (root → current)
        heading_chain_texts  — list of ancestor heading texts (for HierarchyEnricher)
        language             — ISO 639-1 code auto-detected by Unstructured
    """

    name = "unstructured"
    # Catch-all: empty tuples → not matched by extension/MIME routing.
    # pipeline.py selects this parser directly when chunk_strategy != "recursive".
    mime_types: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        try:
            from unstructured.partition.auto import partition  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "unstructured is not installed. "
                "Run: pip install unstructured[all-docs]"
            ) from exc

        suffix = self._suffix(doc.file_name)
        tmp_path: str | None = None
        elements = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
                fh.write(doc.content)
                tmp_path = fh.name

            try:
                elements = partition(filename=tmp_path)
            except Exception as exc:
                log.warning(
                    "unstructured.partition failed for %s: %s — trying PyMuPDF fallback",
                    doc.file_name, exc,
                )
                elements = None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        # ── PyMuPDF / pdfminer fallback for PDFs when unstructured_inference missing ──
        if elements is None:
            yield from self._fallback_parse(doc)
            return

        # Track active heading ancestry: [{depth, text, id}, ...]
        heading_stack: list[dict] = []

        for el in elements:
            el_type = type(el).__name__   # "Title", "NarrativeText", "Table", …
            text = str(el).strip()
            if not text:
                continue

            metadata = getattr(el, "metadata", None)
            page: int | None = (
                getattr(metadata, "page_number", None) if metadata else None
            )
            languages: list | None = (
                getattr(metadata, "languages", None) if metadata else None
            )
            lang: str | None = languages[0] if languages else None

            if el_type == "Title":
                raw_depth = (
                    getattr(metadata, "category_depth", None) if metadata else None
                )
                depth = int(raw_depth) if raw_depth is not None else len(heading_stack)
                # Pop all headings at the same depth or deeper
                heading_stack = [h for h in heading_stack if h["depth"] < depth]
                el_id = f"h_{id(el)}"
                heading_stack.append({"depth": depth, "text": text, "id": el_id})
                section = text
            else:
                section = heading_stack[-1]["text"] if heading_stack else None

            raw_depth = (
                getattr(metadata, "category_depth", None) if metadata else None
            )
            el_depth = (
                int(raw_depth) if raw_depth is not None else len(heading_stack)
            )

            yield Block(
                text=text,
                page=page,
                section=section,
                heading_chain=[h["id"] for h in heading_stack],
                heading_chain_texts=[h["text"] for h in heading_stack],
                extra={
                    "element_type": el_type,
                    "element_id": f"el_{id(el)}",
                    "parent_id": heading_stack[-1]["id"] if heading_stack else None,
                    "depth": el_depth,
                    "heading_chain": [h["id"] for h in heading_stack],
                    "heading_chain_texts": [h["text"] for h in heading_stack],
                    "language": lang,
                },
            )

    def _suffix(self, file_name: str) -> str:
        return ("."+file_name.rsplit(".", 1)[-1]) if "." in file_name else ".txt"

    def _fallback_parse(self, doc: RawDocument) -> Iterable[Block]:
        """Pure-Python PDF/text extraction when unstructured_inference is absent.

        Priority:
          1. PyMuPDF (fitz) — fast, handles most PDFs
          2. pdfminer.six   — pure-Python, slower but no C deps
          3. Raw UTF-8 decode — last resort for plain text
        """
        ext = doc.file_name.rsplit(".", 1)[-1].lower() if "." in doc.file_name else ""
        is_pdf = ext == "pdf" or doc.mime_type == "application/pdf"

        if is_pdf:
            # ── PyMuPDF ───────────────────────────────────────────────────────
            try:
                import fitz  # type: ignore  (pymupdf)
                pdf = fitz.open(stream=doc.content, filetype="pdf")
                log.info("fallback: PyMuPDF parsing %s  pages=%d", doc.file_name, len(pdf))
                for page_num, page in enumerate(pdf, start=1):
                    text = page.get_text("text").strip()
                    if text:
                        yield Block(
                            text=text,
                            page=page_num,
                            section=None,
                            extra={
                                "element_type": "NarrativeText",
                                "element_id": f"pymupdf_p{page_num}",
                                "parent_id": None,
                                "depth": 0,
                                "heading_chain": [],
                                "heading_chain_texts": [],
                                "language": None,
                            },
                        )
                pdf.close()
                return
            except ImportError:
                log.debug("PyMuPDF not available")
            except Exception as exc:
                log.warning("PyMuPDF failed for %s: %s — trying pdfminer", doc.file_name, exc)

            # ── pdfminer.six ──────────────────────────────────────────────────
            try:
                import io
                from pdfminer.high_level import extract_pages  # type: ignore
                from pdfminer.layout import LTTextContainer  # type: ignore
                log.info("fallback: pdfminer parsing %s", doc.file_name)
                page_num = 0
                for page_layout in extract_pages(io.BytesIO(doc.content)):
                    page_num += 1
                    texts = [
                        el.get_text().strip()
                        for el in page_layout
                        if isinstance(el, LTTextContainer)
                    ]
                    text = "\n".join(t for t in texts if t)
                    if text:
                        yield Block(
                            text=text,
                            page=page_num,
                            section=None,
                            extra={
                                "element_type": "NarrativeText",
                                "element_id": f"pdfminer_p{page_num}",
                                "parent_id": None,
                                "depth": 0,
                                "heading_chain": [],
                                "heading_chain_texts": [],
                                "language": None,
                            },
                        )
                return
            except ImportError:
                log.debug("pdfminer not available")
            except Exception as exc:
                log.warning("pdfminer failed for %s: %s", doc.file_name, exc)

        # ── Generic text decode (non-PDF or all PDF parsers failed) ───────────
        try:
            text = doc.content.decode("utf-8", errors="replace").strip()
            if text:
                yield Block(
                    text=text,
                    page=None,
                    section=None,
                    extra={
                        "element_type": "NarrativeText",
                        "element_id": "text_fallback",
                        "parent_id": None,
                        "depth": 0,
                        "heading_chain": [],
                        "heading_chain_texts": [],
                        "language": None,
                    },
                )
        except Exception as exc:
            log.error("all parsing strategies failed for %s: %s", doc.file_name, exc)


# Self-register so pipeline.py can look it up by name
register_parser(UnstructuredParser())
