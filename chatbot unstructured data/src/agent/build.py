"""Single source of truth for building the Deep Agent.

Used by the Streamlit UI, CLI smoke tests, and any future API server.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

from src.agent.prompts import MAIN_PROMPT
from src.agent.skills_loader import memory_virtual_paths, skill_virtual_paths
from src.agent.subagents import build_subagents
from src.agent.tools import make_tools
from src.config import get_settings
from src.llm import get_chat_model

log = logging.getLogger(__name__)

# One checkpointer per process — keeps conversation state across turns.
_checkpointer = MemorySaver()


@lru_cache(maxsize=4)
def build_agent(tenant_id: str | None = None) -> Any:
    s = get_settings()
    tid = tenant_id or s.default_tenant_id

    # GitHub Models has a hard 4 000-token request limit.
    # In slim mode: 1 tool (minimal schema), no subagents, no skills/memory.
    # Ollama has no such constraint so full features are enabled.
    github_mode = s.use_github_models

    main_tools = list(make_tools(tid, slim=github_mode))

    use_skills_memory = not github_mode
    skill_paths = skill_virtual_paths() if use_skills_memory else []
    mem_paths   = memory_virtual_paths() if use_skills_memory else []

    log.info(
        "building agent  tenant=%s  mode=%s  tools=%s  skills=%s  memory=%s  subagents=%s",
        tid,
        "github" if github_mode else "ollama",
        [t.name for t in main_tools],
        skill_paths or "none",
        mem_paths or "none",
        "yes" if not github_mode else "no",
    )

    kwargs: dict[str, Any] = dict(
        model=get_chat_model(),
        tools=main_tools,
        system_prompt=MAIN_PROMPT,
        checkpointer=_checkpointer,
    )
    # Sub-agents add a large `task` tool schema — skip for low-token models.
    if not github_mode:
        kwargs["subagents"] = build_subagents(tid)
    if skill_paths:
        kwargs["skills"] = skill_paths
    if mem_paths:
        kwargs["memory"] = mem_paths

    agent = create_deep_agent(**kwargs)
    log.info("agent ready  tenant=%s", tid)
    return agent
