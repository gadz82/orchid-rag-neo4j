"""Neo4j graph-store backend for the Orchid AI framework.

Auto-registers via ``importlib.metadata`` entry points — no manual
``register_graph_store_backend()`` calls needed.
"""

from __future__ import annotations

import logging

from .neo4j_graph import Neo4jGraphStore

__version__ = "1.0.3"
__all__ = ["Neo4jGraphStore"]

logger = logging.getLogger(__name__)


def _register() -> None:
    """Entry-point callable — invoked by ``orchid_ai.rag.factory`` at import time."""
    try:
        from orchid_ai.rag.factory import register_graph_store_backend

        register_graph_store_backend("neo4j", Neo4jGraphStore)
        logger.debug("[orchid-rag-neo4j] Registered graph store backend")
    except ImportError:
        logger.debug("[orchid-rag-neo4j] Skipping registration (not in this orchid-ai version)")
