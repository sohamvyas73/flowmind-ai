# Vector stores — what FlowMind supports

FlowMind talks to every store through one small interface, so a collection behaves the same wherever it lives.

| Store | Type | Needs a container? | Verified against | Best for |
|---|---|---|---|---|
| **pgvector** | extension in your PostgreSQL | No | pgvector 0.6.0 on PostgreSQL 16 | Starting out, up to a few million chunks |
| **Qdrant** | server | Yes | `qdrant/qdrant:v1.12.4` | Larger collections, filtering |
| **Weaviate** | server | Yes | `semitechnologies/weaviate:1.27.0` | Hybrid search, rich schemas |
| **Chroma** | server | Yes | `chromadb/chroma:0.5.20` | Prototypes |

"Verified" means the repository's test-suite runs the complete lifecycle (index → search → re-index → edit → delete)
against **real running containers** of those versions, with identical results across all four.

## Starting the servers

```bash
./scripts/vectorstores.sh list
./scripts/vectorstores.sh start qdrant     # waits until it answers, then prints the next step
./scripts/vectorstores.sh status
./scripts/vectorstores.sh stop qdrant
```

or with Compose profiles (`docker-compose.vectorstores.yml`) or the one-line `docker run` commands shown on the
Retrieval page. FlowMind deliberately **does not control Docker itself**: giving a web app access to the Docker socket
would hand it root on the host.

## Connecting

Add a connection (type **Qdrant / Weaviate / Chroma**) with the server URL and, if the server has auth, a key.
Connections reuse the platform's protections: credentials are encrypted, requests go through the SSRF guard, and a
**private/local address needs an admin to allow-list its host** on the connection.

## How it behaves (all stores)

* Similarity is **cosine**; scores are normalised to 0–1 (higher is closer).
* **Chunk ids are deterministic** (hash of collection + source + chunk number + content hash), so re-indexing identical
  content overwrites rather than duplicates.
* **Incremental indexing:** each document's content hash is remembered; unchanged documents are skipped.
* **One physical collection per user collection**, with an opaque name — no user-controlled text reaches table or class
  names (pgvector table names are validated; SQL is parameterised).
* A collection is **bound to the embedding model and store it was built with**; a mismatch is refused with an
  explanation instead of returning wrong results.

## Version notes

Servers are driven over their REST APIs (no client libraries), so there is no client/server lock-step. Chroma's
REST path changed between versions; FlowMind auto-detects `/api/v2` (0.5.20 verified) and falls back to `/api/v1`
(older servers; not exercised in tests).

## Adding another store

Implement `VectorStore` in `backend/app/rag/stores.py` (`health, ensure_collection, upsert, delete_source, search, count,
drop`), register it in `REST_STORES` (or like `PgVectorStore`), add a connector in `backend/app/connectors/vector.py`
and a catalog entry in `backend/app/rag/catalog.py`. The shared lifecycle tests in `tests/test_rag.py` (`RetrievalFlow`)
then apply to it with one subclass.
