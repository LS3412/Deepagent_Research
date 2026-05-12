"""Centralized typed settings loaded from .env / environment."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM backend — set USE_GITHUB_MODELS=true to use GitHub Models instead of Ollama
    use_github_models: bool = False

    # Ollama (used when use_github_models=false)
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:14b"
    ollama_embed_model: str = "bge-m3"

    # GitHub Models (used when use_github_models=true)
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_model: str = Field(default="openai/gpt-5-mini", alias="GITHUB_MODEL")
    github_models_endpoint: str = "https://models.github.ai/inference"

    # Weaviate
    weaviate_host: str = "localhost"
    weaviate_http_port: int = 8080
    weaviate_grpc_port: int = 50051
    weaviate_api_key: str = ""
    weaviate_collection: str = "Document"

    # Langfuse
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_enabled: bool = False

    # Paths
    data_dir: Path = Path("./data")
    upload_dir: Path = Path("./data/uploads")
    watch_dir: Path = Path("./data/watch")

    # Ingestion — chunking
    chunk_size: int = 800
    chunk_overlap: int = 120
    chunk_strategy: str = "element"        # "element" | "semantic" | "recursive"
    semantic_chunk_threshold: float = 0.5  # cosine similarity breakpoint (SemanticChunker)

    # Ingestion — embedding
    embed_batch_size: int = 32
    embed_strategy: str = "async"          # "async" | "sync"
    embed_max_concurrent_batches: int = 4  # concurrent Ollama batch calls

    # Ingestion — deduplication (MinHash LSH)
    dedup_enabled: bool = True
    dedup_threshold: float = 0.85          # Jaccard similarity threshold
    dedup_num_perm: int = 128              # MinHash permutations
    dedup_index_path: str = "./data/lsh_index.pkl"

    # Ingestion — enrichment
    enrich_enabled: bool = True
    enrich_keywords_top_n: int = 5

    # Agent
    default_tenant_id: str = "default"
    max_agent_iterations: int = 20
    retrieval_top_k: int = 6
    hybrid_alpha: float = 0.5
    # Minimum hybrid-search score (0-1) for a result to be considered relevant.
    # Results below this threshold are discarded so the agent sees an empty list
    # and correctly replies "not in KB" instead of answering from unrelated chunks.
    retrieval_min_score: float = 0.45

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.upload_dir, self.watch_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
