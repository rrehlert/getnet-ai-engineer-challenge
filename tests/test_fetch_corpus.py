from pathlib import Path

from scripts.fetch_corpus import extract_faq, page_body, page_title, render_page, slug

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_faq_reads_question_and_answer_from_faq_modals():
    html = (FIXTURES / "duvidas_get_smart.html").read_text(encoding="utf-8")

    assert extract_faq(html) == [
        (
            "Como realizo o cancelamento de uma venda da Get Smart realizada em dias anteriores?",
            "Somente entrando em contato com nossa central de atendimento no telefone 4003-4000.",
        ),
        (
            "O que é a Get Smart?",
            "A Get Smart é uma maquininha Android.\nEla aceita aproximação, QR Code e Pix.",
        ),
    ]


def test_slug_is_the_url_path_joined_with_dashes():
    assert slug("https://site.getnet.com.br/duvidas/get-smart/") == "duvidas-get-smart"
    assert slug("https://www.getnet.net/en/our-solutions/in-person-payments") == "en-our-solutions-in-person-payments"


def test_slug_of_a_site_root_is_home():
    assert slug("https://site.getnet.com.br/") == "home"


def test_render_page_writes_front_matter_then_body():
    page = render_page(
        url="https://site.getnet.com.br/duvidas/pix/",
        lang="pt-BR",
        title='Dúvidas: Pix "na maquininha"',
        body="O que é o Pix?\nÉ um pagamento instantâneo.",
    )

    assert page == (
        "---\n"
        'url: "https://site.getnet.com.br/duvidas/pix/"\n'
        'lang: "pt-BR"\n'
        'title: "Dúvidas: Pix \\"na maquininha\\""\n'
        "---\n"
        "\n"
        "O que é o Pix?\nÉ um pagamento instantâneo.\n"
    )


def test_faq_page_body_is_its_questions_and_answers():
    html = (FIXTURES / "duvidas_get_smart.html").read_text(encoding="utf-8")

    assert page_body(html) == (
        "## Como realizo o cancelamento de uma venda da Get Smart realizada em dias anteriores?\n"
        "Somente entrando em contato com nossa central de atendimento no telefone 4003-4000.\n"
        "\n"
        "## O que é a Get Smart?\n"
        "A Get Smart é uma maquininha Android.\n"
        "Ela aceita aproximação, QR Code e Pix."
    )


def test_article_body_keeps_content_and_drops_site_boilerplate():
    html = (FIXTURES / "article_aluguel.html").read_text(encoding="utf-8")

    body = page_body(html)

    assert "Todas as maquininhas aceitam aproximação, QR Code e Pix" in body
    assert "Nos informe CPF ou CNPJ" not in body
    assert "Tenha suporte:" not in body


def test_article_body_lists_product_cards_that_trafilatura_drops():
    html = (FIXTURES / "article_aluguel.html").read_text(encoding="utf-8")

    body = page_body(html)

    assert (
        "Get Clássica: A maquininha feita com material reciclado feita para você. "
        "Recursos: Aproximação, QR Code e PIX; 3G e Wi-fi; Bobina."
    ) in body
    assert (
        "Get Smart: A maquininha mais moderna e completa para o seu negócio. "
        "Recursos: Aproximação, QR Code e PIX; Nota fiscal; 3G, 4G e Wi-fi."
    ) in body


def test_page_title_drops_the_site_suffix():
    assert page_title("<html><head><title>Aluguel de maquininha | Getnet</title></head></html>") == "Aluguel de maquininha"


def test_faq_archive_title_reads_as_faq():
    html = (FIXTURES / "duvidas_get_smart.html").read_text(encoding="utf-8")

    assert page_title(html) == "Perguntas frequentes: Get Smart"


def test_page_title_drops_the_site_prefix_and_ignores_svg_titles():
    html = "<html><head><title>Getnet - Online Payments</title></head><body><svg><title>icon</title></svg></body></html>"

    assert page_title(html) == "Online Payments"


def test_extract_faq_drops_escaped_markup_and_styles_inside_answers():
    html = """
    <div class="o-modal__content o-modal__content--faq" data-modal="1">
      <div class="o-modal__title">Onde vejo as taxas?</div>
      <div class="o-modal__text"><div class="o-modal__text-content">
        <p>No app Getnet.</p>
        <style>.x { color: red }</style>
        <p>.splp-c-taxas {&lt;br /&gt; padding-top: 40px;&lt;br /&gt;}&lt;/p&gt; &lt;p&gt;.is--hidden{&lt;br /&gt;}</p>
      </div></div>
    </div>
    """

    assert extract_faq(html) == [("Onde vejo as taxas?", "No app Getnet.")]
