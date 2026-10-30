"""Fetch the curated Getnet pages and write them to corpus/*.md (ADR 0002)."""

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import lxml.html
import trafilatura

FAQ_MODAL_XPATH = (
    '//div[contains(concat(" ", normalize-space(@class), " "), " o-modal__content--faq ")]'
)
_ESCAPED_MARKUP = re.compile(r"</?[a-z][a-z0-9]*\s*/?>")
_BLOCK_TAGS ={"p", "li", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol"}


def _text(element) -> str:
    """Text of an element: one line per block element, whitespace collapsed.

    Drops <style>/<script> and lines of escaped markup (CSS pasted into a FAQ answer).
    """
    for junk in element.xpath(".//style | .//script"):
        junk.drop_tree()
    for el in element.iter():
        el.text = re.sub(r"\s+", " ", el.text or "")
        el.tail = re.sub(r"\s+", " ", el.tail or "")
        if isinstance(el.tag, str) and el.tag in _BLOCK_TAGS:
            el.tail = "\n" + el.tail
    lines = (re.sub(r"\s+", " ", line).strip() for line in element.text_content().split("\n"))
    return "\n".join(line for line in lines if line and not _ESCAPED_MARKUP.search(line))


def slug(url: str) -> str:
    """File name stem for a page: its URL path joined with dashes ('home' for a root)."""
    parts = [p for p in urlsplit(url).path.split("/") if p]
    return "-".join(parts) or "home"


def render_page(url: str, lang: str, title: str, body: str) -> str:
    """A Corpus markdown file: YAML front matter (url, lang, title), a blank line, the body."""
    # JSON strings are valid YAML double-quoted scalars, so json.dumps quotes safely.
    meta = "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in
                   (("url", url), ("lang", lang), ("title", title)))
    return f"---\n{meta}---\n\n{body.strip()}\n"


def extract_faq(html: str) -> list[tuple[str, str]]:
    """(question, answer) pairs from the /duvidas/ FAQ modals, which trafilatura drops."""
    tree = lxml.html.fromstring(html)
    pairs = []
    for modal in tree.xpath(FAQ_MODAL_XPATH):
        question = " ".join(_text(q) for q in modal.xpath('./div[contains(@class, "o-modal__title")]'))
        answer = "\n".join(_text(a) for a in modal.xpath('./div[contains(@class, "o-modal__text")]'))
        if question and answer:
            pairs.append((question, answer))
    return pairs


def _has_class(name: str) -> str:
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def extract_product_cards(html: str) -> list[str]:
    """One line per Terminal card ("Get X: description. Recursos: a; b."), deduplicated."""
    tree = lxml.html.fromstring(html)
    cards: list[str] = []
    for info in tree.xpath(f"//div[{_has_class('product-info')}]"):
        name = " ".join(info.xpath(f"string(.//div[{_has_class('product-name')}])").split())
        description = " ".join(info.xpath(f"string(.//div[{_has_class('product-description')}])").split())
        features = [" ".join(f.text_content().split()) for f in info.xpath(f".//div[{_has_class('feature')}]")]
        if not name:
            continue
        line = f"{name}: {description}"
        if features:
            line += f" Recursos: {'; '.join(features)}."
        if line not in cards:
            cards.append(line)
    return cards


# Lines site.getnet.com.br repeats on every page (CPF/CNPJ modal, help and sales banners).
BOILERPLATE = {
    "Nos informe CPF ou CNPJ",
    "Para melhor direcionamento, informe o documento solicitado.",
    "Vamos começar o seu atendimento?",
    "Ainda não é cliente?",
    "Adquira agora e venda mais!",
    "CENTRAL DE VENDAS",
    "Já é nosso cliente?",
    "CENTRAL DE AJUDA",
    "Respondeu à sua dúvida?",
    "Com as principais dicas e informações:",
    "Clique abaixo e baixe agora",
    "Acesse a nossa lista de manuais navegáveis.",
    "Adquira nossos produtos e impulsione suas vendas",
    "Tenha suporte:",
    "Nossas ofertas imperdíveis te aguardam: selecione uma opção e acesse agora!",
}


def _article_text(html: str) -> str:
    text = trafilatura.extract(html, favor_recall=True) or ""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line and line not in BOILERPLATE)


def page_body(html: str) -> str:
    """Body of a page: the Q&A of a /duvidas/ FAQ page, else the article text plus Terminal cards."""
    faq = extract_faq(html)
    if faq:
        return "\n\n".join(f"## {question}\n{answer}" for question, answer in faq)
    body = _article_text(html)
    cards = extract_product_cards(html)
    if cards:
        body += "\n\n## Maquininhas\n" + "\n".join(f"- {card}" for card in cards)
    return body.strip()


def page_title(html: str) -> str:
    """The <head> title without the "Getnet" site name; FAQ archives read "Perguntas frequentes: X"."""
    tree = lxml.html.fromstring(html)
    title = " ".join(tree.xpath("string(//head/title)").split())
    title = re.sub(r"^Getnet\s*[-|]\s*", "", title)
    title = re.sub(r"\s*[-|]\s*Getnet$", "", title)
    return re.sub(r"^Arquivos\s+", "Perguntas frequentes: ", title)


BR = "https://site.getnet.com.br/"
EN = "https://www.getnet.net/en/"

# Curated static pages: (url, lang). Covers the example topics: Get Clássica / Get Smart,
# Pix, antecipação, crediário / parcelamento, Link de Pagamento / WhatsApp,
# Terminal connectivity and transaction declines / errors.
PAGES: list[tuple[str, str]] = [
    (EN, "en"),
    (EN + "our-solutions/in-person-payments", "en"),
    (EN + "our-solutions/online-payments", "en"),
    (EN + "our-solutions/omnichannel", "en"),
    (EN + "our-solutions/value-added-solutions", "en"),
    # Terminals (Get Mini / Get Clássica / Get Smart)
    (BR + "aluguel/", "pt-BR"),
    (BR + "maquininha-de-cartao/", "pt-BR"),
    (BR + "melhor-maquininha-para-o-seu-negocio/", "pt-BR"),
    (BR + "get-ajuda-maquininha/solucoes-get-smart/", "pt-BR"),
    (BR + "get-ajuda-maquininha/como-fazer-uma-venda-na-maquininha-getnet/", "pt-BR"),
    (BR + "get-ajuda-maquininha/como-solicitar-a-manutencao-da-maquininha-getnet/", "pt-BR"),
    (BR + "duvidas/get-smart/", "pt-BR"),
    (BR + "duvidas/operacional/", "pt-BR"),
    (BR + "duvidas/aluguel-zero/", "pt-BR"),
    (BR + "duvidas/plano-light/", "pt-BR"),
    (BR + "duvidas/bandeiras/", "pt-BR"),
    (BR + "duvidas/taxas/", "pt-BR"),
    # Connectivity (Wi-Fi, chip / mobile data)
    (BR + "get-ajuda-configuracoes/como-configurar-o-wi-fi-na-sua-maquininha-getnet/", "pt-BR"),
    (BR + "get-ajuda-configuracoes/configuracoes-da-sua-maquininha/", "pt-BR"),
    (BR + "duvidas/algar/", "pt-BR"),
    # Declines and Terminal error codes
    (BR + "get-ajuda-erros-maquininha/", "pt-BR"),
    *[
        (BR + f"get-ajuda-erros-maquininha/erro-{code}/", "pt-BR")
        for code in (
            "adq-1-02", "adq-1-06", "adq-1-07", "adq-1-18", "adq-1-19", "adq-1-21", "adq-1-33",
            "adq-1-50", "adq-1-84", "adq-1-85", "adq-1-87", "adq-3-30", "adq-4-23", "adq-4-27",
            "adq-4-30", "adq-4-83", "adq-4-91", "idl-1-04", "idl-1-08", "idl-1-36", "nfc", "s-2074",
        )
    ],
    (BR + "get-ajuda-gestao-de-vendas/quais-possiveis-status-das-minhas-vendas/", "pt-BR"),
    (BR + "get-ajuda-gestao-de-vendas/entenda-o-que-e-venda-autorizada-aprovada-e-desfeita/", "pt-BR"),
    (BR + "get-ajuda-chargeback/o-que-e-chargeback/", "pt-BR"),
    # Pix
    (BR + "pix/", "pt-BR"),
    (BR + "pix-na-maquininha-getnet/", "pt-BR"),
    (BR + "get-ajuda-pix/como-fazer-uma-venda-com-pix-na-maquininha/", "pt-BR"),
    (BR + "get-ajuda-pix/como-habilitar-o-recebimento-de-vendas-via-pix-no-aplicativo-getnet-brasil/", "pt-BR"),
    (BR + "duvidas/pix/", "pt-BR"),
    (BR + "duvidas/pix-mais-respostas/", "pt-BR"),
    (BR + "duvidas/get-conta/", "pt-BR"),
    (BR + "get-ajuda-get-conta/o-que-e-a-get-conta/", "pt-BR"),
    # Antecipação de recebíveis
    (BR + "quando-vale-a-pena-antecipar-as-suas-vendas-no-cartao/", "pt-BR"),
    (BR + "get-ajuda-antecipacao-de-venda/como-antecipar-sua-vendas-pelo-app/", "pt-BR"),
    (BR + "get-ajuda-antecipacao-de-venda/como-habilitar-antecipacao-automatica-pelo-app/", "pt-BR"),
    (BR + "get-ajuda-receba-ja/plano-de-recebimento-reduzido/", "pt-BR"),
    (BR + "duvidas/antecipacao-de-vendas/", "pt-BR"),
    (BR + "duvidas/app-getnet/", "pt-BR"),
    (BR + "duvidas/venda-com-cartao-de-credito-pre-pago/", "pt-BR"),
    # Crediário / parcelamento
    (BR + "crediario/", "pt-BR"),
    (BR + "duvidas/crediario/", "pt-BR"),
    (BR + "duvidas/parcelado/", "pt-BR"),
    # Link de Pagamento / WhatsApp
    (BR + "link-de-pagamento/", "pt-BR"),
    (BR + "link-de-pagamento-getnet/", "pt-BR"),
    (BR + "vender-pelo-whatsapp/", "pt-BR"),
    (BR + "pagamentos-pelo-whatsapp/", "pt-BR"),
    (BR + "duvidas/link-de-pagamento/", "pt-BR"),
]

MIN_BODY_CHARS = 200
USER_AGENT = "getnet-multi-agent-corpus-fetch/0.1 (one-off static fetch of public pages)"
DELAY_SECONDS = 1.0


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "corpus"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()

    written, skipped = 0, []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30) as client:
        for url, lang in PAGES:
            time.sleep(DELAY_SECONDS)
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                skipped.append((url, f"fetch failed: {exc}"))
                continue
            body = page_body(response.text)
            if len(body) < MIN_BODY_CHARS:
                skipped.append((url, f"empty / JS-only ({len(body)} chars)"))
                continue
            path = out / f"{slug(url)}.md"
            if path.exists():
                raise SystemExit(f"slug collision: {path.name} ({url})")
            path.write_text(render_page(url, lang, page_title(response.text), body), encoding="utf-8")
            written += 1
            print(f"ok   {path.name} ({len(body)} chars)")

    for url, reason in skipped:
        print(f"skip {url}: {reason}")
    print(f"{written} pages written to {out}, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
