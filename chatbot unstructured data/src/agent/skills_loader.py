"""Load skill and memory files from disk for the Deep Agents StateBackend.

StateBackend is in-memory: the actual file bytes must be seeded on every
`agent.invoke(files={...})` call.  This module provides:
  - `load_agent_files()` → files dict ready for inject
  - `skill_virtual_paths()` → list of virtual dirs to pass as `skills=`
  - `memory_virtual_paths()` → list of virtual paths to pass as `memory=`
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = _ROOT / "skills"
MEMORY_DIR = _ROOT / "memory"


def _file_data(text: str) -> Any:
    try:
        from deepagents.backends.utils import create_file_data  # type: ignore
        return create_file_data(text)
    except Exception:
        # Fallback: plain dict that deepagents may also accept.
        return {"content": text, "encoding": "utf-8"}


def load_agent_files() -> dict[str, Any]:
    """Return a {virtual_path: file_data} dict seeding skills + memory."""
    files: dict[str, Any] = {}

    # Skills — every file under skills/**
    if SKILLS_DIR.exists():
        for p in sorted(SKILLS_DIR.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(_ROOT)
            virtual = "/" + rel.as_posix()
            try:
                files[virtual] = _file_data(p.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("skill load failed %s: %s", p, e)

    # Memory — every .md file under memory/
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.glob("*.md")):
            if not p.is_file():
                continue
            rel = p.relative_to(_ROOT)
            virtual = "/" + rel.as_posix()
            try:
                files[virtual] = _file_data(p.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("memory load failed %s: %s", p, e)

    log.info(
        "agent files: %d skill entries, %d memory entries",
        sum(1 for k in files if k.startswith("/skills")),
        sum(1 for k in files if k.startswith("/memory")),
    )
    return files


def skill_virtual_paths() -> list[str]:
    """Virtual directory paths for `create_deep_agent(skills=...)`."""
    if not SKILLS_DIR.exists():
        return []
    dirs = [
        d for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ]
    return ["/skills/"] if dirs else []


def memory_virtual_paths() -> list[str]:
    """Virtual file paths for `create_deep_agent(memory=...)`."""
    if not MEMORY_DIR.exists():
        return []
    return [
        "/memory/" + p.name
        for p in MEMORY_DIR.glob("*.md")
        if p.is_file()
    ]
