---
name: table-qa
description: >
  Use this skill ONLY when the question involves numbers, statistics,
  measurements, comparisons of numeric values, spreadsheets, CSV files,
  or tabular data. Trigger words: how many, total, average, maximum, minimum,
  count, percentage, compare values, highest, lowest, across rows/columns.
  Do NOT use for general text questions.
allowed-tools: hybrid_search, get_chunk
---

# Table & Structured Data Q&A Skill

## When to use
Activate when the answer requires reading rows, columns, numeric data, or
any structured data from CSV, JSON, or table sections in PDF/DOCX.

## Step 1 — Classify the data question
- **Lookup**: "What is the value of X for Y?" → single cell retrieval
- **Comparison**: "Which has the highest X?" → multiple rows needed
- **Aggregation**: "Total / average of X?" → all rows of a column needed
- **Time-series**: "How did X change over time?" → date + value columns

## Step 2 — Target structured formats first
```python
hybrid_search(query, filters={"format": "csv"})   # CSV/spreadsheet first
hybrid_search(query, filters={"format": "json"})  # structured JSON
hybrid_search(query, filters={"format": "pdf"})   # tables embedded in PDF
```

## Step 3 — Expand to recover full table
Tables are often split across chunks. After finding a hit:
1. Note `doc_sha256` and `chunk_index`.
2. Fetch `get_chunk(doc_sha256, chunk_index - 1)` — for headers.
3. Fetch `get_chunk(doc_sha256, chunk_index + 1)` — for continuation rows.
4. Combine to reconstruct the full relevant portion of the table.

## Step 4 — Present structured answers
- Recreate relevant rows as a **Markdown table** when 2+ columns are involved.
- For single-value lookups: state the value directly with citation.
- For aggregations: show your computation from retrieved rows.
- Never invent or estimate values not present in the retrieved chunks.

## Step 5 — Cite structured data
```
[data.csv §row[42]]
[report.pdf §Table 3 p.12]
[metrics.json p.2]
```

## Step 6 — When no structured data found
If structured format searches return `"NO_RELEVANT_RESULTS"`, try a plain
text search before declaring not found. If still nothing, use the standard
not-found reply — do not estimate or fabricate numbers.
