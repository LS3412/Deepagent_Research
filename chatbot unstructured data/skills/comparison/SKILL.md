---
name: comparison
description: >
  Use this skill when the question asks to compare, contrast, or find
  differences and similarities between two or more items, documents,
  specifications, versions, or options.
  Trigger words: compare, vs, versus, difference between, similarities,
  better than, which is, pros and cons, advantages, disadvantages,
  contrast, how does X differ from Y.
allowed-tools: hybrid_search, get_chunk
---

# Comparison Skill

## When to use
Activate when the question requires placing two or more things side-by-side
to highlight their differences, similarities, or relative merits.

## Step 1 — Identify comparison targets
Extract the items being compared:
- "Compare A and B" → targets: A, B
- "Difference between X, Y, Z" → targets: X, Y, Z
- "Which is better: P or Q?" → targets: P, Q

## Step 2 — Search for each target separately
Run one `hybrid_search` per comparison target to gather evidence for each side:
```python
hybrid_search("[item A] specifications features", k=6)
hybrid_search("[item B] specifications features", k=6)
```
If a specific file is known for each item, add `file_name` filters.

## Step 3 — Expand context if needed
Use `get_chunk(doc_sha256, chunk_index ± 1)` to get surrounding context
when a relevant hit appears truncated.

## Step 4 — Present the comparison

**For 2 items — use a Markdown table:**
```markdown
| Attribute       | Item A [source]     | Item B [source]     |
|-----------------|---------------------|---------------------|
| Attribute 1     | value               | value               |
| Attribute 2     | value               | value               |
| Attribute 3     | value               | value               |

**Sources**
- doc_a.pdf (p.X)
- doc_b.pdf (p.Y)
```

**For 3+ items — use a multi-column table** with one column per item.

**For pros/cons questions:**
```markdown
**[Item A]**
- ✅ Pro: ...
- ❌ Con: ...

**[Item B]**
- ✅ Pro: ...
- ❌ Con: ...
```

## Step 5 — Handle asymmetric information
If the KB has information on one item but not another:
> "The knowledge base contains details on [Item A] [source], but no
> indexed documents cover [Item B]. The comparison below is partial."

Never invent attributes for the missing side.

## Step 6 — Cite every cell
Each value in the comparison table must have its own inline citation.
If the same source covers multiple rows, cite it on each row.
