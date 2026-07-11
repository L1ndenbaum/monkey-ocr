# MonkeyOCR

MonkeyOCR is an asynchronous OCR service for PDF and image documents. It uses
PaddleOCR-VL HPS on production GPUs, Kafka for durable dispatch, PostgreSQL 18
for job/checkpoint state, S3-compatible storage for every document artifact,
and ClickHouse for redacted structured logs.

The public deployment path is:

```text
Internet -> server Nginx (TLS) -> Go gateway :13000 -> FastAPI :13001
                                      |              |
                                    Redis      PostgreSQL/Kafka/S3
                                                     |
                                               OCR worker -> HPS :13005
```

## API contract

Every JSON response wraps its DTO in `ApiEnvelope<T>`:

```json
{
  "internal_code": 0,
  "message": "操作成功",
  "data": {},
  "timestamp": "2026-07-11T00:00:00Z",
  "request_id": "019...",
  "error_reason": null
}
```

Only HTTP 200, 500, 502, and 504 are exposed. HTTP describes whether the
transport completed; `internal_code` describes the business result. The
language-neutral registry is `backend/contracts/internal_status_codes.json`.

The asynchronous API surface is:

- `POST /v1/uploads`
- `POST /v1/uploads/{upload_id}/complete`
- `POST /v1/jobs`
- `GET /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/events`
- `POST /v1/jobs/{job_id}/cancel`
- `POST /v1/jobs/{job_id}/retry`
- `GET /v1/jobs/{job_id}/artifacts`

The legacy synchronous `/api/process` and `/api/process-base64` APIs do not
exist in this version.

Each job is checkpointed per normalized page. A failed page receives the
initial attempt plus three exponential retries; a worker restart resumes from
the persisted page checkpoint instead of reprocessing completed pages. Job
state and its SSE event are committed in one PostgreSQL transaction, and job
updates use optimistic revisions so a concurrent cancellation cannot be
overwritten by a stale worker snapshot.

Successful jobs expose Markdown, structured JSON, normalized page images,
engine visualizations, and a manifest containing hashes, MIME types, page
numbers, model metadata, and object keys. Completed jobs and their job-owned
objects are retained for 30 days by default. Original uploads are removed only
after no job still references them.

## Local development

Local development uses a deterministic fake engine and does not require CUDA
or model downloads.

```bash
backend/scripts/compose.sh dev init-env
backend/scripts/compose.sh dev up -d --build
docker exec monkeyocr-backend python -m src.interfaces.cli.api_keys create --name dev
backend/scripts/compose.sh dev ps
```

The key-creation command prints the plaintext key once. Paste it into the web
client at `http://localhost:13002`; the browser keeps it in session storage.

The defaults expose gateway `13000`, backend `13001`, frontend `13002`,
storage-service `13003`, logging-service `13004`, PostgreSQL `13006`, Kafka
`13007`, Redis `13008`, MinIO `13009/13010`, and ClickHouse `13011/13012`.

To run backend tests without Compose:

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests
```

## Production

Production does not create PostgreSQL, Kafka, Redis, MinIO/S3, or ClickHouse.
Configure those host services in `backend/dotenv/production/` first.
PostgreSQL 18 is required because the initial migration uses native
`uuidv7()`. The one-shot `kafka-init` service connects to the external broker
and creates `monkeyocr.events.jobs`, `monkeyocr.events.jobs.dlq`, and
`monkeyocr.events.logging.v1`; it does not run a Kafka broker.

Prepare the official PaddleOCR-VL HPS appliance once on the A10 server:

```bash
backend/scripts/compose.sh production init-env
# Replace every change-me value in backend/dotenv/production before startup.
backend/scripts/prepare_hps.sh
backend/scripts/compose.sh production up -d --build
```

Production startup fails closed while any generated placeholder secret remains.
The API-key pepper and service tokens must contain at least 32 characters;
database, Redis, ClickHouse, and MinIO passwords must contain at least 16.
Configure the external S3/MinIO bucket CORS policy for the public frontend
origin before accepting uploads: allow `GET`, `HEAD`, and `PUT`, allow request
headers, and expose `ETag` for multipart completion. The development stack
applies `backend/infrastructure/minio/cors.xml` automatically.

HPS defaults to PaddleOCR-VL-1.6/PaddleX 3.6 and is bound only to
`127.0.0.1:13005`. Its Triton and vLLM members retain the official private
network topology while retaining outbound access for the online model image;
downloaded model caches persist in `monkeyocr_hps_model_cache`. Pin
`HPS_VLM_IMAGE` to an immutable digest for a controlled release. The worker
waits for HPS, storage, PostgreSQL, and the parser sandbox to become ready
before consuming Kafka, so model warm-up does not spend page retry attempts.
Project-owned production containers use host networking.
Document parsing is handled by a separate read-only, networkless sandbox
container that exchanges only validated page files with the backend.

Build-time proxies and package mirrors live in
`backend/dotenv/{dev,production}/.env.build`. They are wired into project image
builds and the HPS preparation script without becoming runtime configuration.
Set `MONKEYOCR_ENABLE_HPS=0` only when production uses an independently managed
HPS endpoint or when inspecting Compose configuration before preparing HPS.

Terminate TLS at server Nginx with the sample in
`backend/infrastructure/nginx/monkeyocr.conf.example`. Do not expose backend,
storage, logging, HPS, or infrastructure ports publicly.

## API keys

API keys are issued and revoked by administrators. Plaintext is printed only
when a key is created; the database stores a salted PBKDF2 hash and prefix.
Keys belong in `Authorization: Bearer <key>` and should only be kept in browser
session storage.

See the CLI help after installing backend dependencies:

```bash
PYTHONPATH=backend python -m src.interfaces.cli.api_keys --help
```
