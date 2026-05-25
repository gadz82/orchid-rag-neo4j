# orchid-rag-neo4j

Neo4j graph-store backend plugin for the [Orchid AI](https://github.com/gadz82/orchid) framework.

## What it provides

- `Neo4jGraphStore` — implements `OrchidGraphStore` backed by Neo4j

## Installation

```bash
pip install orchid-rag-neo4j
```

## Usage

Reference ``graph_store_backend: neo4j`` in your ``agents.yaml``:

```yaml
rag:
  graph_store_backend: neo4j
  neo4j_url: neo4j://localhost:7687
  neo4j_username: neo4j
  neo4j_password: secret
```

Or build it programmatically:

```python
from orchid_rag_neo4j import Neo4jGraphStore

store = Neo4jGraphStore(
    url="neo4j://localhost:7687",
    username="neo4j",
    password="secret",
)
```

## Development

```bash
cd orchid-rag-neo4j
pip install -e ".[dev]"
pytest tests/ -x
ruff check orchid_rag_neo4j/
```

## License

MIT
