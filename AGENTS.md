# orchid-rag-neo4j — AI Context

## What This Package Is

`orchid-rag-neo4j` is the Neo4j graph-store plugin for the Orchid AI framework.
It provides:

- `Neo4jGraphStore` — implements `OrchidGraphStore` backed by Neo4j

## Auto-Registration

The package registers itself via Python `importlib.metadata` entry points:

```toml
[project.entry-points."orchid.graph_store_backends"]
neo4j = "orchid_rag_neo4j:_register"
```

No manual `register_graph_store_backend()` calls are needed by integrators.

## Key Files

| File | Purpose |
|------|---------|
| `neo4j_graph.py` | `Neo4jGraphStore`, Cypher queries, scope key helpers |
| `__init__.py` | Entry-point `_register()` callable |

## Testing

Tests require `neo4j` but do **not** require a live Neo4j server —
all unit tests mock `AsyncGraphDatabase.driver`.

```bash
cd orchid-rag-neo4j
pip install -e ".[dev]"
pytest tests/ -x
```

## Common Pitfalls

- The Cypher dialect stays intentionally simple.  Performance-sensitive
  integrators should subclass and override `find_entities` / `neighbours`.
- Always call `await store.close()` before process shutdown to release
  the Neo4j driver connection pool.
