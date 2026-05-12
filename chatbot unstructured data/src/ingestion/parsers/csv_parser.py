"""CSV / TSV parser — emits one block per row with header context."""
from __future__ import annotations

import csv
import io
from typing import Iterable

from src.ingestion.interfaces import Block, Parser, RawDocument
from src.ingestion.registry import register_parser


class CsvParser:
    name = "csv"
    mime_types = ("text/csv", "text/tab-separated-values")
    extensions = ("csv", "tsv")

    def parse(self, doc: RawDocument) -> Iterable[Block]:
        text = doc.content.decode("utf-8", errors="replace")
        delimiter = "\t" if doc.file_name.lower().endswith(".tsv") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return
        header = rows[0]
        for i, row in enumerate(rows[1:], start=1):
            pairs = []
            for h, v in zip(header, row):
                if v is None or v == "":
                    continue
                pairs.append(f"{h}: {v}")
            body = " | ".join(pairs)
            if body.strip():
                yield Block(text=body, section=f"row[{i}]", extra={"row": i})


register_parser(CsvParser())
