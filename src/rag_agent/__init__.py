"""RAG agent package.

ADK discovers an agent app by importing this package and reading `root_agent`
from the `agent` submodule, so we re-export it here.
"""

from . import agent  # noqa: F401
