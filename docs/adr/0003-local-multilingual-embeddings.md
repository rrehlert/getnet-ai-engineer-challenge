# Local multilingual embeddings (fastembed MiniLM)

Chunks are embedded with fastembed `paraphrase-multilingual-MiniLM-L12-v2`, which runs locally and is baked into the image. The Corpus is Portuguese and Messages are often English, so the model must be cross-lingual. Running it locally means no extra API key and no per-call cost. The trade-off is weaker retrieval than hosted embeddings and a 128-token input limit, which is why Chunks are small (~300 chars, 50 overlap) and why the Knowledge Agent queries in Portuguese.
