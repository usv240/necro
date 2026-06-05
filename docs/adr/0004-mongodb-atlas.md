# ADR-0004: MongoDB Atlas for persistence and vector search

**Status:** Accepted  
**Date:** 2026-05-21

---

A NECRO scan result is a nested document. A single finding has a kill reason (with category, constraint, confidence, and cited evidence), a viability assessment (with feasibility score, effort estimate, technical risks, and recommendation), an ROI estimate (with demand signals, priority tier, and reasoning), and competitive intelligence. Flattening this into relational tables would require five or six tables and a join query to reconstruct a single finding. The data is document-shaped, so we stored it in a document database.

The vector search piece is what made MongoDB Atlas the choice over a simpler option like SQLite. We wanted to match open issues and new findings against historical demand signals semantically, not just by keyword. Atlas Vector Search lets us store embedding vectors alongside the documents and run approximate nearest-neighbour queries in the same database that stores everything else. Adding a separate vector store like Pinecone would have doubled the infrastructure footprint and added another credential to manage.

The practical consideration: MongoDB Atlas M0 (free tier) supports the features NECRO uses, including vector search. A developer setting up NECRO locally does not have to pay for a database. That matters for an open-source project.

NECRO falls back gracefully when `MONGODB_URI` is not set. The scan runs and returns results; they just are not persisted to the watchlist or revival log. That was an intentional decision so the tool is still useful in a minimal local setup.
