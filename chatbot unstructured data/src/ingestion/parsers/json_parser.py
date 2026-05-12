"""JSON / JSONL parser — flattens nested objects to readable text blocks."""
from __future__ import annotations

import json
from typing import Any, Iterable

from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser


def _flatten(obj: Any, prefix: str = "") -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            yield from _flatten(v, key)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}[{i}]"
            yield from _flatten(v, key)
    else:
        yield f"{prefix}: {obj}"


class JsonParser:
    name = "json"
    mime_types = ("application/json", "application/x-ndjson")
    extensions = ("json", "jsonl", "ndjson")

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        text = doc.content.decode("utf-8", errors="replace")
        # Try JSONL first if multiple lines and any line is a valid JSON object
        lines = [ln for ln in text.splitlines() if ln.strip()]
        is_jsonl = False
        if len(lines) > 1:
            try:
                json.loads(lines[0])
                json.loads(lines[-1])
                is_jsonl = True
            except Exception:
                is_jsonl = False

        if is_jsonl:
            for i, ln in enumerate(lines):
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                body = "\n".join(_flatten(obj))
                if body.strip():
                    yield Block(text=body, section=f"record[{i}]")
            return

        try:
            obj = json.loads(text)
        except Exception:
            if text.strip():
                yield Block(text=text)
            return

        if isinstance(obj, list):
            for i, item in enumerate(obj):
                body = "\n".join(_flatten(item))
                if body.strip():
                    yield Block(text=body, section=f"record[{i}]")
        else:
            body = "\n".join(_flatten(obj))
            if body.strip():
                yield Block(text=body)


register_parser(JsonParser())
