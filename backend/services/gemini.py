"""
Gemini client — Gemini 3 Flash primary (Google AI Studio), Vertex AI Gemini 3 Flash fallback.
"""

import json
import logging
import re

import google.genai as genai
from google.genai import types

from backend.config import settings

logger = logging.getLogger(__name__)

_PRIMARY_MODEL = "gemini-3-flash-preview"
_FALLBACK_MODEL = settings.GEMINI_MODEL  # gemini-3-flash-preview via Vertex AI

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
    )

    # Primary: Gemini 3 Flash
    try:
        client = _get_client()
        resp = await client.aio.models.generate_content(
            model=_PRIMARY_MODEL,
            contents=prompt,
            config=config,
        )
        return resp.text or ""
    except Exception as primary_err:
        logger.warning("Gemini 3 Flash error: %s — falling back to Vertex AI", primary_err)

    # Fallback: Vertex AI Gemini 3 Flash
    try:
        vertex = _get_vertex_client()
        if vertex:
            resp = await vertex.aio.models.generate_content(
                model=_FALLBACK_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0),
            )
            return resp.text or ""
    except Exception as fallback_err:
        logger.error("Vertex AI fallback error: %s", fallback_err)

    return ""


async def generate_json(prompt: str, thinking_budget: int = 0, retries: int = 2) -> dict | None:
    """Generate a JSON response from Gemini. Strips markdown fences if present.

    Pass thinking_budget > 0 (e.g. 1024) for complex reasoning tasks like viability
    scoring and ADK synthesis where deeper chain-of-thought improves output quality.
    Retries up to `retries` times on parse failure before giving up.
    """
    full_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown fences, no explanation outside the JSON."

    for attempt in range(1, retries + 2):  # retries + 1 total attempts
        text = await generate_text(full_prompt, thinking_budget=thinking_budget)
        if not text:
            if attempt <= retries:
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
    Generate a JSON response using the Vertex AI client (Gemini 3 Flash).

    Used by the Challenger Agent to ensure serving independence from the
    primary analysis (Gemini 3 Flash via API key). Same model, different
    serving infrastructure (Vertex AI vs AI Studio) and adversarial system prompt.
    """
    full_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown fences, no explanation outside the JSON."

    # Primary: Vertex AI Gemini 3 Flash (independent serving from primary API-key path)
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
