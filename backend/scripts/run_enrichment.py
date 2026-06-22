#!/usr/bin/env python3
"""
Enrichment runner — SUMMARIZATION + SENTIMENT.

⚠️ Location note: this is a SCRIPT, not a model. Keep it at
backend/scripts/run_enrichment.py. Do NOT put it in
backend/models/operational_analysis.py — that file should stay the
SQLAlchemy table definition only.

Reads unenriched interactions from ai_analysis and writes into
operational_analysis.

Flow:
Ticket + Customer Comments  →  query_summary    (what's the problem)
Ticket.resolution (primary) →  response_summary (what was actually done)
Customer Comments           →  sentiment        (how the customer feels)

Fix applied: response_summary now reads tickets.resolution FIRST — that is
the real fix text written by the service layer. Previously the query only
looked at ai_analysis.runbook_resolution / rag_resolution / decision_reason,
which are often empty or just meta-commentary ("AI identified a similar
incident..."), producing repetitive, low-value summaries.

If MISTRAL_API_KEY is set, Mistral is used. Otherwise an offline fallback.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys
import json
import psycopg2

from mistralai import Mistral

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL not found.")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "mistral-small-latest")
MODEL_VERSION = f"llm:{LLM_MODEL}" if MISTRAL_API_KEY else "fallback:v0.1"

NO_RESOLUTION_MARKER = "NO_RESOLUTION_YET"   # sentinel the model must return verbatim

# Set to True to wipe existing operational_analysis rows before this run.
# Useful right after a prompt/logic fix, so old (bad) rows don't linger
# alongside new ones. Leave False for normal incremental runs.
RESET_OPERATIONAL_ANALYSIS = os.getenv("RESET_OPERATIONAL_ANALYSIS", "false").lower() == "true"


# -------------------------------------------------------------------------
# Mistral helper
# -------------------------------------------------------------------------
def call_llm(prompt):
    if not MISTRAL_API_KEY:
        return None
    client = Mistral(api_key=MISTRAL_API_KEY)
    response = client.chat.complete(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


# -------------------------------------------------------------------------
# Summarizer
# -------------------------------------------------------------------------
def summarize_query(text):
    """Summarize the CUSTOMER'S PROBLEM. Safe to skip if there's no text."""
    if not text or not text.strip():
        return None
    prompt = f"""Summarize the following customer issue in ONE concise sentence.
Do not invent details that are not present in the text.

{text}"""
    output = call_llm(prompt)
    return output if output is not None else text[:150]


def summarize_resolution(text):
    """
    Summarize the ACTUAL FIX. Input should be tickets.resolution when available
    (the real fix text), falling back to AI decision logs only if no
    resolution was ever recorded.

    CRITICAL: if the input is empty or not really a resolution, this must
    return None — never let the model invent a fix that was never given.
    """
    if not text or not text.strip():
        return None
    prompt = f"""You will be given text describing how a support ticket was resolved.
Summarize it in ONE concise sentence, in your own words.

RULES:
- Only summarize what is literally stated in the text below.
- Do NOT invent advice, instructions, or a resolution that is not present.
- If the text does not actually describe a resolution or fix (for example, if it is
  just a category label, a status note, or generic commentary like "AI identified a
  similar incident", with no concrete action described), respond with exactly:
  {NO_RESOLUTION_MARKER}

Text:
{text}"""
    output = call_llm(prompt)
    if output is None:
        return text[:150]
    if NO_RESOLUTION_MARKER in output:
        return None
    return output


# -------------------------------------------------------------------------
# Offline sentiment (fallback when no API key)
# -------------------------------------------------------------------------
def fallback_sentiment(text):
    text = text.lower()
    positive = ["thank", "thanks", "great", "perfect", "resolved", "fixed", "awesome", "appreciate", "worked"]
    negative = ["frustrating", "waiting", "not working", "error", "failed", "issue",
                "problem", "slow", "escalate", "third time"]
    score = sum(w in text for w in positive) - sum(w in text for w in negative)
    if score > 0:
        return "positive", min(score / 5, 1)
    if score < 0:
        return "negative", max(score / 5, -1)
    return "neutral", 0.0


# -------------------------------------------------------------------------
# Sentiment Agent — purpose: capture how the CUSTOMER feels, independent of
# ticket status or what the system thinks it accomplished. Feeds escalation
# risk and customer health score later.
# -------------------------------------------------------------------------
def analyze_sentiment(text):
    if not text:
        return "neutral", 0.0
    prompt = f"""Analyze ONLY the customer's sentiment in the text below.
Calibrate the score honestly — do not default to a strong negative score just
because the message describes a problem. A calm bug report is closer to neutral;
only frustration, anger, or repeated complaints should score strongly negative.

Return ONLY valid JSON, no commentary:
{{"label":"positive|neutral|negative","score":0.0}}

Customer Text:
{text}"""
    output = call_llm(prompt)
    if output is None:
        return fallback_sentiment(text)
    try:
        cleaned = output.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        return data["label"], float(data["score"])
    except Exception:
        return fallback_sentiment(text)


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    if RESET_OPERATIONAL_ANALYSIS:
        cur.execute("DELETE FROM operational_analysis;")
        print(f"Cleared existing operational_analysis rows ({cur.rowcount} deleted).")

    print("Fetching unenriched interactions...")
    cur.execute("""
        SELECT
            a.id, a.ticket_id, t.title, t.description, t.customer_name, t.created_by,
            COALESCE(t.resolution, a.runbook_resolution, a.rag_resolution, a.decision_reason) AS resolution
        FROM ai_analysis a
        JOIN tickets t ON t.id = a.ticket_id
        LEFT JOIN operational_analysis oa ON oa.ai_analysis_id = a.id
        WHERE oa.id IS NULL
        LIMIT 5;
    """)
    rows = cur.fetchall()
    if not rows:
        print("Nothing to enrich.")
        return
    print(f"{len(rows)} interactions found.")

    cur.execute("SELECT id, name FROM users;")
    user_lookup = {name.strip().lower(): uid for uid, name in cur.fetchall()}

    cur.execute("""
        SELECT ticket_id, string_agg(comment_text, ' ')
        FROM comments
        WHERE lower(commented_by) = 'customer'
        GROUP BY ticket_id;
    """)
    customer_comments = {ticket: text for ticket, text in cur.fetchall()}

    inserted = 0
    unresolved_customer = 0

    for ai_id, ticket_id, title, description, customer_name, created_by, resolution in rows:
        customer_id = created_by
        if customer_id is None and customer_name:
            customer_id = user_lookup.get(customer_name.strip().lower())
        if customer_id is None:
            unresolved_customer += 1

        customer_text = " ".join(filter(None, [title, description, customer_comments.get(ticket_id)]))

        query_summary = summarize_query(customer_text)
        response_summary = summarize_resolution(resolution)
        sentiment_label, sentiment_score = analyze_sentiment(customer_text)

        cur.execute("""
            INSERT INTO operational_analysis
                (ai_analysis_id, ticket_id, customer_id,
                 query_summary, response_summary,
                 sentiment_label, sentiment_score, model_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (ai_id, ticket_id, customer_id,
              query_summary, response_summary,
              sentiment_label, sentiment_score, MODEL_VERSION))
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print()
    print("--------------------------------------")
    print("Enrichment Completed")
    print("--------------------------------------")
    print(f"Inserted               : {inserted}")
    print(f"Customer unresolved    : {unresolved_customer}")
    print(f"Model                  : {MODEL_VERSION}")
    print("--------------------------------------")


if __name__ == "__main__":
    main()