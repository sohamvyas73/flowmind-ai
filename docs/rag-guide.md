# Retrieval (RAG) — a beginner-friendly guide

**RAG** means *"look things up in my own documents first, then answer."* Instead of an AI guessing, FlowMind finds the
passages of **your** documents that match a question, and (optionally) lets the AI answer **only** from those passages,
with numbered citations.

You do not need to know what a "vector" is. The idea in one picture:

```
  your documents ──► cut into small chunks ──► turned into numbers ──► stored in a "vector store"
                                                                              │
  a question ─────────────────────────────► turned into numbers ──► find the closest chunks
                                                                              │
                                                  (optional) AI writes the answer from those chunks only
```

> **Nothing is chosen for you.** Retrieval has *no defaults*. Until you pick an embedding model **and** a vector store
> and both connection tests pass, every Retrieval node refuses to run, with a message that tells you what to do.

![A Retrieval node refusing to run before setup](images/gallery/10-retrieval/01-node-refuses-before-setup.png)

---

## 1. Set it up (once, about 3 minutes)

Click **Retrieval** in the toolbar. You make two choices, then test them.

![Setup page](images/gallery/10-retrieval/02-not-set-up.png)

### Choice 1 — how text becomes numbers (embeddings)

| Option | Runs where | Meaning-aware? | Needs |
|---|---|---|---|
| **Local — word hashing** | inside FlowMind | No — matches shared *words* | nothing. Best for learning, offline, tests |
| **Local — FastEmbed** | your server CPU | Yes | `pip install fastembed`, one-time model download |
| **OpenAI** | OpenAI | Yes | your OpenAI API key |
| **Google Gemini** | Google | Yes | your Gemini API key |

If you are just learning, pick **Local — word hashing**. For real use, pick one of the meaning-aware options.

### Choice 2 — where the numbers are stored (vector store)

| Option | What it is | Start it |
|---|---|---|
| **pgvector** | Your **existing PostgreSQL** — nothing new to run | install the `vector` extension (see below) |
| **Qdrant** | Fast, purpose-built vector database | `docker run … qdrant/qdrant` |
| **Weaviate** | Open-source, hybrid search | `docker run … semitechnologies/weaviate` |
| **Chroma** | Simple and friendly | `docker run … chromadb/chroma` |

The page shows the exact Docker command for each one, with a copy button — or use the helper:

```bash
./scripts/vectorstores.sh start qdrant      # or weaviate / chroma
docker compose -f docker-compose.vectorstores.yml --profile qdrant up -d
```

![Choosing Qdrant and the Docker command](images/gallery/10-retrieval/03-choose-qdrant-and-docker.png)

**Using pgvector (existing PostgreSQL).** The extension must exist in your database. Ubuntu/Debian:
`sudo apt install postgresql-16-pgvector`; with Docker use the `pgvector/pgvector` image (FlowMind's own
`docker-compose.yml` already does). Then once, as a superuser: `CREATE EXTENSION vector;`.

**Using Qdrant / Weaviate / Chroma.** Create a **connection** of that type on the **Connections** page
(URL such as `http://localhost:6333`), then pick it on the Retrieval page. FlowMind refuses to reach private or local
addresses by default, so for a local Docker server an **admin must allow-list `localhost`** on that connection.

### Save and test

Press **Save & test connection**. Two independent checks run: *can I make vectors?* and *can I reach the store?*
Both must be green.

![pgvector tested](images/gallery/10-retrieval/04-store-pgvector-tested.png)

The same screen for the other stores (all tested for real against running Docker containers):
[Qdrant](images/gallery/10-retrieval/04-store-qdrant-tested.png) ·
[Weaviate](images/gallery/10-retrieval/04-store-weaviate-tested.png) ·
[Chroma](images/gallery/10-retrieval/04-store-chroma-tested.png)

---

## 2. Add documents and index them

On the same page: **Load example help-centre docs** (three small files from a pretend shop, "Acme Co."), or **Upload** your
own `.txt`, `.md` or `.pdf` files. Then press **Index all**.

![Documents indexed](images/gallery/10-retrieval/05-documents-indexed.png)

* A **collection** (here `help`) is a named shelf of indexed documents.
* **Chunk size / overlap** control how documents are cut. 400 characters with 50 overlap is a good start for short
  documents; 800/100 is the default for longer ones.
* Indexing is **safe to repeat**: unchanged documents are skipped, edited ones are replaced. Result of a second run:
  `0 new, 0 changed, 3 unchanged`.

## 3. Try a search

Type a question under **Try a search**:

![Search results](images/gallery/10-retrieval/06-search-results.png)

Real output for *"how many days until a refund is processed"* (word-hashing embeddings):

| # | Source | Score | Passage |
|---|---|---|---|
| 1 | acme-refund-policy.md | 0.331 | "…Once a refund is approved, it is processed within **5 business days**…" |
| 2 | acme-refund-policy.md | 0.142 | "…If an item arrives damaged…" |
| 3 | acme-shipping.md | 0.116 | "…A tracking link is emailed…" |

The score is similarity from 0 (unrelated) to 1 (identical). The right passage is first.

> **Honest note on the local word-hashing option:** it matches *words*, not *meaning*. "How long until I get my money
> back?" would score poorly because it shares no words with "refund". Meaning-aware embeddings (FastEmbed, OpenAI,
> Gemini) fix that. The setup page labels the option *keyword-style* so there are no surprises.

---

## 4. Use it in a workflow

Three nodes (under **Retrieval** in the palette):

| Node | What it does | Cost |
|---|---|---|
| **Index Documents** | Make documents (or a text column from a table) searchable. Re-run safely. | 2 credits |
| **Retrieve** | Find the best passages for a question. **No AI** involved. | 1 credit |
| **RAG Answer** | Retrieve, then answer *only* from the passages with `[1] [2]` citations. | tokens, like the AI node |

Load the samples **RAG: Index the help centre**, **RAG: Find passages (no AI)** and **RAG: Ask the help centre**.

**Retrieve** result for the question above:

![Retrieve result](images/gallery/10-retrieval/07-retrieve-node-results.png)

```json
{
  "query": "how many days until a refund is processed",
  "count": 3,
  "top_score": 0.331,
  "passages": [{ "source": "acme-refund-policy.md", "score": 0.331, "text": "…processed within 5 business days…" }],
  "context": "[1] (acme-refund-policy.md) # Acme Co. — Refund Policy …"
}
```

**RAG Answer** settings:

![RAG Answer settings](images/gallery/10-retrieval/08-rag-answer-settings.png)

Its output has `answer`, `citations` (`[{"n":1,"source":"acme-refund-policy.md","score":0.33}]`), `passages` and
`grounded`. **If nothing relevant is found, it says so and does not call the AI at all** (`grounded: false`) — it never
asks a model to answer from nothing. Passages are passed to the model as *data*, with an instruction not to follow
anything written inside them.

Use `{{field}}` in the question to take it from an earlier node, e.g. an **Input** node with a field named `question`.

### Index a table column instead of files
Connect **Load Data → Index Documents**, set *What to index* to **A text column from a table**, and pick the text column
(and optionally a name column). Handy for indexing product descriptions or support tickets.

---

## Common questions

**I changed my embedding model and now searches fail.** A collection is tied to the model it was built with — mixing
models silently would give wrong answers. FlowMind tells you: *delete the collection and index it again*.

**Where is my data?** Chunks live in the vector store you chose. Document files and settings live in your FlowMind
account; API keys are stored encrypted and never shown again. Collections are namespaced per user.

**Can I use another vector database?** The four above are supported today (see [vector-stores.md](vector-stores.md)
for details, versions and how to add one).

**What does it cost?** Local options cost nothing but credits for the nodes. Hosted embeddings are billed by the
provider to *your* key.
