# RAG Agent — GCP CI/CD (test3)

A Retrieval-Augmented Generation agent built with **Google Agent Development Kit
(ADK)**, grounded by **Vertex AI RAG Engine**, served as an HTTP API on **Cloud
Run**, packaged with **uv**, and shipped through **Cloud Build** from two GitHub
branches into two GCP projects.

| Concern            | Choice                                                        |
| ------------------ | ------------------------------------------------------------- |
| Agent framework    | Google ADK (`google-adk`), single LLM agent + retrieval tool  |
| Reasoning model    | `gemini-2.5-flash` (Vertex AI)                                |
| Knowledge base     | Vertex AI RAG Engine corpus, ingested from a GCS bucket       |
| Serving            | Cloud Run, public endpoint guarded by an `X-API-Key` header   |
| Packaging          | uv (application mode), Docker multi-stage build               |
| CI/CD              | Cloud Build (GitHub App triggers), one config per environment |
| Environments       | `dev` branch → `rag-agent-dev`, `prod` branch → `rag-agent-prod` (manual approval) |

## Repository layout

```
.
├── src/
│   ├── server.py            # FastAPI entrypoint (ADK app + API-key gate + /health)
│   └── rag_agent/
│       ├── agent.py         # root_agent: Gemini + Vertex RAG retrieval tool
│       ├── config.py        # env-driven settings
│       └── prompts.py       # system instruction
├── scripts/
│   ├── manage_corpus.py     # create/import/list/delete the RAG corpus
│   ├── bootstrap.sh         # one-time GCP setup per project (Cloud Shell)
│   └── bootstrap.ps1        # same, for Windows PowerShell
├── config/{dev,prod}.env    # non-secret per-env config (trigger substitutions)
├── cloudbuild.yaml          # build → push → corpus sync → deploy
├── Dockerfile               # uv-based multi-stage image
└── tests/
```

## Local development

```powershell
uv sync                      # create .venv from uv.lock
Copy-Item .env.example .env  # then edit values
uv run pytest                # run the test suite
uv run uvicorn server:app --app-dir src --reload
```

The local server listens on http://localhost:8000. With `API_KEY` set, send it as
the `X-API-Key` header. `GET /health` is always open.

### Talking to the agent (local)

ADK exposes session + run endpoints. Quick smoke test (after creating a session):

```bash
# create a session
curl -X POST localhost:8000/apps/rag_agent/users/u1/sessions/s1 \
  -H "X-API-Key: $API_KEY"

# ask a question
curl -X POST localhost:8000/run \
  -H "Content-Type: application/json" -H "X-API-Key: $API_KEY" \
  -d '{"app_name":"rag_agent","user_id":"u1","session_id":"s1",
       "new_message":{"role":"user","parts":[{"text":"What does the corpus say about X?"}]}}'
```

### Testing on Cloud Run

Test your deployed agent on Cloud Run. First, save the API key in a variable:

**Bash:**
```bash
export API_KEY=$(gcloud secrets versions access latest --secret="rag-agent-dev-api-key")
```

**PowerShell:**
```powershell
$API_KEY = gcloud secrets versions access latest --secret="rag-agent-dev-api-key"
```

Then run the same tests against your Cloud Run endpoint:

**Check health:**
```bash
curl https://rag-agent-dev-306628348669.europe-west1.run.app/health
```

**Create a session:**
```bash
curl -X POST https://rag-agent-dev-306628348669.europe-west1.run.app/apps/rag_agent/users/u1/sessions/s1 \
  -H "X-API-Key: $API_KEY"
```

**Send a message:**
```bash
curl -X POST https://rag-agent-dev-306628348669.europe-west1.run.app/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "app_name": "rag_agent",
    "user_id": "u1",
    "session_id": "s1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What does the corpus say about PLAYERS?"}]
    }
  }'
```

**Stream responses (SSE):**
```bash
curl -X POST https://rag-agent-dev-306628348669.europe-west1.run.app/run_sse \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "app_name": "rag_agent",
    "user_id": "u1",
    "session_id": "s1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What does the corpus say about PLAYERS?"}]
    }
  }'
```

**Interactive API docs:**
Visit `https://rag-agent-dev-306628348669.europe-west1.run.app/docs` in your browser, click "Authorize", and paste your API key.

## Deploying

Full instructions in [docs/SETUP.md](docs/SETUP.md). In short:

1. `./scripts/bootstrap.sh dev` and `./scripts/bootstrap.sh prod` (once per project).
2. Add the API key to Secret Manager and upload documents to the corpus bucket.
3. Connect the repo and create two Cloud Build triggers (prod requires approval).
4. Push to `dev` → auto-deploys to dev. Merge to `prod` → deploys after approval.

## Managing the corpus manually

```bash
uv run python scripts/manage_corpus.py sync \
  --display-name rag-agent-corpus --gcs-source gs://rag-agent-dev-corpus/
uv run python scripts/manage_corpus.py list
```
