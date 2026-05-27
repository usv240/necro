"""
Semantic vector search for NECRO demand signal matching.

Uses Google text-embedding-004 (768-dim) to embed open GitLab issues,
stores them in MongoDB, and finds semantically similar issues for each
dead feature — replacing simple keyword overlap with genuine meaning.

Two search modes:
  1. MongoDB Atlas $vectorSearch  (fast; requires 'issue_embeddings_index')
  2. In-memory cosine similarity  (no Atlas index needed; automatic fallback)

To enable Atlas Vector Search, create an index in MongoDB Atlas:
  Collection: issue_embeddings
  Index name: issue_embeddings_index
  Config:
    {
      "fields": [{
        "type": "vector",
        "path": "embedding",
        "numDimensions": 768,
        "similarity": "cosine"
      }]
    }
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-004"
_ATLAS_INDEX = "issue_embeddings_index"
_SIMILARITY_THRESHOLD = 0.60


async def embed_text(text: str) -> list[float]:
    """Embed a single string with Google text-embedding-004 (768 dims)."""
    from google import genai
    from backend.config import settings

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = await client.aio.models.embed_content(
        model=_EMBEDDING_MODEL,
        contents=text,
    )
    return list(response.embeddings[0].values)


async def store_issue_embeddings(project_path: str, issues: list[dict]) -> int:
    """
    Batch-embed open GitLab issues and upsert into MongoDB issue_embeddings.
    Returns number of embeddings stored.
    Batches all texts in a single API call to avoid rate limits.
    """
    from google import genai
    from backend.config import settings
    from backend.db.connection import get_db

    batch = issues[:50]
    if not batch:
        return 0

    texts = []
    for issue in batch:
        title = issue.get("title", "")
        body = (issue.get("description") or "")[:200]
        texts.append(f"{title} {body}".strip() or title)

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await client.aio.models.embed_content(
            model=_EMBEDDING_MODEL,
            contents=texts,
        )
        vectors = [list(e.values) for e in response.embeddings]
    except Exception as exc:
        logger.warning("[VecSearch] Batch embed failed: %s", exc)
        return 0

    db = get_db()
    count = 0
    for issue, vec in zip(batch, vectors):
        try:
            await db["issue_embeddings"].replace_one(
                {"project_path": project_path, "issue_iid": issue.get("iid")},
                {
                    "project_path": project_path,
                    "issue_iid": issue.get("iid"),
                    "title": (issue.get("title") or "")[:200],
                    "web_url": issue.get("web_url", ""),
                    "embedding": vec,
                    "created_at": datetime.utcnow().isoformat(),
                },
                upsert=True,
            )
            count += 1
        except Exception as exc:
            logger.debug("[VecSearch] Store failed for iid=%s: %s", issue.get("iid"), exc)

    return count


async def find_similar_issues(
    project_path: str,
    feature_name: str,
    top_k: int = 5,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> list[dict]:
    """
    Semantic search: find open issues most similar to a dead feature name.

    Tries Atlas $vectorSearch first (sub-millisecond at scale), then falls back
    to in-memory cosine similarity over stored embeddings (no index required).

    Returns list of {iid, title, url, score} sorted by score desc.
    """
    from backend.db.connection import get_db

    db = get_db()

    try:
        query_vec = await embed_text(feature_name)
    except Exception as exc:
        logger.warning("[VecSearch] Could not embed '%s': %s", feature_name, exc)
        return []

    # ── Try Atlas $vectorSearch ───────────────────────────────────────────────
    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": _ATLAS_INDEX,
                    "path": "embedding",
                    "queryVector": query_vec,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                    "filter": {"project_path": {"$eq": project_path}},
                }
            },
            {
                "$project": {
                    "issue_iid": 1,
                    "title": 1,
                    "web_url": 1,
                    "score": {"$meta": "vectorSearchScore"},
                    "_id": 0,
                }
            },
        ]
        results = await db["issue_embeddings"].aggregate(pipeline).to_list(length=top_k)
        if results:
            return [
                {
                    "iid": r.get("issue_iid"),
                    "title": r.get("title"),
                    "url": r.get("web_url"),
                    "score": round(r.get("score", 0), 3),
                }
                for r in results
                if r.get("score", 0) >= threshold
            ]
    except Exception as exc:
        logger.debug("[VecSearch] Atlas $vectorSearch unavailable (%s) — in-memory fallback", type(exc).__name__)

    # ── In-memory cosine similarity fallback ─────────────────────────────────
    all_docs = await db["issue_embeddings"].find({"project_path": project_path}).to_list(length=300)
    if not all_docs:
        return []

    q_norm = _norm(query_vec)
    if q_norm == 0:
        return []

    scored = []
    for doc in all_docs:
        emb = doc.get("embedding", [])
        if not emb:
            continue
        score = _cosine(query_vec, emb, q_norm)
        if score >= threshold:
            scored.append({
                "iid": doc.get("issue_iid"),
                "title": doc.get("title"),
                "url": doc.get("web_url"),
                "score": round(score, 3),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def _norm(v: list[float]) -> float:
    return sum(x * x for x in v) ** 0.5


def _cosine(a: list[float], b: list[float], a_norm: float | None = None) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = a_norm if a_norm is not None else _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
