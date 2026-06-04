"""
Gemini client — Gemini 3 Flash primary (Google AI Studio), Vertex AI Gemini 2.5 Flash fallback.

The Vertex project does not currently serve gemini-3-flash-preview, so the fallback
(and the adversarial Challenger, which runs on Vertex) uses gemini-2.5-flash. This is an
honest, deliberate split — and it makes the Challenger a genuinely different model from
the primary, which strengthens the adversarial-independence guarantee.
"""

import json
import logging
import re
import time

import google.genai as genai
from google.genai import types

from backend.config import settings
from backend.services.run_trace import trace_event

logger = logging.getLogger(__name__)

_PRIMARY_MODEL = "gemini-3-flash-preview"  # Google AI Studio (API key) — verified available
_FALLBACK_MODEL = settings.GEMINI_MODEL  # gemini-2.5-flash via Vertex AI (Vertex lacks gemini-3)

# Per-request HTTP timeout (milliseconds). Without this, a single hung connection
# blocks for minutes and holds the whole parallel feature batch hostage.
_HTTP_TIMEOUT_MS = 45000

_client: genai.Client | None = None
_vertex_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _get_vertex_client() -> genai.Client | None:
    global _vertex_client
    if _vertex_client is None and settings.GOOGLE_PROJECT_ID:
        try:
            _vertex_client = genai.Client(
                vertexai=True,
                project=settings.GOOGLE_PROJECT_ID,
                location=settings.GOOGLE_LOCATION,
            )
        except Exception as e:
            logger.warning("Vertex AI client init failed: %s", e)
    return _vertex_client


async def generate_text(prompt: str, thinking_budget: int = 0) -> str:
    """Generate text using Gemini 3 Flash, falling back to Vertex AI on error."""
    config = types.GenerateContentConfig(
        temperature=0.0,  # deterministic scoring — same input must produce same output
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget)
        if thinking_budget > 0 else None,
        http_options=types.HttpOptions(timeout=_HTTP_TIMEOUT_MS),
    )

    # Primary: Gemini 3 Flash
    started = time.perf_counter()
    primary_error = ""
    primary_error_type = ""
    try:
        client = _get_client()
        resp = await client.aio.models.generate_content(
            model=_PRIMARY_MODEL,
            contents=prompt,
            config=config,
        )
        text = resp.text or ""
        trace_event("gemini_call", provider="ai_studio", model=_PRIMARY_MODEL,
                    status="success", duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    response_chars=len(text))
        return text
    except Exception as primary_err:
        primary_error = str(primary_err)
        primary_error_type = type(primary_err).__name__
        logger.warning("Gemini 3 Flash error: %s — falling back to Vertex AI", primary_err)

    trace_event("gemini_call", provider="ai_studio", model=_PRIMARY_MODEL,
                status="error", duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error_type=primary_error_type, error=primary_error)

    # Fallback: Vertex AI Gemini 2.5 Flash
    started = time.perf_counter()
    try:
        vertex = _get_vertex_client()
        if vertex:
            resp = await vertex.aio.models.generate_content(
                model=_FALLBACK_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    http_options=types.HttpOptions(timeout=_HTTP_TIMEOUT_MS),
                ),
            )
            text = resp.text or ""
            trace_event("gemini_call", provider="vertex_ai", model=_FALLBACK_MODEL,
                        status="success", duration_ms=round((time.perf_counter() - started) * 1000, 2),
                        response_chars=len(text))
            return text
    except Exception as fallback_err:
        logger.error("Vertex AI fallback error: %s", fallback_err)

        trace_event("gemini_call", provider="vertex_ai", model=_FALLBACK_MODEL,
                    status="error", duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    error_type=type(fallback_err).__name__, error=str(fallback_err))

    trace_event("gemini_call", provider="all", status="empty_response")
    return ""


async def generate_json(prompt: str, thinking_budget: int = 0, retries: int = 2) -> dict | None:
    """Generate a JSON response from Gemini. Strips markdown fences if present.

    Pass thinking_budget > 0 (e.g. 1024) for complex reasoning tasks like viability
    scoring and ADK synthesis where deeper chain-of-thought improves output quality.
    Retries up to `retries` times on parse failure before giving up.
    """
    full_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown fences, no explanation outside the JSON."

    for attempt in range(1, retries + 2):  # retries + 1 total attempts
        trace_event("gemini_json_attempt", attempt=attempt, max_attempts=retries + 1)
        text = await generate_text(full_prompt, thinking_budget=thinking_budget)
        if not text:
            if attempt <= retries:
                trace_event("gemini_json_retry", attempt=attempt, reason="empty_response")
                logger.warning("Gemini returned empty response, retry %d/%d", attempt, retries)
                continue
            return None

        # Strip markdown fences and stray backticks
        text = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`").strip()

        # Try direct parse first (fast path — Gemini usually returns clean JSON)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Robustly extract the outermost JSON object or array.
        # Uses a depth counter so nested braces don't confuse us.
        result = _extract_json_robust(text)
        if result is not None:
            return result

        logger.warning("JSON parse failed (attempt %d/%d): %.300s", attempt, retries + 1, text)
        trace_event("gemini_json_retry", attempt=attempt, reason="parse_failed")

    return None


def _extract_json_robust(text: str) -> dict | list | None:
    """
    Scan `text` character by character to find the first valid top-level JSON
    object `{...}` or array `[...]`, correctly handling nesting and strings.
    Much more reliable than a greedy `{.*}` regex.
    """
    # Try the container type that appears FIRST in the text
    obj_idx = text.find('{')
    arr_idx = text.find('[')
    if arr_idx != -1 and (obj_idx == -1 or arr_idx < obj_idx):
        pairs = [('[', ']'), ('{', '}')]
    else:
        pairs = [('{', '}'), ('[', ']')]
    for start_char, end_char in pairs:
        idx = text.find(start_char)
        if idx == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[idx:], start=idx):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[idx:i + 1])
                    except json.JSONDecodeError:
                        break  # try the other container type
    return None


async def generate_json_adversarial(prompt: str) -> dict | None:
    """
    Generate a JSON response using the Vertex AI client (Gemini 2.5 Flash).

    Used by the Challenger Agent to ensure independence from the primary analysis
    (Gemini 3 Flash via AI Studio API key). The Challenger runs a DIFFERENT model
    (Gemini 2.5 Flash) on DIFFERENT serving infrastructure (Vertex AI) with an
    adversarial system prompt — genuine model + serving independence.
    """
    full_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown fences, no explanation outside the JSON."

    # Primary: Vertex AI Gemini 2.5 Flash (independent model + serving from primary API-key path)
    vertex = _get_vertex_client()
    if vertex:
        try:
            resp = await vertex.aio.models.generate_content(
                model=_FALLBACK_MODEL,
                contents=full_prompt,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            text = resp.text or ""
            text = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`").strip()
            match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if match:
                text = match.group(1)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        except Exception as exc:
            logger.warning("Vertex adversarial call failed: %s — falling back to primary", exc)

    # Fallback: primary model with adversarial framing preserved
    return await generate_json(prompt)
