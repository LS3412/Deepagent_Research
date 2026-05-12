---
name: troubleshooting
description: >
  Use this skill when the user reports an error, problem, failure, or issue
  and needs help diagnosing or resolving it.
  Trigger words: error, issue, problem, not working, fails, broken, wrong,
  unexpected, how to fix, why is, doesn't work, can't, unable to, debug,
  resolve, troubleshoot, warning, exception, fault.
allowed-tools: hybrid_search, get_chunk
---

# Troubleshooting Skill

## When to use
Activate when the user describes something that is broken, failing, or
producing unexpected results, and wants guidance on how to fix it.

## Step 1 — Extract the problem details
Identify from the user's message:
- **Symptom**: what is happening (error message, wrong output, no response)
- **Context**: which component, step, or document is involved
- **Trigger**: what action caused the problem

## Step 2 — Search for the specific error or symptom
```python
hybrid_search("[error message or symptom]", k=8)
hybrid_search("[component] [error keyword] fix solution", k=6)
hybrid_search("[component] troubleshooting known issues", k=6)
```
If the user mentions a specific file or product, add a `file_name` filter.

## Step 3 — Look for related sections
Also search for:
- Prerequisites / requirements that may have been missed
- Warning sections in relevant procedures
- Known limitations or restrictions

## Step 4 — Present the answer

Structure the troubleshooting answer as follows:

```markdown
## Possible Cause
[Explanation of why this happens, from the document] [source.pdf p.X]

## Resolution Steps
1. [Step 1] [source.pdf p.X]
2. [Step 2] [source.pdf p.X]
3. [Step 3] [source.pdf p.X]

## Prevention
[How to avoid this in future, if documented] [source.pdf p.X]

**Sources**
- source.pdf (p.X, p.Y)
```

## Step 5 — Partial information
If the document describes the symptom but not the fix:
> "The knowledge base describes this issue [source], but does not provide
> a resolution procedure. You may need to consult additional documentation."

If no troubleshooting content is found at all, use the **not-found** skill reply.

## Step 6 — Multiple possible causes
If the symptom can have multiple causes (all documented):
- List each cause as a separate numbered section
- Include the resolution for each
- Let the user identify which cause matches their situation
