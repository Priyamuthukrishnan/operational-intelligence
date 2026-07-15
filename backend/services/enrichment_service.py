#!/usr/bin/env python3
"""
Enrichment runner — SUMMARIZATION + SENTIMENT.

⚠️ Location note: this is a SCRIPT, not a model. Keep it at
scripts/run_enrichment.py. Do NOT put it in
models/operational_analysis.py — that file should stay the
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
import time
import psycopg2

from mistralai import Mistral  # type: ignore

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

# How many tickets to process per run. Keep this small (5-10) if you're
# hitting Mistral API rate limits — just re-run the script to pick up the
# next batch (already-enriched tickets are automatically skipped).
BATCH_SIZE = int(os.getenv("ENRICHMENT_BATCH_SIZE", "5"))

# Seconds to wait between tickets, to stay under Mistral's rate limit.
# Each ticket makes up to 3 calls (query summary, resolution summary,
# sentiment), so this is the main lever if you still see 429 errors.
REQUEST_DELAY_SECONDS = float(os.getenv("ENRICHMENT_REQUEST_DELAY", "2"))


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

    print("Fetching unenriched tickets...")
    # Start FROM tickets — it's the one table guaranteed to have data the
    # moment a ticket is created. ai_analysis is joined as OPTIONAL (LEFT
    # JOIN): if the AI hasn't analyzed this ticket yet, ai_analysis_id and
    # the resolution fields simply come back NULL, and we still enrich the
    # ticket using its title/description. We re-link to ai_analysis later
    # (a future pass) once those rows exist — we are not blocked on it today.
    cur.execute("""
        SELECT
            t.id AS ticket_id, a.id AS ai_analysis_id,
            t.title, t.description, t.customer_name, t.created_by,
            COALESCE(t.resolution, a.runbook_resolution, a.rag_resolution, a.decision_reason) AS resolution
        FROM tickets t
        LEFT JOIN ai_analysis a ON a.ticket_id = t.id
        LEFT JOIN operational_analysis oa ON oa.ticket_id = t.id
        WHERE oa.id IS NULL
        LIMIT %s;
    """, (BATCH_SIZE,))
    rows = cur.fetchall()
    if not rows:
        print("Nothing to enrich.")
        return
    print(f"{len(rows)} tickets found.")

    # NOTE: tickets.customer_name is sometimes a company ("DEF Logistics") and
    # sometimes a person logged in for test/demo purposes ("sanjaikumar") —
    # it is NOT reliably a person's name. So we match it against
    # customer_profiles.company_name (the conceptually correct target),
    # not users.name. Today customer_profiles.company_name is mostly empty,
    # so most rows will correctly fall through to "unresolved" rather than
    # risk a false match against the wrong kind of entity. created_by is now
    # populated by the service team and is the preferred, reliable link.
    cur.execute("""
        SELECT cp.user_id, cp.company_name
        FROM customer_profiles cp
        WHERE cp.company_name IS NOT NULL AND cp.company_name <> '';
    """)
    company_lookup = {name.strip().lower(): uid for uid, name in cur.fetchall()}

    # comments and subtickets are read defensively — both are currently empty,
    # but this still works correctly once either table gets real data, with
    # no code changes needed. comments holds resolution/solution text per the
    # service team (NOT a customer conversation), so it is intentionally NOT
    # used as a sentiment input — only as extra resolution context if needed
    # later. Subticket complaint text (re-raised issues) WOULD belong in the
    # customer-text input once that table has data — flagged as a follow-up.
    cur.execute("""
        SELECT ticket_id, string_agg(comment_text, ' ')
        FROM comments
        GROUP BY ticket_id;
    """)
    ticket_comments = {ticket: text for ticket, text in cur.fetchall()}

    inserted = 0
    unresolved_customer = 0

    for idx, (ticket_id, ai_id, title, description, customer_name, created_by, resolution) in enumerate(rows):
        customer_id = created_by
        if customer_id is None and customer_name:
            customer_id = company_lookup.get(customer_name.strip().lower())
        if customer_id is None:
            unresolved_customer += 1

        # customer's own words: title + description (comments excluded — see note above)
        customer_text = " ".join(filter(None, [title, description]))

        try:
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

            # commit after EACH ticket — if a later ticket hits a rate limit
            # or any other error, everything enriched so far is already saved
            # and won't need to be redone.
            conn.commit()
            inserted += 1
            print(f"  [{idx + 1}/{len(rows)}] enriched ticket {ticket_id}")

        except Exception as e:
            conn.rollback()
            print(f"  [{idx + 1}/{len(rows)}] FAILED on ticket {ticket_id}: {e}")
            print("  Stopping here — already-enriched tickets above are saved. "
                  "Re-run the script later to continue with the rest.")
            break

        # small pause between tickets to stay under the API rate limit.
        # Skip the wait after the very last ticket.
        if idx < len(rows) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

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