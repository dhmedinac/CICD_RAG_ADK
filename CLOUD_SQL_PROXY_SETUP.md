# Cloud SQL Auth Proxy Sidecar Setup

This document explains the Cloud SQL Auth Proxy sidecar configuration for your RAG Agent application running on Cloud Run.

## Overview

The application now uses **Cloud SQL Auth Proxy** deployed as a sidecar container in Cloud Run to manage database connections. This approach:

- Uses standard `postgresql+asyncpg://` URLs that ADK can parse directly
- Handles Cloud SQL authentication automatically via GCP service account credentials
- Proxies connections from `localhost:5432` to the Cloud SQL instance
- Works identically in both local development and Cloud Run environments

## Architecture

```
┌─────────────────────────────────────────┐
│          Cloud Run Service              │
├─────────────────────────────────────────┤
│ ┌──────────────────────────────────────┐│
│ │  RAG Agent Application               ││
│ │  (Connects to localhost:5432)         ││
│ └──────────────────────────────────────┘│
│             ↓ (TCP on :5432)            │
│ ┌──────────────────────────────────────┐│
│ │  Cloud SQL Auth Proxy Sidecar        ││
│ │  (gcr.io/cloud-sql-docker/proxy)    ││
│ │  Listens on localhost:5432           ││
│ └──────────────────────────────────────┘│
│             ↓ (SSL/TLS)                 │
└────────────────┬────────────────────────┘
                 │
        ┌────────▼────────┐
        │   Cloud SQL     │
        │   PostgreSQL    │
        │   Instance      │
        └─────────────────┘
```

## Files Changed

### 1. `service.yaml` (New)
Defines the Cloud Run service with:
- Main container: RAG Agent application
- Sidecar container: Cloud SQL Auth Proxy
- Environment variables and secrets configuration

**Key sidecar configuration:**
```yaml
- name: cloud-sql-proxy
  image: gcr.io/cloud-sql-docker/cloud-sql-proxy:1.33.2
  args:
    - PROJECT_ID:REGION:INSTANCE_NAME
    - --port=5432
```

### 2. `cloudbuild.yaml`
Updated deployment step to:
- Substitute placeholders in `service.yaml` (image, project IDs, instance name, corpus)
- Deploy using `gcloud run replace` with the service YAML

**Key deployment command:**
```bash
gcloud run replace /workspace/service.yaml \
  --region=${_REGION} \
  --project=${PROJECT_ID}
```

### 3. `src/rag_agent/config.py`
Fixed comments and validation message to clarify:
- Both local dev and Cloud Run use `postgresql+asyncpg://localhost:5432/database`
- Explained the proxy sidecar setup on Cloud Run

### 4. `.env.example`
Updated database URL format documentation to reflect localhost approach.

## Database URL Format

Both local development and Cloud Run use the same format:

```
postgresql+asyncpg://user:password@localhost:5432/database
```

### For Local Development
The PostgreSQL server must be running on `localhost:5432`

### For Cloud Run
The Cloud SQL Auth Proxy sidecar listens on `localhost:5432` and proxies to Cloud SQL

## Deployment Flow

1. **Cloud Build Build Step**: Docker image is built with application code
2. **Cloud Build Corpus Sync Step**: RAG corpus is synced from GCS
3. **Cloud Build Deploy Step**:
   - Substitutes actual values into `service.yaml`
   - Deploys service with `gcloud run replace`
   - Cloud Run creates both containers:
     - RAG Agent on port 8080
     - Cloud SQL Auth Proxy on port 5432 (sidecar)

## Prerequisites

### GCP Setup (if not already done)
1. Cloud SQL PostgreSQL instance exists: `rag-agent-postgres`
2. Database created: `rag_agent_sessions`
3. Database user created: `rag_agent`
4. Secret Manager secrets exist:
   - `rag-agent-api-key`: Your API key
   - `rag-agent-database-url`: Full PostgreSQL URL (format: `postgresql+asyncpg://user:password@localhost:5432/database`)
5. Cloud Run service account has `roles/cloudsql.client` IAM role

### Local Development
1. PostgreSQL 16 installed and running on `localhost:5432`
2. Database and user created (see POSTGRESQL_MIGRATION.md)
3. `.env` file with `DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_agent_sessions`

## Verification

### Check Cloud Run Logs
```bash
gcloud run logs read rag-agent-dev \
  --limit=100 \
  --project=rag-agent-dev-499614 \
  --region=europe-west1
```

Look for successful startup and no database connection errors.

### Check Database Connection
```bash
# Port-forward the proxy to verify connectivity
gcloud cloud-sql-proxy rag-agent-dev-499614:europe-west1:rag-agent-postgres \
  --port=5432

# In another terminal, connect with psql
psql -h localhost -U rag_agent -d rag_agent_sessions
```

### Verify Session Persistence
```bash
# Make a request to the application
curl https://rag-agent-dev-*.run.app/health

# Check that sessions table exists
psql -h CLOUD_SQL_IP -U rag_agent -d rag_agent_sessions -c "\dt"
SELECT * FROM sessions LIMIT 1;
```

## Troubleshooting

### "Connection refused" errors
- Verify Cloud SQL Auth Proxy sidecar is running: check Cloud Run service details
- Verify Cloud Run service account has `roles/cloudsql.client` role
- Check sidecar image is accessible: `gcloud run services describe rag-agent-dev`

### "Authentication failed" from proxy
- Verify `roles/cloudsql.client` IAM role on runtime service account
- Check Cloud SQL instance exists and is in the same project/region
- Verify instance name in `service.yaml` matches Cloud SQL instance name

### "Relation does not exist" on first run
- This is expected if tables don't exist yet
- ADK will create session tables automatically
- Check logs for table creation messages

### Database URL format errors
- Verify `DATABASE_URL` secret uses correct format: `postgresql+asyncpg://user:password@localhost:5432/database`
- Verify local `.env` also uses `postgresql+asyncpg://` scheme
- Do NOT use `postgresql+cloudsql://` or other schemes

## Resource Limits

The proxy sidecar has these resource constraints (configured in `service.yaml`):
```yaml
requests:
  memory: 64Mi
  cpu: 100m
limits:
  memory: 256Mi
  cpu: 500m
```

Adjust if experiencing connection pool exhaustion or timeouts.

## Security Notes

- The proxy runs as a sidecar in the same Cloud Run container group
- No inbound traffic on port 5432 from outside Cloud Run
- GCP authentication is automatic via service account credentials
- SSL/TLS communication between proxy and Cloud SQL is automatic

## Next Steps

1. Commit these changes:
   ```bash
   git add service.yaml cloudbuild.yaml src/rag_agent/config.py .env.example
   git commit -m "Configure Cloud SQL Auth Proxy as Cloud Run sidecar"
   ```

2. Verify the service account has `roles/cloudsql.client`:
   ```bash
   gcloud projects get-iam-policy rag-agent-dev-499614 \
     --flatten="bindings[].members" \
     --filter="bindings.role:roles/cloudsql.client"
   ```

3. Push to trigger Cloud Build:
   ```bash
   git push origin dev
   ```

4. Monitor deployment and verify logs