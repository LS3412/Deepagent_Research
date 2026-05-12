"""PDF parser — Docling first (tables/multi-col/OCR), PyMuPDF fast-path."""
from __future__ import annotations

import io
from typing import Iterable

from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser


def _pymupdf_blocks(content: bytes) -> Iterable[Block]:
    import fitz  # PyMuPDF

    with fitz.open(stream=content, filetype="pdf") as pdf:
        for page_num, page in enumerate(pdf, start=1):
            text = page.get_text("text") or ""
            text = text.strip()
            if text:
                yield Block(text=text, page=page_num)


def _docling_blocks(content: bytes, file_name: str) -> Iterable[Block]:
    from docling.document_converter import DocumentConverter  # type: ignore
    from docling.datamodel.base_models import DocumentStream  # type: ignore

    converter = DocumentConverter()
    stream = DocumentStream(name=file_name, stream=io.BytesIO(content))
    result = converter.convert(stream)
    md = result.document.export_to_markdown()
    if md and md.strip():
        # Docling preserves headings/tables in markdown — keep as one block per page if available.
        # For simplicity here, emit a single block; the markdown chunker can split on headings.
        yield Block(text=md, page=None, section=None, extra={"parser": "docling"})


class PdfParser:
    name = "pdf"
    mime_types = ("application/pdf",)
    extensions = ("pdf",)

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        # Fast path: PyMuPDF for text-based PDFs (cheap + per-page metadata).
        try:
            blocks = list(_pymupdf_blocks(doc.content))
        except Exception:
            blocks = []

        total_chars = sum(len(b.text) for b in blocks)
        # If text extraction is sparse (likely scanned / table-heavy), try Docling.
        if total_chars < 200:
            try:
                docling_blocks = list(_docling_blocks(doc.content, doc.file_name))
                if docling_blocks and sum(len(b.text) for b in docling_blocks) > total_chars:
                    yield from docling_blocks
                    return
            except Exception:
                pass

        if blocks:
            yield from blocks


register_parser(PdfParser())
