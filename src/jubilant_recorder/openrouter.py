"""Shared OpenRouter chat-completions plumbing.

Both `tagger.llm.LLMProposer` and `codegen.ai_polish.LLMPolisher` send a
single-turn chat completion through OpenRouter's OpenAI-compatible API
(https://openrouter.ai/api/v1) and share one `httpx.Client` per run, built
by `jubilant_recorder.cli._make_ai_components`. This module holds the one
copy of the base URL, default model, and request/response shape so neither
call site hardcodes them separately.
"""

from __future__ import annotations

import os
from typing import Any

BASE_URL = "https://openrouter.ai/api/v1"

# Matches the model this project used directly via the Anthropic API before
# the OpenRouter migration, so the switch changes transport, not output
# quality. Override with OPENROUTER_MODEL or --ai-model.
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"


def resolve_model(explicit: str | None) -> str:
    """Return the model to use: --ai-model, else OPENROUTER_MODEL, else the default."""
    return explicit or os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL


def make_client(api_key: str) -> Any:
    """Build the shared httpx.Client used by both LLM passes for one run."""
    import httpx

    return httpx.Client(
        base_url=BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/tonyandrewmeyer/jubilant-recorder",
            "X-Title": "jubilant-recorder",
        },
        timeout=60.0,
    )


def complete(client: Any, *, model: str, prompt: str, max_tokens: int) -> str:
    """Run one single-turn chat completion and return the assistant's text.

    Raises on transport or HTTP errors (non-2xx status, connection failure);
    callers catch broadly and fall back to deterministic output.
    """
    response = client.post(
        "/chat/completions",
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""
