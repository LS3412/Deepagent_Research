"""HTML parser — trafilatura when available, BeautifulSoup as fallback."""
from __future__ import annotations

from typing import Iterable

from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser


class HtmlParser:
    name = "html"
    mime_types = ("text/html", "application/xhtml+xml")
    extensions = ("html", "htm", "xhtml")

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        raw = doc.content.decode("utf-8", errors="replace")

        title: str | None = None
        text: str | None = None

        try:
            import trafilatura  # type: ignore
            extracted = trafilatura.extract(
                raw,
                include_tables=True,
                include_links=False,
                favor_recall=True,
            )
            if extracted and extracted.strip():
                text = extracted
                meta = trafilatura.extract_metadata(raw)
                if meta and meta.title:
                    title = meta.title
        except Exception:
            text = None

        if not text:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            text = soup.get_text("\n", strip=True)

        if text and text.strip():
            yield Block(text=text, section=title)


register_parser(HtmlParser())
