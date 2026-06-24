#!/usr/bin/env python3
"""
Clear all points from the operational-summaries Qdrant collection.

Use this when the underlying operational_analysis rows have been wiped
(e.g. the service team reset the tickets table) and the vectors left in
Qdrant are now orphaned — pointing at rows that no longer exist.

This does NOT touch the service team's collections — only your own.

After running this, re-run run_embedding.py to repopulate the collection
from whatever is currently in operational_analysis.

Usage:
    python backend/scripts/clear_qdrant_collection.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
from qdrant_client import QdrantClient

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "operational-summaries")

if not QDRANT_URL or not QDRANT_API_KEY:
    sys.exit("Set QDRANT_URL and QDRANT_API_KEY in your .env first.")

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, check_compatibility=False)

count_before = client.count(collection_name=COLLECTION_NAME).count
print(f"'{COLLECTION_NAME}' currently has {count_before} point(s).")

if count_before == 0:
    print("Nothing to clear.")
    sys.exit(0)

confirm = input(f"Delete all {count_before} point(s) from '{COLLECTION_NAME}'? [y/N]: ")
if confirm.strip().lower() != "y":
    print("Cancelled.")
    sys.exit(0)

client.delete_collection(collection_name=COLLECTION_NAME)

from qdrant_client.models import VectorParams, Distance
client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
)

print(f"Cleared and recreated '{COLLECTION_NAME}'. "
      f"Now re-run run_embedding.py to repopulate it from current operational_analysis rows.")