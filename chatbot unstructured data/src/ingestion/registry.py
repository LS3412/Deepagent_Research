"""MIME / extension → Parser registry.

Adding a new format = write a Parser, then call `register_parser(MyParser())`
(or just import the parser module — each parser self-registers at import time).
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from src.ingestion.interfaces import Parser

_PARSERS: list[Parser] = []
_BY_NAME: dict[str, Parser] = {}


def register_parser(parser: Parser) -> None:
    if parser.name in _BY_NAME:
        return
    _PARSERS.append(parser)
    _BY_NAME[parser.name] = parser


def all_parsers() -> list[Parser]:
    return list(_PARSERS)


def get_parser(name: str) -> Parser | None:
    return _BY_NAME.get(name)


def detect_mime(path_or_name: str) -> str:
    mt, _ = mimetypes.guess_type(path_or_name)
    return mt or "application/octet-stream"


def select_parser(
    file_name: str,
    mime_type: str | None = None,
    parser_hint: str | None = None,
) -> Parser:
    """Pick a parser by hint > extension > MIME."""
    if parser_hint:
        p = _BY_NAME.get(parser_hint)
        if p:
            return p

    ext = Path(file_name).suffix.lower().lstrip(".")
    mime = (mime_type or detect_mime(file_name)).lower()

    for p in _PARSERS:
        if ext and ext in p.extensions:
            return p
    for p in _PARSERS:
        if mime in p.mime_types:
            return p
    # Fallback: plain text parser handles everything text-like
    text = _BY_NAME.get("text")
    if text:
        return text
    raise ValueError(f"No parser registered for file_name={file_name!r} mime={mime!r}")


def load_builtin_parsers() -> None:
    """Trigger import of all built-in parser modules so they self-register."""
    # Import order doesn't matter; just need each to run register_parser().
    from src.ingestion.parsers import (  # noqa: F401
        text_parser,
        markdown_parser,
        html_parser,
        json_parser,
        csv_parser,
        pdf_parser,
        docx_parser,
    )
    # v2: universal Unstructured parser (self-registers, gracefully absent)
    try:
        from src.ingestion.parsers import unstructured_parser  # noqa: F401
    except ImportError:
        pass  # unstructured not installed — legacy parsers above still work
