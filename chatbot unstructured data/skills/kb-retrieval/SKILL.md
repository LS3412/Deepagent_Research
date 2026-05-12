---
name: kb-retrieval
description: >
  Use this skill for ANY factual question, lookup, or "tell me about X" request
  that requires searching documents. This is the PRIMARY skill for most questions.
  Trigger words: what, how, when, where, who, explain, describe, list, find,
  show, give me, tell me, summarize. Do NOT use for pure formatting tasks.
allowed-tools: hybrid_search, list_documents, get_chunk
---

# KB Retrieval Skill

## When to use
Activate for ANY question requiring a factual answer from indexed documents.
This is the default skill for most user queries.

## Critical rule: score-based relevance
`hybrid_search` returns `"NO_RELEVANT_RESULTS"` (a string) when all retrieved
chunks scored below the relevance threshold. If you receive this signal:
- Do NOT use the results to answer.
- Do NOT fall back to training knowledge.
- Use the **not-found** reply template immediately.

## Retrieval workflow

### Step 1 — Understand the question scope
- Is the question about a specific file? → pass `filters={"file_name": "..."}`
- Is it about tabular data? → also activate the `table-qa` skill.
- Is it a step-by-step procedure? → also activate the `procedure-qa` skill.
- Is it a comparison? → also activate the `comparison` skill.

### Step 2 — Decompose into sub-queries
Break complex questions into 1–3 focused sub-queries:
- User: "What are the installation steps and system requirements?" →
  Query A: `"installation steps"` | Query B: `"system requirements"`

### Step 3 — Search with filters
```
hybrid_search(query, k=6, filters=None)
```
Filters to use when context is known:
- Specific file → `{"file_name": "manual.pdf"}`
- Format → `{"format": "csv"}` or `{"format": "pdf"}`
- Page range → `{"page_range": [5, 10]}`
- Language → `{"language": "en"}`

### Step 4 — Handle the result

**If result is `"NO_RELEVANT_RESULTS"` or an empty list:**
```
Call list_documents() to get current file list.
Respond: "I'm sorry, but the knowledge base does not contain information
about [topic]. The currently indexed documents are: [list files].
If this topic is covered in a document not yet indexed, please upload it."
Stop — do not try again with world knowledge.
```

**If results are returned but clearly off-topic** (e.g., user asked about
astronomy, results are about batteries):
```
Treat as NO_RELEVANT_RESULTS. Use the not-found reply above.
```

**If results are relevant:** Continue to compose the answer.

### Step 5 — Expand context if needed
If a hit appears truncated, fetch adjacent chunks:
```
get_chunk(doc_sha256, chunk_index - 1)
get_chunk(doc_sha256, chunk_index + 1)
```
Maximum 4 expansion calls per turn.

### Step 6 — Compose the answer
- Use ONLY text from retrieved chunks. No training knowledge.
- Apply `citation-style` skill rules for formatting.
- If results only partially cover the question, say so explicitly.
