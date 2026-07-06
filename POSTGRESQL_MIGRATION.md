# PostgreSQL Migration Guide

This document outlines all steps needed to migrate from Firestore to PostgreSQL for session persistence on Cloud Run.

## PHASE 1: GCP SETUP

### Step 1: Create Cloud SQL PostgreSQL Instance

```bash
# Set environment variables
export PROJECT_ID="rag-agent-dev-499614"
export INSTANCE_NAME="rag-agent-postgres"
export REGION="europe-west1"
export DB_NAME="rag_agent_sessions"
export DB_USER="rag_agent"
export DB_PASSWORD=$(openssl rand -base64 32)  # Generate strong password
export RUNTIME_SA="rag-agent-runtime@rag-agent-dev-499614.iam.gserviceaccount.com"

# Create Cloud SQL instance
gcloud sql instances create $INSTANCE_NAME \
  --database-version=POSTGRES_16 \
  --region=$REGION \
  --tier=db-perf-optimized-1 \
  --storage-type=SSD \
  --storage-size=10GB \
  --backup \
  --enable-bin-log \
  --project=$PROJECT_ID

# Create database
gcloud sql databases create $DB_NAME \
  --instance=$INSTANCE_NAME \
  --project=$PROJECT_ID

# Create database user
gcloud sql users create $DB_USER \
  --instance=$INSTANCE_NAME \
  --password=$DB_PASSWORD \
  --project=$PROJECT_ID
```

### Step 2: Get Cloud SQL Connection Details

```bash
# Get the connection name (PROJECT:REGION:INSTANCE)
CONNECTION_NAME=$(gcloud sql instances describe $INSTANCE_NAME \
  --project=$PROJECT_ID \
  --format='value(connectionName)')
echo "Connection Name: $CONNECTION_NAME"
# Example output: rag-agent-dev-499614:europe-west1:rag-agent-postgres

# Get the public IP (for local development)
PUBLIC_IP=$(gcloud sql instances describe $INSTANCE_NAME \
  --project=$PROJECT_ID \
  --format='value(ipAddresses[0].ipAddress)')
echo "Public IP: $PUBLIC_IP"
```

### Step 3: Update IAM Roles for Cloud Run Service Account

```bash
# Add Cloud SQL Client role (required for Cloud SQL Auth Proxy)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/cloudsql.client"

# Optional: Add Cloud SQL Editor if you need admin access
# gcloud projects add-iam-policy-binding $PROJECT_ID \
#   --member="serviceAccount:$RUNTIME_SA" \
#   --role="roles/cloudsql.editor"
```

### Step 4: Store Database Credentials in Secret Manager

```bash
# Create secret for the database password
echo -n "$DB_PASSWORD" | gcloud secrets create postgres-password \
  --data-file=- \
  --project=$PROJECT_ID

# Create secret for the full connection URL using Cloud SQL Python Connector
# Format: postgresql+asyncpg+cloudsqlconnector://user:password@PROJECT:REGION:INSTANCE/database
DB_URL="postgresql+asyncpg+cloudsqlconnector://${DB_USER}:${DB_PASSWORD}@${CONNECTION_NAME}/rag_agent_sessions"
echo -n "$DB_URL" | gcloud secrets create rag-agent-database-url \
  --data-file=- \
  --project=$PROJECT_ID

# Grant runtime SA access to both secrets
gcloud secrets add-iam-policy-binding postgres-password \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor" \
  --project=$PROJECT_ID

gcloud secrets add-iam-policy-binding rag-agent-database-url \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor" \
  --project=$PROJECT_ID
```

### Step 5: Update Cloud Build Trigger Configuration

In the Google Cloud Console, update both dev and prod Cloud Build triggers to include:

**Substitution variables:**
- `_DB_INSTANCE` = `rag-agent-postgres`
- `_DB_NAME` = `rag_agent_sessions`
- `_DB_USER` = `rag_agent`
- `_DB_PASSWORD_SECRET` = `postgres-password` (or `rag-agent-database-url`)

These are already in `cloudbuild.yaml` - just ensure your trigger is configured to use the latest version.

## PHASE 2: LOCAL DEVELOPMENT SETUP

### Step 1: Install PostgreSQL Locally

**macOS (using Homebrew):**
```bash
brew install postgresql@16
brew services start postgresql@16
```

**Ubuntu/Debian:**
```bash
sudo apt-get install postgresql-16
sudo service postgresql start
```

**Windows (using PostgreSQL Installer):**
- Download from https://www.postgresql.org/download/windows/
- Run installer, remember the password for `postgres` user

### Step 2: Create Local Database

```bash
# Connect as postgres user
psql -U postgres

# Create database and user (in psql prompt)
CREATE DATABASE rag_agent_sessions;
CREATE USER rag_agent WITH PASSWORD 'your_local_password';
ALTER ROLE rag_agent SET client_encoding TO 'utf8';
ALTER ROLE rag_agent SET default_transaction_isolation TO 'read committed';
ALTER ROLE rag_agent SET default_transaction_deferrable TO on;
ALTER ROLE rag_agent SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE rag_agent_sessions TO rag_agent;
\q
```

### Step 3: Update Local `.env` File

```bash
# Copy example env
cp .env.example .env

# Edit .env and set (for local development with local PostgreSQL):
DATABASE_URL=postgresql+asyncpg://rag_agent:your_local_password@localhost:5432/rag_agent_sessions
```

### Step 4: Install Python Dependencies

```bash
uv sync
```

### Step 5: Test Local Connection

```bash
python -c "import asyncio; from rag_agent.config import settings; print(f'Database URL: {settings.database_url}')"
```

## PHASE 3: DEPENDENCY UPDATES

### Files Changed in `pyproject.toml`:

**Removed:**
- `google-cloud-firestore>=2.20.0`

**Added:**
- `cloud-sql-python-connector>=1.10.0` (Cloud SQL Python Connector for SQLAlchemy + asyncpg)
- `google-cloud-secret-manager>=2.16.0` (for secret retrieval)
- `asyncpg>=0.29.0` (PostgreSQL async driver)
- `sqlalchemy>=2.0.0` (already in file, required for ADK)
- `alembic>=1.13.0` (optional: database migrations)

**Install changes:**
```bash
uv sync
```

The Cloud SQL Python Connector automatically handles:
- GCP authentication via default credentials
- SSL/TLS certificate management
- Connection pooling and socket management
- No need for Cloud SQL Auth Proxy on Cloud Run

## PHASE 4: CODE CHANGES

The following files have been updated:

1. **`pyproject.toml`** - Added `cloud-sql-python-connector` dependency
2. **`src/rag_agent/config.py`** - Added `database_url` setting with corrected URL format
3. **`src/server.py`** - Configured ADK to use PostgreSQL for sessions via `session_service_uri`
4. **`.env.example`** - Updated DATABASE_URL with correct Cloud SQL Connector format
5. **`config/dev.env`** - Added database configuration with Cloud SQL Connector format
6. **`config/prod.env`** - Added database configuration with Cloud SQL Connector format
7. **`cloudbuild.yaml`** - Removed Cloud SQL Auth Proxy flag (not needed with Cloud SQL Connector)

### Key Configuration

**ADK Session Service:**
```python
# src/server.py
app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service_uri=settings.database_url,  # ✅ Now uses PostgreSQL
)
```

**Cloud Run Deployment:**
The `cloudbuild.yaml` now:
- Sets `DATABASE_URL` from Secret Manager as an environment variable
- Uses the Cloud SQL Python Connector format: `postgresql+asyncpg+cloudsqlconnector://user:password@PROJECT:REGION:INSTANCE/database`
- The Cloud SQL Connector handles authentication via GCP service account credentials
- The ADK will automatically create session tables on first run
- No Cloud SQL Auth Proxy needed

## PHASE 5: DEPLOY AND TEST

### Local Testing
```bash
# Run the server locally
uv run uvicorn server:app --app-dir src --reload

# Test the health endpoint
curl http://localhost:8000/health

# The ADK will create session tables automatically on first request
```

### Cloud Deployment

**For development (dev branch):**
```bash
git switch dev
git commit -am "Migrate to PostgreSQL for session persistence"
git push origin dev
# Cloud Build trigger will automatically run
```

**For production (prod branch):**
```bash
git switch prod
git merge dev
git push origin prod
# Manual approval required, then Cloud Build trigger will run
```

### Verify Deployment

```bash
# Check Cloud Run logs
gcloud run logs read rag-agent-dev --limit=100 --project=$PROJECT_ID

# Check that sessions are being persisted
gcloud sql connect rag-agent-postgres \
  --user=rag_agent \
  --project=$PROJECT_ID

# In psql prompt:
\c rag_agent_sessions
\dt  # List tables (should see ADK session tables)
SELECT * FROM sessions LIMIT 1;
```

## PHASE 6: CLEANUP (Optional)

Once PostgreSQL is fully operational and you've confirmed sessions are persisting:

### Remove Firestore Configuration

```bash
# Delete Firestore session data (if you don't need it)
# WARNING: This will delete all session history

# Disable Firestore from GCP project (if not used elsewhere)
gcloud services disable firestore.googleapis.com --project=$PROJECT_ID
```

### Remove Firestore from Code

The `firestore_client.py` module can be kept (for non-session use cases) or deleted:
```bash
rm src/rag_agent/firestore_client.py
```

Update `pyproject.toml` if you're not using Firestore elsewhere:
- Remove `google-cloud-firestore>=2.20.0` (already done)

## Troubleshooting

### Connection Issues

**"connect() got an unexpected keyword argument 'unix_sock_dir'"**
- ✅ Fixed: Now using Cloud SQL Python Connector instead of invalid parameter
- Ensure DATABASE_URL uses the correct format: `postgresql+asyncpg+cloudsqlconnector://user:password@PROJECT:REGION:INSTANCE/database`

**"Connection refused" when connecting locally**
- Check PostgreSQL is running: `psql --version`
- Verify user exists: `psql -U rag_agent`
- Check DATABASE_URL in `.env` uses localhost: `postgresql+asyncpg://rag_agent:password@localhost:5432/rag_agent_sessions`

**"Connector error" or "authentication failed" on Cloud Run**
- Verify the runtime service account has the `roles/cloudsql.client` IAM role
- Check that DATABASE_URL in Secret Manager uses the correct format with `cloudsqlconnector`
- View logs: `gcloud run logs read rag-agent-dev --limit=100`

**"Could not translate DSL" errors**
- Ensure you're using `postgresql+asyncpg+cloudsqlconnector://` scheme (not just `postgresql+asyncpg://`)
- For local dev, use `postgresql+asyncpg://` with localhost

### Database Issues

**"relation does not exist" on first run**
- This is expected; ADK creates tables automatically
- Check logs: `gcloud run logs read rag-agent-dev --limit=50`

**Slow queries on sessions**
- Cloud SQL instance tier affects performance; upgrade if needed:
  ```bash
  gcloud sql instances patch $INSTANCE_NAME \
    --tier=db-perf-optimized-2 \
    --project=$PROJECT_ID
  ```

## Summary of Changes

| Component | Before | After |
|-----------|--------|-------|
| Session Backend | Firestore (NoSQL) | PostgreSQL (SQL) |
| Dependency | `google-cloud-firestore` | `cloud-sql-python-connector` + `asyncpg` + `sqlalchemy` |
| Connection (Local) | `firestore://` | `postgresql+asyncpg://user:password@localhost:5432/database` |
| Connection (Cloud Run) | N/A | `postgresql+asyncpg+cloudsqlconnector://user:password@PROJECT:REGION:INSTANCE/database` |
| ADK Config | Broken (no Firestore dialect) | ✅ Native PostgreSQL support |
| Cloud SQL Auth | N/A | Cloud SQL Python Connector (no proxy needed) |
| Authentication | Service account only | ✅ Service account credentials + connector |
| Secrets | API_KEY only | API_KEY + DATABASE_URL |
| Local Dev | Needed Firestore emulator | Local PostgreSQL instance |
| Cloud Run Setup | N/A | Simpler: no Cloud SQL Auth Proxy required |

## Next Steps

1. Run the GCP setup steps (Phase 1)
2. Set up local PostgreSQL (Phase 2)
3. Test locally with `uv run uvicorn`
4. Deploy to dev branch
5. Verify sessions persist across requests
6. Deploy to prod once dev is stable