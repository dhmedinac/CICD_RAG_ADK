from rag_agent.config import Settings


def test_explicit_corpus_short_circuits_lookup():
    s = Settings(rag_corpus="projects/p/locations/us-central1/ragCorpora/42")
    # Should return the explicit name without any Vertex API call.
    assert s.rag_corpus_resource_name() == "projects/p/locations/us-central1/ragCorpora/42"


def test_defaults():
    s = Settings()
    assert s.agent_model == "gemini-2.5-flash"
    assert s.google_cloud_location == "us-central1"
    assert s.similarity_top_k == 10
