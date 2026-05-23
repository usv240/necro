"""
Gemini client — Gemini 3 Flash primary, Vertex AI Gemini 2.5 Flash fallback.
"""

import json
import logging
import re

import google.genai as genai
from google.genai import types

from backend.config import settings

logger = logging.getLogger(__name__)

_PRIMARY_MODEL = "gemini-3-flash-preview"
_FALLBACK_MODEL = settings.GEMINI_MODEL  # gemini-2.5-flash via Vertex AI

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

    # Fallback: Vertex AI Gemini 2.5 Flash
    try:
        vertex = _get_vertex_client()
        if vertex:
            resp = await vertex.aio.models.generate_content(
                model=_FALLBACK_MODEL,
                contents=prompt,
            )
            return resp.text or ""
    except Exception as fallback_err:
        logger.error("Vertex AI fallback error: %s", fallback_err)

    return ""


async def generate_json(prompt: str) -> dict | None:
    """Generate a JSON response from Gemini. Strips markdown fences if present."""
    full_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown fences, no explanation outside the JSON."
    text = await generate_text(full_prompt)
    if not text:
        return None

    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.strip("`").strip()

    # Extract first JSON object or array
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        text = match.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error: %s\nRaw text: %.200s", exc, text)
        return None
