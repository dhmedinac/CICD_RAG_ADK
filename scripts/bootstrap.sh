#!/usr/bin/env bash
#
# One-time GCP setup for a single environment (dev or prod). Idempotent.
# Run once per project, e.g. in Cloud Shell:
#
#   ./scripts/bootstrap.sh dev
#   ./scripts/bootstrap.sh prod
#
# Reads config/<env>.env for PROJECT_ID, REGION, etc.

set -euo pipefail

ENV_NAME="${1:?usage: bootstrap.sh <dev|prod>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="${HERE}/config/${ENV_NAME}.env"
[ -f "${CONF}" ] || { echo "Missing ${CONF}"; exit 1; }
# shellcheck disable=SC1090
set -a; source "${CONF}"; set +a

BUCKET="${GCS_SOURCE#gs://}"; BUCKET="${BUCKET%%/*}"
RUNTIME_SA_ID="rag-agent-runtime"
CI_SA_ID="rag-agent-ci"
RUNTIME_SA="${RUNTIME_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
CI_SA="${CI_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "== Project: ${PROJECT_ID} (env=${ENV_NAME}, region=${REGION})"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "== Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  firestore.googleapis.com

echo "== Artifact Registry repo: ${AR_REPO}"
gcloud artifacts repositories describe "${AR_REPO}" --location="${REGION}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker --location="${REGION}" \
    --description="RAG agent images"

echo "== GCS corpus bucket: gs://${BUCKET}"
gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" --uniform-bucket-level-access

echo "== Runtime service account: ${RUNTIME_SA}"
gcloud iam service-accounts describe "${RUNTIME_SA}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${RUNTIME_SA_ID}" --display-name="RAG agent runtime"
for role in roles/aiplatform.user roles/storage.objectViewer roles/secretmanager.secretAccessor roles/datastore.user; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" --role="${role}" --condition=None >/dev/null
done

echo "== CI service account: ${CI_SA}"
gcloud iam service-accounts describe "${CI_SA}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${CI_SA_ID}" --display-name="RAG agent CI/CD"
for role in roles/run.admin roles/artifactregistry.writer roles/aiplatform.user \
            roles/storage.admin roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CI_SA}" --role="${role}" --condition=None >/dev/null
done
# CI must be able to deploy Cloud Run services that run AS the runtime SA.
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member="serviceAccount:${CI_SA}" --role="roles/iam.serviceAccountUser" >/dev/null

echo "== API key secret: ${API_KEY_SECRET}"
if ! gcloud secrets describe "${API_KEY_SECRET}" >/dev/null 2>&1; then
  gcloud secrets create "${API_KEY_SECRET}" --replication-policy=automatic
  echo "  -> Add a value:  printf 'YOUR_KEY' | gcloud secrets versions add ${API_KEY_SECRET} --data-file=- --project=${PROJECT_ID}"
fi

cat <<EOF

== Done for ${PROJECT_ID}.

Next:
  1. Put a real API key in Secret Manager (command printed above, if new).
  2. Upload documents:  gcloud storage cp ./your-docs/* gs://${BUCKET}/
  3. Connect this repo to Cloud Build (Console > Cloud Build > Triggers > Connect Repository).
  4. Create the trigger (see docs/SETUP.md), using service account:
       ${CI_SA}
EOF
