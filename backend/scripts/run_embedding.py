#!/usr/bin/env python3
"""
Embedding Service — turns each interaction's query_summary into a vector
and stores it in YOUR Qdrant collection (operational-summaries), separate
from the service team's resolution-search collections.

This is NOT RAG. There is no generation step here — only:
    text (query_summary)  →  vector (mistral-embed)  →  stored in Qdrant

The stored vectors are what the clustering agent will later search against
to find and group similar issues (for the dashboard view), not to generate
a resolution for any customer.

Flow:
  1. Find operational_analysis rows with a query_summary but no qdrant_vector_id yet.
  2. Call mistral-embed on each query_summary.
  3. Upsert the vector into Qdrant, using the operational_analysis row's own id
     as the Qdrant point id (so the two are always trivially linkable).
  4. Write that same id back into operational_analysis.qdrant_vector_id.

Usage:
    python backend/scripts/run_embedding.py
"""
from dotenv import load_dotenv
load_dotenv()

import os
import sys
import psycopg2

from mistralai import Mistral
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

DATABASE_URL = os.getenv("DATABASE_URL")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
EMBED_MODEL = os.getenv("MISTRAL_EMBEDDING_MODEL", "mistral-embed")

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "operational-summaries")

if not DATABASE_URL:
    sys.exit("DATABASE_URL not found in .env")
if not MISTRAL_API_KEY:
    sys.exit("MISTRAL_API_KEY not found in .env")
if not QDRANT_URL or not QDRANT_API_KEY:
    sys.exit("QDRANT_URL / QDRANT_API_KEY not found in .env")

mistral_client = Mistral(api_key=MISTRAL_API_KEY)
qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, check_compatibility=False)


def embed_text(text):
    """Call mistral-embed and return the vector (list of floats)."""
    response = mistral_client.embeddings.create(
        model=EMBED_MODEL,
        inputs=[text],
    )
    return response.data[0].embedding


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print("Fetching interactions that need embedding...")
    cur.execute("""
        SELECT id, query_summary
        FROM operational_analysis
        WHERE query_summary IS NOT NULL
          AND qdrant_vector_id IS NULL
        LIMIT 500;
    """)
    rows = cur.fetchall()

    if not rows:
        print("Nothing to embed — all rows with a summary already have a vector.")
        return

    print(f"{len(rows)} interactions to embed.")

    embedded = 0
    failed = 0

    for row_id, query_summary in rows:
        try:
            vector = embed_text(query_summary)

            # use the operational_analysis row's own uuid as the Qdrant point id
            # so the two records are always trivially linkable, in both directions.
            point_id = str(row_id)

            qdrant_client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "operational_analysis_id": str(row_id),
                            "query_summary": query_summary,
                        },
                    )
                ],
            )

            cur.execute(
                "UPDATE operational_analysis SET qdrant_vector_id = %s WHERE id = %s;",
                (point_id, row_id),
            )
            embedded += 1

        except Exception as e:
            print(f"  Failed on row {row_id}: {e}")
            failed += 1

    conn.commit()
    cur.close()
    conn.close()

    print()
    print("--------------------------------------")
    print("Embedding Completed")
    print("--------------------------------------")
    print(f"Embedded   : {embedded}")
    print(f"Failed     : {failed}")
    print(f"Collection : {COLLECTION_NAME}")
    print(f"Model      : {EMBED_MODEL}")
    print("--------------------------------------")


if __name__ == "__main__":
    main()