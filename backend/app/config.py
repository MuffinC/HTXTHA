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
    # Docker Compose hostname. For local development against a natively
    # installed Ollama, set OLLAMA_BASE_URL=http://127.0.0.1:11434 (ASSUMPTIONS A-112).
    ollama_base_url: str = "http://ollama:11434"
    # Verified in M2 against Ollama 0.40.16 (DECISIONS D-023): vision-capable,
    # non-thinking instruct variant, Q4_K_M, 3.3 GB.
    ollama_model: str = "qwen3-vl:4b-instruct"
    ollama_num_ctx: int = Field(default=16384, gt=0)
    llm_timeout_seconds: float = Field(default=300, gt=0)
    # Mock provider only: pause per model call so progress is visible in demos and
    # screenshots (the mock otherwise finishes a job in milliseconds). 0 in tests.
    mock_delay_seconds: float = Field(default=0, ge=0, le=30)

    # ---- Upload limits ----
    max_files: int = Field(default=10, gt=0)
    max_file_mb: int = Field(default=25, gt=0)
    max_pages: int = Field(default=60, gt=0)

    # ---- Visual analysis ----
    max_visual_pages_per_doc: int = Field(default=20, ge=0)
    render_dpi: int = Field(default=150, ge=36, le=600)

    # ---- Security / retention ----
    active_content_policy: Literal["reject", "warn"] = "reject"
    # Backstop regex masking of NRIC/FIN and phone numbers in model output.
    # Trade-off (DECISIONS D-021): masking protects against leaks, but can hide
    # contact details an investigator legitimately needs. Inference is local.
    mask_pii: bool = True
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
