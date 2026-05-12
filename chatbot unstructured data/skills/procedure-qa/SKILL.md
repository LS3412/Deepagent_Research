---
name: procedure-qa
description: >
  Use this skill when the question asks for steps, instructions, a procedure,
  how-to guide, setup process, or ordered sequence of actions.
  Trigger words: how do I, how to, steps to, procedure for, process to,
  instructions for, configure, install, set up, enable, run, execute, perform.
allowed-tools: hybrid_search, get_chunk
---

# Procedure Q&A Skill

## When to use
Activate when the user wants to know *how* to do something — any ordered
sequence of actions, configuration steps, or operational instructions.

## Step 1 — Identify the procedure scope
- What is the end goal? (e.g., "set up the battery tester", "install the app")
- Is there a specific document or version mentioned? → add a `file_name` filter
- Is there a specific phase/stage? → search for it directly

## Step 2 — Search for procedural content
```python
hybrid_search("steps to <goal>", k=8)
hybrid_search("how to <goal>", k=8)
hybrid_search("<goal> procedure instructions", k=8)
```
Use a higher `k` (8–10) for procedures — they typically span many chunks.

## Step 3 — Reconstruct the full sequence
Procedural steps are often split across multiple chunks. After finding step N:
1. Note `doc_sha256` and `chunk_index`.
2. Fetch `get_chunk(doc_sha256, chunk_index - 1)` and `get_chunk(doc_sha256, chunk_index + 1)`
   to capture steps before and after.
3. Repeat until you have the complete procedure.

## Step 4 — Present the answer

Always present procedures as a **numbered list** in the exact order found in
the document. Never reorder steps based on your own judgment.

```markdown
**[Procedure Name]**

1. [Step 1 text] [source.pdf p.X]
2. [Step 2 text] [source.pdf p.X]
3. [Step 3 text] [source.pdf p.X]

**Notes / Warnings** (if present in the document):
- ⚠️ [Warning text] [source.pdf p.X]

**Sources**
- source.pdf (p.X–Y)
```

## Step 5 — Warnings and prerequisites
If the document contains warnings, cautions, or prerequisites before a step:
- Include them immediately before the relevant step
- Use ⚠️ prefix for warnings, 📋 for prerequisites

## Step 6 — Partial procedures
If only part of the procedure was found, say explicitly:
> "The following steps were found for [phase]. Steps for [other phase] were
> not found in the indexed documents."

Never fill gaps with assumed steps.
