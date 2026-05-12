"""Plain-text parser (also acts as the universal fallback)."""
from __future__ import annotations

from typing import Iterable

from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser


class TextParser:
    name = "text"
    mime_types = ("text/plain",)
    extensions = ("txt", "log", "rst")

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        try:
            text = doc.content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                import chardet  # type: ignore
                enc = chardet.detect(doc.content).get("encoding") or "latin-1"
                text = doc.content.decode(enc, errors="replace")
            except Exception:
                text = doc.content.decode("latin-1", errors="replace")
        if text.strip():
            yield Block(text=text, page=None, section=None)


register_parser(TextParser())
