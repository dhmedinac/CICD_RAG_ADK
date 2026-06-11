"""ADK agent definition.

Exposes `root_agent`, which ADK's runner / FastAPI app discovers automatically.
The agent is a single LLM agent equipped with a Vertex AI RAG Engine retrieval
tool so it can ground answers in the managed corpus.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.retrieval.vertex_ai_rag_retrieval import VertexAiRagRetrieval
from vertexai.preview import rag

from .config import settings
from .prompts import SYSTEM_INSTRUCTION

rag_retrieval_tool = VertexAiRagRetrieval(
    name="retrieve_documentation",
    description=(
        "Retrieve the most relevant passages from the private knowledge corpus "
        "to ground an answer. Call this for any factual question."
    ),
    rag_resources=[rag.RagResource(rag_corpus=settings.rag_corpus_resource_name())],
    similarity_top_k=settings.similarity_top_k,
    vector_distance_threshold=settings.vector_distance_threshold,
)

root_agent = Agent(
    model=settings.agent_model,
    name="rag_agent",
    instruction=SYSTEM_INSTRUCTION,
    tools=[rag_retrieval_tool],
)
