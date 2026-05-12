I'll create a complete, step-by-step explanation of the entire DeepAgents pipeline:

---

## **COMPLETE DEEPAGENTS PIPELINE — Simple Explanation**

### **PHASE 0: SETUP (Before Any Question)**

```
1. Agent Initialization (build_agent)
   ├─ Load PROMPTS (4 system instructions)
   │  ├─ MAIN_PROMPT (for main agent)
   │  ├─ RESEARCHER_PROMPT (for researcher)
   │  ├─ WRITER_PROMPT (for writer)
   │  └─ VERIFIER_PROMPT (for verifier)
   │
   ├─ Create SUB-AGENTS (3 specialists)
   │  ├─ Researcher (with tools: search, list, get_chunk)
   │  ├─ Writer (with tools: read files)
   │  └─ Verifier (with tools: get_chunk)
   │
   ├─ Load SKILLS (reference materials)
   │  ├─ /skills/citation-style/SKILL.md
   │  ├─ /skills/kb-retrieval/SKILL.md
   │  └─ /skills/table-qa/SKILL.md
   │
   └─ Load MEMORY
      └─ /memory/AGENTS.md (reference) + any learned facts

2. Create Checkpointer (for state persistence)
   └─ Remembers conversation across turns

RESULT: Ready-to-use agent system ✓
```

---

### **PHASE 1: USER ASKS QUESTION**

```
Streamlit UI:
  You type: "What embedding model does this system use?"
            ↓
  Saved to session state
            ↓
  Sent to agent
```

---

### **PHASE 2: AGENT INITIALIZATION (Per Turn)**

```
Agent wakes up and loads:

1. StateBackend (virtual filesystem)
   ├─ /skills/citation-style/SKILL.md → Available to read
   ├─ /skills/kb-retrieval/SKILL.md → Available to read
   ├─ /skills/table-qa/SKILL.md → Available to read
   └─ /memory/AGENTS.md → Available to read

2. Checkpointer (conversation history)
   └─ Loads ALL prior messages from this session

3. System Prompt
   └─ MAIN_PROMPT tells agent: "Always search first!"

RESULT: Agent ready with full context ✓
```

---

### **PHASE 3: AGENT DECIDES (MAIN AGENT THINKING)**

```
Main Agent reads MAIN_PROMPT:
  "PRIME DIRECTIVE: ALWAYS call hybrid_search IMMEDIATELY"
  
Main Agent thinks:
  "Is this a factual question?" → YES
  "Must I search?" → YES
  "Simple or complex?" 
    ├─ Simple Q? → I'll search directly
    └─ Complex Q? → Send to specialists

Your Q: "What embedding model does this use?"
Decision: SIMPLE → Search directly OR send to Researcher

(In this flow, let's say: Send to Researcher for thorough search)
```

---

### **PHASE 4: RESEARCHER SUB-AGENT SEARCHES** 🔬

```
Researcher receives task:
  Query: "What embedding model does this system use?"
  
Researcher reads RESEARCHER_PROMPT:
  "Break into sub-queries"
  "Search thoroughly"
  "Expand context if needed"

Researcher reads SKILL:
  /skills/kb-retrieval/SKILL.md
  Learns: Step-by-step workflow for retrieval
  
Researcher ACTION:
  1. Decompose query: "embedding model"
  
  2. Search using tools:
     hybrid_search("embedding model", k=6)
     ↓
     Weaviate returns 6 hits:
     [
       {"text": "Uses bge-m3...", "file": "sample.md", "page": 12, "score": 0.87},
       {"text": "1024-dimensional...", "file": "sample.md", "page": 12, "score": 0.85},
       ...more hits
     ]
  
  3. Save to /retrieved/abc123.json
     (virtual file in StateBackend, will persist to disk)
  
  4. Report back: "Found 6 relevant chunks about embedding model"
```

---

### **PHASE 5: WRITER SUB-AGENT COMPOSES** ✍️

```
Writer receives task:
  Path: /retrieved/abc123.json
  
Writer reads WRITER_PROMPT:
  "Read retrieved chunks"
  "Compose clean answer"
  "Add citations"
  "Include Sources section"

Writer reads SKILL:
  /skills/citation-style/SKILL.md
  Learns: Citation format [file p.X], [file §Section]
  Learns: How to format Sources section
  
Writer ACTION:
  1. Load /retrieved/abc123.json
     Reads all 6 chunks
  
  2. Plan answer structure
     "Single fact → one paragraph"
  
  3. Write answer:
     "The system uses **bge-m3** for embeddings [sample.md p.12],
      producing 1024-dimensional vectors [sample.md p.12]."
  
  4. Add Sources section:
     **Sources**
     - sample.md p.12
  
  5. Save draft to /drafts/answer.md
     (virtual file in StateBackend)
  
  6. Return draft to main agent
```

---

### **PHASE 6: VERIFIER SUB-AGENT CHECKS** ✅

```
Verifier receives task:
  Draft: /drafts/answer.md
  Evidence: /retrieved/abc123.json
  
Verifier reads VERIFIER_PROMPT:
  "Check every claim is cited"
  "Verify citations match chunks"
  "Find hallucinated facts"

Verifier ACTION:
  1. Load /drafts/answer.md
  
  2. Extract claims:
     - "System uses bge-m3" [sample.md p.12]
     - "1024-dimensional vectors" [sample.md p.12]
  
  3. Verify each claim:
     Check /retrieved/abc123.json
     ✅ Claim 1: SUPPORTED (found in chunk)
     ✅ Claim 2: SUPPORTED (found in chunk)
  
  4. Check for missing citations:
     All claims have citations ✓
  
  5. Return VERDICT:
     {
       "grounded": true,
       "verdict": "PASS",
       "issues": []
     }
```

---

### **PHASE 7: MAIN AGENT RECEIVES RESULT**

```
Verifier says: "PASS ✓"

Main Agent receives:
  - Draft answer
  - Verification result
  - Hits from researcher
  
Main Agent thinks:
  "Verified ✓"
  "All claims cited ✓"
  "No hallucinations ✓"
  "Ready to send to user"
```

---

### **PHASE 8: STREAM TO UI**

```
In real-time, user sees trace:

🤖 [Agent] reasoning
  > I should search for embedding model information

🛠 Tool called: hybrid_search
  Args: {"query": "embedding model", "k": 6}

📦 Tool result: 6 hits found
  Chunks about bge-m3, dimensions, etc.

🔬 [Researcher] reasoning
  > Found relevant chunks, saving to /retrieved/

✍️ [Writer] reasoning
  > Composing answer with proper citations

✅ [Verifier] reasoning
  > All claims are grounded and cited

─────────────────────────────────

FINAL ANSWER (appears in chat):

The system uses **bge-m3** for embeddings [sample.md p.12],
producing 1024-dimensional vectors [sample.md p.12].

**Sources**
- sample.md p.12
```

---

### **PHASE 9: SAVE TO MEMORY & HISTORY**

```
Answer delivered. Now save:

1. Checkpointer saves state:
   └─ Adds to message chain for next turn

2. SQLite saves chat history:
   └─ Session ID → all messages

3. /memory/ folder gets updated:
   └─ Agent can write learned facts here

4. StateBackend saves:
   └─ /retrieved/abc123.json → disk
   └─ /drafts/answer.md → disk (if needed)

RESULT: Memory persisted ✓
```

---

### **PHASE 10: NEXT TURN (Follow-up Question)**

```
You ask: "What vector size does bge-m3 produce?"

Agent wakes up:
  ├─ Loads checkpointer → Sees prior conversation
  ├─ Loads /memory/ → Recalls "embedding_model=bge-m3"
  ├─ Loads StateBackend → Skills still available
  └─ Ready to answer

Agent thinks:
  "I already know it's bge-m3"
  "But I must search for vector size confirmation"
  
Searches: "bge-m3 vector dimensions"
Results: "1024-dimensional"

Answer: "bge-m3 produces 1024-dimensional vectors [sample.md p.12]"

Memory updated with: "bge-m3_vectors=1024"
```

---

## **COMPLETE PIPELINE IN ONE IMAGE**

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER ASKS QUESTION                           │
│           (Streamlit UI) → Message sent to agent                │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                   AGENT INITIALIZATION                          │
│  ├─ Load 4 PROMPTS (instructions for each agent)               │
│  ├─ Load 3 SUB-AGENTS with their tools                        │
│  ├─ Load SKILLS (reference materials)                         │
│  ├─ Load MEMORY (from /memory/ folder)                        │
│  └─ Load Checkpointer (prior conversation)                    │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│            MAIN AGENT DECIDES (reads MAIN_PROMPT)              │
│                                                                │
│  "Is this factual?" → YES                                     │
│  "Must search?" → ALWAYS                                      │
│  "Delegate to specialists?" → MAYBE                           │
│                                                                │
│  ├─ Simple Q? → Search directly with tools                    │
│  └─ Complex Q? → Send to specialists                          │
└────────────────┬───────────────────────────┬────────────────────┘
                 │                           │
          [Direct Path]              [Specialist Path]
                 │                           │
        Use tools:              Send to RESEARCHER 🔬:
        hybrid_search           ├─ Read RESEARCHER_PROMPT
        list_documents          ├─ Read /skills/kb-retrieval
        get_chunk              ├─ Search thoroughly
                 │              ├─ Save to /retrieved/*.json
                 │              └─ Return "Found N chunks"
                 │                       ↓
                 │              Send to WRITER ✍️:
                 │              ├─ Read WRITER_PROMPT
                 │              ├─ Read /skills/citation-style
                 │              ├─ Compose answer
                 │              ├─ Add [citations]
                 │              ├─ Save to /drafts/answer.md
                 │              └─ Return draft
                 │                       ↓
                 │              Send to VERIFIER ✅:
                 │              ├─ Read VERIFIER_PROMPT
                 │              ├─ Check every claim
                 │              ├─ Verify citations match
                 │              └─ Return "PASS" or "FAIL"
                 │                       ↓
                 ├──────────────┴────────────────────┤
                                                      ↓
                        ┌──────────────────────────────────────┐
                        │   MAIN AGENT RECEIVES RESULT         │
                        │   • Draft answer                     │
                        │   • Verification: PASS/FAIL          │
                        │   • Retrieved chunks                 │
                        └────────────┬─────────────────────────┘
                                     ↓
                        ┌──────────────────────────────────────┐
                        │   STREAM TO STREAMLIT UI             │
                        │   Real-time trace of all steps       │
                        │   Final answer appears in chat       │
                        └────────────┬─────────────────────────┘
                                     ↓
                        ┌──────────────────────────────────────┐
                        │   SAVE TO PERSISTENT STORAGE         │
                        │   ├─ Checkpointer (state)            │
                        │   ├─ SQLite (chat history)           │
                        │   ├─ /memory/ (learned facts)        │
                        │   └─ /retrieved/ & /drafts/          │
                        └────────────┬─────────────────────────┘
                                     ↓
                        ┌──────────────────────────────────────┐
                        │   READY FOR NEXT TURN                │
                        │   (Conversation continues)           │
                        └──────────────────────────────────────┘
```

---

## **KEY FLOWS IN ONE TABLE**

| Phase | What Happens | Storage | Output |
|-------|--------------|---------|--------|
| **Setup** | Build agents, load skills, create checkpointer | In-memory + /skills/ + /memory/ | Ready agent system |
| **Initialize** | Load StateBackend, prompt, prior context | Checkpointer + StateBackend | Agent ready |
| **Decide** | Main agent reads prompt, chooses path | N/A | Route: direct or delegate |
| **Search** | Researcher searches, saves results | /retrieved/*.json | Chunks found |
| **Compose** | Writer reads chunks, writes answer | /drafts/answer.md | Draft answer |
| **Verify** | Verifier checks claims against chunks | N/A | PASS/FAIL verdict |
| **Return** | Main agent approves, sends to user | N/A | Final answer |
| **Persist** | Save chat, memory, state | Checkpointer + SQLite + /memory/ | State saved |

---

## **WHAT HAPPENS TO DATA**

```
EPHEMERAL (Lost on restart):
├─ StateBackend virtual FS
├─ Checkpointer memory (in-memory)
└─ /drafts/ and /retrieved/ (temporary)

PERSISTENT (Survives restart):
├─ chat_history.db (SQLite) ← All messages
├─ /memory/ folder ← Learned facts
└─ Weaviate ← Indexed documents
```

---

## **SUMMARY IN 10 STEPS**

1. **User asks** → Message goes to agent
2. **Agent initializes** → Loads prompts, skills, memory, checkpointer
3. **Main agent decides** → "Search? Delegate?"
4. **Researcher searches** → Finds chunks, saves to /retrieved/
5. **Writer composes** → Reads chunks, writes answer, cites sources, saves to /drafts/
6. **Verifier checks** → Validates all claims are cited and accurate
7. **Main agent approves** → Gets PASS verdict
8. **Stream to UI** → Real-time trace + final answer in chat
9. **Save everywhere** → Checkpointer, SQLite, /memory/, StateBackend
10. **Ready for next turn** → Conversation continues with context

**That's the complete DeepAgents pipeline!** 🎯