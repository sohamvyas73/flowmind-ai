"""What FlowMind can use for retrieval, including how to start each vector database with Docker."""
from typing import Any, Dict, List

from app.rag.embedders import CATALOG as EMBEDDERS

STORES: List[Dict[str, Any]] = [
    {
        "type": "pgvector", "label": "pgvector — your existing PostgreSQL",
        "summary": "Vectors live next to your app data in the PostgreSQL FlowMind already uses. Nothing new to run.",
        "needs_connection": False, "needs_docker": False, "best_for": "Getting started, small to medium collections (up to a few million chunks).",
        "setup": ["Make sure the 'vector' extension is installed in your PostgreSQL:",
                  "  Ubuntu/Debian:  sudo apt install postgresql-16-pgvector",
                  "  Docker image:   use  pgvector/pgvector:pg16  instead of  postgres:16",
                  "Then, once, as a superuser:  CREATE EXTENSION vector;"],
        "docker": None, "default_port": None, "verified_here": True,
    },
    {
        "type": "qdrant", "label": "Qdrant", "summary": "Fast, purpose-built vector database with rich filtering.",
        "needs_connection": True, "needs_docker": True, "best_for": "Larger collections, filtering, production search.",
        "docker": "docker run -d --name flowmind-qdrant -p 6333:6333 -v flowmind_qdrant:/qdrant/storage qdrant/qdrant:v1.12.4",
        "profile": "qdrant", "default_port": 6333, "default_url": "http://localhost:6333", "verified_here": True,
    },
    {
        "type": "weaviate", "label": "Weaviate", "summary": "Open-source vector database with hybrid search and many integrations.",
        "needs_connection": True, "needs_docker": True, "best_for": "Hybrid search, rich schemas, multi-tenant setups.",
        "docker": ("docker run -d --name flowmind-weaviate -p 8080:8080 -v flowmind_weaviate:/var/lib/weaviate "
                   "-e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true -e PERSISTENCE_DATA_PATH=/var/lib/weaviate "
                   "-e DEFAULT_VECTORIZER_MODULE=none semitechnologies/weaviate:1.27.0"),
        "profile": "weaviate", "default_port": 8080, "default_url": "http://localhost:8080", "verified_here": True,
    },
    {
        "type": "chroma", "label": "Chroma", "summary": "Simple, developer-friendly vector database.",
        "needs_connection": True, "needs_docker": True, "best_for": "Prototyping and small projects.",
        "docker": "docker run -d --name flowmind-chroma -p 8001:8000 -v flowmind_chroma:/chroma/chroma chromadb/chroma:0.5.20",
        "profile": "chroma", "default_port": 8001, "default_url": "http://localhost:8001", "verified_here": True,
    },
]


def catalog() -> Dict[str, Any]:
    return {
        "stores": STORES,
        "embedders": [e.__dict__ for e in EMBEDDERS],
        "compose": "docker compose -f docker-compose.vectorstores.yml --profile <qdrant|weaviate|chroma> up -d",
        "script": "./scripts/vectorstores.sh start <qdrant|weaviate|chroma>",
    }
