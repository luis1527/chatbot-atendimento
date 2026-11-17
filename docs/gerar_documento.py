"""
Gera o documento de entrega do protótipo:

    docs/Entrega - Chatbot de Atendimento.docx

Uso (a partir da raiz do projeto):

    .venv/bin/python docs/gerar_documento.py

Depende só do python-docx (não está no requirements.txt, porque não é
dependência do sistema):

    uv pip install --python .venv/bin/python python-docx

A imagem docs/diagrama-er.png é lida no momento da execução: se o diagrama
for refeito, basta rodar o script de novo.
"""
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

DOCS = Path(__file__).resolve().parent
SAIDA = DOCS / "Entrega - Chatbot de Atendimento.docx"
DIAGRAMA = DOCS / "diagrama-er.png"

FONTE = "Calibri"
DESTAQUE = RGBColor(0x4F, 0x46, 0xE5)
DESTAQUE_HEX = "4F46E5"
TEXTO = RGBColor(0x1F, 0x23, 0x2B)
CINZA = RGBColor(0x5B, 0x61, 0x70)
BORDA_HEX = "D3D6E0"
FUNDO_ZEBRA = "F5F5FB"

LARGURA_UTIL = Cm(21.0 - 2.2 - 2.2)  # A4 menos as margens laterais

SITE = "https://chatbot-atendimento-tau.vercel.app"


# ---------------------------------------------------------------------------
# Auxiliares de formatação
# ---------------------------------------------------------------------------
def _fonte_no_estilo(estilo, tamanho, *, negrito=False, cor=TEXTO):
    estilo.font.name = FONTE
    estilo.font.size = Pt(tamanho)
    estilo.font.bold = negrito
    estilo.font.color.rgb = cor
    rpr = estilo.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for att in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(att), FONTE)
    # Remove o tema, senão o Word/Docs usa a fonte do tema nos títulos.
    for att in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if rfonts.get(qn(att)) is not None:
            del rfonts.attrib[qn(att)]


def configurar_estilos(doc):
    normal = doc.styles["Normal"]
    _fonte_no_estilo(normal, 11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    h1 = doc.styles["Heading 1"]
    _fonte_no_estilo(h1, 16, negrito=True, cor=DESTAQUE)
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after = Pt(8)
    h1.paragraph_format.keep_with_next = True

    h2 = doc.styles["Heading 2"]
    _fonte_no_estilo(h2, 12.5, negrito=True, cor=DESTAQUE)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(4)
    h2.paragraph_format.keep_with_next = True

    for nome in ("List Bullet", "List Number"):
        est = doc.styles[nome]
        _fonte_no_estilo(est, 11)
        est.paragraph_format.space_after = Pt(3)

    # Estilo de hyperlink (cor de destaque, sublinhado)
    hl = doc.styles.add_style("Link", 2)  # 2 = caractere
    hl.font.name = FONTE
    hl.font.color.rgb = DESTAQUE
    hl.font.underline = True


def numero_de_pagina_no_rodape(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Página ")
    r.font.size = Pt(9)
    r.font.color.rgb = CINZA
    run = p.add_run()
    run.font.size = Pt(9)
    run.font.color.rgb = CINZA
    for tipo, texto in (("begin", None), (None, "PAGE"), ("end", None)):
        if tipo:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), tipo)
            run._r.append(fld)
        else:
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = texto
            run._r.append(instr)


def hyperlink(paragrafo, url, texto=None):
    """Insere um hyperlink de verdade (clicável no Word e no Google Docs)."""
    r_id = paragrafo.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    estilo = OxmlElement("w:rStyle")
    estilo.set(qn("w:val"), "Link")
    rpr.append(estilo)
    cor = OxmlElement("w:color")
    cor.set(qn("w:val"), DESTAQUE_HEX)
    rpr.append(cor)
    sub = OxmlElement("w:u")
    sub.set(qn("w:val"), "single")
    rpr.append(sub)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = texto or url
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    h.append(run)
    paragrafo._p.append(h)
    return h


def texto_rico(paragrafo, texto):
    """Escreve texto com trechos em `código` ou **negrito** destacados em negrito.

    Uma fonte só no documento inteiro: o "código" vira negrito, não monoespaçado.
    """
    for i, parte in enumerate(re.split(r"`|\*\*", texto)):
        if not parte:
            continue
        run = paragrafo.add_run(parte)
        if i % 2 == 1:
            run.bold = True


def par(doc, texto, *, estilo=None, depois=None, cor=None, tamanho=None, italico=False):
    p = doc.add_paragraph(style=estilo)
    texto_rico(p, texto)
    if depois is not None:
        p.paragraph_format.space_after = Pt(depois)
    for r in p.runs:
        if cor is not None:
            r.font.color.rgb = cor
        if tamanho is not None:
            r.font.size = Pt(tamanho)
        r.italic = italico
    return p


def marcador(doc, texto):
    return par(doc, texto, estilo="List Bullet")


def numerado(doc, itens):
    """Lista numerada simples (o número é escrito no texto: reinicia em cada lista)."""
    for i, texto in enumerate(itens, 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.75)
        p.paragraph_format.first_line_indent = Cm(-0.75)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(0.75))
        n = p.add_run(f"{i}.\t")
        n.bold = True
        n.font.color.rgb = DESTAQUE
        texto_rico(p, texto)


def _borda(elemento, lados, cor=BORDA_HEX, tamanho=4):
    bordas = OxmlElement("w:tblBorders" if elemento.tag.endswith("tblPr") else "w:tcBorders")
    for lado in lados:
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(tamanho))
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), cor)
        bordas.append(b)
    elemento.append(bordas)


def _sombrear(celula, cor_hex):
    tcpr = celula._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor_hex)
    tcpr.append(shd)


def _margens_celula(tabela, cima=70, baixo=110, lados=110):
    tblpr = tabela._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for lado, valor in (("top", cima), ("left", lados), ("bottom", baixo), ("right", lados)):
        el = OxmlElement(f"w:{lado}")
        el.set(qn("w:w"), str(valor))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblpr.append(mar)


def tabela(doc, cabecalho, linhas, larguras_cm, *, tamanho=10, primeira_negrito=False):
    """Tabela com cabeçalho na cor de destaque, bordas leves e linhas zebradas.

    Cada célula pode ser texto (aceita `código`) ou uma função f(paragrafo).
    """
    t = doc.add_table(rows=1, cols=len(cabecalho))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    tblpr = t._tbl.tblPr
    _borda(tblpr, ("top", "left", "bottom", "right", "insideH", "insideV"))
    _margens_celula(t)
    # Largura fixa (dxa), para o Google Docs respeitar.
    larg = OxmlElement("w:tblW")
    larg.set(qn("w:w"), str(int(sum(larguras_cm) * 567)))
    larg.set(qn("w:type"), "dxa")
    for antigo in tblpr.findall(qn("w:tblW")):
        tblpr.remove(antigo)
    tblpr.append(larg)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)

    def preencher(celula, conteudo, *, cab=False, negrito=False):
        p = celula.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        if callable(conteudo):
            conteudo(p)
        else:
            texto_rico(p, conteudo)
        for r in p.runs:
            r.font.size = Pt(tamanho)
            if cab:
                r.bold = True
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            elif negrito:
                r.bold = True
        for h in p._p.findall(qn("w:hyperlink")):
            for rpr in h.iter(qn("w:rPr")):
                sz = OxmlElement("w:sz")
                sz.set(qn("w:val"), str(int(tamanho * 2)))
                rpr.append(sz)

    linha_cab = t.rows[0]
    for celula, txt in zip(linha_cab.cells, cabecalho):
        preencher(celula, txt, cab=True)
        _sombrear(celula, DESTAQUE_HEX)
    # Repete o cabeçalho se a tabela passar de página; nenhuma linha se parte ao meio.
    trpr = linha_cab._tr.get_or_add_trPr()
    rep = OxmlElement("w:tblHeader")
    trpr.append(rep)

    for i, linha in enumerate(linhas):
        row = t.add_row()
        for j, (celula, conteudo) in enumerate(zip(row.cells, linha)):
            preencher(celula, conteudo, negrito=primeira_negrito and j == 0)
            if i % 2 == 1:
                _sombrear(celula, FUNDO_ZEBRA)

    # A grade da tabela precisa das mesmas larguras das células (Pages/Docs usam a grade).
    for col, cm in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), larguras_cm):
        col.set(qn("w:w"), str(int(cm * 567)))
    for row in t.rows:
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement("w:cantSplit"))
        for celula, cm in zip(row.cells, larguras_cm):
            celula.width = Cm(cm)
    # Espaço depois da tabela
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def link_celula(url, texto=None, extra=None):
    def f(p):
        hyperlink(p, url, texto)
        if extra:
            r = p.add_run(extra)
            r.font.color.rgb = CINZA
    return f


# ---------------------------------------------------------------------------
# Conteúdo
# ---------------------------------------------------------------------------
def capa(doc):
    for _ in range(7):
        doc.add_paragraph()
    faixa = doc.add_paragraph()
    faixa.paragraph_format.space_after = Pt(4)
    r = faixa.add_run("PROJETO DE ESTÁGIO · SQUAD DE DADOS")
    r.font.size = Pt(10)
    r.bold = True
    r.font.color.rgb = DESTAQUE

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run("Chatbot de Atendimento Automatizado — Protótipo")
    r.font.size = Pt(28)
    r.bold = True
    r.font.color.rgb = TEXTO
    p.paragraph_format.line_spacing = 1.0

    p = doc.add_paragraph()
    pbdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "12")
    b.set(qn("w:space"), "8")
    b.set(qn("w:color"), DESTAQUE_HEX)
    pbdr.append(b)
    p._p.get_or_add_pPr().append(pbdr)
    r = p.add_run("Documento de entrega")
    r.font.size = Pt(16)
    r.font.color.rgb = CINZA

    for _ in range(2):
        doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run("Data: ")
    r.bold = True
    p.add_run("17/11/2026")
    p = doc.add_paragraph()
    r = p.add_run("Bot no Telegram: ")
    r.bold = True
    hyperlink(p, "https://t.me/felipeprojeto_bot", "@felipeprojeto_bot")
    p = doc.add_paragraph()
    r = p.add_run("Site: ")
    r.bold = True
    hyperlink(p, SITE)

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def acesso_rapido(doc):
    doc.add_heading("1. Acesso rápido", level=1)
    linhas = [
        ("Site", link_celula(SITE)),
        ("Painel dos funcionários", link_celula(f"{SITE}/painel/")),
        ("Chat pelo site", link_celula(f"{SITE}/chat/")),
        ("Bot no Telegram", link_celula("https://t.me/felipeprojeto_bot", extra="  (@felipeprojeto_bot)")),
        ("Código-fonte (GitHub, público)", link_celula("https://github.com/daviddanielbp/chatbot-atendimento")),
        ("Status do servidor", link_celula(f"{SITE}/saude/")),
    ]
    tabela(doc, ("Item", "Endereço"), linhas, (5.2, 11.4), primeira_negrito=True)


def logins(doc):
    doc.add_heading("2. Logins", level=1)
    linhas = [
        ("`felipe`", "`felipe9955`", "Supervisor", "Acesso total (dashboard completo, funcionários, /admin/)"),
        ("`supervisor`", "`teste123`", "Supervisor", "Usuário de teste"),
        ("`atendente1`", "`teste123`", "Atendente", "Usuário de teste"),
        ("`atendente2`", "`teste123`", "Atendente", "Usuário de teste"),
    ]
    tabela(doc, ("Login", "Senha", "Cargo", "Uso"), linhas, (3.2, 3.2, 2.8, 7.4))
    par(doc, "Observação: estas senhas servem para a demonstração. Se o sistema for usado de verdade, "
             "troque todas no menu **Funcionários** do painel (o supervisor tem a opção de redefinir a "
             "senha de cada funcionário). Para testar vários atendentes ao mesmo tempo, use uma janela "
             "anônima ou outro navegador para cada login.", tamanho=10, cor=CINZA)


def o_que_faz(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_heading("3. O que o sistema faz", level=1)
    par(doc, "Requisitos do documento do estágio e como cada um foi atendido no protótipo.")
    doc.add_heading("Funcionalidades básicas", level=2)
    tabela(doc, ("Requisito", "Como foi atendido"), [
        ("FAQ automatizado",
         "O bot responde pela base de perguntas frequentes (por palavras-chave, ou pela IA quando ela está "
         "disponível). O FAQ é organizado em categorias e editado no painel; cada pergunta pode ser "
         "desativada sem ser apagada."),
        ("Abertura de tickets",
         "No menu do bot, “Abrir ticket” coleta categoria e descrição e gera um protocolo (`TCK-0001`). "
         "“Meus tickets” mostra o andamento. A equipe trata os tickets no painel e o cliente é avisado "
         "pelo próprio canal quando o ticket é resolvido."),
        ("Encaminhamento para humano",
         "O cliente toca em “Falar com atendente” (ou o bot oferece o atendente depois de duas respostas "
         "sem solução no Chat de dúvida). A conversa entra na fila; um funcionário assume e pode "
         "transferir, devolver ao bot ou encerrar a conversa."),
        ("Relatórios",
         "Dashboard no painel (com filtro de 7, 30, 90 dias ou 1 ano) e consultas SQL prontas em "
         "`docs/consultas-relatorios.sql`."),
    ], (4.4, 12.2), primeira_negrito=True)

    doc.add_heading("Funcionalidades avançadas", level=2)
    tabela(doc, ("Requisito", "Como foi atendido"), [
        ("Identificação de intenção (IA/NLP)",
         "O Google Gemini classifica a intenção de cada mensagem do cliente e a confiança (0 a 1) fica "
         "gravada no banco. Se a IA estiver indisponível, entra o fallback por regras e palavras-chave."),
        ("Respostas personalizadas",
         "A IA reescreve a resposta do FAQ em linguagem natural, usando só o que o FAQ diz; chama o cliente "
         "pelo nome e extrai da conversa os dados do ticket. O atendente aparece com o apelido "
         "(“Ana (atendente)”)."),
        ("Integração Telegram + Webchat",
         "O mesmo motor e o mesmo banco atendem os dois canais. O site tem página inicial com QR code do "
         "bot do Telegram e o chat em /chat/."),
        ("Dashboard com satisfação",
         "Ao encerrar, o cliente avalia de 1 a 5. O dashboard mostra nota média e distribuição das notas, "
         "tempo médio na fila, % resolvido só pelo bot, intenções, origem das respostas (FAQ, IA, humano), "
         "canais e perguntas mais usadas; o supervisor vê também a tabela por funcionário."),
    ], (4.4, 12.2), primeira_negrito=True)


def como_funciona(doc):
    doc.add_heading("4. Como funciona", level=1)
    par(doc, "O Telegram é o núcleo do atendimento. Tudo roda em um único app Django publicado na Vercel; "
             "o chat do site usa exatamente o mesmo motor do bot.")
    tabela(doc, ("Peça", "Papel no sistema"), [
        ("Telegram (@felipeprojeto_bot)",
         "Canal principal do cliente. Cada mensagem chega ao servidor por webhook HTTPS."),
        ("Django na Vercel",
         "Recebe o webhook, decide a resposta (menu, FAQ, IA, ticket, fila) e envia ao Telegram. Também "
         "serve o site, o chat do site e o painel dos funcionários."),
        ("PostgreSQL no Neon", "Guarda clientes, conversas, mensagens, tickets, FAQ e funcionários (9 tabelas)."),
        ("Google Gemini", "Interpreta a mensagem (intenção e dados) e redige a resposta a partir do FAQ."),
        ("Painel web", "Vários funcionários, cada um com seu login, atendem pelo mesmo bot."),
    ], (4.6, 12.0), primeira_negrito=True)

    doc.add_heading("Fluxo de um atendimento humano", level=2)
    numerado(doc, [
        "**Fila**: o cliente pede atendente; a conversa aparece na fila do painel de todos os funcionários.",
        "**Assumir**: um funcionário clica em Assumir. O banco trava a conversa, então, se dois clicarem "
        "juntos, só um consegue; o outro recebe o aviso “Conversa já está com …”.",
        "**Responder**: o funcionário escreve no painel e a mensagem chega ao cliente pelo mesmo bot, com o "
        "nome dele.",
        "**Transferir / devolver / encerrar**: a conversa pode ir para outro funcionário, voltar para o bot "
        "ou ser encerrada.",
        "**Avaliação**: ao encerrar, o bot pede uma nota de 1 a 5, que alimenta o dashboard.",
    ])


def como_usar(doc):
    doc.add_heading("5. Como usar", level=1)
    doc.add_heading("Cliente no Telegram", level=2)
    numerado(doc, [
        "Abra o bot **@felipeprojeto_bot** (link na seção 1) e envie `/start`. O bot dá boas-vindas e mostra o menu.",
        "`Chat de dúvida`: pergunte algo (ex.: “como pago com pix?”); o bot responde pelo FAQ.",
        "`Chat de conversa`: papo livre com o assistente; se precisar, ele chama um atendente.",
        "`Abrir ticket`: o bot pergunta a categoria e a descrição e devolve o protocolo `TCK-…`.",
        "`Meus tickets`: lista os tickets do cliente e a situação de cada um.",
        "`Falar com atendente`: entra na fila e informa a posição e o horário de atendimento humano.",
        "`/encerrar` finaliza a conversa; em seguida o bot pede a avaliação de 1 a 5. `/menu` volta ao menu.",
    ])
    doc.add_heading("Funcionário no painel", level=2)
    numerado(doc, [
        "**Login**: acesse /painel/ e entre com o usuário e a senha (seção 2).",
        "**Fila**: a lista de conversas se atualiza sozinha; as que estão esperando aparecem na fila.",
        "**Assumir**: abra a conversa e clique em Assumir para ficar responsável por ela.",
        "**Responder**: escreva a resposta; também há transferir, devolver ao bot e encerrar.",
        "**Tickets**: veja os tickets, mude o status e registre a resposta; ao resolver, o cliente é avisado.",
        "**Dashboard**: números de atendimento, satisfação, intenções e tempo na fila.",
        "**FAQ**: crie, edite, ative ou desative perguntas e categorias usadas pelo bot.",
        "**Funcionários** (só supervisor): cadastre, edite, desative e troque a senha dos funcionários.",
    ])


def banco(doc):
    doc.add_heading("6. Banco de dados (parte do squad de dados)", level=1)
    par(doc, "PostgreSQL (Neon em produção). As tabelas são criadas pelas migrations do Django a partir de "
             "`core/models.py`. Diagrama entidade-relacionamento:")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(DIAGRAMA), width=LARGURA_UTIL)
    par(doc, "Figura 1: diagrama ER (editável em docs/diagrama-er.drawio).", tamanho=9, cor=CINZA, italico=True)

    doc.add_heading("As 9 tabelas", level=2)
    tabela(doc, ("Tabela", "Grupo", "Objetivo"), [
        ("`core_usuario`", "Funcionários", "Login do painel: atendentes e supervisor (cargo, apelido, online)."),
        ("`core_contato`", "Clientes", "Quem fala com o bot, pelo Telegram ou pelo site; cadastrado uma única vez."),
        ("`core_ticket`", "Clientes", "Solicitação que não se resolve na hora, com protocolo, prioridade e status."),
        ("`core_conversa`", "Atendimento", "Um atendimento do começo ao fim: status bot, fila, humano ou encerrada; avaliação."),
        ("`core_mensagem`", "Atendimento", "Cada mensagem (cliente, bot, atendente, sistema), com intenção, confiança e origem da resposta."),
        ("`core_eventoconversa`", "Atendimento", "Trilha de auditoria: quem assumiu, transferiu, devolveu ou encerrou, e quando."),
        ("`core_intencao`", "Conhecimento", "Catálogo das intenções que o bot reconhece (dúvida, suporte, financeiro…)."),
        ("`core_categoriafaq`", "Conhecimento", "Categorias do FAQ (Pagamentos, Suporte técnico…)."),
        ("`core_perguntafaq`", "Conhecimento", "Pergunta, resposta e palavras-chave usadas pelo bot."),
    ], (4.3, 2.8, 9.5), tamanho=9.5)

    doc.add_heading("Principais regras de integridade", level=2)
    par(doc, "As regras ficam no próprio PostgreSQL (não só no Python): mesmo com um bug no código ou duas "
             "requisições simultâneas, o banco recusa o dado errado.").paragraph_format.keep_with_next = True
    tabela(doc, ("Regra", "O que garante", "Por quê"), [
        ("Uma conversa aberta por cliente (UNIQUE parcial)",
         "Cada cliente tem no máximo uma conversa não encerrada.",
         "Evita dois atendentes respondendo a mesma pessoa e o cliente duplicado na fila."),
        ("Mensagem do Telegram sem duplicidade (UNIQUE parcial)",
         "A mesma mensagem não é gravada duas vezes.",
         "O Telegram reenvia o webhook quando o servidor demora (cold start); sem a regra, a pergunta seria respondida duas vezes."),
        ("Um chat do Telegram = um contato (UNIQUE)",
         "Não há cadastro duplicado do mesmo cliente.",
         "Mantém o histórico inteiro e o “Meus tickets” completo."),
        ("Identificador por canal (CHECK)",
         "Contato do Telegram tem chat_id; do site, a sessão.",
         "Sem o chat_id, o bot não teria para onde mandar a resposta."),
        ("Conversa humana tem atendente (CHECK)",
         "Status “humano” sempre tem um responsável.",
         "Evita conversa órfã, que não aparece para ninguém."),
        ("Avaliação de 1 a 5 (CHECK)",
         "Nota vazia ou entre 1 e 5.",
         "Uma nota forjada (0 ou 50) estragaria a média do dashboard."),
        ("Mensagem de atendente identificada (CHECK)",
         "Toda mensagem de atendente registra quem enviou.",
         "Garante auditoria e relatório por atendente."),
        ("Protocolo único (UNIQUE)",
         "O protocolo do ticket nunca se repete.",
         "Um cliente nunca vê o ticket de outro."),
        ("Pergunta única por categoria (UNIQUE composto)",
         "Não há pergunta repetida na mesma categoria.",
         "Evita respostas inconsistentes do bot."),
        ("Chaves estrangeiras", "Nenhum registro aponta para algo inexistente.",
         "Evita registros soltos que quebram o painel."),
    ], (4.9, 5.0, 6.7), tamanho=9.5, primeira_negrito=True)
    par(doc, "Além do banco, o código se protege: ao assumir, a conversa é travada (`SELECT … FOR UPDATE`), "
             "para que só um funcionário consiga. Funcionário não deve ser apagado, e sim desativado, para "
             "preservar a autoria do histórico.", tamanho=10)

    doc.add_heading("Onde estão os arquivos", level=2)
    tabela(doc, ("Arquivo", "Conteúdo"), [
        ("`docs/diagrama-er.drawio`",
         lambda p: (p.add_run("Diagrama ER editável; abre em "), hyperlink(p, "https://app.diagrams.net", "app.diagrams.net"),
                    p.add_run(" (File › Open from › Device)."))),
        ("`docs/schema.sql`", "DDL real das tabelas, gerado pelo Django."),
        ("`docs/consultas-relatorios.sql`", "Consultas de relatório prontas (intenções, fila, satisfação, tickets…)."),
        ("`docs/testes-integridade.sql`", "Script que tenta gravar dados inválidos e mostra o banco recusando."),
        ("`docs/modelo-de-dados.md`", "Dicionário de dados completo, regras e ciclo de vida da conversa."),
    ], (5.6, 11.0), tamanho=10)


def tecnologias(doc):
    doc.add_heading("7. Tecnologias", level=1)
    tabela(doc, ("Tecnologia", "Uso"), [
        ("Python 3.12", "Linguagem do projeto."),
        ("Django 5.2", "Servidor web: bot, site, painel e /admin/."),
        ("PostgreSQL (Neon)", "Banco de dados em produção."),
        ("Vercel", "Hospedagem (o app roda como uma Vercel Function)."),
        ("API de Bots do Telegram", "Recebimento por webhook e envio das mensagens."),
        ("Google Gemini", "Identificação de intenção e redação das respostas."),
        ("Testes automatizados", "105 testes (banco e regras, bot, painel e chat do site)."),
    ], (5.0, 11.6), primeira_negrito=True)


def roteiro(doc):
    doc.add_heading("8. Roteiro de apresentação (5 min)", level=1)
    tabela(doc, ("Tempo", "O que mostrar", "Mensagem"), [
        ("0:00–0:40", "Visão geral da arquitetura (seção 4).",
         "Um bot, dois canais (Telegram e site), vários atendentes, um banco PostgreSQL."),
        ("0:40–1:50", "Telegram ao vivo: `/start` → Chat de dúvida → “como pago com pix?” → Abrir ticket (recebe `TCK-…`).",
         "Atendimento automático e protocolo."),
        ("1:50–3:00", "“Falar com atendente”. Painel em dois navegadores (atendente1 e atendente2): um assume, "
                      "o outro recebe o aviso. Responder, encerrar e o cliente avalia com 5 estrelas.",
         "Escalonamento humano, vários funcionários, sem conflito."),
        ("3:00–4:20", "Diagrama ER (9 tabelas, PK/FK, 1:N); regras “uma conversa aberta por cliente” e "
                      "“sem mensagem duplicada”; `testes-integridade.sql` e uma consulta (nota média por atendente).",
         "Modelagem, chaves, integridade e consultas: a entrega do squad de dados."),
        ("4:20–5:00", "Dashboard: satisfação, intenções, tempo na fila. Fechar com os testes automatizados passando.",
         "Relatórios e qualidade."),
    ], (2.2, 8.6, 5.8), tamanho=9.5)
    par(doc, "Dica: antes de apresentar, deixe o painel logado nos dois navegadores e confira se o dashboard "
             "tem dados (o comando `popular_demo --conversas` cria conversas fictícias).", tamanho=10, cor=CINZA)


def limitacoes(doc):
    doc.add_heading("9. Limitações do protótipo", level=1)
    for texto in (
        "Só texto: o bot não processa áudio, foto ou figurinha; quando recebe um, pede que o cliente escreva.",
        "O “tempo real” do painel é feito por atualização automática a cada 2–3 segundos (não há conexão "
        "permanente com o servidor).",
        "O Gemini usa a cota gratuita. Se ele ficar indisponível, o bot continua respondendo no modo simples "
        "(FAQ por palavras-chave e regras).",
        "O WhatsApp não está incluído; os canais são o Telegram e o chat do site.",
    ):
        marcador(doc, texto)


# ---------------------------------------------------------------------------
def main():
    if not DIAGRAMA.exists():
        raise SystemExit(f"Imagem não encontrada: {DIAGRAMA}")

    doc = Document()
    configurar_estilos(doc)
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.left_margin = s.right_margin = Cm(2.2)
    s.top_margin = s.bottom_margin = Cm(2.2)
    s.different_first_page_header_footer = True  # capa sem número
    numero_de_pagina_no_rodape(s)

    props = doc.core_properties
    props.title = "Chatbot de Atendimento Automatizado — Protótipo"
    props.subject = "Documento de entrega"
    props.author = "Squad de dados"
    props.language = "pt-BR"

    capa(doc)
    acesso_rapido(doc)
    logins(doc)
    o_que_faz(doc)
    como_funciona(doc)
    como_usar(doc)
    banco(doc)
    tecnologias(doc)
    roteiro(doc)
    limitacoes(doc)

    # Idioma pt-BR no estilo padrão (corretor ortográfico do Docs/Word)
    rpr = doc.styles["Normal"].element.get_or_add_rPr()
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "pt-BR")
    rpr.append(lang)

    doc.save(SAIDA)
    print(f"Gerado: {SAIDA}")


if __name__ == "__main__":
    main()
