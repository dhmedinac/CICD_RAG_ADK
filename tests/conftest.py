"""Test configuration.

Sets environment variables before the app/agent modules are imported so that
construction never touches the network: a fake (but well-formed) RAG corpus
resource name is provided, which the retrieval tool stores without resolving.
"""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault(
    "RAG_CORPUS",
    "projects/test-project/locations/us-central1/ragCorpora/1234567890",
)
os.environ.setdefault("API_KEY", "test-secret-key")
