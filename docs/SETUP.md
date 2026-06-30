# Setup & Deployment Guide

End-to-end setup for the two-environment (dev/prod) RAG agent pipeline.

## 0. Prerequisites

- Two GCP projects. Defaults assume `rag-agent-dev` and `rag-agent-prod` — change
  them in `config/dev.env` / `config/prod.env` (and the example IDs below) if yours differ.
- Billing enabled on both projects.
- A GitHub repo with two long-lived branches: `dev` and `prod`.
- `gcloud` authenticated (`gcloud auth login`) with Owner/Editor on both projects.

## 1. Branch & project mapping

| Branch | GCP project     | Cloud Run service | Approval |
| ------ | --------------- | ----------------- | -------- |
| `dev`  | `rag-agent-dev` | `rag-agent-dev`   | none     |
| `prod` | `rag-agent-prod`| `rag-agent-prod`  | required |

Work happens on `dev`. To release, open a PR from `dev` → `prod` and merge; the
prod trigger then waits for manual approval before deploying.

## 2. Bootstrap each project (once)

```bash
./scripts/bootstrap.sh dev     # or:  .\scripts\bootstrap.ps1 dev
./scripts/bootstrap.sh prod    #      .\scripts\bootstrap.ps1 prod
```

This enables APIs and creates, idempotently:

- Firestore API (for session persistence)
- Artifact Registry repo `rag-agent`
- GCS corpus bucket (from `GCS_SOURCE` in the env file)
- Runtime SA `rag-agent-runtime@…` — roles: `aiplatform.user`,
  `storage.objectViewer`, `secretmanager.secretAccessor`, `datastore.user`
- CI SA `rag-agent-ci@…` — roles: `run.admin`, `artifactregistry.writer`,
  `aiplatform.user`, `storage.admin`, `logging.logWriter`, plus
  `iam.serviceAccountUser` on the runtime SA
- Empty Secret Manager secret `rag-agent-api-key`

## 3. Add the API key and documents

```bash
# Pick a strong key; store it for your API clients. Project value is the project id in GCP
printf 'CHANGE_ME_STRONG_KEY' | \
  gcloud secrets versions add rag-agent-api-key --data-file=- --project=rag-agent-dev

# Upload source documents (PDF, TXT, HTML, MD, …) to the corpus bucket.
gcloud storage cp ./docs/* gs://rag-agent-dev-corpus/
```

Repeat for prod with its own key and bucket.

## 4. Connect GitHub to Cloud Build

In each project: **Cloud Build → Triggers → Connect Repository**, choose GitHub
(Cloud Build GitHub App), authorize, and select the repo.

## 5. Create the triggers

**Dev trigger** (project `rag-agent-dev`):

```bash
gcloud builds triggers create github \
  --name=rag-agent-dev \
  --repo-owner=YOUR_GH_ORG --repo-name=YOUR_REPO \
  --branch-pattern='^dev$' \
  --build-config=cloudbuild.yaml \
  --service-account=projects/rag-agent-dev/serviceAccounts/rag-agent-ci@rag-agent-dev.iam.gserviceaccount.com \
  --region=us-central1 \
  --substitutions=_ENV=dev,_GCS_SOURCE=gs://rag-agent-dev-corpus/,_RUNTIME_SA=rag-agent-runtime@rag-agent-dev.iam.gserviceaccount.com
```

**Prod trigger** (project `rag-agent-prod`) — note `--require-approval`:

```bash
gcloud builds triggers create github \
  --name=rag-agent-prod \
  --repo-owner=YOUR_GH_ORG --repo-name=YOUR_REPO \
  --branch-pattern='^prod$' \
  --build-config=cloudbuild.yaml \
  --service-account=projects/rag-agent-prod/serviceAccounts/rag-agent-ci@rag-agent-prod.iam.gserviceaccount.com \
  --region=us-central1 \
  --require-approval \
  --substitutions=_ENV=prod,_GCS_SOURCE=gs://rag-agent-prod-corpus/,_RUNTIME_SA=rag-agent-runtime@rag-agent-prod.iam.gserviceaccount.com
```

> The CI service account must also be granted the `Cloud Build Service Account`
> usage; bootstrap handles the project-level roles. If the trigger UI complains
> about the SA, grant `roles/cloudbuild.builds.editor` to your user and re-run.

## 6. First deploy

- Push to `dev`. Watch **Cloud Build → History** in `rag-agent-dev`.
- The build: builds the image → pushes → `manage_corpus.py sync` (creates the
  corpus + imports from GCS) → `gcloud run deploy`.
- Grab the URL: `gcloud run services describe rag-agent-dev --region=us-central1 --format='value(status.url)'`
- Smoke test: `curl $URL/health` (open), then the `/run` calls from the README
  with your `X-API-Key`.

Release to prod: merge `dev` → `prod`, then **approve** the pending build in
`rag-agent-prod`'s Cloud Build console.

## 7. How config flows

- **Non-secret config** → trigger `--substitutions` (mirrored in `config/*.env`
  for reference and the bootstrap script) → Cloud Run env vars.
- **Secret** (`API_KEY`) → Secret Manager → mounted via `--set-secrets` at deploy.
- **Corpus** → `manage_corpus.py` prints `RAG_CORPUS=<resource>`; the deploy step
  captures it and sets it as an env var so cold starts skip the lookup.

## Tuning

| Setting | Where | Notes |
| ------- | ----- | ----- |
| Model | `_AGENT_MODEL` substitution / `AGENT_MODEL` | e.g. `gemini-2.5-pro` |
| Retrieval depth | `SIMILARITY_TOP_K`, `VECTOR_DISTANCE_THRESHOLD` | env vars on Cloud Run |
| Chunking | `CHUNK_SIZE`, `CHUNK_OVERLAP` in `scripts/manage_corpus.py` | re-import after change |
| Scaling | `_MIN_INSTANCES`, `_MAX_INSTANCES`, `_CPU`, `_MEMORY` | substitutions |
