# 04: Fetch script and committed Corpus

Status: ready-for-agent
Blocked by: 02

- `scripts/fetch_corpus.py`: curated URL list (getnet.net/en, site.getnet.com.br product pages, `/duvidas/` FAQs); httpx + trafilatura; lxml XPath for the FAQ modals.
- Writes `corpus/*.md` with `url/lang/title` front matter; run it and commit the output.

Done when the Corpus covers every example topic: Get Clássica/Smart, Pix, antecipação, crediário, Link de Pagamento, connectivity, declines.
