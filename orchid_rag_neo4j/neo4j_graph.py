"""
Neo4j-backed :class:`OrchidGraphStore`.

Behind the optional ``neo4j`` package (``pip install neo4j``).
Default deployments use the in-memory store from
``orchid_ai.rag.backends.in_memory_graph``; Neo4j slots in for production
GraphRAG workloads where the entity graph outgrows process memory.

The Cypher dialect intentionally stays simple — ``MERGE`` for upserts, a
scope-property filter on every clause, and a parameterised variable-length
pattern for neighbour walks.  Integrators with stricter performance needs
subclass and override.
"""

from __future__ import annotations

from typing import Any

from orchid_ai.core.graph_store import OrchidEdge, OrchidEntity, OrchidGraphStore
from orchid_ai.core.scopes import OrchidRAGScope


def _scope_key(scope: OrchidRAGScope) -> str:
    return "|".join(
        (
            scope.tenant_id,
            scope.user_id,
            scope.chat_id,
            scope.agent_id,
        )
    )


class Neo4jGraphStore(OrchidGraphStore):
    """Cypher-free knowledge-graph store backed by Neo4j.

    Parameters
    ----------
    url:
        Bolt URL — e.g. ``"neo4j://localhost:7687"``.
    username:
        Neo4j username (usually ``"neo4j"``).
    password:
        Neo4j password.
    database:
        Optional database name (multi-DB Enterprise).  Defaults to the
        server's default database.
    """

    def __init__(
        self,
        *,
        url: str,
        username: str,
        password: str,
        database: str | None = None,
    ) -> None:
        try:
            import neo4j
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "neo4j is not installed. Run `pip install orchid-rag-neo4j` to use Neo4jGraphStore."
            ) from exc

        self._driver = neo4j.AsyncGraphDatabase.driver(
            url,
            auth=neo4j.basic_auth(username, password),
        )
        self._database = database

    async def close(self) -> None:
        """Close the underlying Neo4j driver."""
        await self._driver.close()

    def _session(self):
        return self._driver.session(database=self._database)

    # ── Mutations ─────────────────────────────────────────────

    async def upsert_entities(
        self,
        entities: list[OrchidEntity],
        scope: OrchidRAGScope,
    ) -> None:
        if not entities:
            return
        sk = _scope_key(scope)
        async with self._session() as session:
            await session.run(
                """UNWIND $entities AS e
                   MERGE (n:Entity {scope: $scope, id: e.id})
                   SET n.type = e.type,
                       n.name = e.name,
                       n.properties = e.properties,
                       n.metadata = e.metadata""",
                scope=sk,
                entities=[
                    {
                        "id": e.id,
                        "type": e.type,
                        "name": e.name,
                        "properties": _json_safe(e.properties),
                        "metadata": _json_safe(e.metadata),
                    }
                    for e in entities
                ],
            )

    async def upsert_edges(
        self,
        edges: list[OrchidEdge],
        scope: OrchidRAGScope,
    ) -> None:
        if not edges:
            return
        sk = _scope_key(scope)
        async with self._session() as session:
            await session.run(
                """UNWIND $edges AS e
                   MATCH (a:Entity {scope: $scope, id: e.source}),
                         (b:Entity {scope: $scope, id: e.target})
                   MERGE (a)-[r:RELATION {scope: $scope, relation: e.relation}]->(b)
                   SET r.properties = e.properties,
                       r.metadata = e.metadata""",
                scope=sk,
                edges=[
                    {
                        "source": e.source_id,
                        "target": e.target_id,
                        "relation": e.relation,
                        "properties": _json_safe(e.properties),
                        "metadata": _json_safe(e.metadata),
                    }
                    for e in edges
                ],
            )

    # ── Queries ──────────────────────────────────────────────

    async def find_entities(
        self,
        *,
        query: str,
        scope: OrchidRAGScope,
        type_filter: list[str] | None = None,
        k: int = 10,
    ) -> list[OrchidEntity]:
        sk = _scope_key(scope)
        type_clause = "AND n.type IN $types" if type_filter else ""
        cypher = f"""MATCH (n:Entity {{scope: $scope}})
                 WHERE toLower(n.name) CONTAINS toLower($query) {type_clause}
                 RETURN n LIMIT $k"""
        async with self._session() as session:
            result = await session.run(
                cypher,
                scope=sk,
                query=query,
                types=type_filter or [],
                k=k,
            )
            records = [record async for record in result]
            return [_node_to_entity(r["n"]) for r in records]

    async def neighbours(
        self,
        entity_ids: list[str],
        *,
        scope: OrchidRAGScope,
        max_hops: int = 2,
        relation_filter: list[str] | None = None,
    ) -> tuple[list[OrchidEntity], list[OrchidEdge]]:
        if not entity_ids:
            return ([], [])

        sk = _scope_key(scope)
        hops = max(1, max_hops)

        # Build the relationship-type filter for the Cypher pattern.
        rel_type = "|".join(relation_filter) if relation_filter else "RELATION"

        cypher = f"""MATCH (start:Entity {{scope: $scope}})
                 WHERE start.id IN $ids
                 CALL {{
                   WITH start
                   MATCH path = (start)-[:{rel_type}*1..{hops}]->(n:Entity {{scope: $scope}})
                   RETURN nodes(path) AS nodes, relationships(path) AS rels
                 }}
                 RETURN nodes, rels"""

        seen_entities: dict[str, OrchidEntity] = {}
        seen_edges: dict[str, OrchidEdge] = {}

        async with self._session() as session:
            result = await session.run(cypher, scope=sk, ids=entity_ids)
            async for record in result:
                nodes = record["nodes"]
                rels = record["rels"]
                for node in nodes:
                    e = _node_to_entity(node)
                    seen_entities[e.id] = e
                for rel in rels:
                    edge = _rel_to_edge(rel)
                    if edge is not None:
                        key = f"{edge.source_id}-[{edge.relation}]->{edge.target_id}"
                        seen_edges[key] = edge

        return (list(seen_entities.values()), list(seen_edges.values()))


# ── Helpers ─────────────────────────────────────────────────


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Ensure a dict is JSON-safe for Neo4j parameter serialisation."""
    # Neo4j driver handles most Python types; this is a shallow safety net.
    return {k: v for k, v in value.items() if v is not None}


def _node_to_entity(node: Any) -> OrchidEntity:
    """Convert a Neo4j node record into :class:`OrchidEntity`."""
    props = dict(node)
    return OrchidEntity(
        id=props.get("id", ""),
        type=props.get("type", ""),
        name=props.get("name", ""),
        properties=props.get("properties", {}),
        metadata=props.get("metadata", {}),
    )


def _rel_to_edge(rel: Any) -> OrchidEdge | None:
    """Convert a Neo4j relationship record into :class:`OrchidEdge`."""
    props = dict(rel)
    # Neo4j relationship records may not expose start/end node IDs directly
    # in all driver versions; we fall back to the properties we set during
    # upsert.
    source_id = props.get("source_id")
    target_id = props.get("target_id")
    if source_id is None or target_id is None:
        # Try to extract from the rel object's start_node / end_node if present.
        start = getattr(rel, "start_node", None)
        end = getattr(rel, "end_node", None)
        if start is not None and end is not None:
            source_id = dict(start).get("id")
            target_id = dict(end).get("id")
    if source_id is None or target_id is None:
        return None
    return OrchidEdge(
        source_id=source_id,
        target_id=target_id,
        relation=props.get("relation", ""),
        properties=props.get("properties", {}),
        metadata=props.get("metadata", {}),
    )
