"""
MongoDB Atlas Vector Search index setup for NECRO.

Creates the 'issue_embeddings_index' on the 'issue_embeddings' collection —
required for Atlas $vectorSearch to work in find_similar_issues().

The index uses:
  - text-embedding-004: 768 dimensions
  - cosine similarity
  - Filter on project_path field

Run this script once after your MongoDB Atlas cluster is ready:
    python -m backend.services.atlas_setup

Or call ensure_vector_index() programmatically on startup.

Atlas UI alternative (if the API approach below fails):
  1. Go to Atlas → your cluster → Search → Create Index
  2. Select 'Atlas Vector Search'
  3. Use this JSON config:
     {
       "fields": [
         {
           "type": "vector",
           "path": "embedding",
           "numDimensions": 768,
           "similarity": "cosine"
         },
         {
           "type": "filter",
           "path": "project_path"
         }
       ]
     }
  4. Name: issue_embeddings_index
  5. Collection: issue_embeddings
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_INDEX_NAME = "issue_embeddings_index"
_COLLECTION = "issue_embeddings"
_INDEX_DEFINITION = {
    "fields": [
        {
            "type": "vector",
            "path": "embedding",
            "numDimensions": 768,
            "similarity": "cosine",
        },
        {
            "type": "filter",
            "path": "project_path",
        },
    ]
}


async def ensure_vector_index() -> bool:
    """
    Create the Atlas Vector Search index if it doesn't already exist.

    Returns True if index exists or was created successfully.
    Returns False if creation failed (likely because the cluster tier
    doesn't support Atlas Search — free tier M0 doesn't support it;
    upgrade to M10+ or use the in-memory cosine fallback in vector_search.py).
    """
    from backend.config import settings

    if not settings.MONGODB_URI:
        logger.debug("[Atlas] No MONGODB_URI — skipping vector index setup")
        return False

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from pymongo.operations import SearchIndexModel

        client = AsyncIOMotorClient(settings.MONGODB_URI)
        db = client[settings.MONGODB_DB_NAME]
        collection = db[_COLLECTION]

        # List existing search indexes
        existing_names = set()
        try:
            async for idx in await collection.list_search_indexes():
                existing_names.add(idx.get("name", ""))
        except Exception:
            # list_search_indexes may not be available on all driver versions
            existing_names = set()

        if _INDEX_NAME in existing_names:
            logger.info("[Atlas] Vector Search index '%s' already exists ✓", _INDEX_NAME)
            client.close()
            return True

        # Create the index
        index_model = SearchIndexModel(
            definition=_INDEX_DEFINITION,
            name=_INDEX_NAME,
            type="vectorSearch",
        )
        await collection.create_search_index(index_model)
        logger.info("[Atlas] Vector Search index '%s' created ✓ (768-dim cosine, text-embedding-004)", _INDEX_NAME)
        client.close()
        return True

    except Exception as exc:
        err_str = str(exc)
        if "M0" in err_str or "free tier" in err_str.lower() or "not supported" in err_str.lower():
            logger.warning(
                "[Atlas] Vector Search requires M10+ cluster tier (M0 free tier not supported). "
                "NECRO will use in-memory cosine similarity fallback. "
                "To enable Atlas $vectorSearch: upgrade to M10+ and run this script again."
            )
        else:
            logger.warning("[Atlas] Could not create Vector Search index: %s — using in-memory fallback", exc)
        return False


async def check_vector_index_status() -> dict:
    """
    Return the current status of the Vector Search index.
    Used by the /api/health endpoint.
    """
    from backend.config import settings

    if not settings.MONGODB_URI:
        return {"status": "no_mongodb", "index": _INDEX_NAME}

    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.MONGODB_URI)
        db = client[settings.MONGODB_DB_NAME]
        collection = db[_COLLECTION]

        async for idx in await collection.list_search_indexes():
            if idx.get("name") == _INDEX_NAME:
                client.close()
                return {
                    "status": idx.get("status", "unknown"),
                    "index": _INDEX_NAME,
                    "type": "vectorSearch",
                    "dimensions": 768,
                    "similarity": "cosine",
                }
        client.close()
        return {"status": "not_found", "index": _INDEX_NAME}
    except Exception as exc:
        return {"status": f"error: {type(exc).__name__}", "index": _INDEX_NAME}


async def main():
    """CLI entry point: python -m backend.services.atlas_setup"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")

    print("NECRO — MongoDB Atlas Vector Search Index Setup")
    print("=" * 50)

    ok = await ensure_vector_index()
    if ok:
        print("\n✓ Vector Search index ready")
        status = await check_vector_index_status()
        print(f"  Index: {status['index']}")
        print(f"  Status: {status['status']}")
        print(f"  Dimensions: {status.get('dimensions', 768)}")
        print(f"  Similarity: {status.get('similarity', 'cosine')}")
    else:
        print("\n✗ Vector Search index not available")
        print("  NECRO will use in-memory cosine similarity fallback")
        print("\nTo enable Atlas Vector Search:")
        print("  1. Upgrade your MongoDB Atlas cluster to M10+")
        print("  2. Run: python -m backend.services.atlas_setup")
        print("  OR create the index manually via Atlas UI (see docs at top of this file)")


if __name__ == "__main__":
    asyncio.run(main())
