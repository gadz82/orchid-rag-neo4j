"""Tests for ``Neo4jGraphStore``.

The Neo4j driver ships as a dependency of ``orchid-rag-neo4j``, so these
unit tests mock ``AsyncGraphDatabase.driver`` rather than requiring a live
Neo4j instance.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchid_ai.core.graph_store import OrchidEntity
from orchid_ai.core.scopes import OrchidRAGScope

from orchid_rag_neo4j.neo4j_graph import Neo4jGraphStore, _scope_key


# ── Helpers ─────────────────────────────────────────────────


def _mock_driver() -> MagicMock:
    """Return a mocked Neo4j async driver with a session factory."""
    driver = MagicMock()
    session = AsyncMock()
    result = AsyncMock()

    # Make ``async for record in result`` yield the records we inject later.
    result.__aiter__.return_value = []

    session.run = AsyncMock(return_value=result)
    driver.session = MagicMock(return_value=session)
    driver.close = AsyncMock()

    # Support ``async with driver.session() as s``
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    return driver


def _scope() -> OrchidRAGScope:
    return OrchidRAGScope(tenant_id="t1", user_id="u1", chat_id="c1", agent_id="a1")


# ── Construction ──────────────────────────────────────────────


class TestConstruction:
    @pytest.mark.asyncio
    async def test_missing_driver_raises_import_error(self):
        """Without ``neo4j`` installed the constructor must raise ImportError."""
        with patch.dict("sys.modules", {"neo4j": None}):
            with pytest.raises(ImportError, match="pip install orchid-rag-neo4j"):
                Neo4jGraphStore(url="bolt://x", username="x", password="x")

    def test_construction_with_mocked_driver(self):
        mock_module = MagicMock()
        mock_db = MagicMock()
        mock_db.driver = MagicMock(return_value=_mock_driver())
        mock_module.AsyncGraphDatabase = mock_db
        mock_module.basic_auth = MagicMock(return_value=("u", "p"))
        with patch.dict("sys.modules", {"neo4j": mock_module}):
            # Force re-import of the module so it picks up the mocked neo4j
            import importlib
            import orchid_rag_neo4j.neo4j_graph as ng_mod
            importlib.reload(ng_mod)
            store = ng_mod.Neo4jGraphStore(url="bolt://x", username="u", password="p")
            assert store is not None
            mock_db.driver.assert_called_once()


# ── Scope key ───────────────────────────────────────────────


def test_scope_key_format():
    scope = OrchidRAGScope(tenant_id="t1", user_id="u1", chat_id="c1", agent_id="a1")
    assert _scope_key(scope) == "t1|u1|c1|a1"


def test_scope_key_defaults():
    scope = OrchidRAGScope(tenant_id="t1")
    assert _scope_key(scope) == "t1|||"


# ── Upsert entities ─────────────────────────────────────────


class TestUpsertEntities:
    @pytest.mark.asyncio
    async def test_upsert_entities_runs_merge(self):
        driver = _mock_driver()
        store = Neo4jGraphStore(url="bolt://x", username="u", password="p")
        store._driver = driver

        entities = [
            OrchidEntity(id="e1", type="Person", name="Alice"),
            OrchidEntity(id="e2", type="Person", name="Bob"),
        ]
        await store.upsert_entities(entities, _scope())

        driver.session.assert_called_once_with(database=None)
        session = driver.session.return_value
        session.run.assert_awaited_once()
        call = session.run.await_args
        assert "MERGE" in call.args[0]
        assert len(call.kwargs["entities"]) == 2

    @pytest.mark.asyncio
    async def test_upsert_entities_empty_list_noop(self):
        driver = _mock_driver()
        store = Neo4jGraphStore(url="bolt://x", username="u", password="p")
        store._driver = driver

        await store.upsert_entities([], _scope())
        driver.session.assert_not_called()


# ── Upsert edges ────────────────────────────────────────────


class TestUpsertEdges:
    @pytest.mark.asyncio
    async def test_upsert_edges_runs_merge(self):
        driver = _mock_driver()
        store = Neo4jGraphStore(url="bolt://x", username="u", password="p")
        store._driver = driver

        from orchid_ai.core.graph_store import OrchidEdge

        edges = [
            OrchidEdge(source_id="e1", target_id="e2", relation="knows"),
        ]
        await store.upsert_edges(edges, _scope())

        session = driver.session.return_value
        session.run.assert_awaited_once()
        call = session.run.await_args
        assert len(call.kwargs["edges"]) == 1
        assert call.kwargs["edges"][0]["relation"] == "knows"

    @pytest.mark.asyncio
    async def test_upsert_edges_empty_list_noop(self):
        driver = _mock_driver()
        store = Neo4jGraphStore(url="bolt://x", username="u", password="p")
        store._driver = driver

        await store.upsert_edges([], _scope())
        driver.session.assert_not_called()


# ── Find entities ───────────────────────────────────────────


class TestFindEntities:
    @pytest.mark.asyncio
    async def test_find_entities_returns_parsed_nodes(self):
        driver = _mock_driver()
        result = AsyncMock()
        result.__aiter__.return_value = [
            {"n": {"id": "e1", "type": "Person", "name": "Alice"}},
        ]
        session = driver.session.return_value
        session.run = AsyncMock(return_value=result)

        store = Neo4jGraphStore(url="bolt://x", username="u", password="p")
        store._driver = driver

        out = await store.find_entities(query="ali", scope=_scope())
        assert len(out) == 1
        assert out[0].id == "e1"
        assert out[0].name == "Alice"


# ── Neighbours ──────────────────────────────────────────────


class TestNeighbours:
    @pytest.mark.asyncio
    async def test_neighbours_empty_seed_returns_empty(self):
        driver = _mock_driver()
        store = Neo4jGraphStore(url="bolt://x", username="u", password="p")
        store._driver = driver

        entities, edges = await store.neighbours([], scope=_scope())
        assert entities == []
        assert edges == []
        driver.session.assert_not_called()
