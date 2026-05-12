"""Ollama-backed embedders: synchronous batch and async concurrent (v2)."""
from __future__ import annotations

import asyncio
import logging

from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings
from src.llm import get_embeddings

log = logging.getLogger(__name__)


class OllamaBatchEmbedder:
    def __init__(self, batch_size: int | None = None) -> None:
        s = get_settings()
        self.batch_size = batch_size or s.embed_batch_size
        self._client = get_embeddings()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._embed_batch(texts[i : i + self.batch_size]))
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Async concurrent embedder  (v2) — ~3-4x faster on large documents
# ─────────────────────────────────────────────────────────────────────────────

class AsyncOllamaBatchEmbedder:
    """Concurrent Ollama embedder using asyncio.gather.

    Splits texts into batches and fires up to *max_concurrent* requests at once.
    Falls back to sequential OllamaBatchEmbedder if aembed_documents is unavailable.
    """

    def __init__(
        self,
        batch_size: int | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        s = get_settings()
        self.batch_size     = batch_size     or s.embed_batch_size
        self.max_concurrent = max_concurrent or s.embed_max_concurrent_batches
        self._client        = get_embeddings()
        self._has_async: bool | None = None

    def _check_async(self) -> bool:
        if self._has_async is None:
            self._has_async = hasattr(self._client, "aembed_documents")
            if not self._has_async:
                log.warning(
                    "Embedding client does not support aembed_documents \u2014 "
                    "falling back to sequential embedding"
                )
        return self._has_async

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    async def _embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)

    async def _embed_all_async(self, texts: list[str]) -> list[list[float]]:
        batches = [
            texts[i : i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]
        sem = asyncio.Semaphore(self.max_concurrent)

        async def _bounded(batch: list[str]) -> list[list[float]]:
            async with sem:
                for attempt in range(3):
                    try:
                        return await self._embed_batch_async(batch)
                    except Exception as exc:
                        if attempt == 2:
                            raise
                        wait = 2 ** attempt
                        log.debug("embed retry %d after %ss: %s", attempt + 1, wait, exc)
                        await asyncio.sleep(wait)
                return []  # unreachable

        results: list[list[list[float]]] = await asyncio.gather(
            *[_bounded(b) for b in batches]
        )
        out: list[list[float]] = []
        for r in results:
            out.extend(r)
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* using concurrent async batches where supported."""
        if not texts:
            return []
        if not self._check_async():
            # Graceful sync fallback
            out: list[list[float]] = []
            for i in range(0, len(texts), self.batch_size):
                out.extend(self._embed_batch_sync(texts[i : i + self.batch_size]))
            return out

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an event loop (e.g. Jupyter / Streamlit async context)
                import nest_asyncio  # type: ignore
                nest_asyncio.apply()
            return loop.run_until_complete(self._embed_all_async(texts))
        except ImportError:
            # nest_asyncio not installed; fall back to a fresh event loop
            return asyncio.run(self._embed_all_async(texts))
        except Exception as exc:
            log.warning("async embed failed (%s) \u2014 falling back to sync", exc)
            out = []
            for i in range(0, len(texts), self.batch_size):
                out.extend(self._embed_batch_sync(texts[i : i + self.batch_size]))
            return out

