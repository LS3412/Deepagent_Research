"""Chat + embedding model factories (Ollama or GitHub Models)."""
from __future__ import annotations

import logging
from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings

from src.config import get_settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOllama:
    s = get_settings()
    if s.use_github_models:
        return _make_github_chat_model(s)
    log.info(
        "chat model: Ollama  model=%s  base_url=%s",
        s.ollama_chat_model, s.ollama_base_url,
    )
    return ChatOllama(
        model=s.ollama_chat_model,
        base_url=s.ollama_base_url,
        temperature=0.1,
        # Keep model loaded between calls; speeds up agent loops a lot.
        keep_alive="30m",
    )


def _make_github_chat_model(s):  # type: ignore[no-untyped-def]
    """Return a ChatOpenAI pointed at the GitHub Models inference endpoint."""
    try:
        import truststore  # type: ignore
        truststore.inject_into_ssl()
        log.debug("truststore SSL injection OK")
    except ImportError:
        log.debug("truststore not installed — skipping SSL injection")

    from langchain_openai import ChatOpenAI  # type: ignore
    log.info(
        "chat model: GitHub Models  model=%s  endpoint=%s",
        s.github_model, s.github_models_endpoint,
    )
    return ChatOpenAI(
        model=s.github_model,
        base_url=s.github_models_endpoint,
        api_key=s.github_token,
        temperature=0.1,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    s = get_settings()
    log.info(
        "embeddings: Ollama  model=%s  base_url=%s",
        s.ollama_embed_model, s.ollama_base_url,
    )
    return OllamaEmbeddings(
        model=s.ollama_embed_model,
        base_url=s.ollama_base_url,
    )
