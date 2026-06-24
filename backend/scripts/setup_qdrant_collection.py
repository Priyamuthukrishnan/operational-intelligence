#!/usr/bin/env python3
"""
One-time setup: create the Operational Intelligence layer's own Qdrant
collection for summary embeddings.

This does NOT touch the service team's collections (incidentrunbook, runbook,
etc.) — it creates a new, separate collection that only your team writes to
and reads from.

Safe to run multiple times: it checks whether the collection already exists
before creating it.

Usage:
    export QDRANT_URL="https://....cloud.qdrant.io:6333"
    export QDRANT_API_KEY="..."
    export QDRANT_COLLECTION_NAME="operational-summaries"   # optional, has a default
    python backend/scripts/setup_qdrant_collection.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "operational-summaries")

# mistral-embed outputs 1024-dimensional vectors.
# If the service team ever changes the embedding model, this must change too.
VECTOR_SIZE = 1024

if not QDRANT_URL or not QDRANT_API_KEY:
    sys.exit("Set QDRANT_URL and QDRANT_API_KEY in your .env first.")


def main():
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        print(f"Collection '{COLLECTION_NAME}' already exists. Nothing to do.")
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    print(f"Created collection '{COLLECTION_NAME}' (size={VECTOR_SIZE}, distance=Cosine).")


if __name__ == "__main__":
    main()