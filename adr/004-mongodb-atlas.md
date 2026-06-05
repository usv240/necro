# ADR 004: MongoDB Atlas for persistence

**Status:** Accepted
**Date:** 2026-05-21

## What we decided

Scan results, feature findings, watchlist entries, and revival logs are all stored in MongoDB Atlas. We also use Atlas Vector Search for semantic matching between new findings and historical demand signals.

## Why we made this call

**The data model is document-shaped.** A scan finding is a nested document with a kill reason, a viability assessment, an ROI estimate, competitive intelligence, and context snippets. Flattening this into a relational schema would require five or six tables and a join to reconstruct a single finding. MongoDB stores it as-is and retrieves it as-is.

**We wanted semantic search without a separate service.** Atlas Vector Search lets us store embedding vectors alongside the documents and run approximate-nearest-neighbor queries in the same database that stores everything else. The use case is finding issues or past findings that are semantically similar to a new revival candidate. Adding a separate vector store (Pinecone, Weaviate, etc.) would have doubled the infrastructure footprint.

**The free tier is genuinely useful.** MongoDB Atlas M0 supports the features we need, including vector search. A developer trying to run NECRO locally does not need to pay for a database.

## What we gave up

MongoDB Atlas requires a network connection. If the `MONGODB_URI` environment variable is not set, NECRO falls back to stateless mode, which works for a single scan but loses watchlist persistence and revival logs. This is documented in the quick start.

## Schema overview

| Collection | What it stores |
|---|---|
| `scans` | One document per completed scan with summary stats |
| `features` | One document per finding, linked to a scan by `scan_id` |
| `watch_list` | Repos the monitoring loop re-scans every 24 hours |
| `revival_log` | GitLab issues and MRs NECRO created |
| `necrosis_scans` | Dead-code scan results, separate from revival scans |
