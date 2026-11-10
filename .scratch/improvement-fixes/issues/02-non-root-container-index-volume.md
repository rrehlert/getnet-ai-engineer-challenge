# 02: Non-root container and index volume

**What to build:** the container process runs as a non-root user, and the Corpus index lives on a named volume so recreating the container reuses it instead of rebuilding. The index directory exists in the image owned by the non-root user, so a fresh named volume inherits that ownership; the embedding model cache stays readable by that user.

**Blocked by:** None (can start immediately; best after 01 so CI validates it)

**Status:** done

- [x] The app process inside the container is not root
- [x] Compose mounts a named volume at the index directory
- [x] First `docker compose up --build` builds the index on the fresh volume without permission errors
- [x] After `docker compose down` and `up`, the index is reused (log shows no rebuild) and `/health` is 200
- [x] Embedding model still loads offline from the baked cache
- [x] CI smoke job (01) passes
