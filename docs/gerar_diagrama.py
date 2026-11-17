"""Gera docs/diagrama-er.drawio (fonte única do diagrama ER).

Uso (na raiz do projeto):
    python3 docs/gerar_diagrama.py            # gera o .drawio e confere o traçado
    drawio --export --format png --scale 2.5 --border 24 --background '#FFFFFF' \
        -o docs/diagrama-er.png docs/diagrama-er.drawio
    drawio --export --format svg --border 24 -o docs/diagrama-er.svg docs/diagrama-er.drawio

O PNG e o SVG são exportados pelo próprio draw.io a partir do .drawio, então
os três ficam idênticos. Se mudar core/models.py, atualize TABELAS e RELACOES.

Todas as rotas são ortogonais e calculadas aqui. Antes de gravar, o script
verifica que nenhuma linha atravessa tabela, que nenhuma linha cruza outra e
que nenhum rótulo encosta em linha ou tabela (falha com erro se houver).
"""
import os
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

DOCS = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
FONTE = "Helvetica"

# ---------------------------------------------------------------------------
# Medidas
# ---------------------------------------------------------------------------
W, HDR, ROW = 380, 46, 24
COLS = (60, 172, 116, 32)  # chave, coluna, tipo, NN  (soma = W)
PAD, TOPO_GRUPO = 30, 52   # respiro interno dos grupos e altura da faixa de título

CORES = {  # fundo do grupo, borda do grupo, título do grupo, cabeçalho tabela, borda tabela
    "cli": ("#F3F9F5", "#CFE5D6", "#2E7D4F", "#D7EEDF", "#7FB894"),
    "atend": ("#F2F6FC", "#CCD9EE", "#2F5E9E", "#DCE7F7", "#7F9FCF"),
    "func": ("#FCF4F3", "#EDD2CF", "#A4443F", "#F6DAD7", "#CC8A85"),
    "kb": ("#F7F3FB", "#DDD1EA", "#6B4C8C", "#E8DDF2", "#A68CC1"),
}
TINTA, TINTA2, TINTA3 = "#1F2933", "#52606D", "#7B8794"
LINHA = "#4A5563"
PK_FUNDO = "#FFF6D6"
SEPARADOR = "#E7EAEE"

TZ = "timestamptz"
# nome: (grupo, x, y, descrição, [(marcadores, coluna, tipo, NOT NULL)])
TABELAS = {
    "core_contato": ("cli", 80, 170, "Cliente (Telegram ou site)", [
        ("PK", "id", "bigint", 1), ("CK", "canal", "varchar(20)", 1), ("", "nome", "varchar(120)", 1),
        ("UQ", "telegram_chat_id", "bigint", 0), ("", "telegram_username", "varchar(64)", 1),
        ("UQ", "web_sessao", "varchar(64)", 0), ("", "email", "varchar(254)", 1),
        ("", "telefone", "varchar(30)", 1), ("", "criado_em", TZ, 1), ("", "ultimo_contato_em", TZ, 1)]),
    "core_ticket": ("cli", 80, 518, "Solicitação com protocolo", [
        ("PK", "id", "bigint", 1), ("UQ", "protocolo", "varchar(20)", 1), ("FK", "contato_id", "bigint", 1),
        ("FK", "conversa_id", "bigint", 0), ("FK", "responsavel_id", "bigint", 0),
        ("", "assunto", "varchar(150)", 1), ("", "descricao", "text", 1), ("", "categoria", "varchar(20)", 1),
        ("", "prioridade", "varchar(10)", 1), ("", "status", "varchar(20)", 1), ("", "resposta", "text", 1),
        ("", "criado_em", TZ, 1), ("", "atualizado_em", TZ, 1), ("", "resolvido_em", TZ, 0)]),
    "core_conversa": ("atend", 580, 170, "Um atendimento, do início ao fim", [
        ("PK", "id", "bigint", 1), ("FK UQ¹", "contato_id", "bigint", 1), ("FK", "atendente_id", "bigint", 0),
        ("", "canal", "varchar(20)", 1), ("CK", "status", "varchar(20)", 1), ("", "modo", "varchar(20)", 1),
        ("", "motivo_escalonamento", "varchar(255)", 1), ("CK", "avaliacao", "smallint", 0),
        ("", "comentario_avaliacao", "varchar(500)", 1), ("", "iniciada_em", TZ, 1),
        ("", "atualizada_em", TZ, 1), ("", "escalada_em", TZ, 0), ("", "assumida_em", TZ, 0),
        ("", "encerrada_em", TZ, 0), ("", "ultima_leitura_atendente_em", TZ, 0)]),
    "core_mensagem": ("atend", 1100, 170, "Cada mensagem trocada na conversa", [
        ("PK", "id", "bigint", 1), ("FK UQ²", "conversa_id", "bigint", 1), ("FK", "intencao_id", "bigint", 0),
        ("FK", "faq_id", "bigint", 0), ("FK", "atendente_id", "bigint", 0), ("CK", "remetente", "varchar(20)", 1),
        ("", "texto", "text", 1), ("", "confianca", "double precision", 0),
        ("", "origem_resposta", "varchar(20)", 1), ("", "botoes", "jsonb", 0),
        ("UQ²", "telegram_message_id", "bigint", 0), ("", "criada_em", TZ, 1)]),
    "core_eventoconversa": ("atend", 1100, 566, "Histórico / auditoria da conversa", [
        ("PK", "id", "bigint", 1), ("FK", "conversa_id", "bigint", 1), ("FK", "usuario_id", "bigint", 0),
        ("FK", "para_usuario_id", "bigint", 0), ("", "tipo", "varchar(20)", 1),
        ("", "detalhe", "varchar(255)", 1), ("", "criado_em", TZ, 1)]),
    "core_usuario": ("func", 820, 898, "Funcionário que acessa o painel", [
        ("PK", "id", "bigint", 1), ("UQ", "username", "varchar(150)", 1), ("", "email", "varchar(254)", 1),
        ("", "apelido", "varchar(60)", 1), ("", "cargo", "varchar(20)", 1), ("", "online", "boolean", 1),
        ("", "is_active", "boolean", 1), ("", "ultimo_acesso_painel", TZ, 0),
        ("+", "+ campos padrão de autenticação do Django", "", 0)]),
    "core_intencao": ("kb", 1670, 170, "Intenções que o bot reconhece", [
        ("PK", "id", "bigint", 1), ("UQ", "slug", "varchar(40)", 1), ("", "nome", "varchar(80)", 1),
        ("", "descricao", "varchar(255)", 1)]),
    "core_perguntafaq": ("kb", 1670, 374, "Pergunta e resposta do FAQ", [
        ("PK", "id", "bigint", 1), ("FK UQ³", "categoria_id", "bigint", 1), ("UQ³", "pergunta", "varchar(255)", 1),
        ("", "resposta", "text", 1), ("", "palavras_chave", "varchar(255)", 1), ("", "ativa", "boolean", 1),
        ("CK", "vezes_usada", "integer", 1), ("", "criada_em", TZ, 1), ("", "atualizada_em", TZ, 1)]),
    "core_categoriafaq": ("kb", 1670, 716, "Agrupa as perguntas do FAQ", [
        ("PK", "id", "bigint", 1), ("UQ", "nome", "varchar(80)", 1), ("CK", "ordem", "smallint", 1)]),
}

# Grupos (fundo + título): (id, grupo, título, legenda curta, x, y, largura, altura)
GRUPOS = [
    ("g_cli", "cli", "Clientes e tickets", "quem fala com o bot e o que abriu", 40, 118, 460, 818),
    ("g_atend", "atend", "Atendimento", "conversa, mensagens e histórico", 540, 118, 980, 696),
    ("g_func", "func", "Funcionários", "login do painel", 600, 846, 640, 360),
    ("g_kb", "kb", "Base de conhecimento", "intenções e FAQ", 1640, 118, 470, 818),
]


def altura(t):
    return HDR + ROW * len(TABELAS[t][4])


def ret(t):
    _, x, y, _, _ = TABELAS[t]
    return x, y, x + W, y + altura(t)


def ylin(t, col):
    _, _, y, _, cols = TABELAS[t]
    i = [c[1] for c in cols].index(col)
    return y + HDR + ROW * i + ROW / 2


def xe(t):
    return ret(t)[0]


def xd(t):
    return ret(t)[2]


def ytopo(t):
    return ret(t)[1]


def ybase(t):
    return ret(t)[3]


def nn(t, col):
    return next(c[3] for c in TABELAS[t][4] if c[1] == col)


# ---------------------------------------------------------------------------
# Relações. Cada uma: pai, âncora no pai, filho, coluna FK, lado no filho,
# pontos intermediários (rota ortogonal), verbo e posição do verbo.
#   âncora no pai: ("lin", lado, coluna)  -> linha da coluna (lado "L"/"R")
#                  ("borda", lado, x|y)   -> borda da tabela ("T"/"B"/"L"/"R")
# ---------------------------------------------------------------------------
Y_CONV_TK = ylin("core_ticket", "conversa_id")
Y_RESP_TK = ylin("core_ticket", "responsavel_id")
Y_HDR_USU = ytopo("core_usuario") + HDR / 2

RELACOES = [
    # Clientes
    dict(pai="core_contato", ap=("lin", "R", "id"), filho="core_conversa", col="contato_id", lf="L",
         via=[(530, ylin("core_contato", "id")), (530, ylin("core_conversa", "contato_id"))],
         verbo="inicia", rot=(520, ylin("core_contato", "id") - 12)),
    dict(pai="core_contato", ap=("lin", "L", "id"), filho="core_ticket", col="contato_id", lf="L",
         via=[(58, ylin("core_contato", "id")), (58, ylin("core_ticket", "contato_id"))],
         verbo="abre", rot=(58, 470), rot_lado="vert"),
    dict(pai="core_conversa", ap=("borda", "B", 620), filho="core_ticket", col="conversa_id", lf="R",
         via=[(620, Y_CONV_TK)],
         verbo="origina", rot=(582, Y_CONV_TK - 12)),
    dict(pai="core_usuario", ap=("borda", "T", 850), filho="core_ticket", col="responsavel_id", lf="R",
         via=[(850, Y_RESP_TK)],
         verbo="é responsável", rot=(645, Y_RESP_TK + 12)),
    # Atendimento
    dict(pai="core_usuario", ap=("borda", "T", 910), filho="core_conversa", col=None, lf=("B", 910),
         via=[], verbo="atende", rot=(910, 740), rot_lado="vert"),
    dict(pai="core_conversa", ap=("lin", "R", "id"), filho="core_mensagem", col="conversa_id", lf="L",
         via=[(1030, ylin("core_conversa", "id")), (1030, ylin("core_mensagem", "conversa_id"))],
         verbo="contém", rot=(995, ylin("core_conversa", "id") - 12)),
    dict(pai="core_conversa", ap=("borda", "B", 940), filho="core_eventoconversa", col="conversa_id", lf="L",
         via=[(940, ylin("core_eventoconversa", "conversa_id"))],
         verbo="registra", rot=(1040, ylin("core_eventoconversa", "conversa_id") - 12)),
    dict(pai="core_usuario", ap=("borda", "T", 990), filho="core_eventoconversa", col="usuario_id", lf="L",
         via=[(990, ylin("core_eventoconversa", "usuario_id"))],
         verbo="executa", rot=(990, 800), rot_lado="vertL"),
    dict(pai="core_usuario", ap=("borda", "T", 1050), filho="core_eventoconversa", col="para_usuario_id",
         lf="L", via=[(1050, ylin("core_eventoconversa", "para_usuario_id"))],
         verbo="recebe", rot=(1050, 800), rot_lado="vert"),
    dict(pai="core_usuario", ap=("borda", "R", Y_HDR_USU), filho="core_mensagem", col="atendente_id", lf="R",
         via=[(1535, Y_HDR_USU), (1535, ylin("core_mensagem", "atendente_id"))],
         verbo="envia", rot=(1370, Y_HDR_USU - 12)),
    # Base de conhecimento
    dict(pai="core_intencao", ap=("lin", "L", "id"), filho="core_mensagem", col="intencao_id", lf="R",
         via=[(1600, ylin("core_intencao", "id")), (1600, ylin("core_mensagem", "intencao_id"))],
         verbo="classifica", rot=(1558, ylin("core_mensagem", "intencao_id") - 12)),
    dict(pai="core_perguntafaq", ap=("lin", "L", "id"), filho="core_mensagem", col="faq_id", lf="R",
         via=[(1565, ylin("core_perguntafaq", "id")), (1565, ylin("core_mensagem", "faq_id"))],
         verbo="responde", rot=(1565, 372), rot_lado="vert"),
    dict(pai="core_categoriafaq", ap=("lin", "R", "id"), filho="core_perguntafaq", col="categoria_id", lf="R",
         via=[(2080, ylin("core_categoriafaq", "id")), (2080, ylin("core_perguntafaq", "categoria_id"))],
         verbo="agrupa", rot=(2080, 676), rot_lado="vertL"),
]


def ponto_pai(r):
    tipo, lado, v = r["ap"]
    t = r["pai"]
    x0, y0, x1, y1 = ret(t)
    if tipo == "lin":
        return (x0 if lado == "L" else x1, ylin(t, v))
    if lado in ("T", "B"):
        return (v, y0 if lado == "T" else y1)
    return (x0 if lado == "L" else x1, v)


def ponto_filho(r):
    t = r["filho"]
    x0, y0, x1, y1 = ret(t)
    if r["col"] is None:
        lado, v = r["lf"]
        return (v, y0 if lado == "T" else y1)
    return (x0 if r["lf"] == "L" else x1, ylin(t, r["col"]))


def caminho(r):
    return [ponto_pai(r)] + r["via"] + [ponto_filho(r)]


def opcional(r):
    if r["col"] is None:  # conversa.atendente_id
        return True
    return not nn(r["filho"], r["col"])


r_conv_atend = RELACOES[4]
r_conv_atend["col_real"] = "atendente_id"

# Tamanho aproximado dos rótulos (Helvetica 11px)
FONTE_ROT = 11


def caixa_rotulo(r):
    w = 5.6 * len(r["verbo"]) + 6
    h = 16
    x, y = r["rot"]
    if r.get("rot_lado") == "vert":  # ao lado de um traço vertical, à direita
        return (x + 7, y - h / 2, x + 7 + w, y + h / 2)
    if r.get("rot_lado") == "vertL":  # ao lado de um traço vertical, à esquerda
        return (x - 7 - w, y - h / 2, x - 7, y + h / 2)
    return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


# ---------------------------------------------------------------------------
# Conferência geométrica
# ---------------------------------------------------------------------------
def segmentos(pts):
    return list(zip(pts, pts[1:]))


def cruza(a, b):
    (p1, p2), (q1, q2) = a, b
    ax0, ax1 = sorted((p1[0], p2[0])); ay0, ay1 = sorted((p1[1], p2[1]))
    bx0, bx1 = sorted((q1[0], q2[0])); by0, by1 = sorted((q1[1], q2[1]))
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1


def seg_em_ret(s, rc, folga=0.5):
    (p1, p2) = s
    x0, y0, x1, y1 = rc
    sx0, sx1 = sorted((p1[0], p2[0])); sy0, sy1 = sorted((p1[1], p2[1]))
    return sx0 < x1 - folga and sx1 > x0 + folga and sy0 < y1 - folga and sy1 > y0 + folga


def conferir():
    erros = []
    caminhos = {i: caminho(r) for i, r in enumerate(RELACOES)}
    for i, pts in caminhos.items():
        for a, b in segmentos(pts):
            if a[0] != b[0] and a[1] != b[1]:
                erros.append(f"rel {i} tem trecho diagonal {a}->{b}")
            for t in TABELAS:
                if seg_em_ret((a, b), ret(t)):
                    erros.append(f"rel {i} atravessa {t}")
    for i in caminhos:
        for j in caminhos:
            if j <= i:
                continue
            for s in segmentos(caminhos[i]):
                for u in segmentos(caminhos[j]):
                    if cruza(s, u):
                        erros.append(f"rel {i} ({RELACOES[i]['verbo']}) cruza rel {j} ({RELACOES[j]['verbo']})")
    for i, r in enumerate(RELACOES):
        cx = caixa_rotulo(r)
        for t in TABELAS:
            if seg_em_ret(((cx[0], cx[1]), (cx[2], cx[3])), ret(t), folga=-4):
                erros.append(f"rótulo '{r['verbo']}' encosta em {t}")
        for j, pts in caminhos.items():
            for s in segmentos(pts):
                if seg_em_ret(s, (cx[0] - 2, cx[1] - 2, cx[2] + 2, cx[3] + 2), folga=0):
                    erros.append(f"rótulo '{r['verbo']}' encosta na rel {j}")
    return erros


# ---------------------------------------------------------------------------
# draw.io
# ---------------------------------------------------------------------------
def q(s):
    return escape(s, {'"': "&quot;"})


def gerar_drawio():
    cel = []
    add = cel.append

    def texto(id_, html, x, y, w, h, estilo=""):
        add(f'<mxCell id="{id_}" value="{q(html)}" style="text;html=1;whiteSpace=wrap;fontFamily={FONTE};'
            f'strokeColor=none;fillColor=none;{estilo}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')

    # Título
    texto("titulo", "Chatbot de Atendimento — Modelo de Dados", 40, 28, 1200, 36,
          f"fontSize=28;fontStyle=1;fontColor={TINTA};align=left;verticalAlign=middle;spacing=0;")
    texto("subtitulo",
          "Diagrama entidade-relacionamento · PostgreSQL · 9 tabelas do app <i>core</i> "
          "(core/models.py, migrações 0001 e 0002)",
          40, 68, 1200, 24, f"fontSize=14;fontColor={TINTA2};align=left;verticalAlign=middle;spacing=0;")

    # Grupos (ficam por baixo de tudo)
    for gid, g, tit, sub, x, y, w, h in GRUPOS:
        fundo, borda, cor_tit, _, _ = CORES[g]
        add(f'<mxCell id="{gid}" value="" style="rounded=1;arcSize=2;absoluteArcSize=1;html=1;'
            f'fillColor={fundo};strokeColor={borda};strokeWidth=1;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        texto(f"{gid}_titulo", escape(tit.upper()), x + PAD, y + 10, 300, 20,
              f"fontSize=14;fontStyle=1;fontColor={cor_tit};align=left;verticalAlign=middle;spacing=0;")
        texto(f"{gid}_sub", escape(sub), x + PAD, y + 29, 300, 16,
              f"fontSize=11;fontColor={TINTA3};align=left;verticalAlign=middle;spacing=0;")

    # Relações (antes das tabelas, para ficarem por baixo)
    for n, r in enumerate(RELACOES):
        pts = caminho(r)
        p0, p1 = pts[0], pts[-1]
        tp, lado, v = r["ap"]
        if tp == "lin":
            src = f'{r["pai"]}.{v}'
            ex, ey = (0 if lado == "L" else 1), 0.5
        else:
            src = r["pai"]
            x0, y0, x1, y1 = ret(r["pai"])
            ex, ey = (p0[0] - x0) / W, (p0[1] - y0) / (y1 - y0)
        if r["col"] is None:
            tgt = r["filho"]
            x0, y0, x1, y1 = ret(r["filho"])
            nx, ny = (p1[0] - x0) / W, (p1[1] - y0) / (y1 - y0)
        else:
            tgt = f'{r["filho"]}.{r["col"]}'
            nx, ny = (0 if r["lf"] == "L" else 1), 0.5
        inicio = "ERzeroToOne" if opcional(r) else "ERmandOne"
        meio = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in r["via"])
        add(f'<mxCell id="rel{n}" value="" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;'
            f'html=1;strokeColor={LINHA};strokeWidth=1.4;startArrow={inicio};endArrow=ERzeroToMany;'
            f'startFill=0;endFill=0;startSize=11;endSize=11;jettySize=auto;'
            f'exitX={ex:.6f};exitY={ey:.6f};exitDx=0;exitDy=0;exitPerimeter=0;'
            f'entryX={nx:.6f};entryY={ny:.6f};entryDx=0;entryDy=0;entryPerimeter=0;" edge="1" parent="1" '
            f'source="{src}" target="{tgt}"><mxGeometry relative="1" as="geometry">'
            f'<Array as="points">{meio}</Array></mxGeometry></mxCell>')
        cx = caixa_rotulo(r)
        al = {"vert": "left", "vertL": "right"}.get(r.get("rot_lado"), "center")
        texto(f"rel{n}_verbo", escape(r["verbo"]), cx[0], cx[1], cx[2] - cx[0], cx[3] - cx[1],
              f"fontSize={FONTE_ROT};fontStyle=2;fontColor={TINTA2};align={al};verticalAlign=middle;spacing=0;")

    # Tabelas
    for nome, (g, x, y, desc, cols) in TABELAS.items():
        _, _, _, cab, borda = CORES[g]
        h = altura(nome)
        titulo = (f'<b style="font-size:14px;color:{TINTA}">{nome}</b><br>'
                  f'<i style="font-size:11px;color:{TINTA2}">{escape(desc)}</i>')
        add(f'<mxCell id="{nome}" value="{q(titulo)}" style="shape=table;startSize={HDR};container=1;'
            f'collapsible=0;childLayout=tableLayout;fixedRows=1;rowLines=0;columnLines=0;resizeLast=1;html=1;'
            f'whiteSpace=wrap;align=center;verticalAlign=middle;fontFamily={FONTE};fillColor={cab};'
            f'strokeColor={borda};strokeWidth=1.2;swimlaneFillColor=#FFFFFF;rounded=0;'
            f'shadow=0;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{W}" height="{h}" as="geometry"/></mxCell>')
        for i, (k, c, tp, obrig) in enumerate(cols):
            rid = f"{nome}.{c}" if k != "+" else f"{nome}.mais"
            pk = k == "PK"
            fundo = PK_FUNDO if pk else "none"
            add(f'<mxCell id="{rid}" value="" style="shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;'
                f'swimlaneBody=0;fillColor={fundo};collapsible=0;dropTarget=0;points=[[0,0.5],[1,0.5]];'
                f'portConstraint=eastwest;top={0 if i == 0 else 1};left=0;right=0;bottom=0;'
                f'strokeColor={SEPARADOR};" vertex="1" parent="{nome}">'
                f'<mxGeometry y="{HDR + ROW * i}" width="{W}" height="{ROW}" as="geometry"/></mxCell>')
            if k == "+":
                vals = [(c, f"fontSize=11;fontStyle=2;fontColor={TINTA3};align=left;spacingLeft=10;"
                            "overflow=visible;whiteSpace=nowrap;"), ("", ""), ("", ""), ("", "")]
            else:
                peso = 1 if pk else 0
                marc = f"fontSize=10;fontStyle=1;align=center;fontColor={'#9A6B00' if pk else TINTA2};"
                nomec = (f"fontSize=12;fontStyle={peso | (4 if 'FK' in k else 0)};align=left;spacingLeft=6;"
                         f"fontColor={TINTA};")
                tipo = f"fontSize=11;align=left;spacingLeft=6;fontColor={TINTA3};fontFamily=Menlo;"
                nnc = f"fontSize=9;fontStyle=1;align=center;fontColor={TINTA3};"
                vals = [(k, marc), (c, nomec), (tp, tipo), ("NN" if obrig else "", nnc)]
            xs = 0
            for j, ((txt, est), larg) in enumerate(zip(vals, COLS)):
                ff = "" if "fontFamily" in est else f"fontFamily={FONTE};"
                add(f'<mxCell id="{rid}#{j}" value="{q(txt)}" style="shape=partialRectangle;connectable=0;'
                    f'fillColor=none;top=0;left=0;bottom=0;right=0;verticalAlign=middle;overflow=hidden;html=1;'
                    f'{ff}{est}" vertex="1" parent="{rid}">'
                    f'<mxGeometry x="{xs}" width="{larg}" height="{ROW}" as="geometry">'
                    f'<mxRectangle width="{larg}" height="{ROW}" as="alternateBounds"/></mxGeometry></mxCell>')
                xs += larg

    gerar_legenda(add, texto)

    corpo = "".join(cel)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="app.diagrams.net" agent="docs/gerar_diagrama.py" version="24.7.17">\n'
        '  <diagram id="modelo-er" name="Modelo ER">\n'
        '    <mxGraphModel dx="1800" dy="1100" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
        'arrows="1" fold="1" page="0" pageScale="1" pageWidth="2100" pageHeight="1300" '
        'background="#FFFFFF" math="0" shadow="0">\n'
        f'      <root><mxCell id="0"/><mxCell id="1" parent="0"/>{corpo}</root>\n'
        '    </mxGraphModel>\n  </diagram>\n</mxfile>\n'
    )


# ---------------------------------------------------------------------------
# Legenda: dois cartões, à esquerda e à direita de Funcionários
# ---------------------------------------------------------------------------
LEG_Y, LEG_H = 966, 240


def gerar_legenda(add, texto):
    def cartao(id_, x, w):
        add(f'<mxCell id="{id_}" value="" style="rounded=1;arcSize=2;absoluteArcSize=1;html=1;'
            f'fillColor=#FAFBFC;strokeColor=#D9DEE4;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{LEG_Y}" width="{w}" height="{LEG_H}" as="geometry"/></mxCell>')

    est_txt = f"fontSize=12;fontColor={TINTA};align=left;verticalAlign=top;spacing=0;"

    # Cartão 1: notação
    x, w = 40, 530
    cartao("leg_notacao", x, w)
    texto("leg_notacao_tit", f'<b style="font-size:14px;color:{TINTA}">Como ler</b>', x + 24, LEG_Y + 16, 300, 20,
          "align=left;verticalAlign=middle;spacing=0;")
    exemplos = [
        ("ERmandOne", "<b>exatamente 1</b> → 0..N &nbsp;<span style='color:#7B8794'>FK obrigatória (NOT NULL)</span>"),
        ("ERzeroToOne", "<b>0 ou 1</b> → 0..N &nbsp;<span style='color:#7B8794'>FK opcional (aceita NULL)</span>"),
    ]
    for i, (ini, txt) in enumerate(exemplos):
        yy = LEG_Y + 58 + i * 30
        add(f'<mxCell id="leg_ex{i}" value="" style="edgeStyle=none;html=1;strokeColor={LINHA};strokeWidth=1.4;'
            f'startArrow={ini};endArrow=ERzeroToMany;startFill=0;endFill=0;startSize=11;endSize=11;" '
            f'edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
            f'<mxPoint x="{x + 24}" y="{yy}" as="sourcePoint"/><mxPoint x="{x + 104}" y="{yy}" as="targetPoint"/>'
            f'</mxGeometry></mxCell>')
        texto(f"leg_ex{i}_t", txt, x + 120, yy - 9, w - 144, 18, est_txt.replace("verticalAlign=top", "verticalAlign=middle"))
    texto("leg_ex_nota",
          "O traço sai da tabela-pai (lado “um”) e o pé-de-galinha entra na linha da coluna FK da tabela-filha. "
          "O verbo se lê do pai para o filho: <i>contato inicia conversa</i>.",
          x + 24, LEG_Y + 108, w - 48, 32, f"fontSize=11;fontColor={TINTA2};align=left;verticalAlign=top;spacing=0;")

    marc = [("PK", "chave primária (linha destacada)"), ("FK", "chave estrangeira (sublinhada)"),
            ("UQ", "valor único"), ("NN", "obrigatório (NOT NULL)"), ("CK", "regra CHECK"),
            ("UQ¹", "unicidade parcial ou composta")]
    for i, (m, d) in enumerate(marc):
        xx = x + 24 + (i % 2) * 250
        yy = LEG_Y + 146 + (i // 2) * 25
        cor = "#9A6B00" if m == "PK" else TINTA2
        fundo = PK_FUNDO if m == "PK" else "#FFFFFF"
        add(f'<mxCell id="leg_m{i}" value="{q(m)}" style="rounded=1;arcSize=20;html=1;fontFamily={FONTE};'
            f'fontSize=10;fontStyle=1;fontColor={cor};fillColor={fundo};strokeColor=#D9DEE4;" vertex="1" '
            f'parent="1"><mxGeometry x="{xx}" y="{yy}" width="34" height="19" as="geometry"/></mxCell>')
        texto(f"leg_m{i}_t", escape(d), xx + 42, yy, 200, 19,
              f"fontSize=11;fontColor={TINTA2};align=left;verticalAlign=middle;spacing=0;")
    texto("leg_tipos", "Tipos PostgreSQL gerados pelo Django · timestamptz = timestamp with time zone",
          x + 24, LEG_Y + 218, w - 48, 16,
          f"fontSize=10;fontColor={TINTA3};align=left;verticalAlign=middle;spacing=0;")

    # Cartão 2: regras de integridade
    x, w = 1270, 840
    cartao("leg_regras", x, w)
    texto("leg_regras_tit", f'<b style="font-size:14px;color:{TINTA}">Regras de integridade no banco</b>',
          x + 24, LEG_Y + 16, 400, 20, "align=left;verticalAlign=middle;spacing=0;")
    regras = [
        ("UQ¹", "<b>uma conversa aberta por contato</b>: UNIQUE (contato_id) WHERE status &lt;&gt; 'encerrada'"),
        ("UQ²", "<b>mensagem do Telegram sem duplicidade</b>: UNIQUE (conversa_id, telegram_message_id) "
                "WHERE remetente = 'cliente'"),
        ("UQ³", "<b>pergunta única por categoria</b>: UNIQUE (categoria_id, pergunta)"),
        ("CK", "<b>contato</b>: canal telegram exige telegram_chat_id; canal web exige web_sessao"),
        ("CK", "<b>conversa</b>: status 'humano' exige atendente_id; avaliacao vazia ou de 1 a 5"),
        ("CK", "<b>mensagem</b>: remetente 'atendente' exige atendente_id"),
        ("CK", "<b>não negativos</b>: categoriafaq.ordem, perguntafaq.vezes_usada"),
    ]
    for i, (m, txt) in enumerate(regras):
        yy = LEG_Y + 48 + i * 24
        add(f'<mxCell id="leg_r{i}" value="{q(m)}" style="rounded=1;arcSize=20;html=1;fontFamily={FONTE};'
            f'fontSize=10;fontStyle=1;fontColor={TINTA2};fillColor=#FFFFFF;strokeColor=#D9DEE4;" vertex="1" '
            f'parent="1"><mxGeometry x="{x + 24}" y="{yy}" width="34" height="19" as="geometry"/></mxCell>')
        texto(f"leg_r{i}_t", txt, x + 68, yy, w - 92, 19,
              f"fontSize=11;fontColor={TINTA2};align=left;verticalAlign=middle;spacing=0;")


if __name__ == "__main__":
    erros = conferir()
    if erros:
        print("\n".join(erros))
        sys.exit(1)
    xml = gerar_drawio()
    ET.fromstring(xml.encode("utf-8"))  # XML bem-formado
    destino = os.path.join(DOCS, "diagrama-er.drawio")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(xml)
    print("ok:", destino)
