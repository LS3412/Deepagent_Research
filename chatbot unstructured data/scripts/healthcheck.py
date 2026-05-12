"""Pings every external dependency.

Usage:  python scripts/healthcheck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check_ollama() -> tuple[bool, str]:
    try:
        import httpx
        from src.config import get_settings
        s = get_settings()
        r = httpx.get(f"{s.ollama_base_url}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        have_chat = any(n.startswith(s.ollama_chat_model.split(":")[0]) for n in names)
        have_embed = any(n.startswith(s.ollama_embed_model.split(":")[0]) for n in names)
        msg = (
            f"Ollama OK ({len(names)} models). "
            f"chat={'✓' if have_chat else '✗'} "
            f"embed={'✓' if have_embed else '✗'}"
        )
        return (have_chat and have_embed, msg)
    except Exception as e:
        return False, f"Ollama FAIL: {e}"


def check_weaviate() -> tuple[bool, str]:
    try:
        from src.retrieval.weaviate_client import ensure_schema, get_client
        c = get_client()
        ready = c.is_ready()
        if ready:
            ensure_schema()
            from src.config import get_settings
            return True, f"Weaviate OK (collection={get_settings().weaviate_collection} ensured)"
        return False, "Weaviate FAIL: not ready"
    except Exception as e:
        return False, f"Weaviate FAIL: {e}"


def check_embed_call() -> tuple[bool, str]:
    try:
        from src.llm import get_embeddings
        v = get_embeddings().embed_query("hello world")
        return (len(v) > 0, f"Embed call OK (dim={len(v)})")
    except Exception as e:
        return False, f"Embed call FAIL: {e}"


def check_langfuse() -> tuple[bool, str]:
    try:
        from src.config import get_settings
        s = get_settings()
        if not s.langfuse_enabled:
            return True, "Langfuse disabled (skip)"
        import httpx
        r = httpx.get(f"{s.langfuse_host}/api/public/health", timeout=5)
        r.raise_for_status()
        return True, "Langfuse OK"
    except Exception as e:
        return False, f"Langfuse FAIL: {e}"


def main() -> int:
    checks = [
        ("Ollama daemon + models", check_ollama),
        ("Weaviate connection + schema", check_weaviate),
        ("Embedding call (bge-m3)", check_embed_call),
        ("Langfuse (optional)", check_langfuse),
    ]
    all_ok = True
    for label, fn in checks:
        ok, msg = fn()
        print(f"[{'OK' if ok else 'FAIL'}] {label:<35} {msg}")
        all_ok = all_ok and ok
    try:
        from src.retrieval.weaviate_client import close_client
        close_client()
    except Exception:
        pass
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
