"""Langfuse v4 tracing — LangChain CallbackHandler integration.

v4 pattern (langfuse >= 3.0.0 / 4.x):
  1. Configure singleton once:  Langfuse(public_key=..., secret_key=..., host=...)
  2. Create handler with NO args:  CallbackHandler()
  3. Flush via singleton:  get_client().flush()

The old v2 pattern (passing keys to CallbackHandler) no longer works.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from src.config import get_settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _init_langfuse_client() -> Any | None:
    """Configure and return the Langfuse singleton, or None if disabled/unavailable."""
    s = get_settings()
    if not s.langfuse_enabled:
        log.info("Langfuse disabled (LANGFUSE_ENABLED=false)")
        return None
    if not s.langfuse_public_key or not s.langfuse_secret_key:
        log.warning("Langfuse enabled but keys are missing — tracing skipped")
        return None
    try:
        from langfuse import Langfuse, get_client  # type: ignore
        # Configure the singleton (host= maps to LANGFUSE_BASE_URL in v4).
        Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
        client = get_client()
        if client.auth_check():
            log.info("Langfuse tracing enabled → %s", s.langfuse_host)
        else:
            log.warning("Langfuse auth_check() failed — check keys and host")
        return client
    except Exception as e:
        log.warning("Langfuse client init failed: %s", e)
        return None


def get_langfuse_handler() -> Any | None:
    """Return a fresh CallbackHandler (v4: no-arg constructor uses the singleton)."""
    client = _init_langfuse_client()
    if client is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler  # type: ignore
        return CallbackHandler()  # v4: inherits config from the singleton
    except Exception as e:
        log.warning("Langfuse CallbackHandler init failed: %s", e)
        return None


def flush_langfuse() -> None:
    """Flush buffered traces. Call after each agent run to ensure delivery."""
    client = _init_langfuse_client()
    if client is None:
        return
    try:
        from langfuse import get_client  # type: ignore
        get_client().flush()
    except Exception as e:
        log.debug("Langfuse flush error: %s", e)


def callbacks_with_langfuse(extra: list | None = None) -> list:
    cbs = list(extra or [])
    h = get_langfuse_handler()
    if h is not None:
        cbs.append(h)
    return cbs
