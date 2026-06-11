def test_root_agent_is_configured():
    from rag_agent.agent import root_agent

    assert root_agent.name == "rag_agent"
    assert root_agent.model == "gemini-2.5-flash"
    # The Vertex RAG retrieval tool must be attached.
    tool_names = {getattr(t, "name", None) for t in root_agent.tools}
    assert "retrieve_documentation" in tool_names
