---
name: citation-style
description: >
  Use ONLY at the final answer-writing step to format inline citations and the
  Sources section. Do NOT use this skill to decide what to search or whether
  the KB contains an answer. Trigger: you are about to write the user-facing
  answer and need citation and formatting rules.
---

# Citation Style Skill

## When to use
Activate this skill only when you are composing the final answer for the user.
Never use it to guide retrieval or decide if a topic is in the KB.

## Inline citation format

Place citations **immediately after** the sentence or clause they support.

| Situation | Format |
|---|---|
| Chunk has a page number | `[file_name p.<page>]` |
| Chunk has a section but no page | `[file_name §<section>]` |
| Neither page nor section available | `[file_name]` |

Examples:
- "The system uses bge-m3 for embeddings [sample.md §Architecture]."
- "Installation requires Python 3.10+ [setup.pdf p.3]."
- "Multiple sources for one claim [doc1.pdf p.7][doc2.md §Config]."

### Uncertainty
If a retrieved chunk is ambiguous, add `(paraphrased)` after the citation:
`"The timeout defaults to 30 minutes [config.md p.5] (paraphrased)."`

## Sources section (mandatory)
End every factual answer with a **Sources** section:

```
**Sources**
- file_name.pdf (p.3, p.7)
- manual.docx (§Installation)
- report.md
```

One line per unique file. List all pages/sections cited from that file.

## Answer format rules
- Concise: answer the question directly, no preamble.
- Use bullet lists for multiple items; numbered lists when order matters.
- Use Markdown tables when the answer has 2+ columns.
- Use `## Sub-heading` for each part of a multi-part question.
- No padding phrases like "Based on the documents..." — just state and cite.
- Maximum 3 verbatim sentences from any single chunk; paraphrase the rest.
- For summaries: at most 5 bullet points per document.
