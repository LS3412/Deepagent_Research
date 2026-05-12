"""Sub-agent definitions passed to `create_deep_agent(subagents=...)`."""
from __future__ import annotations

from typing import Any

from src.agent.prompts import RESEARCHER_PROMPT, VERIFIER_PROMPT, WRITER_PROMPT
from src.agent.tools import make_tools


def build_subagents(tenant_id: str) -> list[dict[str, Any]]:
    tools = make_tools(tenant_id)
    by_name = {t.name: t for t in tools}

    return [
        {
            "name": "researcher",
            "description": (
                "Searches the knowledge base. Use for any task that requires "
                "looking up information from indexed documents. Saves results "
                "to /retrieved/<hash>.json and returns the path."
            ),
            "system_prompt": RESEARCHER_PROMPT,
            "tools": [
                by_name["hybrid_search"],
                by_name["list_documents"],
                by_name["get_chunk"],
            ],
        },
        {
            "name": "writer",
            "description": (
                "Composes the final cited answer from a /retrieved/*.json file. "
                "Use after the researcher has saved hits."
            ),
            "system_prompt": WRITER_PROMPT,
            "tools": [],  # filesystem tools come from the harness
        },
        {
            "name": "verifier",
            "description": (
                "Checks a draft answer against retrieved hits and reports "
                "missing citations or unsupported claims as JSON."
            ),
            "system_prompt": VERIFIER_PROMPT,
            "tools": [by_name["get_chunk"]],
        },
    ]
