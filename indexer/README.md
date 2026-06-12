# indexer/ — kowalski-indexer (`kowindex`)

Semantic file index for Kowalski OS (plan phase 2):

```
filesystem scan -> paragraph-aware chunking -> embeddings (Ollama, nomic-embed-text)
               -> SQLite vector store (sqlite-vec, numpy fallback) -> kow-index search
```

## Pipeline

1. **Scan** (`kowindex.scanner`) walks the index roots, picking up text files
   (`.md .txt .rst .py .js .ts .tsx .json .yaml .yml .toml .ini .cfg .sh .csv`)
   plus `.pdf` when `pdftotext` is on PATH. Hidden directories and
   `node_modules`, `.venv`, `venv`, `__pycache__`, `.git`, `dist`, `build` are
   pruned; files over 2 MB are skipped; decode errors are replaced.
2. **Chunk** (`kowindex.chunker`) splits text into ~1200-char chunks with a
   ~200-char overlap, preferring paragraph and line boundaries.
3. **Embed** (`kowindex.embedder`) batches chunks (16 at a time) through
   `ollama.Client(host).embed(model=..., input=batch)`. If the model is missing
   you get a clear hint: `ollama pull nomic-embed-text`.
4. **Store** (`kowindex.store`) keeps everything in one SQLite database (WAL):
   `files`, `chunks` (embedding = float32 little-endian BLOB, L2-normalized) and
   a `meta` table that pins the embedding dimension (validated on reopen).

## CLI

```sh
kow-index index                  # incremental scan of the configured roots
kow-index index --paths ~/a:~/b  # override the roots for this run
kow-index search "wake word" -n 8
kow-index watch                  # initial scan, then watchdog with 2 s debounce
kow-index status                 # files/chunks/db_path/model/vec_backend
```

## Config keys

Read via `kowalski.config.Config` (environment first, then
`~/.config/kowalski/kowalski.conf`, then defaults):

| Key               | Default                          | Meaning                                  |
|-------------------|----------------------------------|------------------------------------------|
| `KOW_INDEX_DB`    | `~/.local/share/kowalski/index.db` | index database path                    |
| `KOW_INDEX_PATHS` | empty → `KOW_ALLOWED_PATHS`      | colon-separated roots to index           |
| `KOW_EMBED_MODEL` | `nomic-embed-text`               | Ollama embedding model                   |
| `OLLAMA_HOST`     | `http://127.0.0.1:11434`         | Ollama server                            |

## Vector backends

On open the store tries to load the `sqlite-vec` extension
(`enable_load_extension` + `sqlite_vec.load`). If it loads, KNN runs in SQL
against a `vec0` virtual table (`vec_chunks`, rowid = `chunks.id`). If
extension loading is unavailable (some macOS Python builds), the store falls
back to a numpy brute-force scan over the stored embedding BLOBs — same
results, just O(n). `kow-index status` reports which backend is active.
Embeddings are normalized, so scores are `1 - cosine distance` in `[0..1]`.

## Incremental & watch behaviour

- A file whose `(path, mtime, size)` is unchanged is skipped (no re-embedding).
- Changed files are re-chunked, re-embedded and replaced atomically.
- Files that vanished from the scanned roots have their chunks deleted.
- `kow-index watch` performs an initial scan, then funnels watchdog events
  through a 2-second debounce into the same incremental update (deleted
  directories drop everything indexed beneath them).

## Public API

```python
from kowindex.api import SemanticIndex

index = SemanticIndex("~/.local/share/kowalski/index.db")
for hit in index.search("voice pipeline wake word", limit=10):
    print(hit.score, hit.path, hit.snippet)
print(index.stats())
```

Tests run without a network: `pytest indexer/tests -q` uses a deterministic
fake embedder and exercises both vector backends.
