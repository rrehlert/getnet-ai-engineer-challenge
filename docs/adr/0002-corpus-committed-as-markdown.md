# Corpus fetched by a static script and committed as markdown

Getnet pages are fetched once by a script (httpx + trafilatura, plus lxml XPath for the `/duvidas/` FAQ modals that trafilatura drops) and committed as markdown files with `url`/`lang`/`title` front matter. The index is built from these files at startup. We rejected live crawling at startup and headless browsers (Playwright) because of reproducibility, image size and build time. The trade-off is that the Corpus goes stale until the script is re-run, and JS-rendered pages and PDF manuals are not covered.
