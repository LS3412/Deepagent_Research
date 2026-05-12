"""Metadata enrichment chain for the v2 ingestion pipeline.

Four enrichers run sequentially after chunking:

    HierarchyEnricher   → ancestral_headings[], hierarchy_path, breadcrumb, hierarchy_depth
    KeywordEnricher     → keywords[]  (KeyBERT, reuses bge-m3 — no extra model download)
    LanguageEnricher    → language ISO 639-1  (langdetect, 55 languages)
    ConfidenceEnricher  → confidence_score 0.0-1.0  (rule-based, no deps)

All enrichers degrade gracefully when optional libraries are not installed.
Use build_enricher_chain() to get the pre-wired default chain.
"""
from __future__ import annotations

import logging
from typing import Any

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # truststore not installed; SSL uses default verification

from src.ingestion.interfaces import Chunk, RawDocument

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 3a  HierarchyEnricher
# ─────────────────────────────────────────────────────────────────────────────

class HierarchyEnricher:
    """Build full ancestral heading chain from heading_chain_texts set by UnstructuredParser."""

    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        chain_texts: list[str] = chunk.extra.get("heading_chain_texts", [])
        current_section: str = chunk.section or "Untitled"

        ancestral: list[dict[str, Any]] = [
            {"level": i, "text": t} for i, t in enumerate(chain_texts)
        ]
        if not ancestral or ancestral[-1]["text"] != current_section:
            ancestral.append({"level": len(ancestral), "text": current_section})

        hierarchy_path = " > ".join(h["text"] for h in ancestral)
        breadcrumb = " / ".join(h["text"][:20] for h in ancestral)

        chunk.extra["ancestral_headings"] = ancestral
        chunk.extra["hierarchy_path"] = hierarchy_path
        chunk.extra["breadcrumb"] = breadcrumb
        chunk.extra["hierarchy_depth"] = max(len(ancestral) - 1, 0)
        return chunk


# ─────────────────────────────────────────────────────────────────────────────
# 3b  KeywordEnricher
# ─────────────────────────────────────────────────────────────────────────────

class _OllamaKeyBERTBackend:
    """KeyBERT-compatible backend that calls the local Ollama embedding API.

    Uses the same bge-m3 model that is already running in Ollama — no HF
    download required, no SSL issues.
    """

    def __init__(self, model: str = "bge-m3:latest", base_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def encode(self, sentences: list[str], **kwargs) -> "Any":
        import numpy as np  # type: ignore
        import httpx  # type: ignore

        vecs: list[list[float]] = []
        for sentence in sentences:
            resp = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": sentence},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama /api/embed returns {"embeddings": [[...], ...]}
            vecs.append(data["embeddings"][0])
        return np.array(vecs, dtype="float32")


class KeywordEnricher:
    """Extract top-N keyphrases per chunk using KeyBERT.

    Model loading priority (fastest / most reliable first):
      1. BAAI/bge-m3 — local HuggingFace cache  (no network)
      2. Ollama bge-m3 — local Ollama server     (no HF, no SSL)
      3. all-MiniLM-L6-v2 — local HF cache      (smaller, already cached)
      4. HF network download                     (last resort, needs SSL/token)
      5. Disabled — keywords left empty          (graceful degradation)
    """

    # HF model IDs tried with local_files_only=True first, then network
    _HF_CANDIDATES = [
        "BAAI/bge-m3",
        "sentence-transformers/all-MiniLM-L6-v2",
    ]

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model

        # Inject corporate CA certs once before any HTTPS call
        try:
            import truststore
            truststore.inject_into_ssl()
        except ImportError:
            pass

        try:
            from keybert import KeyBERT  # type: ignore
        except ImportError:
            log.warning("keybert not installed — keywords disabled")
            self._model = False
            return self._model

        # ── 1 & 3: local HF cache (no network) ──────────────────────────────
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            for model_name in self._HF_CANDIDATES:
                try:
                    st = SentenceTransformer(model_name, local_files_only=True)
                    self._model = KeyBERT(model=st)
                    log.info("KeyBERT ready: %s (HF local cache)", model_name)
                    return self._model
                except Exception as exc:
                    log.debug("HF local cache miss [%s]: %s", model_name, exc)
        except ImportError:
            pass  # sentence-transformers not installed; fall through to Ollama

        # ── 2: Ollama bge-m3 (local server, no HF dependency) ───────────────
        try:
            from src.config import get_settings
            s = get_settings()
            ollama_model = getattr(s, "ollama_embed_model", "bge-m3:latest")
            # Ensure it has a tag (Ollama requires one)
            if ":" not in ollama_model:
                ollama_model = f"{ollama_model}:latest"
            backend = _OllamaKeyBERTBackend(
                model=ollama_model,
                base_url=getattr(s, "ollama_base_url", "http://localhost:11434"),
            )
            # Quick probe — encode a short string to verify Ollama is reachable
            backend.encode(["test"])
            self._model = KeyBERT(model=backend)
            log.info("KeyBERT ready: Ollama %s", ollama_model)
            return self._model
        except Exception as exc:
            log.debug("Ollama KeyBERT backend unavailable: %s", exc)

        # ── 4: HF network download (last resort) ─────────────────────────────
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            for model_name in self._HF_CANDIDATES:
                try:
                    st = SentenceTransformer(model_name, local_files_only=False)
                    self._model = KeyBERT(model=st)
                    log.info("KeyBERT ready: %s (HF network download)", model_name)
                    return self._model
                except Exception as exc:
                    log.debug("HF network load failed [%s]: %s", model_name, exc)
        except ImportError:
            pass

        log.warning("KeyBERT: no usable backend found — keyword extraction disabled")
        self._model = False
        return self._model

    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        if len(chunk.text) < 30:
            chunk.extra.setdefault("keywords", [])
            return chunk
        model = self._get_model()
        if not model:
            chunk.extra.setdefault("keywords", [])
            return chunk
        try:
            kws = model.extract_keywords(
                chunk.text,
                keyphrase_ngram_range=(1, 2),
                stop_words="english",
                top_n=self.top_n,
            )
            chunk.extra["keywords"] = [kw for kw, _ in kws]
        except Exception as exc:
            log.debug("keyword extraction failed: %s", exc)
            chunk.extra.setdefault("keywords", [])
        return chunk


# ─────────────────────────────────────────────────────────────────────────────
# 3c  LanguageEnricher
# ─────────────────────────────────────────────────────────────────────────────

# ISO 639-3 → ISO 639-1 normalisation for the most common Unstructured language codes
_ISO3_TO_ISO1: dict[str, str] = {
    "eng": "en", "fra": "fr", "deu": "de", "spa": "es", "ita": "it",
    "por": "pt", "nld": "nl", "rus": "ru", "zho": "zh", "jpn": "ja",
    "kor": "ko", "ara": "ar", "hin": "hi", "pol": "pl", "swe": "sv",
    "nor": "no", "dan": "da", "fin": "fi", "tur": "tr", "ces": "cs",
    "ron": "ro", "hun": "hu", "heb": "he", "vie": "vi", "tha": "th",
    "ind": "id", "msa": "ms", "ukr": "uk", "cat": "ca",
}


class LanguageEnricher:
    """Detect chunk language via langdetect (55 languages, <1 ms per chunk).

    Normalises ISO 639-3 codes (e.g. "eng") from Unstructured to ISO 639-1
    ("en") so language values are consistent regardless of which parser ran.
    Falls back to langdetect for chunks without a pre-detected language.
    """

    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        existing = chunk.extra.get("language")
        if existing:
            # Normalise 3-letter codes; leave 2-letter codes untouched
            if len(existing) == 3:
                chunk.extra["language"] = _ISO3_TO_ISO1.get(existing, existing)
            return chunk
        if len(chunk.text) < 20:
            return chunk
        try:
            from langdetect import detect, LangDetectException  # type: ignore
            lang: str | None = detect(chunk.text)
        except ImportError:
            log.debug(
                "langdetect not installed — language detection skipped. "
                "Run: pip install langdetect"
            )
            lang = None
        except Exception:
            lang = None
        chunk.extra["language"] = lang
        return chunk


# ─────────────────────────────────────────────────────────────────────────────
# 3d  ConfidenceEnricher
# ─────────────────────────────────────────────────────────────────────────────

_ELEMENT_BASE_CONFIDENCE: dict[str, float] = {
    "Title":         1.00,
    "Header":        0.95,
    "NarrativeText": 0.85,
    "ListItem":      0.80,
    "Table":         0.85,
    "Footer":        0.40,
    "Image":         0.30,
}
_DEPTH_PENALTY = 0.03
_MAX_PENALTY   = 0.15


class ConfidenceEnricher:
    """Score chunk reliability 0.0-1.0 based on element_type and nesting depth.

    Higher score = more authoritative.  Used by the confidence_min search filter.
    No external dependencies.
    """

    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk:
        el_type = chunk.extra.get("element_type", "NarrativeText")
        depth   = chunk.extra.get("hierarchy_depth", 0)
        base    = _ELEMENT_BASE_CONFIDENCE.get(el_type, 0.75)
        penalty = min(depth * _DEPTH_PENALTY, _MAX_PENALTY)
        chunk.extra["confidence_score"] = round(max(base - penalty, 0.10), 3)
        return chunk


# ─────────────────────────────────────────────────────────────────────────────
# EnricherChain
# ─────────────────────────────────────────────────────────────────────────────

class EnricherChain:
    """Run a list of enrichers in order on every chunk."""

    def __init__(self, enrichers: list) -> None:
        self.enrichers = enrichers

    def enrich_all(self, chunks: list[Chunk], doc: RawDocument) -> list[Chunk]:
        result: list[Chunk] = []
        for chunk in chunks:
            for enricher in self.enrichers:
                try:
                    chunk = enricher.enrich(chunk, doc)
                except Exception as exc:
                    log.warning(
                        "enricher %s failed on chunk %d: %s",
                        type(enricher).__name__, chunk.chunk_index, exc,
                    )
            result.append(chunk)
        return result


def build_enricher_chain(top_n_keywords: int = 5) -> EnricherChain:
    """Return the default four-enricher chain."""
    return EnricherChain([
        HierarchyEnricher(),
        KeywordEnricher(top_n=top_n_keywords),
        LanguageEnricher(),
        ConfidenceEnricher(),
    ])
