"""Markdown parser — keeps headings as section markers."""
from __future__ import annotations

import re
from typing import Iterable

from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


class MarkdownParser:
    name = "markdown"
    mime_types = ("text/markdown",)
    extensions = ("md", "markdown", "mdx")

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        text = doc.content.decode("utf-8", errors="replace")
        # Split on headings; each section keeps its heading as `section`.
        positions = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(text)]
        if not positions:
            if text.strip():
                yield Block(text=text, section=None)
            return
        # Pre-heading content
        if positions[0][0] > 0:
            pre = text[: positions[0][0]].strip()
            if pre:
                yield Block(text=pre, section=None)
        for i, (start, heading) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                yield Block(text=chunk, section=heading)


register_parser(MarkdownParser())
