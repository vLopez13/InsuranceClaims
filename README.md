# InsuranceClaims

Prior-authorization API for surgery requests. A request is checked by configurable business rules, scored by a pluggable medical-necessity model, and then either auto-approved or queued for a person. The service never auto-denies.

The product decisions for this milestone are in [docs/m1-decisions.md](docs/m1-decisions.md).

## Flow

```text
POST /api/v1/claims
        |
        v
Business rules  -->  scorer  -->  router
        |                |            |
        |                |            +--> approved          (score >= APPROVE_T and rules pass)
        |                |            +--> pended_docs       (missing documents is the only failure)
        |                +------------+--> in_triage         (any other failure, low score, or scorer error)
        |
        +--> 422 for schema, format, unknown patient, or unknown provider (not stored)
```

`APPROVE_T` is **0.80**. A score equal to 0.8000 after `ROUND_HALF_UP` to four decimal places is approved. `HIGH_AMOUNT_T` is **70000.00**. A requested amount above that goes to triage even when the score is high. Exactly 70000.00 does not.

Required documents are `letter_of_medical_necessity` and `clinical_notes`.

### Status

| From | To |
| --- | --- |
| submitted | pended_docs, in_triage, approved, withdrawn |
| pended_docs | in_triage, approved, withdrawn |
| in_triage | approved, denied, pended_docs, withdrawn |
| approved, denied, withdrawn | terminal |

Only a human reviewer can set `denied` (`POST /api/v1/claims/{id}/decision`, header `X-Reviewer-Id`). Only the submitting provider can withdraw (`POST /api/v1/claims/{id}/withdraw`, header `X-Provider-Id`). A same-status or otherwise illegal transition returns 409 and writes an audit row with action `transition_rejected`.

## Layout

- `app/services/rules` — pure rules. Add a class and register it in `build_rules_engine`.
- `app/services/scoring` — `MedicalNecessityScorer` protocol. `SCORER_IMPL=heuristic` or `stub`.
- `app/services/decision` — state machine and router. The router depends only on `ScoreResult`.
- `app/services/documents` — file reference, SHA-256, and MIME type. Bytes stay in the store. `DocumentTextExtractor` is the OCR seam and is not called yet.
- `app/services/integrations` — `integration_outbox` rows for a later Salesforce Case worker. Payloads are ids and reason codes.
- `alembic` — schema and synthetic seed. Legacy SQL files are retired.

To swap the scorer, implement `score(features) -> ScoreResult` and register it in `app/services/scoring/factory.py`, or assign `app.state.scorer` in a test. Features are codes, specialty, document types, priority, amount, and two booleans. Failures return a `ScoreResult` with `error` set. A timeout of 5 seconds discards a late result and leaves the claim in triage.

## API

All `/api/v1` routes require `X-API-Key`. `POST /api/v1/claims` also requires `Idempotency-Key` (missing → 400). The same key and canonical body replays 200. A different body, or a key still in progress, returns 409.

| Method | Path | Success |
| --- | --- | --- |
| POST | `/api/v1/claims` | 201, or 200 on replay |
| GET | `/api/v1/claims/{id}` | 200 |
| GET | `/api/v1/triage` | 200, urgency then oldest `submitted_at` then id |
| POST | `/api/v1/claims/{id}/documents` | 201; 413 over 20 MiB; 415 bad magic bytes; 409 if terminal |
| POST | `/api/v1/claims/{id}/decision` | 200 |
| POST | `/api/v1/claims/{id}/withdraw` | 200 |
| GET | `/api/v1/claims/{id}/audit` | 200 |
| GET | `/api/v1/metrics` | 200 |
| GET | `/health` | 200 |

An upload is allowed on `submitted`, `pended_docs`, and `in_triage`. Only an upload to `pended_docs` re-runs rules and the scorer. `submitted_at` does not move. Audit actions for that re-run are `document_uploaded`, `rules_rerun`, then `routed`.

Straight-through rate is `auto_approved / persisted claims excluding withdrawn`. Decision latency is `decided_at - submitted_at`. Routing latency is `routed_at - submitted_at`. Percentiles are nearest-rank.

## Configuration

Copy `.env.example` to `.env`. Nothing secret is committed. Do not log request bodies; validation and database errors are returned without the submitted values or MySQL's `Duplicate entry` text.

| Variable | Default |
| --- | --- |
| `DATABASE_URL` | MySQL URL (`mysql+pymysql://`) |
| `API_KEY` | required, at least 8 characters |
| `APPROVE_T` | `0.80` |
| `HIGH_AMOUNT_T` | `70000.00` |
| `SCORER_TIMEOUT_SECONDS` | `5` |
| `SCORER_IMPL` | `heuristic` or `stub` |
| `THRESHOLD_VERSION` / `RULES_VERSION` | stored on each audit row |

Invalid thresholds fail process startup. The failure text names the setting and does not print the value.

## Run

```bash
docker compose up --build
```

The API listens on `127.0.0.1:8000` and MySQL on `127.0.0.1:3306`. Migrations and the synthetic seed run before the app serves traffic. Local passwords in `docker-compose.yml` are development placeholders.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d db
export TEST_DATABASE_URL=mysql+pymysql://claims:devpassword@127.0.0.1:3306/insurance_claims_test?charset=utf8mb4
export MYSQL_ADMIN_URL=mysql+pymysql://claims:devpassword@127.0.0.1:3306/mysql?charset=utf8mb4
pytest
ruff check app tests
```

Tests run against MySQL so foreign keys, enums, and checks are enforced. Seed patients use `@example.com` addresses. Provider NPIs fail the NPI checksum and tax ids use the unissued `00-` prefix.
