# API Inventory

This file lists every HTTP API route currently defined in the `operational-intelligence` repo, what each one does, where it lives, and where it is called from.

## Summary

- Actual HTTP routes found: 4
- FastAPI docs routes are also enabled: `/docs` and `/redoc`
- No real frontend API callers were found in this checkout. The `frontend/` tree currently contains only `README.md` placeholders.

## Routes

| Method | Path | File | What it does | Called from |
|---|---|---|---|---|
| `GET` | `/health` | [`backend/main.py`](backend/main.py) | Liveness/health probe for orchestrators and load balancers. Returns `{"status": "healthy"}`. | Not called by repo code. Typically called by infra, uptime checks, or load balancers. |
| `POST` | `/api/v1/events/capture` | [`backend/api/v1/endpoints/events.py`](backend/api/v1/endpoints/events.py) | Captures a single operational interaction event and persists it into `operational_analysis`. The endpoint validates the payload and delegates persistence to `EventProcessor`. | Called by external clients or the upstream service layer. Inside the repo, the endpoint calls [`EventProcessor.capture_event()`](backend/services/event_processor.py). |
| `GET` | `/api/v1/clustering/customer/{customer_id}` | [`backend/api/v1/endpoints/clustering.py`](backend/api/v1/endpoints/clustering.py) | Returns customer clustering analysis, similarity groups, repeat-issue metadata, time clusters, and issue clusters for a given customer UUID. | Called by external clients or the dashboard layer. Inside the repo, the endpoint calls [`CustomerClusteringService.get_customer_interactions()`](backend/services/customer_clustering_service.py) and [`CustomerClusteringService.group_customer_issues()`](backend/services/customer_clustering_service.py). |
| `GET` | `/api/v1/intelligence/risk/{ticket_id}` | [`backend/api/v1/endpoints/intelligence.py`](backend/api/v1/endpoints/intelligence.py) | Returns the latest stored escalation risk snapshot for a ticket. It does not recompute risk. | Called by external clients or dashboards. Inside the repo, the endpoint calls [`InteractionRepository.get_latest_analysis()`](backend/repositories/interaction_repository.py). |

## Router Wiring

- [`backend/main.py`](backend/main.py) mounts the v1 API router at `settings.API_V1_PREFIX`, which is `/api/v1`.
- [`backend/api/v1/api.py`](backend/api/v1/api.py) registers:
  - `events.router` at `/events`
  - `clustering.router` at `/clustering`
  - `intelligence.router` at `/intelligence`

## Internal Call Chain

### Capture Flow

1. Client calls `POST /api/v1/events/capture`
2. [`backend/api/v1/endpoints/events.py`](backend/api/v1/endpoints/events.py) creates `EventProcessor`
3. [`backend/services/event_processor.py`](backend/services/event_processor.py) maps request data to `OperationalAnalysis`
4. [`backend/repositories/interaction_repository.py`](backend/repositories/interaction_repository.py) persists the row

### Clustering Flow

1. Client calls `GET /api/v1/clustering/customer/{customer_id}`
2. [`backend/api/v1/endpoints/clustering.py`](backend/api/v1/endpoints/clustering.py) creates `CustomerClusteringService`
3. [`backend/services/customer_clustering_service.py`](backend/services/customer_clustering_service.py) reads interaction rows and Qdrant data
4. [`backend/repositories/cluster_repository.py`](backend/repositories/cluster_repository.py) performs DB queries and cluster persistence

### Risk Lookup Flow

1. Client calls `GET /api/v1/intelligence/risk/{ticket_id}`
2. [`backend/api/v1/endpoints/intelligence.py`](backend/api/v1/endpoints/intelligence.py) fetches the latest row
3. [`backend/repositories/interaction_repository.py`](backend/repositories/interaction_repository.py) returns the stored risk snapshot

## Current Usage Status

- No concrete frontend callers were found in the repo.
- The `frontend/` tree contains folder documentation only, so there are no `fetch`, `axios`, or similar API call implementations in this checkout.
- The backend APIs are therefore currently exposed, but not wired to an implemented UI in this repository snapshot.

## Auto-Generated Docs

- FastAPI OpenAPI docs: `/docs`
- FastAPI ReDoc docs: `/redoc`

## Notes

- If you add frontend code later, this inventory should be updated with the exact service/module and function that calls each endpoint.
- If more routes are added under `backend/api/v1/endpoints/`, they should be appended here.
