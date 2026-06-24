#!/usr/bin/env python3

from dotenv import load_dotenv
load_dotenv()
import os
import sys
import random
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: set DATABASE_URL to your Neon connection string.")

N_TICKETS = int(sys.argv[1]) if len(sys.argv) > 1 else 30

# customer users:  (full_name, company_name, email)
CUSTOMERS = [
    ("John Redding", "Acme Manufacturing", "john@acme.example"),
    ("Mira Patel",   "Bright Logistics",   "mira@bright.example"),
    ("Sam Okafor",   "Northwind Energy",   "sam@northwind.example"),
    ("Lena Ortiz",   "Vertex Aerospace",   "lena@vertex.example"),
    ("Raj Menon",    "Harbor Foods",       "raj@harbor.example"),
]

ROOT_CAUSES = [
    ("Forgotten or expired password", "User cannot access account due to password issues"),
    ("Tax code mapping error",        "Invoice posting fails due to missing/incorrect tax code"),
    ("Manual confirmation dependency","Process stalls waiting on a manual confirmation step"),
    ("Stock level mismatch",          "Inventory counts disagree between modules"),
    ("Permission/role misconfig",     "User lacks the role needed for an action"),
]

ISSUES = [
    dict(category="User access", app="IFS Cloud",
         title="Cannot reset password",
         desc="I forgot my password and cannot log in. Please help me reset it.",
         ai="I have triggered a password reset email. Please set a new password and confirm it works.",
         source="runbook", conf=0.92, sim=0.94, rb=0.94,
         rb_res="Trigger automated password reset email; user sets a new password."),
    dict(category="Finance", app="IFS Cloud",
         title="Invoice will not save",
         desc="My invoice will not save, I just get error FIN-302 and no explanation.",
         ai="Could you share the exact error code and the customer account on the invoice?",
         source="rag", conf=0.55, sim=0.61,
         rag_c="Invoice fails to save with FIN-302", rag_r="Check tax code mapping before posting."),
    dict(category="Supply chain", app="IFS Cloud",
         title="Stock count mismatch",
         desc="The stock count in the system does not match what we physically have in the warehouse.",
         ai="Can you tell me the part number and the warehouse location so I can compare transactions?",
         source="rag", conf=0.48, sim=0.52,
         rag_c="Inventory mismatch", rag_r="Reconcile via inventory adjustment transaction."),
    dict(category="Manufacturing", app="IFS Cloud",
         title="Work order stuck in released state",
         desc="My work order is stuck on 'released' and will not start. Production is waiting.",
         ai="Please confirm the work order number and whether all required materials are reserved.",
         source="runbook", conf=0.81, sim=0.83, rb=0.83,
         rb_res="Verify material reservations, then re-trigger the state change."),
    dict(category="Field service", app="IFS Cloud",
         title="Technician missing from dispatch board",
         desc="One of our technicians is not showing up on the dispatch board today.",
         ai="Can you confirm the technician ID and whether they are marked active for today's shift?",
         source="human", conf=0.40, sim=0.44),
]

POSITIVE = ["That worked, thank you so much!",
            "Perfect, all sorted now. Appreciate the quick help.",
            "Great, that fixed it. Thanks!"]
NEUTRAL  = ["Okay, here is the information you asked for.",
            "Sure, the details are attached. Let me know.",
            "Understood, I will check and get back to you."]
NEGATIVE = ["This is the third time this week, it is really slowing us down.",
            "Still not working and I have been waiting for hours. This is frustrating.",
            "We keep hitting this same problem and it is costing us time. Please escalate."]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # seed root_cause_taxonomy if empty
    cur.execute("SELECT count(*) FROM root_cause_taxonomy;")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO root_cause_taxonomy (category, description, is_active) VALUES (%s,%s,true);",
            ROOT_CAUSES)

    # seed customer users + profiles if none exist yet
    cur.execute("SELECT id FROM users WHERE user_type = 'CUSTOMER';")
    customer_ids = [r[0] for r in cur.fetchall()]
    if not customer_ids:
        for i, (name, company, email) in enumerate(CUSTOMERS):
            cur.execute(
                """INSERT INTO users (name, email, password_hash, user_type, role, is_active)
                   VALUES (%s,%s,%s,'CUSTOMER','CUSTOMER',true) RETURNING id;""",
                (name, email, "mock-hash"))
            uid = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO customer_profiles (user_id, company_name, phone)
                   VALUES (%s,%s,%s);""",
                (uid, company, f"555-0{i}00"))
            customer_ids.append(uid)

    # map user_id -> company name (for ticket.customer_name)
    cur.execute("SELECT user_id, company_name FROM customer_profiles;")
    company_of = {r[0]: r[1] for r in cur.fetchall()}

    statuses = ["open", "in_progress", "resolved", "closed"]

    for _ in range(N_TICKETS):
        cust = random.choice(customer_ids)
        issue = random.choice(ISSUES)

        # ticket (created_by = the customer user)
        cur.execute(
            """INSERT INTO tickets
               (title, description, status, priority, category, application_name,
                customer_name, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id;""",
            (issue["title"], issue["desc"], random.choice(statuses),
             random.choice(["High", "Medium", "Low"]), issue["category"],
             issue["app"], company_of.get(cust, "Unknown"), cust))
        ticket_id = cur.fetchone()[0]

        # conversation: customer -> ai -> customer follow-up (random tone)
        tone = random.choices(["pos", "neu", "neg"], weights=[3, 3, 4])[0]
        followup = random.choice({"pos": POSITIVE, "neu": NEUTRAL, "neg": NEGATIVE}[tone])
        cur.executemany(
            "INSERT INTO comments (ticket_id, comment_text, commented_by) VALUES (%s,%s,%s);",
            [(ticket_id, issue["desc"], "customer"),
             (ticket_id, issue["ai"],   "ai"),
             (ticket_id, followup,      "customer")])

        # ai_analysis (one resolution-decision row per ticket)
        cur.execute(
            """INSERT INTO ai_analysis
               (ticket_id, category_prediction, similarity_score, confidence_score,
                source_used, decision_reason, runbook_score, runbook_resolution,
                rag_complaint, rag_resolution)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
            (ticket_id, issue["category"], issue.get("sim"), issue.get("conf"),
             issue["source"], f"Mock decision ({issue['source']})",
             issue.get("rb"), issue.get("rb_res"),
             issue.get("rag_c"), issue.get("rag_r")))

    conn.commit()
    cur.close()
    conn.close()
    print(f"Inserted {N_TICKETS} tickets with comments + ai_analysis. "
          f"operational_analysis left empty for your agents.")


if __name__ == "__main__":
    main()