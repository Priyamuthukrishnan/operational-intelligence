# Operational Intelligence API Reference Documentation

## Backend startup

```powershell
cd backend
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload
```

On macOS or Linux, use `cp .env.example .env` instead of `Copy-Item`.

This document describes the REST API endpoints, schemas, request parameters, and response structures for the Operational Intelligence platform's analytics and enrichment layer.

---

## Global API Configuration
- **Base Path Prefix:** `/api/v1`
- **Default Port (Local):** `http://localhost:8000` (or as configured in `.env`)
- **Format:** All requests and responses use `application/json` format.

---

## Summary of Endpoints

| Endpoint | Method | Tag | Description |
|---|---|---|---|
| [`/`](#1-api-root-health) | `GET` | `root` | Root API discovery / health check |
| [`/health`](#2-liveness-probe) | `GET` | `health` | Core liveness health check probe |
| [`/api/v1/events/capture`](#3-capture-an-interaction-event) | `POST` | `events` | Ingest ticket interaction event and trigger background enrichment |
| [`/api/v1/clustering/customer/{customer_id}`](#4-customer-clustering--similarity-analysis) | `GET` | `clustering` | Retrieve customer clustering, semantic groups, and time-granularity buckets |
| [`/api/v1/dashboard/operational`](#5-retrieve-operational-dashboard-metrics) | `GET` | `dashboard` | Aggregated dashboard metrics for support and operational teams |
| [`/api/v1/dashboard/executive`](#6-retrieve-executive-dashboard-summary) | `GET` | `dashboard` | High-level summary metrics for executive/C-suite reviews |
| [`/api/v1/dashboard/customer/{customer_id}`](#7-retrieve-customer-health-profile) | `GET` | `dashboard` | Detailed health profile and historic interactions for a specific customer |
| [`/api/v1/dashboard/refresh-trends`](#8-trigger-historical-trend-rollups) | `POST` | `dashboard` | Aggregates and recalculates metric rollups across all logs |
| [`/api/v1/intelligence/risk/{ticket_id}`](#9-retrieve-ticket-risk-snapshot) | `GET` | `intelligence` | Retrieve stored escalation risk and analytics detail for a ticket |

---

## Detailed Endpoint References

### 1. API Root Health
Basic discovery endpoint verifying that the service is running.

- **Route:** `GET /`
- **Response Code:** `200 OK`
- **Response Structure:**
  ```json
  {
    "message": "Operational Intelligence API"
  }
  ```

---

### 2. Liveness Probe
Liveness health check for orchestrators (e.g., Kubernetes) and load balancers.

- **Route:** `GET /health`
- **Response Code:** `200 OK`
- **Response Structure:**
  ```json
  {
    "status": "healthy"
  }
  ```

---

### 3. Capture an Interaction Event
Receives a ticket interaction event from the Service Intelligence layer, persists it in the database, and schedules downstream enrichment pipelines (sentiment, escalation risk, root cause, clustering) in the background.

- **Route:** `POST /api/v1/events/capture`
- **Response Code:** `201 Created`
- **Request Body (`EventCaptureRequest`):**

| Field | Type | Required | Description |
|---|---|---|---|
| `ai_analysis_id` | `UUID` | **Yes** | Unique identifier from the Service Intelligence layer |
| `ticket_id` | `UUID` | **Yes** | Source ticket identifier |
| `customer_id` | `UUID` | **Yes** | Customer identifier |
| `comment_id` | `UUID` | No | Specific comment within the ticket |
| `source_used` | `string` | No | Source agent helper (e.g., `rag`, `runbook`, `hybrid`, `human`, `manager`) |
| `assigned_agent_id` | `UUID` | No | Assigned agent identifier |
| `assigned_manager_id` | `UUID` | No | Assigned manager identifier |
| `resolution_state` | `string` | No | Resolution state snapshot (`open`, `waiting`, `resolved`, `closed`) |
| `query_summary` | `string` | No | AI-generated summary of the customer query |
| `response_summary` | `string` | No | AI-generated summary of the agent response |
| `sentiment_label` | `string` | No | Sentiment classification label (e.g., `negative`, `neutral`, `positive`) |
| `sentiment_score` | `float` | No | Sentiment score in range `[-1.0, 1.0]` |
| `escalation_risk_score` | `float` | No | Escalation risk probability in range `[0.0, 1.0]` |
| `escalation_risk_band` | `string` | No | Escalation risk band classification (e.g., `low`, `medium`, `high`, `critical`) |
| `root_cause_category` | `string` | No | Predicted root-cause category classification |
| `root_cause_confidence` | `float` | No | Confidence score of the root-cause prediction |
| `repeat_count` | `integer` | No | Number of times the issue has been repeated (non-negative) |
| `cluster_id` | `UUID` | No | Assigned cluster identifier |
| `qdrant_vector_id` | `string` | No | Vector ID in Qdrant store |
| `model_version` | `string` | No | Version of AI model used for analysis |

- **Request Example:**
  ```json
  {
    "ai_analysis_id": "4b92b678-43df-4033-91a5-81679093bf7b",
    "ticket_id": "b9623e10-c4e2-411a-be33-d1f2bfa5113d",
    "customer_id": "3c983a56-ee25-4c07-ba71-a083d03cb1df",
    "comment_id": "f5b828cd-bb88-410a-8bf8-d1d8df5c2692",
    "sentiment_label": "negative",
    "sentiment_score": -0.72,
    "escalation_risk_score": 0.85,
    "escalation_risk_band": "high",
    "model_version": "v2.1.0"
  }
  ```

- **Response Body (`EventCaptureResponse`):**

| Field | Type | Description |
|---|---|---|
| `status` | `string` | Outcome status of the capture operation (e.g., `"success"`) |
| `message` | `string` | Human-readable result status description |
| `operational_analysis_id` | `string` | Generated UUID of the persisted analytics record |

- **Response Example:**
  ```json
  {
    "status": "success",
    "message": "Event captured successfully",
    "operational_analysis_id": "d04a64a3-7fa3-4318-b2a6-06eb36573c09"
  }
  ```

---

### 4. Customer Clustering & Similarity Analysis
Assess customer interactions and retrieve semantic groupings, chronological clusters, similarity matches from the Qdrant store, and time-based metrics.

- **Route:** `GET /api/v1/clustering/customer/{customer_id}`
- **Path Parameters:**
  - `customer_id` (UUID, Required): Unique customer ID.
- **Response Code:** `200 OK`
- **Error Codes:**
  - `404 Not Found`: No interaction records exist for the specified customer.
- **Response Body (`CustomerClusteringResponse`):**

| Field | Type | Description |
|---|---|---|
| `customer_id` | `UUID` | The queried customer identifier |
| `interaction_count` | `integer` | Total interaction records found for this customer |
| `cluster_count` | `integer` | Number of similarity groups identified from vector search |
| `clusters` | `list[SimilarityGroup]` | Similarity groups from nearest-neighbour search |
| `vectors_available` | `integer` | Count of interactions having a vector representation |
| `vectors_missing` | `integer` | Count of interactions lacking a vector representation |
| `repeat_issues` | `list[RepeatIssueDetail]` | Repeat issue frequencies grouped by source vector similarity |
| `clustering_ready` | `boolean` | Flag indicating whether all required enrichment dependencies are satisfied |
| `pending_dependencies` | `list[string]` | Active intelligence module dependencies whose data is missing |
| `feature_placeholders` | `list[ClusteringFeaturePlaceholder]` | Enrichment states for each individual interaction |
| `repeat_pattern_metadata` | `RepeatPatternMetadata` | Aggregated statistics regarding repeat issue behaviors |
| `repeat_issue_clusters` | `list[RepeatIssueCluster]` | Chronologically grouped parent-subticket clusters |
| `customer_clusters` | `CustomerClusterSummary` | Customer-level rollups including average sentiment and risk |
| `issue_clusters` | `list[IssueClusterGroup]` | Semantically deduplicated issue clusters |
| `time_clusters` | `list[TimeClusterResult]` | Daily, weekly, and monthly time buckets of interactions |
| `persisted` | `boolean` | Indicates if the cluster grouping details were saved to PostgreSQL |

#### Sub-schemas

##### `SimilarityGroup`
```json
{
  "source_interaction_id": "uuid",
  "source_vector_id": "string",
  "similar_interactions": [
    {
      "interaction_id": "string",
      "similarity_score": 0.92,
      "payload": {}
    }
  ],
  "group_size": 1,
  "avg_similarity_score": 0.92
}
```

##### `RepeatIssueCluster`
```json
{
  "parent_interaction_id": "uuid",
  "parent_ticket_id": "uuid",
  "interaction_count": 3,
  "subticket_count": 2,
  "interaction_ids": ["uuid", "uuid", "uuid"],
  "ticket_ids": ["uuid", "uuid", "uuid"],
  "subticket_ids": ["uuid", "uuid"],
  "first_seen": "2026-07-01T08:00:00Z",
  "last_seen": "2026-07-09T12:00:00Z",
  "avg_similarity_score": 0.84,
  "avg_sentiment_score": -0.45,
  "avg_escalation_risk": 0.65
}
```

##### `TimeClusterResult`
```json
{
  "granularity": "weekly",
  "buckets": [
    {
      "period_label": "2026-W27",
      "granularity": "weekly",
      "interaction_count": 5,
      "ticket_ids": ["uuid"],
      "categories": ["billing", "account"],
      "has_repeat_issues": true
    }
  ],
  "total_periods": 1
}
```

---

### 5. Retrieve Operational Dashboard Metrics
Calculates operational indicators for support engineers and managers, displaying escalation queues, top root-cause counts, and current resolution rates.

- **Route:** `GET /api/v1/dashboard/operational`
- **Response Code:** `200 OK`
- **Response Body (`OperationalDashboardResponse`):**

| Field | Type | Description |
|---|---|---|
| `total_interactions` | `integer` | Count of all processed interaction snapshots |
| `total_tickets` | `integer` | Count of unique tickets tracked |
| `resolved_tickets` | `integer` | Count of tickets with response summaries |
| `resolution_rate` | `float` | Percent of resolved tickets over total tickets |
| `average_sentiment` | `float` | Mean sentiment score across all records |
| `average_escalation_risk` | `float` | Mean escalation risk score across all records |
| `critical_escalations_count` | `integer` | Count of tickets classified in critical/high risk bands |
| `recent_escalations` | `list[RecentEscalation]` | List of recent individual high-risk items |
| `top_categories` | `list[CategoryMetric]` | Categories sorted by occurrence volume |
| `recent_clusters` | `list[RecentCluster]` | Recently created or updated issue clusters |

- **Response Example:**
  ```json
  {
    "total_interactions": 150,
    "total_tickets": 120,
    "resolved_tickets": 90,
    "resolution_rate": 0.75,
    "average_sentiment": 0.12,
    "average_escalation_risk": 0.35,
    "critical_escalations_count": 12,
    "recent_escalations": [
      {
        "interaction_id": "b0f7dc68-60cf-46d5-a3cc-93e185854898",
        "ticket_id": "060d4e33-728f-4ad1-b223-289569fae7c9",
        "customer_id": "3c983a56-ee25-4c07-ba71-a083d03cb1df",
        "sentiment_label": "negative",
        "escalation_risk_score": 0.89,
        "escalation_risk_band": "critical",
        "query_summary": "Customer cannot access checkout portal",
        "captured_at": "2026-07-09T14:00:00Z"
      }
    ],
    "top_categories": [
      {
        "category": "Checkout Failure",
        "count": 45
      },
      {
        "category": "Password Reset",
        "count": 30
      }
    ],
    "recent_clusters": [
      {
        "cluster_id": "c1f7a268-30cf-48d5-b3cc-93e185854877",
        "cluster_name": "issue_cluster_1",
        "issue_category": "Checkout Failure",
        "frequency_count": 8,
        "last_seen_at": "2026-07-09T14:10:00Z"
      }
    ]
  }
  ```

---

### 6. Retrieve Executive Dashboard Summary
Provides high-level insights for leadership teams, showing overall customer health, weekly trends, and critical at-risk accounts.

- **Route:** `GET /api/v1/dashboard/executive`
- **Response Code:** `200 OK`
- **Response Body (`ExecutiveDashboardResponse`):**

| Field | Type | Description |
|---|---|---|
| `overall_health_index` | `float` | Weighted health score across all customer accounts (0-100) |
| `health_distribution` | `HealthDistribution` | Accounts grouped into healthy, warning, and critical buckets |
| `average_sentiment` | `float` | Combined mean sentiment score across all customer logs |
| `average_escalation_risk` | `float` | Combined mean escalation risk score |
| `risk_distribution` | `RiskDistribution` | Counts of interactions categorized by risk bands |
| `weekly_trends` | `list[TrendMetric]` | Historical rolling analytics for weekly intervals |
| `at_risk_customers` | `list[AtRiskCustomer]` | List of customer accounts requiring urgent outreach |

- **Response Example:**
  ```json
  {
    "overall_health_index": 78.4,
    "health_distribution": {
      "healthy_count": 85,
      "warning_count": 14,
      "critical_count": 3
    },
    "average_sentiment": 0.21,
    "average_escalation_risk": 0.28,
    "risk_distribution": {
      "critical_count": 3,
      "high_count": 9,
      "medium_count": 42,
      "low_count": 96
    },
    "weekly_trends": [
      {
        "period_label": "2026-W26",
        "interaction_count": 48,
        "ticket_count": 40,
        "resolution_rate": 0.80,
        "average_sentiment": 0.18,
        "average_escalation_risk": 0.31
      }
    ],
    "at_risk_customers": [
      {
        "customer_id": "3c983a56-ee25-4c07-ba71-a083d03cb1df",
        "health_score": 42.0,
        "sentiment_average": -0.45,
        "escalation_risk_average": 0.72,
        "interaction_count": 8
      }
    ]
  }
  ```

---

### 7. Retrieve Customer Health Profile
Obtain the complete health dashboard profile, historical timeline, and topic clusters for a single customer.

- **Route:** `GET /api/v1/dashboard/customer/{customer_id}`
- **Path Parameters:**
  - `customer_id` (UUID, Required): The identifier of the customer.
- **Response Code:** `200 OK`
- **Response Body (`CustomerDashboardResponse`):**

| Field | Type | Description |
|---|---|---|
| `customer_id` | `UUID` | The queried customer identifier |
| `health_score` | `float` | Customer health score scaled from `0` to `100` |
| `sentiment_average` | `float` | Historical mean sentiment score |
| `escalation_risk_average` | `float` | Historical mean risk score |
| `repeat_issue_frequency` | `float` | Ratio of repeat interactions to total interactions |
| `resolution_rate` | `float` | Ratio of resolved tickets for this customer |
| `interaction_count` | `integer` | Total interaction count in database |
| `interactions` | `list[CustomerInteractionDetail]` | Full list of historical interactions |
| `clusters` | `list[RecentCluster]` | Issue clusters linked with this customer's tickets |

- **Response Example:**
  ```json
  {
    "customer_id": "3c983a56-ee25-4c07-ba71-a083d03cb1df",
    "health_score": 42.0,
    "sentiment_average": -0.45,
    "escalation_risk_average": 0.72,
    "repeat_issue_frequency": 0.50,
    "resolution_rate": 0.60,
    "interaction_count": 10,
    "interactions": [
      {
        "interaction_id": "b0f7dc68-60cf-46d5-a3cc-93e185854898",
        "ticket_id": "060d4e33-728f-4ad1-b223-289569fae7c9",
        "query_summary": "Cannot access checkout portal",
        "response_summary": "Assigned to engineering team to fix cookies issue",
        "sentiment_label": "negative",
        "sentiment_score": -0.65,
        "escalation_risk_score": 0.82,
        "escalation_risk_band": "high",
        "root_cause_category": "Checkout Failure",
        "captured_at": "2026-07-09T14:00:00Z"
      }
    ],
    "clusters": [
      {
        "cluster_id": "c1f7a268-30cf-48d5-b3cc-93e185854877",
        "cluster_name": "issue_cluster_1",
        "issue_category": "Checkout Failure",
        "frequency_count": 8,
        "last_seen_at": "2026-07-09T14:10:00Z"
      }
    ]
  }
  ```

---

### 8. Trigger Historical Trend Rollups
Forces the aggregation engine to parse all interaction records and rebuild time-series summaries (daily, weekly, monthly rollups) for trend forecasting.

- **Route:** `POST /api/v1/dashboard/refresh-trends`
- **Response Code:** `200 OK`
- **Response Body:**
  ```json
  {
    "status": "success",
    "message": "Aggregation rollups generated successfully. Total records processed: 150"
  }
  ```

---

### 9. Retrieve Ticket Risk Snapshot
Fetch the latest persisted escalation risk details and risk engine diagnostics (such as confidence decay and momentum multipliers) for a single ticket.

- **Route:** `GET /api/v1/intelligence/risk/{ticket_id}`
- **Path Parameters:**
  - `ticket_id` (UUID, Required): Ticket identifier.
- **Response Code:** `200 OK`
- **Error Codes:**
  - `404 Not Found`: Escalation risk has not yet been computed/processed for the specified ticket.
- **Response Body:**

| Field | Type | Description |
|---|---|---|
| `ticket_id` | `UUID` | Source ticket identifier |
| `analysis_id` | `UUID` | Primary key of the analysis interaction record |
| `escalation_risk_score` | `float` | Escalation risk probability (0.0 to 1.0) |
| `escalation_risk_band` | `string` | Classification band (e.g., `low`, `medium`, `high`, `critical`) |
| `confidence_decay_score` | `float` | Exponential confidence decay value over time |
| `momentum_score` | `float` | Interaction velocity/momentum factor |
| `risk_multiplier` | `float` | Calculated multiplier applied to baseline risk |
| `risk_reason` | `string` | Natural language explanation justifying the risk level |
| `risk_processed` | `boolean` | Flag indicating whether risk processing has finished |
| `captured_at` | `datetime` | Timestamp of calculation snapshot |

- **Response Example:**
  ```json
  {
    "ticket_id": "060d4e33-728f-4ad1-b223-289569fae7c9",
    "analysis_id": "b0f7dc68-60cf-46d5-a3cc-93e185854898",
    "escalation_risk_score": 0.89,
    "escalation_risk_band": "critical",
    "confidence_decay_score": 0.95,
    "momentum_score": 1.25,
    "risk_multiplier": 1.15,
    "risk_reason": "Multiple repeated negative sentiment comments detected in short interval without successful agent resolution.",
    "risk_processed": true,
    "captured_at": "2026-07-09T14:00:00Z"
  }
  ```
