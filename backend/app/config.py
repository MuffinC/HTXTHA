"""Application settings loaded from environment variables.

All configuration lives here so the rest of the code never reads ``os.environ``
directly. Every setting has a safe default, which lets the app start (and the
test-suite run) with no ``.env`` file at all.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Field names map 1:1 to upper-case env vars."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- LLM ----
    llm_provider: Literal["ollama", "mock"] = "ollama"
    ollama_base_url: str = "http://ollama:11434"
    # ASSUMPTION: the default tag is verified against the Ollama registry in M2
    # (see docs/ASSUMPTIONS.md).
    ollama_model: str = "qwen3-vl:4b-instruct"
    ollama_num_ctx: int = Field(default=16384, gt=0)
    llm_timeout_seconds: float = Field(default=300, gt=0)

    # ---- Upload limits ----
    max_files: int = Field(default=10, gt=0)
    max_file_mb: int = Field(default=25, gt=0)
    max_pages: int = Field(default=60, gt=0)

    # ---- Visual analysis ----
    max_visual_pages_per_doc: int = Field(default=20, ge=0)
    render_dpi: int = Field(default=150, ge=36, le=600)

    # ---- Security / retention ----
    active_content_policy: Literal["reject", "warn"] = "reject"
    retain_uploads: bool = False

    # ---- Ops ----
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_dir: Path = Path("/data")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so env parsing happens once. Tests pass their own ``Settings`` to
    ``create_app`` instead of relying on this.
    """
    return Settings()
