"""Time stage-2 visual analysis per page against a real Ollama model.

Sends exactly what the pipeline sends (same render, prompt and schema) for two
pages: the vector chart (general profile) and a real photo (incident profile).
For each page it reports one cold run (model unloaded first, so load time is
included) and N warm runs.

Usage (from the repo root, backend environment active, Ollama running):

    python scripts/benchmark_vision.py [--runs 3] [--num-ctx 16384]

``OLLAMA_BASE_URL`` defaults to http://127.0.0.1:11434 (native Ollama) and
``OLLAMA_MODEL`` to the app default. ``--num-ctx`` overrides ``OLLAMA_NUM_CTX``.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.llm.base import LLMError  # noqa: E402
from app.llm.ollama import OllamaProvider  # noqa: E402
from app.llm.structured import generate_structured  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.pipeline.extraction import extract_document, render_page_png  # noqa: E402
from app.pipeline.visual import build_visual_request  # noqa: E402
from app.schemas.common import Profile  # noqa: E402
from app.schemas.extraction import PageContent  # noqa: E402
from app.schemas.visual import VisualPageModelOutput  # noqa: E402
from tests import pdf_factory  # noqa: E402

# (label, PDF builder, profile). Each fixture has exactly one visual page, page 1.
CASES: list[tuple[str, Callable[[], bytes], Profile]] = [
    ("vector_chart.pdf p1", pdf_factory.vector_chart_pdf, "general"),
    ("real photo p1 (incident)", pdf_factory.real_photo_pdf, "incident"),
]


async def unload(settings: Settings) -> None:
    """Ask Ollama to unload the model so the next call includes load time."""
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=30) as client:
        await client.post("/api/generate", json={"model": settings.ollama_model, "keep_alive": 0})


async def loaded_model_info(settings: Settings) -> str:
    """Model size in VRAM and context, as reported by Ollama's /api/ps."""
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=10) as client:
        models = (await client.get("/api/ps")).json().get("models", [])
    for m in models:
        if m.get("name") == settings.ollama_model:
            vram = m.get("size_vram", 0) / 1e9
            total = m.get("size", 0) / 1e9
            return f"{total:.1f} GB loaded, {vram:.1f} GB in VRAM, ctx {m.get('context_length')}"
    return "model not loaded"


async def run_once(
    provider: OllamaProvider, png: bytes, page: PageContent, profile: Profile
) -> tuple[float, str]:
    """One page through the model. Failures are reported, not raised."""
    request = build_visual_request(png, page, profile)
    started = time.perf_counter()
    try:
        output, result = await generate_structured(provider, request, VisualPageModelOutput)
    except LLMError as exc:
        return time.perf_counter() - started, f"FAILED: {exc.code}"
    seconds = time.perf_counter() - started
    types = ",".join(e.type for e in output.elements) or "none"
    rate = (result.output_tokens or 0) / seconds if seconds else 0
    detail = (
        f"prompt={result.prompt_tokens} out={result.output_tokens} "
        f"({rate:.0f} tok/s overall) elements={types}"
    )
    return seconds, detail


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="warm runs per page (default 3)")
    parser.add_argument("--num-ctx", type=int, default=None, help="override OLLAMA_NUM_CTX")
    args = parser.parse_args()

    configure_logging("ERROR")
    overrides: dict[str, object] = {"llm_provider": "ollama", "log_level": "ERROR"}
    if "OLLAMA_BASE_URL" not in os.environ:
        overrides["ollama_base_url"] = "http://127.0.0.1:11434"
    if args.num_ctx:
        overrides["ollama_num_ctx"] = args.num_ctx
    settings = Settings(**overrides)  # type: ignore[arg-type]  # dict of mixed values
    provider = OllamaProvider(settings)
    if not await provider.is_ready():
        print(f"Ollama not ready at {settings.ollama_base_url} ({settings.ollama_model})")
        return 1

    print(
        f"model={settings.ollama_model} num_ctx={settings.ollama_num_ctx} "
        f"dpi={settings.render_dpi} timeout={settings.llm_timeout_seconds:g}s"
    )
    prepared: list[tuple[str, bytes, PageContent, Profile]] = []
    for label, builder, profile in CASES:
        data = builder()
        page = extract_document(data, settings).pages[0]
        prepared.append((label, render_page_png(data, 1, settings.render_dpi), page, profile))

    # Cold: model unloaded before each case, so the time includes loading it.
    for label, png, page, profile in prepared:
        await unload(settings)
        seconds, detail = await run_once(provider, png, page, profile)
        print(f"[cold] {label:<26} {seconds:6.1f} s  {detail}")
    print(f"loaded: {await loaded_model_info(settings)}")

    # Warm: cases interleaved, so Ollama cannot reuse the previous page's prompt
    # cache (in a real job consecutive pages differ too).
    warm: dict[str, list[float]] = {label: [] for label, *_ in prepared}
    for _ in range(args.runs):
        for label, png, page, profile in prepared:
            seconds, detail = await run_once(provider, png, page, profile)
            warm[label].append(seconds)
            print(f"[warm] {label:<26} {seconds:6.1f} s  {detail}")

    print("\nsummary (warm, per page)")
    for label, times in warm.items():
        if times:
            print(
                f"  {label:<26} median {statistics.median(times):5.1f} s "
                f"(min {min(times):.1f}, max {max(times):.1f}, n={len(times)})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
