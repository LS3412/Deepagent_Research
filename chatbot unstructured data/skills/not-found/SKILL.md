---
name: not-found
description: >
  Use this skill ONLY when hybrid_search returns "NO_RELEVANT_RESULTS" or an
  empty list after all search attempts, meaning the topic is not in the KB.
  Trigger: tool returned NO_RELEVANT_RESULTS, empty results, or results are
  completely unrelated to the question. Produces a polite, helpful not-found reply.
---

# Not-Found Reply Skill

## When to use
Activate this skill when:
- `hybrid_search` returns the string `"NO_RELEVANT_RESULTS"`
- `hybrid_search` returns an empty list `[]` after 1–2 attempts
- Search results are returned but are clearly about a completely different topic

## What NOT to do
- Do NOT answer from training knowledge or general world facts
- Do NOT say "While I can't find this in the KB, generally speaking..."
- Do NOT make up plausible-sounding content about the topic
- Do NOT keep searching indefinitely — 2 attempts maximum before using this reply

## How to compose the not-found reply

### Step 1 — Get the current document list
Call `list_documents()` to retrieve the list of indexed files.

### Step 2 — Compose the reply using this exact template

```
I'm sorry, but the knowledge base does not contain information about "[topic]".

The documents currently indexed are:
- [file 1]
- [file 2]
- ...

If you have a document covering this topic, you can upload it using the
sidebar uploader and I will be able to answer from it.
```

### Tone rules
- Polite and helpful — never dismissive
- Brief — 3–5 lines maximum
- Do not explain *why* the topic is not there or speculate
- Do not apologise excessively — one "I'm sorry" is enough
- Suggest the upload option as the clear next step

## Examples

**Good reply:**
> I'm sorry, but the knowledge base does not contain information about "black holes".
> The currently indexed documents cover: battery testing procedures, battery management work instructions.
> If you have a relevant document, please upload it using the sidebar.

**Bad reply (never do this):**
> While the KB doesn't cover this, a black hole is a region in space where gravity is so intense...
> *(This uses world knowledge — forbidden)*
