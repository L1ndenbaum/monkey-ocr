# Repository Rules

## General

- Commit every completed logical change immediately after its verification succeeds.
- Keep each commit scoped to that completed change; never bundle unrelated or unfinished workspace changes.
- Keep changes scoped to the current task and preserve unrelated user changes.
- Use environment variables for all deploy-time addresses, credentials, ports, topics, buckets, and database names.
- Never commit real credentials, API keys, presigned URLs, OCR document content, or generated model artifacts.
- New public behavior requires tests at the appropriate domain, adapter, and interface boundaries.

## Backend architecture

- Python business code is context-first under `backend/src/contexts/ocr/`; OCR is the only business context and must not be split into bounded contexts.
- Domain code contains entities, value objects, state transitions, and pure rules. It must not depend on Application, Infrastructure, or Interfaces.
- Application code owns transport-neutral commands, DTOs, orchestration, worker scheduling, cancellation, retry, and checkpoint behavior.
- HTTP handlers under `backend/src/contexts/ocr/interfaces/http/v1/` only decode requests, invoke Application APIs, and translate results into the shared API contract.
- PostgreSQL, Kafka, object storage, PaddleOCR-VL, and logging clients belong under `backend/src/infrastructure/`; repositories must not depend on HTTP interfaces.
- PostgreSQL schema changes use `backend/alembic/`. Runtime table creation or mutation is forbidden.
- JSON APIs always return `ApiEnvelope<T>` with `internal_code`; the field name `code` is forbidden in the envelope, generated clients, and structured API logs.
- Public HTTP status codes are limited to 200, 500, 502, and 504. Business outcomes use `InternalStatusCode`.
- Kafka payloads carry identifiers and schema versions, never document bytes or OCR content. Consumers must be idempotent.

## Go services

- Shared HTTP, logging, and environment primitives belong in `backend/services/lib-go`.
- Gateway authentication, rate limiting, request IDs, transport error mapping, and reverse proxying stay separate from backend business logic.
- Gateway-generated JSON and upstream JSON must conform to the shared `ApiEnvelope` contract.

## Frontend

- Use React, TypeScript, Radix UI, Tailwind CSS, and Axios.
- API access belongs in infrastructure modules; pages must not construct raw HTTP requests.
- Axios interceptors decide business success from `internal_code`, never from HTTP 200 alone.
- API keys may be held in browser session storage only and must never be logged.

## Deployment

- `backend/scripts/compose.sh dev|production` is the supported entrypoint.
- Dev compose provides infrastructure containers. Production compose uses host networking and must not provide PostgreSQL, Kafka, Redis, MinIO/S3, or ClickHouse containers.
- Dev and production dotenv examples remain separate. Example topics, buckets, consumer groups, and database names use the `monkeyocr` prefix; example ports start at 13000 and remain configurable.
